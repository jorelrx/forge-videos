from __future__ import annotations

import sqlite3
from datetime import UTC, datetime

import pytest

from forge.domain.operacao import RunStatus
from forge.repositories.connection import Database
from forge.repositories.operacao import OperacaoRepository
from forge.repositories.migrations import migrate, LATEST_SCHEMA_VERSION
from forge.domain.operacao import StageName
from forge.services.control_plane import ControlPlaneService, HistoricoSomenteLeitura


SCHEMA_V1_SQL = """
    CREATE TABLE IF NOT EXISTS schema_version (
        id INTEGER PRIMARY KEY CHECK(id = 1),
        version INTEGER NOT NULL
    );
    CREATE TABLE IF NOT EXISTS videos (
        id TEXT PRIMARY KEY,
        tema TEXT NOT NULL CHECK(length(trim(tema)) > 0),
        tese TEXT,
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL
    );
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
    );
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
    );
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
    );
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
    );
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
    );
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
    );
"""


@pytest.fixture
def v1_db(tmp_path):
    db = Database(tmp_path / "forge.db")
    with db.transaction(immediate=True) as conn:
        for stmt in SCHEMA_V1_SQL.split(";"):
            stmt = stmt.strip()
            if stmt:
                conn.execute(stmt)
        conn.execute("INSERT INTO schema_version (id, version) VALUES (1, 1)")
        conn.execute(
            "INSERT INTO videos (id, tema, created_at, updated_at) VALUES (?, ?, ?, ?)",
            ("video-1", "Tema", "2026-01-01T00:00:00+00:00", "2026-01-01T00:00:00+00:00"),
        )
        conn.execute(
            "INSERT INTO runs (id, video_id, status, priority, queue_position, "
            "config_snapshot_json, workflow_version, git_commit, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                "run-1",
                "video-1",
                "queued",
                50,
                1,
                "{}",
                1,
                "abc123",
                "2026-01-01T00:00:00+00:00",
            ),
        )
    return db


def test_migrate_preserves_existing_run_and_adds_read_only(v1_db):
    assert migrate(v1_db) == LATEST_SCHEMA_VERSION
    assert migrate(v1_db) == LATEST_SCHEMA_VERSION

    with v1_db.connection() as conn:
        row = conn.execute("SELECT id, is_read_only FROM runs WHERE id = ?", ("run-1",)).fetchone()
    assert dict(row) == {"id": "run-1", "is_read_only": 0}


def test_read_only_run_cannot_pause_resume_or_retry(v1_db):
    migrate(v1_db)

    db = v1_db
    with db.transaction(immediate=True) as conn:
        conn.execute(
            "UPDATE runs SET status = ?, is_read_only = 1 WHERE id = ?",
            (RunStatus.COMPLETED.value, "run-1"),
        )

    service = ControlPlaneService(db)
    with pytest.raises(HistoricoSomenteLeitura):
        service.request_pause("run-1", idempotency_key="pause-legacy")
    with pytest.raises(HistoricoSomenteLeitura):
        service.request_resume("run-1", idempotency_key="resume-legacy")
    with pytest.raises(HistoricoSomenteLeitura):
        service.request_retry_stage("run-1", StageName.ROTEIRO, idempotency_key="retry-legacy")
