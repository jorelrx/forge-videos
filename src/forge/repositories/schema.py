from __future__ import annotations

from forge.repositories.connection import Database

SCHEMA_VERSION = 1

TABLES = {
    "schema_version",
    "videos",
    "runs",
    "stage_runs",
    "work_items",
    "artifacts",
    "events",
    "commands",
}

SCHEMA_SQL = (
    """
    CREATE TABLE IF NOT EXISTS schema_version (
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
        UNIQUE(stage_run_id, item_key)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS artifacts (
        id TEXT PRIMARY KEY,
        run_id TEXT NOT NULL REFERENCES runs(id),
        stage_run_id TEXT NOT NULL REFERENCES stage_runs(id),
        work_item_id TEXT REFERENCES work_items(id),
        kind TEXT NOT NULL,
        relative_path TEXT NOT NULL,
        sha256 TEXT NOT NULL,
        size_bytes INTEGER NOT NULL CHECK(size_bytes >= 0),
        mime_type TEXT NOT NULL,
        metadata_json TEXT NOT NULL,
        is_current INTEGER NOT NULL DEFAULT 1 CHECK(is_current IN (0, 1)),
        created_at TEXT NOT NULL
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
        created_at TEXT NOT NULL
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


def init_db(db: Database) -> None:
    with db.transaction(immediate=True) as conn:
        for statement in SCHEMA_SQL:
            conn.execute(statement)

        row = conn.execute("SELECT version FROM schema_version").fetchone()
        if row is None:
            conn.execute("INSERT INTO schema_version (version) VALUES (?)", (SCHEMA_VERSION,))
        elif row[0] > SCHEMA_VERSION:
            raise RuntimeError(
                "Versão do schema é mais nova que a versão suportada pelo código"
            )
