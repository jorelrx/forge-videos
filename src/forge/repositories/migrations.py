from __future__ import annotations

import sqlite3
from collections.abc import Callable

from forge.repositories.connection import Database

LATEST_SCHEMA_VERSION = 3

SCHEMA_SQL = (
    """
    CREATE TABLE IF NOT EXISTS schema_version (
        id INTEGER PRIMARY KEY CHECK(id = 1),
        version INTEGER NOT NULL
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS videos (
        id TEXT PRIMARY KEY,
        tema TEXT NOT NULL CHECK(length(trim(tema)) > 0),
        tese TEXT,
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS runs (
        id TEXT PRIMARY KEY,
        video_id TEXT NOT NULL REFERENCES videos(id),
        status TEXT NOT NULL,
        priority INTEGER NOT NULL CHECK(priority BETWEEN 0 AND 100),
        queue_position INTEGER NOT NULL CHECK(queue_position >= 1),
        config_snapshot_json TEXT NOT NULL,
        workflow_version INTEGER NOT NULL CHECK(workflow_version >= 1),
        git_commit TEXT NOT NULL,
        lease_owner TEXT,
        lease_expires_at TEXT,
        pause_requested_at TEXT,
        created_at TEXT NOT NULL,
        started_at TEXT,
        finished_at TEXT,
        failure_code TEXT,
        failure_message TEXT
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS stage_runs (
        id TEXT PRIMARY KEY,
        run_id TEXT NOT NULL REFERENCES runs(id),
        stage TEXT NOT NULL,
        attempt INTEGER NOT NULL CHECK(attempt >= 1),
        status TEXT NOT NULL,
        current_items INTEGER NOT NULL DEFAULT 0 CHECK(current_items >= 0),
        total_items INTEGER NOT NULL DEFAULT 0 CHECK(total_items >= 0),
        progress REAL NOT NULL DEFAULT 0 CHECK(progress BETWEEN 0 AND 1),
        gate_status TEXT,
        input_hash TEXT,
        created_at TEXT NOT NULL,
        started_at TEXT,
        finished_at TEXT,
        failure_code TEXT,
        failure_message TEXT,
        UNIQUE(run_id, id),
        UNIQUE(run_id, stage, attempt)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS work_items (
        id TEXT PRIMARY KEY,
        stage_run_id TEXT NOT NULL REFERENCES stage_runs(id),
        item_key TEXT NOT NULL,
        status TEXT NOT NULL,
        input_json TEXT NOT NULL,
        input_hash TEXT NOT NULL,
        attempts INTEGER NOT NULL DEFAULT 0 CHECK(attempts >= 0),
        duration_ms INTEGER CHECK(duration_ms >= 0),
        failure_code TEXT,
        failure_message TEXT,
        UNIQUE(stage_run_id, id),
        UNIQUE(stage_run_id, item_key)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS artifacts (
        id TEXT PRIMARY KEY,
        run_id TEXT NOT NULL REFERENCES runs(id),
        stage_run_id TEXT REFERENCES stage_runs(id),
        work_item_id TEXT REFERENCES work_items(id),
        kind TEXT NOT NULL,
        relative_path TEXT NOT NULL,
        sha256 TEXT NOT NULL,
        size_bytes INTEGER NOT NULL CHECK(size_bytes >= 0),
        mime_type TEXT NOT NULL,
        metadata_json TEXT NOT NULL,
        is_current INTEGER NOT NULL DEFAULT 1 CHECK(is_current IN (0, 1)),
        created_at TEXT NOT NULL,
        FOREIGN KEY (run_id, stage_run_id) REFERENCES stage_runs(run_id, id),
        FOREIGN KEY (stage_run_id, work_item_id) REFERENCES work_items(stage_run_id, id)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS events (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        run_id TEXT REFERENCES runs(id),
        stage_run_id TEXT REFERENCES stage_runs(id),
        work_item_id TEXT REFERENCES work_items(id),
        kind TEXT NOT NULL,
        level TEXT NOT NULL,
        message TEXT NOT NULL,
        payload_json TEXT NOT NULL,
        created_at TEXT NOT NULL,
        CHECK(stage_run_id IS NULL OR run_id IS NOT NULL),
        CHECK(work_item_id IS NULL OR (stage_run_id IS NOT NULL AND run_id IS NOT NULL)),
        FOREIGN KEY (run_id, stage_run_id) REFERENCES stage_runs(run_id, id),
        FOREIGN KEY (stage_run_id, work_item_id) REFERENCES work_items(stage_run_id, id)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS commands (
        id TEXT PRIMARY KEY,
        run_id TEXT NOT NULL REFERENCES runs(id),
        type TEXT NOT NULL,
        stage TEXT,
        idempotency_key TEXT NOT NULL,
        status TEXT NOT NULL,
        result_json TEXT NOT NULL,
        created_at TEXT NOT NULL,
        applied_at TEXT,
        UNIQUE(run_id, idempotency_key)
    )
    """,
    """
    CREATE INDEX IF NOT EXISTS idx_runs_queue
    ON runs(status, priority DESC, queue_position ASC, created_at ASC)
    """,
    """
    CREATE INDEX IF NOT EXISTS idx_stage_runs_current
    ON stage_runs(run_id, stage, attempt DESC)
    """,
    """
    CREATE INDEX IF NOT EXISTS idx_artifacts_current
    ON artifacts(run_id, is_current, kind)
    """,
    """
    CREATE INDEX IF NOT EXISTS idx_events_cursor
    ON events(run_id, id)
    """,
    """
    CREATE INDEX IF NOT EXISTS idx_commands_pending
    ON commands(status, created_at)
    """,
)


def _validate_schema_version_table(conn) -> None:
    columns = list(conn.execute("PRAGMA table_info(schema_version)"))
    column_by_name = {column[1]: column for column in columns}
    if len(columns) != 2 or set(column_by_name) != {"id", "version"}:
        raise RuntimeError(
            "Schema incompatível: schema_version requer colunas id e version; "
            "migração necessária"
        )

    if column_by_name["id"][5] != 1 or column_by_name["version"][5] != 0:
        raise RuntimeError(
            "Schema incompatível: schema_version requer id como única chave primária; "
            "migração necessária"
        )

    conn.execute("SAVEPOINT validate_schema_version_singleton")
    try:
        try:
            conn.execute(
                "INSERT INTO schema_version (id, version) VALUES (?, ?)",
                (2, LATEST_SCHEMA_VERSION),
            )
        except sqlite3.IntegrityError:
            singleton_constraint_enforced = True
        else:
            singleton_constraint_enforced = False
    finally:
        conn.execute("ROLLBACK TO SAVEPOINT validate_schema_version_singleton")
        conn.execute("RELEASE SAVEPOINT validate_schema_version_singleton")

    if not singleton_constraint_enforced:
        raise RuntimeError(
            "Schema incompatível: schema_version requer CHECK(id = 1) para singleton "
            "físico; migração necessária"
        )


def _validate_schema_version(conn) -> None:
    rows = conn.execute("SELECT id, version FROM schema_version").fetchall()
    if not rows:
        conn.execute(
            "INSERT INTO schema_version (id, version) VALUES (?, ?)",
            (1, LATEST_SCHEMA_VERSION),
        )
        rows = conn.execute("SELECT id, version FROM schema_version").fetchall()

    if len(rows) != 1 or rows[0][0] != 1:
        raise RuntimeError(
            "Schema incompatível: schema_version deve conter exatamente uma versão; "
            "migração necessária"
        )

    version = rows[0][1]
    if version != LATEST_SCHEMA_VERSION:
        raise RuntimeError(
            "Schema incompatível: migração necessária "
            f"(banco={version}, código={LATEST_SCHEMA_VERSION})"
        )


def _create_v1_if_absent(conn: sqlite3.Connection) -> None:
    tables = {
        row[0]
        for row in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        ).fetchall()
    }
    if "schema_version" not in tables:
        for statement in SCHEMA_SQL:
            conn.execute(statement)
        _validate_schema_version_table(conn)
        conn.execute(
            "INSERT INTO schema_version (id, version) VALUES (?, ?)",
            (1, 1),
        )
    else:
        _validate_schema_version_table(conn)


def _column_exists(conn: sqlite3.Connection, table: str, column: str) -> bool:
    columns = {row[1] for row in conn.execute(f"PRAGMA table_info({table})")}
    return column in columns


def _upgrade_v1_to_v2(conn: sqlite3.Connection) -> None:
    if not _column_exists(conn, "runs", "is_read_only"):
        conn.execute(
            "ALTER TABLE runs ADD COLUMN is_read_only "
            "INTEGER NOT NULL DEFAULT 0 CHECK(is_read_only IN (0, 1))"
        )


def _upgrade_v2_to_v3(conn: sqlite3.Connection) -> None:
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS fluxos_geracao (
            id TEXT PRIMARY KEY,
            nome TEXT NOT NULL,
            descricao TEXT NOT NULL,
            instrucoes TEXT NOT NULL
        )
        """
    )


MIGRATIONS: dict[int, Callable[[sqlite3.Connection], None]] = {
    1: _upgrade_v1_to_v2,
    2: _upgrade_v2_to_v3,
}


def _read_schema_version(conn: sqlite3.Connection) -> int:
    rows = conn.execute("SELECT id, version FROM schema_version ORDER BY id").fetchall()
    if not rows:
        return 0
    if len(rows) > 1:
        raise RuntimeError(
            "Schema incompatível: schema_version deve conter exatamente uma versão; "
            "migração necessária"
        )
    return rows[0][1]


def migrate(db: Database) -> int:
    with db.transaction(immediate=True) as conn:
        _create_v1_if_absent(conn)
        version = _read_schema_version(conn)
        while version < LATEST_SCHEMA_VERSION:
            MIGRATIONS[version](conn)
            version += 1
            conn.execute("UPDATE schema_version SET version = ? WHERE id = 1", (version,))
        if version != LATEST_SCHEMA_VERSION:
            raise RuntimeError(
                "Schema incompatível: migração necessária "
                f"(banco={version}, código={LATEST_SCHEMA_VERSION})"
            )
    return LATEST_SCHEMA_VERSION
