import sqlite3

import pytest

from forge.repositories.connection import Database
from forge.repositories.schema import SCHEMA_VERSION, TABLES, init_db


def _insert_chain(conn, *, run_id: str, stage_run_id: str, work_item_id: str) -> None:
    conn.execute(
        """
        INSERT INTO videos (id, tema, created_at, updated_at)
        VALUES (?, 'tema', '2026-01-01', '2026-01-01')
        """,
        (f"video-{run_id}",),
    )
    conn.execute(
        """
        INSERT INTO runs (
            id, video_id, status, priority, queue_position, config_snapshot_json,
            workflow_version, git_commit, created_at
        ) VALUES (?, ?, 'queued', 1, 1, '{}', 1, 'abc', '2026-01-01')
        """,
        (run_id, f"video-{run_id}"),
    )
    conn.execute(
        """
        INSERT INTO stage_runs (id, run_id, stage, attempt, status, created_at)
        VALUES (?, ?, 'research', 1, 'queued', '2026-01-01')
        """,
        (stage_run_id, run_id),
    )
    conn.execute(
        """
        INSERT INTO work_items (
            id, stage_run_id, item_key, status, input_json, input_hash
        ) VALUES (?, ?, 'item', 'queued', '{}', 'hash')
        """,
        (work_item_id, stage_run_id),
    )


def test_init_db_cria_exatamente_todas_as_tabelas_do_app(tmp_path):
    db = Database(tmp_path / "forge.db")
    init_db(db)

    with db.connection() as conn:
        names = {
            row[0]
            for row in conn.execute(
                "SELECT name FROM sqlite_master "
                "WHERE type='table' AND name NOT LIKE 'sqlite_%'"
            )
        }

    assert names == TABLES


def test_init_db_e_idempotente_e_mantem_singleton_da_versao(tmp_path):
    db = Database(tmp_path / "forge.db")
    init_db(db)
    init_db(db)

    with db.connection() as conn:
        rows = conn.execute("SELECT id, version FROM schema_version").fetchall()

    assert [tuple(row) for row in rows] == [(1, SCHEMA_VERSION)]


@pytest.mark.parametrize("version", [SCHEMA_VERSION - 1, SCHEMA_VERSION + 1])
def test_init_db_rejeita_schema_com_versao_diferente_da_suportada(tmp_path, version):
    db = Database(tmp_path / "forge.db")
    init_db(db)

    with db.transaction(immediate=True) as conn:
        conn.execute("UPDATE schema_version SET version = ? WHERE id = 1", (version,))

    with pytest.raises(RuntimeError, match="incompatível|migração"):
        init_db(db)


def test_init_db_rejeita_schema_version_legado_sem_colunas_do_singleton(tmp_path):
    db = Database(tmp_path / "forge.db")

    with db.connection() as conn:
        conn.execute("CREATE TABLE schema_version (version INTEGER NOT NULL)")
        conn.execute("INSERT INTO schema_version (version) VALUES (1)")

    with pytest.raises(RuntimeError, match="incompatível|migração"):
        init_db(db)


def test_artifact_rejeita_stage_run_de_outro_run(tmp_path):
    db = Database(tmp_path / "forge.db")
    init_db(db)

    with db.transaction(immediate=True) as conn:
        _insert_chain(conn, run_id="run-1", stage_run_id="stage-1", work_item_id="work-1")
        _insert_chain(conn, run_id="run-2", stage_run_id="stage-2", work_item_id="work-2")

        with pytest.raises(sqlite3.IntegrityError):
            conn.execute(
                """
                INSERT INTO artifacts (
                    id, run_id, stage_run_id, work_item_id, kind, relative_path, sha256,
                    size_bytes, mime_type, metadata_json, created_at
                ) VALUES (
                    'artifact-1', 'run-1', 'stage-2', 'work-2', 'script', 'script.md',
                    'hash', 1, 'text/markdown', '{}', '2026-01-01'
                )
                """
            )


def test_artifact_rejeita_work_item_de_outro_stage_run(tmp_path):
    db = Database(tmp_path / "forge.db")
    init_db(db)

    with db.transaction(immediate=True) as conn:
        _insert_chain(conn, run_id="run-1", stage_run_id="stage-1", work_item_id="work-1")
        _insert_chain(conn, run_id="run-2", stage_run_id="stage-2", work_item_id="work-2")

        with pytest.raises(sqlite3.IntegrityError):
            conn.execute(
                """
                INSERT INTO artifacts (
                    id, run_id, stage_run_id, work_item_id, kind, relative_path, sha256,
                    size_bytes, mime_type, metadata_json, created_at
                ) VALUES (
                    'artifact-1', 'run-1', 'stage-1', 'work-2', 'script', 'script.md',
                    'hash', 1, 'text/markdown', '{}', '2026-01-01'
                )
                """
            )


def test_event_rejeita_cadeia_contraditoria(tmp_path):
    db = Database(tmp_path / "forge.db")
    init_db(db)

    with db.transaction(immediate=True) as conn:
        _insert_chain(conn, run_id="run-1", stage_run_id="stage-1", work_item_id="work-1")
        _insert_chain(conn, run_id="run-2", stage_run_id="stage-2", work_item_id="work-2")

        with pytest.raises(sqlite3.IntegrityError):
            conn.execute(
                """
                INSERT INTO events (
                    run_id, stage_run_id, work_item_id, kind, level, message, payload_json,
                    created_at
                ) VALUES (
                    'run-1', 'stage-2', 'work-2', 'started', 'info', 'mensagem', '{}',
                    '2026-01-01'
                )
                """
            )


def test_event_rejeita_stage_ou_work_item_sem_cadeia_pai(tmp_path):
    db = Database(tmp_path / "forge.db")
    init_db(db)

    with db.transaction(immediate=True) as conn:
        _insert_chain(conn, run_id="run-1", stage_run_id="stage-1", work_item_id="work-1")

        with pytest.raises(sqlite3.IntegrityError):
            conn.execute(
                """
                INSERT INTO events (stage_run_id, kind, level, message, payload_json, created_at)
                VALUES ('stage-1', 'started', 'info', 'mensagem', '{}', '2026-01-01')
                """
            )

        with pytest.raises(sqlite3.IntegrityError):
            conn.execute(
                """
                INSERT INTO events (work_item_id, kind, level, message, payload_json, created_at)
                VALUES ('work-1', 'started', 'info', 'mensagem', '{}', '2026-01-01')
                """
            )
