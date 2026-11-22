from __future__ import annotations

import json
import sqlite3
from datetime import UTC, datetime

from forge.domain.operacao import Event


class EventosRepository:
    def __init__(self, conn: sqlite3.Connection) -> None:
        self.conn = conn

    def append(
        self,
        *,
        kind: str,
        level: str,
        message: str,
        payload: dict,
        run_id: str | None = None,
        stage_run_id: str | None = None,
        work_item_id: str | None = None,
    ) -> Event:
        created_at = _now()
        result = self.conn.execute(
            """
            INSERT INTO events (
                run_id, stage_run_id, work_item_id, kind, level, message, payload_json, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                run_id,
                stage_run_id,
                work_item_id,
                kind,
                level,
                message,
                _json(payload),
                _iso(created_at),
            ),
        )
        assert result.lastrowid is not None
        return Event(
            id=result.lastrowid,
            run_id=run_id,
            stage_run_id=stage_run_id,
            work_item_id=work_item_id,
            kind=kind,
            level=level,
            message=message,
            payload=payload,
            created_at=created_at,
        )

    def page(
        self, run_id: str, *, before_id: int | None = None, limit: int = 100
    ) -> list:
        if not 1 <= limit <= 1000:
            raise ValueError("limit must be between 1 and 1000")
        query = "SELECT * FROM events WHERE run_id = ?"
        params: list = [run_id]
        if before_id is not None:
            query += " AND id < ?"
            params.append(before_id)
        query += " ORDER BY id DESC LIMIT ?"
        params.append(limit)
        rows = self.conn.execute(query, params).fetchall()
        return list(reversed([_event_from_row(row) for row in rows]))

    def latest_stage_metrics(self, run_id: str) -> dict:
        rows = self.conn.execute(
            """
            SELECT stage_runs.stage, events.payload_json
            FROM events
            JOIN stage_runs ON stage_runs.id = events.stage_run_id
            JOIN (
                SELECT stage, MAX(attempt) AS attempt
                FROM stage_runs WHERE run_id = ? GROUP BY stage
            ) current ON current.stage = stage_runs.stage
                     AND current.attempt = stage_runs.attempt
            WHERE events.run_id = ? AND events.kind = 'stage.result'
            ORDER BY events.id ASC
            """,
            (run_id, run_id),
        ).fetchall()
        metrics: dict = {}
        for row in rows:
            payload = json.loads(row["payload_json"])
            metrics[row["stage"]] = payload.get("gate", {}).get("metrics", {})
        return metrics

    def after(
        self, cursor: int, *, limit: int = 200, run_id: str | None = None, canal_id: str | None = None
    ) -> list[Event]:
        if cursor < 0:
            raise ValueError("cursor must be nonnegative")
        if not 1 <= limit <= 1000:
            raise ValueError("limit must be between 1 and 1000")

        query = "SELECT * FROM events WHERE id > ?"
        params: tuple[object, ...] = (cursor,)
        if canal_id is not None:
            query += " AND run_id IN (SELECT id FROM runs WHERE canal_id = ?)"
            params += (canal_id,)
        if run_id is not None:
            query += " AND run_id = ?"
            params += (run_id,)
        query += " ORDER BY id ASC LIMIT ?"
        rows = self.conn.execute(query, (*params, limit)).fetchall()
        return [_event_from_row(row) for row in rows]


def _now() -> datetime:
    return datetime.now(UTC)


def _iso(value: datetime) -> str:
    return value.isoformat()


def _json(value: dict) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True)


def _event_from_row(row: sqlite3.Row) -> Event:
    return Event(
        id=row["id"],
        run_id=row["run_id"],
        stage_run_id=row["stage_run_id"],
        work_item_id=row["work_item_id"],
        kind=row["kind"],
        level=row["level"],
        message=row["message"],
        payload=json.loads(row["payload_json"]),
        created_at=datetime.fromisoformat(row["created_at"]),
    )
