from __future__ import annotations

import json
import sqlite3
import uuid
from datetime import UTC, datetime

from forge.domain.operacao import Command, CommandStatus, CommandType, StageName


class IdempotencyConflict(ValueError):
    def __init__(self, run_id: str, idempotency_key: str) -> None:
        super().__init__(
            f"idempotency key {idempotency_key!r} already has another payload "
            f"for run {run_id}"
        )


class ComandosRepository:
    def __init__(self, conn: sqlite3.Connection) -> None:
        self.conn = conn

    def create_idempotent(
        self,
        *,
        run_id: str,
        type: CommandType,
        stage: StageName | None,
        idempotency_key: str,
        status: CommandStatus,
    ) -> tuple[Command, bool]:
        if not idempotency_key.strip():
            raise ValueError("idempotency_key must not be blank")

        existing = self.conn.execute(
            "SELECT * FROM commands WHERE run_id = ? AND idempotency_key = ?",
            (run_id, idempotency_key),
        ).fetchone()
        if existing is not None:
            command = _command_from_row(existing)
            if command.type == type and command.stage == stage:
                return command, False
            raise IdempotencyConflict(run_id, idempotency_key)

        created_at = _now()
        applied_at = (
            created_at
            if status in {CommandStatus.APPLIED, CommandStatus.REJECTED}
            else None
        )
        command = Command(
            id=str(uuid.uuid4()),
            run_id=run_id,
            type=type,
            stage=stage,
            idempotency_key=idempotency_key,
            status=status,
            result={},
            created_at=created_at,
            applied_at=applied_at,
        )
        try:
            self.conn.execute(
                """
                INSERT INTO commands (
                    id, run_id, type, stage, idempotency_key, status, result_json, created_at, applied_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    command.id,
                    command.run_id,
                    command.type.value,
                    command.stage.value if command.stage is not None else None,
                    command.idempotency_key,
                    command.status.value,
                    _json(command.result),
                    _iso(command.created_at),
                    _iso(command.applied_at) if command.applied_at is not None else None,
                ),
            )
        except sqlite3.IntegrityError:
            existing = self.conn.execute(
                "SELECT * FROM commands WHERE run_id = ? AND idempotency_key = ?",
                (run_id, idempotency_key),
            ).fetchone()
            if existing is None:
                raise
            command = _command_from_row(existing)
            if command.type == type and command.stage == stage:
                return command, False
            raise IdempotencyConflict(run_id, idempotency_key)
        return command, True

    def get(self, command_id: str) -> Command | None:
        row = self.conn.execute("SELECT * FROM commands WHERE id = ?", (command_id,)).fetchone()
        return _command_from_row(row) if row is not None else None

    def pending(self, run_id: str) -> list[Command]:
        rows = self.conn.execute(
            """
            SELECT * FROM commands
            WHERE run_id = ? AND status = ?
            ORDER BY created_at ASC, id ASC
            """,
            (run_id, CommandStatus.PENDING.value),
        ).fetchall()
        return [_command_from_row(row) for row in rows]

    def set_status(
        self, command_id: str, status: CommandStatus, *, result: dict
    ) -> Command:
        applied_at = _now() if status in {CommandStatus.APPLIED, CommandStatus.REJECTED} else None
        updated = self.conn.execute(
            """
            UPDATE commands
            SET status = ?, result_json = ?, applied_at = ?
            WHERE id = ?
            """,
            (status.value, _json(result), _iso(applied_at) if applied_at is not None else None, command_id),
        )
        if updated.rowcount != 1:
            raise KeyError(command_id)
        command = self.get(command_id)
        assert command is not None
        return command


def _now() -> datetime:
    return datetime.now(UTC)


def _iso(value: datetime) -> str:
    return value.isoformat()


def _json(value: dict) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True)


def _command_from_row(row: sqlite3.Row) -> Command:
    return Command(
        id=row["id"],
        run_id=row["run_id"],
        type=row["type"],
        stage=row["stage"],
        idempotency_key=row["idempotency_key"],
        status=row["status"],
        result=json.loads(row["result_json"]),
        created_at=datetime.fromisoformat(row["created_at"]),
        applied_at=(
            datetime.fromisoformat(row["applied_at"]) if row["applied_at"] is not None else None
        ),
    )
