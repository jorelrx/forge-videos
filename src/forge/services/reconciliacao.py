from __future__ import annotations

import hashlib
import fnmatch
from pathlib import Path
from typing import NamedTuple

from forge.domain.operacao import Artifact, ItemStatus, StageName
from forge.repositories.operacao import OperacaoRepository


KNOWN_OUTPUTS = (
    "video/input.json",
    "video/midia.json",
    "video/manifesto.json",
    "video/audio/*.wav",
    "video/images/*.png",
    "video/images/*.jpg",
    "video/narration.wav",
    "video/subtitles.srt",
    "video/final.mp4",
    "video/validation.json",
    "video/validation/frame-*.jpg",
)


class ReconciliationReport(NamedTuple):
    preserved: list[str]
    invalidated: list[str]
    orphans: list[str]
    reset_items: list[str]


class Reconciliador:
    def __init__(self, db, output_root: Path) -> None:
        self._db = db
        self.output_root = Path(output_root)

    def _repo(self, conn) -> OperacaoRepository:
        return OperacaoRepository(conn)

    def reconcile(self, run_id: str) -> ReconciliationReport:
        preserved: list[str] = []
        invalidated: list[str] = []
        orphans: list[str] = []
        reset_items: list[str] = []

        with self._db.transaction(immediate=True) as conn:
            repo = self._repo(conn)
            run_dir = self.output_root / run_id
            artifacts = repo.list_artifacts(run_id, current_only=True)

            # 1. Validate each current artifact
            for art in artifacts:
                file_path = self._resolve_file(run_dir, art.relative_path)
                if file_path is not None and file_path.is_file():
                    size_match = file_path.stat().st_size == art.size_bytes
                    hash_match = hashlib.sha256(file_path.read_bytes()).hexdigest() == art.sha256
                    if size_match and hash_match:
                        preserved.append(art.id)
                        continue
                # Invalid: missing or changed
                invalidated.append(art.id)
                conn.execute(
                    "UPDATE artifacts SET is_current = 0 WHERE id = ?",
                    (art.id,),
                )
                # Reset linked item
                if art.work_item_id is not None:
                    conn.execute(
                        "UPDATE work_items SET status = ?, duration_ms = NULL, "
                        "failure_code = ?, failure_message = ? WHERE id = ?",
                        (
                            ItemStatus.FAILED.value,
                            "artifact_hash_mismatch" if file_path is not None else "artifact_missing",
                            "File hash or size mismatch" if file_path is not None else "Artifact file missing",
                            art.work_item_id,
                        ),
                    )
                    reset_items.append(art.work_item_id)

            # 2. Catalog known orphans: files matching KNOWN_OUTPUTS with no catalog row
            known_files = self._discover_known_outputs(run_dir)
            current_artifact_paths = {
                art.relative_path for art in artifacts
            }
            for rel_path in known_files:
                # Skip paths that have a current catalog entry (already handled above)
                if rel_path in current_artifact_paths:
                    continue
                # Skip if any non-current artifact has this relative_path
                # (only create orphan when absolutely no row exists)
                existing_rows = conn.execute(
                    "SELECT 1 FROM artifacts WHERE run_id = ? AND relative_path = ?",
                    (run_id, rel_path),
                ).fetchall()
                if existing_rows:
                    # Already registered (even if not current); don't duplicate
                    continue
                orphan_path = self._resolve_file(run_dir, rel_path)
                if orphan_path is None or not orphan_path.is_file():
                    continue
                # Create orphan artifact
                sha = hashlib.sha256(orphan_path.read_bytes()).hexdigest()
                size_bytes = orphan_path.stat().st_size
                kind = self._kind_for_path(rel_path)
                mime_type = self._mime_for_path(rel_path)
                orphan_id = str(__import__("uuid").uuid4())
                conn.execute(
                    "INSERT INTO artifacts (id, run_id, stage_run_id, work_item_id, kind, "
                    "relative_path, sha256, size_bytes, mime_type, metadata_json, is_current, created_at) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (
                        orphan_id,
                        run_id,
                        None,
                        None,
                        kind,
                        rel_path,
                        sha,
                        size_bytes,
                        mime_type,
                        '{"discovered_during": "reconciliation"}',
                        0,
                        __import__("datetime").datetime.now(__import__("datetime").timezone.utc).isoformat(),
                    ),
                )
                orphans.append(orphan_id)
                # Reset any linked work item by item_key inferred from path
                item_key = self._item_key_for_path(rel_path)
                if item_key is not None:
                    item_row = conn.execute(
                        "SELECT id FROM work_items WHERE stage_run_id IN ("
                        "SELECT id FROM stage_runs WHERE run_id = ?"
                        ") AND item_key = ?",
                        (run_id, item_key),
                    ).fetchone()
                    if item_row is not None:
                        item_id = item_row[0]
                        conn.execute(
                            "UPDATE work_items SET status = ?, failure_code = ?, failure_message = ? WHERE id = ?",
                            (
                                ItemStatus.PENDING.value,
                                "artifact_missing",
                                "Artifact missing during reconciliation",
                                item_id,
                            ),
                        )
                        # Only add if not already tracked
                        if item_id not in reset_items:
                            reset_items.append(item_id)

        # Refresh lists with IDs from DB after commit
        with self._db.transaction(immediate=True) as conn:
            repo = self._repo(conn)
            # Build final lists from committed DB state
            preserved_ids = preserved
            invalidated_ids = invalidated
            # Refresh orphan IDs (already persisted)
            orphan_ids = orphans
            # Refresh reset item IDs (already persisted)
            reset_ids = reset_items
        return ReconciliationReport(
            preserved=preserved_ids,
            invalidated=invalidated_ids,
            orphans=orphan_ids,
            reset_items=reset_ids,
        )

    def _resolve_file(self, run_dir: Path, relative_path: str) -> Path | None:
        normalized = relative_path.replace("\\", "/")
        if not normalized or normalized.startswith("/") or ".." in normalized.split("/"):
            return None
        try:
            root = run_dir.resolve(strict=False)
            path = (root / normalized).resolve(strict=False)
            # Ensure resolved path is within root
            root_resolved = root.resolve()
            path_resolved = path.resolve()
            path_resolved.relative_to(root_resolved)
        except (ValueError, FileNotFoundError, OSError):
            return None
        return path_resolved if path_resolved.is_file() else None

    def _discover_known_outputs(self, run_dir: Path) -> list[str]:
        if not run_dir.exists():
            return []
        results: list[str] = []
        for pattern in KNOWN_OUTPUTS:
            if "*" in pattern:
                # Use fnmatch-style glob relative to run_dir
                # For simplicity, scan recursively and match relative paths
                for file_path in run_dir.rglob("*"):
                    if not file_path.is_file():
                        continue
                    rel = file_path.relative_to(run_dir).as_posix()
                    if fnmatch.fnmatch(rel, pattern):
                        results.append(rel)
            else:
                file_path = run_dir / pattern
                if file_path.is_file():
                    results.append(pattern)
        # Deduplicate
        seen = set()
        deduped = []
        for r in results:
            if r not in seen:
                seen.add(r)
                deduped.append(r)
        return deduped

    def _kind_for_path(self, rel_path: str) -> str:
        if rel_path.endswith(".json"):
            return "manifest.json" if "manifesto" in rel_path else ("midia.json" if "midia" in rel_path else "input.json")
        if rel_path.endswith(".wav"):
            return "audio.wav"
        if rel_path.endswith(".png") or rel_path.endswith(".jpg"):
            return "image.png" if rel_path.endswith(".png") else "image.jpg"
        if rel_path.endswith(".mp4"):
            return "video.mp4"
        if rel_path.endswith(".srt"):
            return "subtitle.srt"
        return "unknown"

    def _mime_for_path(self, rel_path: str) -> str:
        if rel_path.endswith(".json"):
            return "application/json"
        if rel_path.endswith(".wav"):
            return "audio/wav"
        if rel_path.endswith(".png"):
            return "image/png"
        if rel_path.endswith(".jpg"):
            return "image/jpeg"
        if rel_path.endswith(".mp4"):
            return "video/mp4"
        if rel_path.endswith(".srt"):
            return "application/x-subrip"
        return "application/octet-stream"

    def _item_key_for_path(self, rel_path: str) -> str | None:
        # Try to infer item_key from basename (e.g., video/audio/b001.wav -> b001)
        basename = Path(rel_path).stem
        # If basename looks like an item key (not frame-*, not validation)
        if basename.startswith("frame-") or basename.startswith("final") or basename in ("narration", "subtitles", "manifesto", "midia", "input", "validation"):
            return None
        # For audio/images, basename is typically the item key
        if basename and len(basename) <= 20:
            return basename
        return None


# Convenience mutation helpers for repository layer

def mark_artifact_not_current(conn, artifact_id: str) -> None:
    conn.execute("UPDATE artifacts SET is_current = 0 WHERE id = ?", (artifact_id,))


def reset_missing_item(conn, work_item_id: str, code: str = "artifact_missing", message: str | None = None) -> None:
    # Per spec: missing -> PENDING with artifact_missing; changed -> FAILED with artifact_hash_mismatch
    # Default to PENDING with the given stable code; caller passes explicit status if needed.
    conn.execute(
        "UPDATE work_items SET status = ?, duration_ms = NULL, failure_code = ?, failure_message = ? WHERE id = ?",
        (
            ItemStatus.PENDING.value,
            code,
            message or "Artifact missing or invalid during reconciliation",
            work_item_id,
        ),
    )


def register_orphan(
    conn,
    orphan_id: str,
    run_id: str,
    relative_path: str,
    sha256: str,
    size_bytes: int,
    kind: str,
    mime_type: str,
    metadata_json: str,
) -> None:
    conn.execute(
        "INSERT INTO artifacts (id, run_id, stage_run_id, work_item_id, kind, relative_path, sha256, size_bytes, mime_type, metadata_json, is_current, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (
            orphan_id,
            run_id,
            None,
            None,
            kind,
            relative_path,
            sha256,
            size_bytes,
            mime_type,
            metadata_json,
            0,
            __import__("datetime").datetime.now(__import__("datetime").timezone.utc).isoformat(),
        ),
    )
