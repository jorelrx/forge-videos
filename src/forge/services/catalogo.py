from __future__ import annotations

import hashlib
import json
import uuid
from datetime import datetime
from pathlib import Path

import sqlite3

from forge.domain.operacao import ItemStatus
from forge.repositories.operacao import OperacaoRepository


ALLOWED_MIME = {
    "audio/wav", "audio/mpeg", "audio/ogg", "audio/flac",
    "video/mp4", "video/quicktime", "video/x-msvideo",
    "application/json",
}


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


class CatalogoArtefatos:
    _cm_holder: list = []

    def __init__(self, db, run_dir: Path, conn: sqlite3.Connection | None = None) -> None:
        self._db = db
        if conn is not None:
            self._conn = conn
        else:
            self._cm = db.connection()
            CatalogoArtefatos._cm_holder.append(self._cm)
            self._conn = self._cm.__enter__()
        self._run_dir = run_dir
        self._repo = OperacaoRepository(self._conn)

    def register_file(
        self, *, run, stage_run, item, kind, path, mime_type, metadata
    ) -> Artifact:
        try:
            resolved = path.resolve(strict=True)
        except FileNotFoundError:
            raise ValueError(f"outside: {path}")
        try:
            resolved.relative_to(self._run_dir.resolve(strict=True))
        except ValueError:
            raise ValueError(f"outside: {path}")
        if mime_type not in ALLOWED_MIME:
            raise ValueError(f"MIME não permitido: {mime_type}")
        return self._persist(
            run=run, stage_run=stage_run, item=item, kind=kind,
            relative_path=resolved.relative_to(self._run_dir).as_posix(),
            sha256=sha256_file(resolved), size_bytes=resolved.stat().st_size,
            mime_type=mime_type, metadata=metadata,
        )

    def _persist(
        self, *, run, stage_run, item, kind, relative_path, sha256,
        size_bytes, mime_type, metadata
    ) -> Artifact:
        work_item_id = item.id if item is not None else None
        artifact_id = str(uuid.uuid4())
        self._conn.execute(
            "INSERT INTO artifacts "
            "(id, run_id, stage_run_id, work_item_id, kind, relative_path, sha256, "
            "size_bytes, mime_type, metadata_json, is_current, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (artifact_id, run.id, stage_run.id, work_item_id, kind,
             relative_path, sha256, size_bytes, mime_type,
             json.dumps(metadata), True, datetime.now().isoformat()),
        )
        self._conn.commit()
        return _artifact_from_row(
            self._conn.execute(
                "SELECT * FROM artifacts WHERE id = ?", (artifact_id,)
            ).fetchone()
        )

    def register_artifact(self, artifact: Artifact) -> Artifact:
        if self._conn.execute(
            "SELECT 1 FROM runs WHERE id = ?", (artifact.run_id,)
        ).fetchone() is None:
            raise ValueError(f"run {artifact.run_id} não encontrada")
        result = self._conn.execute(
            "INSERT INTO artifacts "
            "(id, run_id, stage_run_id, work_item_id, kind, relative_path, sha256, "
            "size_bytes, mime_type, metadata_json, is_current, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (artifact.id, artifact.run_id, artifact.stage_run_id,
             artifact.work_item_id, artifact.kind, artifact.relative_path,
             artifact.sha256, artifact.size_bytes, artifact.mime_type,
             json.dumps(artifact.metadata), artifact.is_current,
             artifact.created_at.isoformat()),
        )
        artifact_id = result.lastrowid
        artifact_row = self._conn.execute(
            "SELECT * FROM artifacts WHERE id = ?", (artifact_id,)
        ).fetchone()
        return _artifact_from_row(artifact_row)

    def list_artifacts(self, run_id: str) -> list[Artifact]:
        rows = self._conn.execute(
            "SELECT * FROM artifacts WHERE run_id = ? ORDER BY created_at", (run_id,)
        ).fetchall()
        return [_artifact_from_row(row) for row in rows]

    def invalidate_artifacts(self, run_id: str) -> None:
        self._conn.execute("UPDATE artifacts SET is_current = 0 WHERE run_id = ?", (run_id,))

    def list_artifacts_by_item(self, work_item_id: str) -> list[Artifact]:
        rows = self._conn.execute(
            "SELECT * FROM artifacts WHERE work_item_id = ?", (work_item_id,)
        ).fetchall()
        return [_artifact_from_row(row) for row in rows]


def _artifact_from_row(row: sqlite3.Row) -> Artifact:
    from forge.domain.operacao import Artifact
    return Artifact(
        id=row["id"], run_id=row["run_id"], stage_run_id=row["stage_run_id"],
        work_item_id=row["work_item_id"], kind=row["kind"],
        relative_path=row["relative_path"], sha256=row["sha256"],
        size_bytes=row["size_bytes"], mime_type=row["mime_type"],
        metadata=json.loads(row["metadata_json"]),
        is_current=bool(row["is_current"]),
        created_at=datetime.fromisoformat(row["created_at"]).replace(tzinfo=__import__("datetime").timezone.utc),
    )


class ChildProtocolError(Exception):
    pass


class ChildEventProjector:
    _cm_holder: list = []

    def __init__(self, db, run_dir: Path, stage_run_id: str | None = None, conn: sqlite3.Connection | None = None) -> None:
        self._db = db
        if conn is not None:
            self._conn = conn
        else:
            self._cm = db.connection()
            ChildEventProjector._cm_holder.append(self._cm)
            self._conn = self._cm.__enter__()
        self._run_dir = run_dir
        self._repo = OperacaoRepository(self._conn)
        self._stage_run_id = stage_run_id

    def project(self, kind: str, payload: dict) -> None:
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
        elif kind == "stage.progress":
            self._project_stage_progress(payload)
        elif kind == "stage.result":
            self._project_stage_result(payload)

    def _validate_item_key(self, payload: dict) -> str:
        item_key = payload.get("item_key")
        if item_key is None:
            raise ChildProtocolError("item_key is required")
        stage_run_id = self._stage_run_id
        row = self._conn.execute(
            "SELECT 1 FROM work_items WHERE stage_run_id = ? AND item_key = ?",
            (stage_run_id, item_key),
        ).fetchone()
        if row is None:
            raise ChildProtocolError(f"unknown item_key: {item_key}")
        return item_key

    def _project_item_planned(self, payload: dict) -> None:
        item_key = self._validate_item_key(payload)
        kind = payload.get("kind")
        if kind is None:
            raise ChildProtocolError("kind is required for item.planned")

    def _project_item_started(self, payload: dict) -> None:
        item_key = self._validate_item_key(payload)
        duration_ms = payload.get("duration_ms")
        if duration_ms is None:
            raise ChildProtocolError("duration_ms is required for item.started")

    def _project_item_succeeded(self, payload: dict) -> None:
        item_key = self._validate_item_key(payload)
        self._conn.execute(
            "UPDATE work_items SET status = ?, duration_ms = ? WHERE stage_run_id = ? AND item_key = ?",
            (ItemStatus.SUCCEEDED.value, payload.get("duration_ms"), self._stage_run_id, item_key),
        )

    def _project_item_failed(self, payload: dict) -> None:
        item_key = self._validate_item_key(payload)
        failure_code = payload.get("failure_code")
        failure_message = payload.get("failure_message")
        self._conn.execute(
            "UPDATE work_items SET status = ?, failure_code = ?, failure_message = ? WHERE stage_run_id = ? AND item_key = ?",
            (ItemStatus.FAILED.value, failure_code, failure_message, self._stage_run_id, item_key),
        )

    def _project_artifact_created(self, payload: dict) -> None:
        item_key = payload.get("item_key")
        relative_path = payload.get("relative_path", "")
        if ".." in relative_path.split("/"):
            raise ChildProtocolError("path outside run_dir")
        mime_type = payload.get("mime_type", "")
        if mime_type not in ALLOWED_MIME:
            raise ValueError(f"MIME não permitido: {mime_type}")
        if item_key is None:
            raise ChildProtocolError("unknown item_key")
        if item_key is not None and item_key != "":
            self._validate_item_key(payload)

    def _project_stage_progress(self, payload: dict) -> None:
        pass

    def _project_stage_result(self, payload: dict) -> None:
        pass
