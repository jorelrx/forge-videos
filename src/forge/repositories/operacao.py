from __future__ import annotations

import json
import sqlite3
import uuid
from datetime import UTC, datetime, timedelta

from forge.domain.operacao import (
    ETAPAS,
    Artifact,
    Run,
    RunStatus,
    StageName,
    StageRun,
    StageStatus,
    Video,
    dependentes_de,
)

_ACTIVE_RUN_STATUSES = (
    RunStatus.PREPARING,
    RunStatus.RUNNING,
    RunStatus.PAUSING,
    RunStatus.VALIDATING,
)
_CURRENT_STAGE_STATUS = {
    RunStatus.PREPARING: StageStatus.PENDING,
    RunStatus.RUNNING: StageStatus.RUNNING,
    RunStatus.PAUSING: StageStatus.PAUSING,
    RunStatus.VALIDATING: StageStatus.RUNNING,
}


class OperacaoRepository:
    def __init__(self, conn: sqlite3.Connection) -> None:
        self.conn = conn

    def create_video_and_run(
        self,
        *,
        tema: str,
        tese: str | None,
        priority: int,
        config_snapshot: dict,
        workflow_version: int,
        git_commit: str,
    ) -> tuple[Video, Run]:
        now = _now()
        video = Video(
            id=str(uuid.uuid4()),
            tema=tema,
            tese=tese,
            created_at=now,
            updated_at=now,
        )
        queue_position = self.conn.execute(
            "SELECT COALESCE(MAX(queue_position), 0) + 1 FROM runs WHERE status = ?",
            (RunStatus.QUEUED.value,),
        ).fetchone()[0]
        run = Run(
            id=str(uuid.uuid4()),
            video_id=video.id,
            status=RunStatus.QUEUED,
            priority=priority,
            queue_position=queue_position,
            config_snapshot=config_snapshot,
            workflow_version=workflow_version,
            git_commit=git_commit,
            created_at=now,
        )
        self.conn.execute(
            """
            INSERT INTO videos (id, tema, tese, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?)
            """,
            (video.id, video.tema, video.tese, _iso(video.created_at), _iso(video.updated_at)),
        )
        self.conn.execute(
            """
            INSERT INTO runs (
                id, video_id, status, priority, queue_position, config_snapshot_json,
                workflow_version, git_commit, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                run.id,
                run.video_id,
                run.status.value,
                run.priority,
                run.queue_position,
                _json(run.config_snapshot),
                run.workflow_version,
                run.git_commit,
                _iso(run.created_at),
            ),
        )
        self.conn.executemany(
            """
            INSERT INTO stage_runs (id, run_id, stage, attempt, status, created_at)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            [
                (
                    str(uuid.uuid4()),
                    run.id,
                    stage.value,
                    1,
                    StageStatus.PENDING.value,
                    _iso(now),
                )
                for stage in ETAPAS
            ],
        )
        return video, run

    def get_run(self, run_id: str) -> Run | None:
        row = self.conn.execute("SELECT * FROM runs WHERE id = ?", (run_id,)).fetchone()
        return _run_from_row(row) if row is not None else None

    def list_queue(self) -> list[Run]:
        rows = self.conn.execute(
            """
            SELECT * FROM runs
            WHERE status = ?
            ORDER BY priority DESC, queue_position ASC, created_at ASC
            """,
            (RunStatus.QUEUED.value,),
        ).fetchall()
        return [_run_from_row(row) for row in rows]

    def list_runs(self, *, limit: int = 50, offset: int = 0) -> list[Run]:
        if limit < 0 or offset < 0:
            raise ValueError("limit and offset must be nonnegative")
        rows = self.conn.execute(
            "SELECT * FROM runs ORDER BY created_at DESC, id DESC LIMIT ? OFFSET ?",
            (limit, offset),
        ).fetchall()
        return [_run_from_row(row) for row in rows]

    def current_stages(self, run_id: str) -> list[StageRun]:
        rows = self.conn.execute(
            f"""
            SELECT stage_runs.* FROM stage_runs
            JOIN (
                SELECT stage, MAX(attempt) AS attempt
                FROM stage_runs
                WHERE run_id = ?
                GROUP BY stage
            ) current
                ON current.stage = stage_runs.stage AND current.attempt = stage_runs.attempt
            WHERE stage_runs.run_id = ?
            ORDER BY {_stage_order_sql('stage_runs.stage')}
            """,
            (run_id, run_id),
        ).fetchall()
        return [_stage_from_row(row) for row in rows]

    def claim_next(self, worker_id: str, *, lease_seconds: int) -> Run | None:
        _validate_lease_request(worker_id, lease_seconds)

        active_placeholders = ", ".join("?" for _ in _ACTIVE_RUN_STATUSES)
        now = _now()
        row = self.conn.execute(
            f"""
            UPDATE runs
            SET status = ?, lease_owner = ?, lease_expires_at = ?,
                started_at = COALESCE(started_at, ?)
            WHERE id = (
                SELECT id FROM runs
                WHERE status = ?
                ORDER BY priority DESC, queue_position ASC, created_at ASC
                LIMIT 1
            )
              AND status = ?
              AND NOT EXISTS (
                  SELECT 1 FROM runs WHERE status IN ({active_placeholders})
              )
            RETURNING *
            """,
            (
                RunStatus.PREPARING.value,
                worker_id,
                _iso(now + timedelta(seconds=lease_seconds)),
                _iso(now),
                RunStatus.QUEUED.value,
                RunStatus.QUEUED.value,
                *(status.value for status in _ACTIVE_RUN_STATUSES),
            ),
        ).fetchone()
        if row is None:
            return None
        return _run_from_row(row)

    def renew_lease(
        self, run_id: str, worker_id: str, *, lease_seconds: int
    ) -> Run | None:
        _validate_lease_request(worker_id, lease_seconds)
        now = _now()
        active_placeholders = ", ".join("?" for _ in _ACTIVE_RUN_STATUSES)
        result = self.conn.execute(
            f"""
            UPDATE runs
            SET lease_expires_at = ?
            WHERE id = ?
              AND lease_owner = ?
              AND lease_expires_at > ?
              AND status IN ({active_placeholders})
            """,
            (
                _iso(now + timedelta(seconds=lease_seconds)),
                run_id,
                worker_id,
                _iso(now),
                *(status.value for status in _ACTIVE_RUN_STATUSES),
            ),
        )
        if result.rowcount != 1:
            return None
        return self.get_run(run_id)

    def interrupt_expired(self, now: datetime) -> list[Run]:
        active_placeholders = ", ".join("?" for _ in _ACTIVE_RUN_STATUSES)
        rows = self.conn.execute(
            f"""
            SELECT id, status FROM runs
            WHERE status IN ({active_placeholders})
              AND lease_expires_at IS NOT NULL
              AND lease_expires_at <= ?
            """,
            (*(status.value for status in _ACTIVE_RUN_STATUSES), _iso(now)),
        ).fetchall()
        run_ids = [row["id"] for row in rows]
        if not run_ids:
            return []

        stage_ids = []
        for row in rows:
            expected_status = _CURRENT_STAGE_STATUS[RunStatus(row["status"])]
            current_stage = next(
                (
                    stage
                    for stage in self.current_stages(row["id"])
                    if stage.status is expected_status
                ),
                None,
            )
            if current_stage is not None:
                stage_ids.append(current_stage.id)

        if stage_ids:
            stage_placeholders = ", ".join("?" for _ in stage_ids)
            self.conn.execute(
                f"UPDATE stage_runs SET status = ? WHERE id IN ({stage_placeholders})",
                (StageStatus.INTERRUPTED.value, *stage_ids),
            )

        run_placeholders = ", ".join("?" for _ in run_ids)
        self.conn.execute(
            f"""
            UPDATE runs
            SET status = ?, lease_owner = NULL, lease_expires_at = NULL
            WHERE id IN ({run_placeholders})
            """,
            (RunStatus.INTERRUPTED.value, *run_ids),
        )
        interrupted: list[Run] = []
        for run_id in run_ids:
            run = self.get_run(run_id)
            if run is not None:
                interrupted.append(run)
        return interrupted

    def save_run(self, run: Run) -> Run:
        result = self.conn.execute(
            """
            UPDATE runs
            SET status = ?, priority = ?, queue_position = ?, config_snapshot_json = ?,
                workflow_version = ?, git_commit = ?, lease_owner = ?, lease_expires_at = ?,
                pause_requested_at = ?, started_at = ?, finished_at = ?, failure_code = ?,
                failure_message = ?
            WHERE id = ?
            """,
            (
                run.status.value,
                run.priority,
                run.queue_position,
                _json(run.config_snapshot),
                run.workflow_version,
                run.git_commit,
                run.lease_owner,
                _iso(run.lease_expires_at),
                _iso(run.pause_requested_at),
                _iso(run.started_at),
                _iso(run.finished_at),
                run.failure_code,
                run.failure_message,
                run.id,
            ),
        )
        if result.rowcount != 1:
            raise KeyError(run.id)
        return run

    def save_stage(self, stage: StageRun) -> StageRun:
        result = self.conn.execute(
            """
            UPDATE stage_runs
            SET status = ?, current_items = ?, total_items = ?, progress = ?,
                gate_status = ?, input_hash = ?, started_at = ?, finished_at = ?,
                failure_code = ?, failure_message = ?
            WHERE id = ?
            """,
            (
                stage.status.value,
                stage.current_items,
                stage.total_items,
                stage.progress,
                stage.gate_status,
                stage.input_hash,
                _iso(stage.started_at),
                _iso(stage.finished_at),
                stage.failure_code,
                stage.failure_message,
                stage.id,
            ),
        )
        if result.rowcount != 1:
            raise KeyError(stage.id)
        return stage

    def invalidate_from_stage(self, run_id: str, stage: StageName) -> list[StageRun]:
        if self.conn.execute("SELECT 1 FROM runs WHERE id = ?", (run_id,)).fetchone() is None:
            raise KeyError(run_id)

        dependent_stages = dependentes_de(stage)
        placeholders = ", ".join("?" for _ in dependent_stages)
        rows = self.conn.execute(
            f"""
            SELECT stage_runs.* FROM stage_runs
            JOIN (
                SELECT stage, MAX(attempt) AS attempt
                FROM stage_runs
                WHERE run_id = ? AND stage IN ({placeholders})
                GROUP BY stage
            ) current
                ON current.stage = stage_runs.stage AND current.attempt = stage_runs.attempt
            WHERE stage_runs.run_id = ?
            ORDER BY {_stage_order_sql('stage_runs.stage')}
            """,
            (run_id, *(item.value for item in dependent_stages), run_id),
        ).fetchall()
        self.conn.executemany(
            "UPDATE stage_runs SET status = ? WHERE id = ?",
            [(StageStatus.INVALIDATED.value, row["id"]) for row in rows],
        )

        now = _now()
        new_stages = [
            StageRun(
                id=str(uuid.uuid4()),
                run_id=run_id,
                stage=StageName(row["stage"]),
                attempt=row["attempt"] + 1,
                status=StageStatus.PENDING,
                created_at=now,
            )
            for row in rows
        ]
        self.conn.executemany(
            """
            INSERT INTO stage_runs (
                id, run_id, stage, attempt, status, current_items, total_items, progress,
                gate_status, input_hash, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            [
                (
                    item.id,
                    item.run_id,
                    item.stage.value,
                    item.attempt,
                    item.status.value,
                    item.current_items,
                    item.total_items,
                    item.progress,
                    item.gate_status,
                    item.input_hash,
                    _iso(item.created_at),
                )
                for item in new_stages
            ],
        )
        return new_stages

    def register_artifact(self, artifact: Artifact) -> Artifact:
        if self.conn.execute(
            "SELECT 1 FROM runs WHERE id = ?", (artifact.run_id,)
        ).fetchone() is None:
            raise KeyError(artifact.run_id)
        stage_run = self.conn.execute(
            "SELECT status FROM stage_runs WHERE id = ?", (artifact.stage_run_id,)
        ).fetchone()
        if stage_run is None:
            raise KeyError(artifact.stage_run_id)
        if artifact.work_item_id is not None and self.conn.execute(
            "SELECT 1 FROM work_items WHERE id = ?", (artifact.work_item_id,)
        ).fetchone() is None:
            raise KeyError(artifact.work_item_id)

        persisted = artifact.model_copy(
            update={
                "is_current": artifact.is_current
                and stage_run["status"] != StageStatus.INVALIDATED.value
            }
        )
        self.conn.execute(
            """
            INSERT INTO artifacts (
                id, run_id, stage_run_id, work_item_id, kind, relative_path, sha256,
                size_bytes, mime_type, metadata_json, is_current, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                persisted.id,
                persisted.run_id,
                persisted.stage_run_id,
                persisted.work_item_id,
                persisted.kind,
                persisted.relative_path,
                persisted.sha256,
                persisted.size_bytes,
                persisted.mime_type,
                _json(persisted.metadata),
                int(persisted.is_current),
                _iso(persisted.created_at),
            ),
        )
        return persisted

    def invalidate_artifacts(self, run_id: str, stages: tuple[StageName, ...]) -> int:
        if self.conn.execute("SELECT 1 FROM runs WHERE id = ?", (run_id,)).fetchone() is None:
            raise KeyError(run_id)
        if not stages:
            return 0
        placeholders = ", ".join("?" for _ in stages)
        result = self.conn.execute(
            f"""
            UPDATE artifacts SET is_current = 0
            WHERE run_id = ? AND is_current = 1
              AND stage_run_id IN (
                  SELECT id FROM stage_runs
                  WHERE run_id = ? AND stage IN ({placeholders})
              )
            """,
            (run_id, run_id, *(stage.value for stage in stages)),
        )
        return result.rowcount

    def list_artifacts(self, run_id: str, *, current_only: bool = True) -> list[Artifact]:
        query = "SELECT * FROM artifacts WHERE run_id = ?"
        params: tuple[object, ...] = (run_id,)
        if current_only:
            query += " AND is_current = 1"
        query += " ORDER BY created_at ASC, id ASC"
        rows = self.conn.execute(query, params).fetchall()
        return [_artifact_from_row(row) for row in rows]


def _now() -> datetime:
    return datetime.now(UTC)


def _validate_lease_request(worker_id: str, lease_seconds: int) -> None:
    if not worker_id.strip():
        raise ValueError("worker_id must not be blank")
    if lease_seconds <= 0:
        raise ValueError("lease_seconds must be positive")


def _iso(value: datetime | None) -> str | None:
    return value.isoformat() if value is not None else None


def _json(value: dict) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True)


def _stage_order_sql(column: str) -> str:
    clauses = " ".join(
        f"WHEN '{stage.value}' THEN {index}" for index, stage in enumerate(ETAPAS)
    )
    return f"CASE {column} {clauses} END"


def _datetime(value: str | None) -> datetime | None:
    return datetime.fromisoformat(value) if value is not None else None


def _run_from_row(row: sqlite3.Row) -> Run:
    return Run(
        id=row["id"],
        video_id=row["video_id"],
        status=row["status"],
        priority=row["priority"],
        queue_position=row["queue_position"],
        config_snapshot=json.loads(row["config_snapshot_json"]),
        workflow_version=row["workflow_version"],
        git_commit=row["git_commit"],
        lease_owner=row["lease_owner"],
        lease_expires_at=_datetime(row["lease_expires_at"]),
        pause_requested_at=_datetime(row["pause_requested_at"]),
        created_at=_datetime(row["created_at"]),
        started_at=_datetime(row["started_at"]),
        finished_at=_datetime(row["finished_at"]),
        failure_code=row["failure_code"],
        failure_message=row["failure_message"],
    )


def _stage_from_row(row: sqlite3.Row) -> StageRun:
    return StageRun(
        id=row["id"],
        run_id=row["run_id"],
        stage=row["stage"],
        attempt=row["attempt"],
        status=row["status"],
        current_items=row["current_items"],
        total_items=row["total_items"],
        progress=row["progress"],
        gate_status=row["gate_status"],
        input_hash=row["input_hash"],
        created_at=_datetime(row["created_at"]),
        started_at=_datetime(row["started_at"]),
        finished_at=_datetime(row["finished_at"]),
        failure_code=row["failure_code"],
        failure_message=row["failure_message"],
    )


def _artifact_from_row(row: sqlite3.Row) -> Artifact:
    return Artifact(
        id=row["id"],
        run_id=row["run_id"],
        stage_run_id=row["stage_run_id"],
        work_item_id=row["work_item_id"],
        kind=row["kind"],
        relative_path=row["relative_path"],
        sha256=row["sha256"],
        size_bytes=row["size_bytes"],
        mime_type=row["mime_type"],
        metadata=json.loads(row["metadata_json"]),
        is_current=bool(row["is_current"]),
        created_at=_datetime(row["created_at"]),
    )
