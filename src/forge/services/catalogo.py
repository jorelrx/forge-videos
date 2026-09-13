from __future__ import annotations

import hashlib
import uuid
from datetime import UTC, datetime
from pathlib import Path, PureWindowsPath
from typing import Iterator

import sqlite3
from pydantic import ValidationError

from forge.domain.execucao import ReusableOutput, WorkItemPlan
from forge.domain.operacao import Artifact, ItemStatus, StageName
from forge.repositories.operacao import OperacaoRepository

ALLOWED_MIME = {
    "audio/wav", "audio/mpeg", "audio/ogg", "audio/flac",
    "video/mp4", "video/quicktime", "video/x-msvideo",
    "application/json", "text/markdown",
}


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _resolved_run_file(run_dir: Path, relative_path: str) -> Path | None:
    if not isinstance(relative_path, str) or not relative_path:
        return None
    normalized = relative_path.replace("\\", "/")
    if (
        Path(normalized).is_absolute()
        or PureWindowsPath(normalized).is_absolute()
        or ".." in normalized.split("/")
    ):
        return None
    try:
        root = run_dir.resolve(strict=True)
        path = (root / normalized).resolve(strict=True)
        path.relative_to(root)
    except (FileNotFoundError, ValueError):
        return None
    return path if path.is_file() else None


class CatalogoArtefatos:
    """Parent-owned artifact catalog; children submit only run-relative events."""

    # Compatibility for test fixtures that keep manually-entered connections alive.
    _cm_holder: list = []

    def __init__(self, db, run_dir: Path, conn: sqlite3.Connection | None = None) -> None:
        self._db = db
        self._run_dir = Path(run_dir)
        self._conn = conn

    def _connection(self) -> Iterator[sqlite3.Connection]:
        if self._conn is not None:
            class _Existing:
                def __enter__(inner):
                    return self._conn

                def __exit__(inner, *args):
                    return False

            return _Existing()
        return self._db.transaction(immediate=True)

    def register_file(self, *, run, stage_run, item, kind, path, mime_type, metadata) -> Artifact:
        path = Path(path).resolve()
        root = self._run_dir.resolve(strict=True)
        try:
            path.relative_to(root)
        except ValueError as error:
            raise ValueError(f"outside: {path}") from error
        if not path.is_file():
            raise ValueError(f"outside: {path}")
        if mime_type not in ALLOWED_MIME:
            raise ValueError(f"MIME não permitido: {mime_type}")
        artifact = Artifact(
            id=str(uuid.uuid4()), run_id=run.id, stage_run_id=stage_run.id,
            work_item_id=item.id if item is not None else None, kind=kind,
            relative_path=path.relative_to(root).as_posix(), sha256=sha256_file(path),
            size_bytes=path.stat().st_size, mime_type=mime_type, metadata=metadata,
            is_current=True, created_at=datetime.now(UTC),
        )
        with self._connection() as conn:
            return OperacaoRepository(conn).register_artifact(artifact)

    def find_reusable_output(
        self, *, run_id: str, stage: StageName, item_key: str, input_hash: str,
        current_stage_run_id: str | None = None,
    ) -> Artifact | None:
        """Return only a prior succeeded item with an intact current file."""
        with self._connection() as conn:
            repo = OperacaoRepository(conn)
            query = """
                SELECT artifacts.* FROM artifacts
                JOIN work_items ON work_items.id = artifacts.work_item_id
                JOIN stage_runs ON stage_runs.id = work_items.stage_run_id
                WHERE artifacts.run_id = ?
                  AND artifacts.is_current = 1
                  AND work_items.item_key = ?
                  AND work_items.input_hash = ?
                  AND work_items.status = ?
                  AND stage_runs.stage = ?
            """
            params: list[object] = [
                run_id, item_key, input_hash, ItemStatus.SUCCEEDED.value, stage.value,
            ]
            if current_stage_run_id is not None:
                query += " AND stage_runs.id != ?"
                params.append(current_stage_run_id)
            query += " ORDER BY stage_runs.attempt DESC, artifacts.created_at DESC LIMIT 1"
            row = conn.execute(query, params).fetchone()
            if row is None:
                return None
            artifact = repo.list_artifacts(run_id, current_only=False)
            candidate = next(item for item in artifact if item.id == row["id"])
            path = _resolved_run_file(self._run_dir, candidate.relative_path)
            if path is None or path.stat().st_size != candidate.size_bytes:
                return None
            if sha256_file(path) != candidate.sha256:
                return None
            return candidate

    def reusable_outputs(
        self, *, run_id: str, stage: StageName, current_stage_run_id: str,
        items: list[WorkItemPlan],
    ) -> list[ReusableOutput]:
        outputs: list[ReusableOutput] = []
        for item in items:
            artifact = self.find_reusable_output(
                run_id=run_id, stage=stage, item_key=item.item_key,
                input_hash=item.input_hash, current_stage_run_id=current_stage_run_id,
            )
            if artifact is not None:
                outputs.append(ReusableOutput(artifact=artifact, input_hash=item.input_hash))
        return outputs


class ChildProtocolError(Exception):
    pass


class ChildEventProjector:
    # Compatibility for test fixtures that keep manually-entered connections alive.
    _cm_holder: list = []

    def __init__(
        self, db, run_dir: Path, stage_run_id: str | None = None,
        conn: sqlite3.Connection | None = None,
    ) -> None:
        self._db = db
        self._run_dir = Path(run_dir)
        self._stage_run_id = stage_run_id
        self._conn = conn
        self._active_conn: sqlite3.Connection | None = None

    def project(self, kind: str, payload: dict) -> None:
        if self._conn is None:
            with self._db.transaction(immediate=True) as conn:
                self._active_conn = conn
                self._project(kind, payload)
                self._active_conn = None
            return
        self._active_conn = self._conn
        self._project(kind, payload)
        self._active_conn = None

    @property
    def conn(self) -> sqlite3.Connection:
        if self._active_conn is None:
            raise RuntimeError("projector is not active")
        return self._active_conn

    @property
    def repo(self) -> OperacaoRepository:
        return OperacaoRepository(self.conn)

    def _project(self, kind: str, payload: dict) -> None:
        if kind == "item.planned":
            self._project_item_planned(payload)
        elif kind == "item.started":
            self._project_item_started(payload)
        elif kind == "item.succeeded":
            self._project_item_succeeded(payload)
        elif kind == "item.failed":
            self._project_item_failed(payload)
        elif kind == "artifact.created":
            self._project_artifact_created(payload)
        elif kind in {"stage.progress", "stage.result"}:
            return

    def _validate_item_key(self, payload: dict) -> tuple[str, sqlite3.Row]:
        item_key = payload.get("item_key")
        if item_key is None:
            raise ChildProtocolError("item_key is required")
        row = self.conn.execute(
            "SELECT * FROM work_items WHERE stage_run_id = ? AND item_key = ?",
            (self._stage_run_id, item_key),
        ).fetchone()
        if row is None:
            raise ChildProtocolError(f"unknown item_key: {item_key}")
        return item_key, row

    def _item_status(self, item_key: str) -> ItemStatus:
        _, row = self._validate_item_key({"item_key": item_key})
        return ItemStatus(row["status"])

    def _require_transition(self, item_key: str, kind: str, allowed: set[ItemStatus]) -> None:
        current = self._item_status(item_key)
        if current not in allowed:
            allowed_values = ", ".join(sorted(status.value for status in allowed))
            raise ChildProtocolError(
                f"invalid transition for {kind}: {current.value} -> "
                f"{kind.removeprefix('item.')} (expected {allowed_values})"
            )

    def _project_item_planned(self, payload: dict) -> None:
        item_key = payload.get("item_key")
        kind = payload.get("kind")
        destination = payload.get("stage")
        if not item_key:
            raise ChildProtocolError("item_key is required")
        if destination not in {StageName.AUDIO.value, StageName.IMAGENS.value}:
            raise ChildProtocolError("item.planned stage must be 'audio' or 'imagens'")
        expected_kind = "audio" if destination == StageName.AUDIO.value else "imagem"
        if kind != expected_kind:
            raise ChildProtocolError(f"item.planned kind does not match stage: {kind!r}/{destination!r}")
        if "input" not in payload or "input_hash" not in payload:
            raise ChildProtocolError("item.planned requires input and input_hash")
        if self._stage_run_id is None:
            raise ChildProtocolError("stage_run_id is required for item.planned")
        source = self.conn.execute(
            "SELECT run_id FROM stage_runs WHERE id = ?", (self._stage_run_id,)
        ).fetchone()
        if source is None:
            raise ChildProtocolError(f"unknown stage_run_id: {self._stage_run_id}")
        if destination == self.conn.execute(
            "SELECT stage FROM stage_runs WHERE id = ?", (self._stage_run_id,)
        ).fetchone()["stage"]:
            target_stage_id = self._stage_run_id
        else:
            target = next(
                (stage for stage in self.repo.current_stages(source["run_id"]) if stage.stage.value == destination),
                None,
            )
            if target is None:
                raise ChildProtocolError(f"destination stage is not available: {destination}")
            target_stage_id = target.id
        try:
            plan = WorkItemPlan(
                item_key=item_key, input=payload["input"], input_hash=payload["input_hash"],
            )
        except (ValidationError, TypeError) as error:
            raise ChildProtocolError(f"invalid item.planned payload: {error}") from error
        self.repo.upsert_work_items(target_stage_id, [plan])

    def _project_item_started(self, payload: dict) -> None:
        item_key, _ = self._validate_item_key(payload)
        duration_ms = payload.get("duration_ms")
        if duration_ms is None:
            raise ChildProtocolError("duration_ms is required for item.started")
        self._require_transition(item_key, "item.started", {ItemStatus.PENDING, ItemStatus.FAILED})
        result = self.conn.execute(
            "UPDATE work_items SET status = ?, attempts = attempts + 1, duration_ms = ?, "
            "failure_code = NULL, failure_message = NULL WHERE stage_run_id = ? "
            "AND item_key = ? AND status IN (?, ?)",
            (ItemStatus.RUNNING.value, duration_ms, self._stage_run_id, item_key,
             ItemStatus.PENDING.value, ItemStatus.FAILED.value),
        )
        if result.rowcount != 1:
            raise ChildProtocolError("item.started transition was not applied")

    def _project_item_succeeded(self, payload: dict) -> None:
        item_key, _ = self._validate_item_key(payload)
        self._require_transition(item_key, "item.succeeded", {ItemStatus.RUNNING})
        result = self.conn.execute(
            "UPDATE work_items SET status = ?, duration_ms = ?, failure_code = NULL, "
            "failure_message = NULL WHERE stage_run_id = ? AND item_key = ? AND status = ?",
            (ItemStatus.SUCCEEDED.value, payload.get("duration_ms"), self._stage_run_id,
             item_key, ItemStatus.RUNNING.value),
        )
        if result.rowcount != 1:
            raise ChildProtocolError("item.succeeded transition was not applied")

    def _project_item_failed(self, payload: dict) -> None:
        item_key, _ = self._validate_item_key(payload)
        failure_code = payload.get("failure_code")
        failure_message = payload.get("failure_message")
        self._require_transition(item_key, "item.failed", {ItemStatus.RUNNING})
        result = self.conn.execute(
            "UPDATE work_items SET status = ?, failure_code = ?, failure_message = ? "
            "WHERE stage_run_id = ? AND item_key = ? AND status = ?",
            (ItemStatus.FAILED.value, failure_code, failure_message, self._stage_run_id,
             item_key, ItemStatus.RUNNING.value),
        )
        if result.rowcount != 1:
            raise ChildProtocolError("item.failed transition was not applied")

    def _project_artifact_created(self, payload: dict) -> None:
        item_key = payload.get("item_key")
        mime_type = payload.get("mime_type", "")
        if mime_type not in ALLOWED_MIME:
            raise ValueError(f"MIME não permitido: {mime_type}")
        path = _resolved_run_file(self._run_dir, payload.get("relative_path", ""))
        if path is None:
            raise ChildProtocolError("path outside run_dir or not a regular file")
        if item_key is None:
            raise ChildProtocolError("unknown item_key")
        stage_row = self.conn.execute(
            "SELECT run_id FROM stage_runs WHERE id = ?", (self._stage_run_id,)
        ).fetchone()
        if stage_row is None:
            raise ChildProtocolError(f"unknown stage_run_id: {self._stage_run_id}")
        work_item_id = None
        if item_key != "":
            _, item = self._validate_item_key(payload)
            work_item_id = item["id"]
        artifact = Artifact(
            id=str(uuid.uuid4()), run_id=stage_row["run_id"], stage_run_id=self._stage_run_id,
            work_item_id=work_item_id, kind=payload.get("kind", ""),
            relative_path=path.relative_to(self._run_dir.resolve(strict=True)).as_posix(),
            sha256=sha256_file(path), size_bytes=path.stat().st_size, mime_type=mime_type,
            metadata=payload.get("metadata", {}), is_current=True, created_at=datetime.now(UTC),
        )
        self.repo.register_artifact(artifact)


__all__ = [
    "ALLOWED_MIME", "CatalogoArtefatos", "ChildEventProjector", "ChildProtocolError",
    "sha256_file",
]
