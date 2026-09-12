import sqlite3

import pytest

from forge.repositories.connection import Database
from forge.repositories.schema import SCHEMA_VERSION, TABLES, init_db

APP_INDEXES = {
    "idx_runs_queue": [
        ("status", "ASC"),
        ("priority", "DESC"),
        ("queue_position", "ASC"),
        ("created_at", "ASC"),
    ],
    "idx_stage_runs_current": [
        ("run_id", "ASC"),
        ("stage", "ASC"),
        ("attempt", "DESC"),
    ],
    "idx_artifacts_current": [
        ("run_id", "ASC"),
        ("is_current", "ASC"),
        ("kind", "ASC"),
    ],
    "idx_events_cursor": [("run_id", "ASC"), ("id", "ASC")],
    "idx_commands_pending": [("status", "ASC"), ("created_at", "ASC")],
}


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


def _index_columns(conn, index_name: str) -> list[tuple[str, str]]:
    rows = conn.execute(f"PRAGMA index_xinfo({index_name})").fetchall()
    return [
        (row[2], "DESC" if row[3] else "ASC")
        for row in rows
        if row[5] == 1
    ]


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


def test_init_db_cria_exatamente_os_cinco_indices_explicitos_do_app(tmp_path):
    db = Database(tmp_path / "forge.db")
    init_db(db)

    with db.connection() as conn:
        names = {
            row[0]
            for row in conn.execute(
                "SELECT name FROM sqlite_master "
                "WHERE type = 'index' AND name NOT LIKE 'sqlite_autoindex_%'"
            )
        }

    assert names == set(APP_INDEXES)


def test_init_db_configura_colunas_e_ordem_dos_indices_explicitos(tmp_path):
    db = Database(tmp_path / "forge.db")
    init_db(db)

    with db.connection() as conn:
        actual = {
            index_name: _index_columns(conn, index_name)
            for index_name in APP_INDEXES
        }

    assert actual == APP_INDEXES


def test_init_db_e_idempotente_e_mantem_singleton_da_versao(tmp_path):
    db = Database(tmp_path / "forge.db")
    init_db(db)
    init_db(db)

    with db.connection() as conn:
        rows = conn.execute("SELECT id, version FROM schema_version").fetchall()

    assert [tuple(row) for row in rows] == [(1, SCHEMA_VERSION)]


def test_schema_version_impede_fisicamente_id_diferente_de_um(tmp_path):
    db = Database(tmp_path / "forge.db")
    init_db(db)

    with (
        db.transaction(immediate=True) as conn,
        pytest.raises(sqlite3.IntegrityError),
    ):
        conn.execute("INSERT INTO schema_version (id, version) VALUES (2, 1)")


def test_schema_version_impede_fisicamente_segunda_linha_com_id_um(tmp_path):
    db = Database(tmp_path / "forge.db")
    init_db(db)

    with (
        db.transaction(immediate=True) as conn,
        pytest.raises(sqlite3.IntegrityError),
    ):
        conn.execute("INSERT INTO schema_version (id, version) VALUES (1, 1)")


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


def test_init_db_rejeita_schema_version_legado_sem_primary_key_do_singleton(tmp_path):
    db = Database(tmp_path / "forge.db")

    with db.connection() as conn:
        conn.execute(
            "CREATE TABLE schema_version (id INTEGER CHECK(id=1), version INTEGER NOT NULL)"
        )

    with pytest.raises(RuntimeError, match="incompatível|migração"):
        init_db(db)


def test_init_db_rejeita_schema_version_legado_sem_check_do_singleton(tmp_path):
    db = Database(tmp_path / "forge.db")

    with db.connection() as conn:
        conn.execute(
            "CREATE TABLE schema_version (id INTEGER PRIMARY KEY, version INTEGER NOT NULL)"
        )

    with pytest.raises(RuntimeError, match="incompatível|migração"):
        init_db(db)


def test_init_db_rejeita_check_de_singleton_apenas_em_comentario(tmp_path):
    db = Database(tmp_path / "forge.db")

    with db.connection() as conn:
        conn.execute(
            """
            CREATE TABLE schema_version (
                id INTEGER PRIMARY KEY,
                version INTEGER NOT NULL,
                CHECK (version >= 1) /* CHECK(id = 1) */
            )
            """
        )

    with pytest.raises(RuntimeError, match="incompatível|migração"):
        init_db(db)


def test_init_db_rejeita_schema_version_corrompida_com_duas_linhas(tmp_path):
    db = Database(tmp_path / "forge.db")
    init_db(db)

    with db.transaction(immediate=True) as conn:
        conn.execute("PRAGMA ignore_check_constraints=ON")
        conn.execute("INSERT INTO schema_version (id, version) VALUES (2, 1)")

    with pytest.raises(RuntimeError, match="incompatível|migração"):
        init_db(db)


@pytest.mark.parametrize("tema", ["", "   "])
def test_video_rejeita_tema_vazio_ou_apenas_espacos(tmp_path, tema):
    db = Database(tmp_path / "forge.db")
    init_db(db)

    with (
        db.transaction(immediate=True) as conn,
        pytest.raises(sqlite3.IntegrityError),
    ):
        conn.execute(
            """
            INSERT INTO videos (id, tema, created_at, updated_at)
            VALUES ('video-invalido', ?, '2026-01-01', '2026-01-01')
            """,
            (tema,),
        )


@pytest.mark.parametrize(
    ("column", "value"),
    [
        ("priority", -1),
        ("priority", 101),
        ("queue_position", 0),
        ("workflow_version", 0),
    ],
)
def test_run_rejeita_valores_fora_dos_limites(tmp_path, column, value):
    db = Database(tmp_path / "forge.db")
    init_db(db)

    with db.transaction(immediate=True) as conn:
        conn.execute(
            """
            INSERT INTO videos (id, tema, created_at, updated_at)
            VALUES ('video-1', 'tema', '2026-01-01', '2026-01-01')
            """
        )

        with pytest.raises(sqlite3.IntegrityError):
            conn.execute(
                f"""
                INSERT INTO runs (
                    id, video_id, status, priority, queue_position, config_snapshot_json,
                    workflow_version, git_commit, created_at
                ) VALUES (
                    'run-invalido', 'video-1', 'queued',
                    {value if column == 'priority' else 1},
                    {value if column == 'queue_position' else 1},
                    '{{}}',
                    {value if column == 'workflow_version' else 1},
                    'abc', '2026-01-01'
                )
                """
            )


def test_run_rejeita_video_inexistente(tmp_path):
    db = Database(tmp_path / "forge.db")
    init_db(db)

    with (
        db.transaction(immediate=True) as conn,
        pytest.raises(sqlite3.IntegrityError),
    ):
        conn.execute(
            """
            INSERT INTO runs (
                id, video_id, status, priority, queue_position, config_snapshot_json,
                workflow_version, git_commit, created_at
            ) VALUES ('run-invalido', 'video-inexistente', 'queued', 1, 1, '{}', 1, 'abc',
                      '2026-01-01')
            """
        )


@pytest.mark.parametrize(
    ("column", "value"),
    [
        ("attempt", 0),
        ("current_items", -1),
        ("total_items", -1),
        ("progress", -0.01),
        ("progress", 1.01),
    ],
)
def test_stage_run_rejeita_valores_fora_dos_limites(tmp_path, column, value):
    db = Database(tmp_path / "forge.db")
    init_db(db)

    with db.transaction(immediate=True) as conn:
        _insert_chain(conn, run_id="run-1", stage_run_id="stage-1", work_item_id="work-1")

        with pytest.raises(sqlite3.IntegrityError):
            conn.execute(
                f"""
                INSERT INTO stage_runs (
                    id, run_id, stage, attempt, status, current_items, total_items, progress,
                    created_at
                ) VALUES (
                    'stage-invalido', 'run-1', 'review',
                    {value if column == 'attempt' else 1}, 'queued',
                    {value if column == 'current_items' else 0},
                    {value if column == 'total_items' else 0},
                    {value if column == 'progress' else 0}, '2026-01-01'
                )
                """
            )


def test_stage_run_rejeita_run_inexistente(tmp_path):
    db = Database(tmp_path / "forge.db")
    init_db(db)

    with (
        db.transaction(immediate=True) as conn,
        pytest.raises(sqlite3.IntegrityError),
    ):
        conn.execute(
            """
            INSERT INTO stage_runs (id, run_id, stage, attempt, status, created_at)
            VALUES ('stage-invalido', 'run-inexistente', 'research', 1, 'queued', '2026-01-01')
            """
        )


@pytest.mark.parametrize(("column", "value"), [("attempts", -1), ("duration_ms", -1)])
def test_work_item_rejeita_valores_fora_dos_limites(tmp_path, column, value):
    db = Database(tmp_path / "forge.db")
    init_db(db)

    with db.transaction(immediate=True) as conn:
        _insert_chain(conn, run_id="run-1", stage_run_id="stage-1", work_item_id="work-1")

        with pytest.raises(sqlite3.IntegrityError):
            conn.execute(
                f"""
                INSERT INTO work_items (
                    id, stage_run_id, item_key, status, input_json, input_hash, attempts,
                    duration_ms
                ) VALUES (
                    'work-invalido', 'stage-1', 'item-invalido', 'queued', '{{}}', 'hash',
                    {value if column == 'attempts' else 0},
                    {value if column == 'duration_ms' else 0}
                )
                """
            )


def test_work_item_rejeita_stage_run_inexistente(tmp_path):
    db = Database(tmp_path / "forge.db")
    init_db(db)

    with (
        db.transaction(immediate=True) as conn,
        pytest.raises(sqlite3.IntegrityError),
    ):
        conn.execute(
            """
            INSERT INTO work_items (
                id, stage_run_id, item_key, status, input_json, input_hash
            ) VALUES ('work-invalido', 'stage-inexistente', 'item', 'queued', '{}', 'hash')
            """
        )


@pytest.mark.parametrize(("column", "value"), [("size_bytes", -1), ("is_current", 2)])
def test_artifact_rejeita_valores_fora_dos_limites_em_cadeia_valida(tmp_path, column, value):
    db = Database(tmp_path / "forge.db")
    init_db(db)

    with db.transaction(immediate=True) as conn:
        _insert_chain(conn, run_id="run-1", stage_run_id="stage-1", work_item_id="work-1")

        with pytest.raises(sqlite3.IntegrityError):
            conn.execute(
                f"""
                INSERT INTO artifacts (
                    id, run_id, stage_run_id, work_item_id, kind, relative_path, sha256,
                    size_bytes, mime_type, metadata_json, is_current, created_at
                ) VALUES (
                    'artifact-invalido', 'run-1', 'stage-1', 'work-1', 'script', 'script.md',
                    'hash', {value if column == 'size_bytes' else 1}, 'text/markdown', '{{}}',
                    {value if column == 'is_current' else 1}, '2026-01-01'
                )
                """
            )


def test_artifact_rejeita_run_inexistente(tmp_path):
    db = Database(tmp_path / "forge.db")
    init_db(db)

    with db.transaction(immediate=True) as conn:
        _insert_chain(conn, run_id="run-1", stage_run_id="stage-1", work_item_id="work-1")

        with pytest.raises(sqlite3.IntegrityError):
            conn.execute(
                """
                INSERT INTO artifacts (
                    id, run_id, stage_run_id, work_item_id, kind, relative_path, sha256,
                    size_bytes, mime_type, metadata_json, created_at
                ) VALUES (
                    'artifact-run-invalido', 'run-inexistente', 'stage-1', 'work-1', 'script',
                    'script.md', 'hash', 1, 'text/markdown', '{}', '2026-01-01'
                )
                """
            )


def test_artifact_rejeita_stage_run_inexistente(tmp_path):
    db = Database(tmp_path / "forge.db")
    init_db(db)

    with db.transaction(immediate=True) as conn:
        _insert_chain(conn, run_id="run-1", stage_run_id="stage-1", work_item_id="work-1")

        with pytest.raises(sqlite3.IntegrityError):
            conn.execute(
                """
                INSERT INTO artifacts (
                    id, run_id, stage_run_id, work_item_id, kind, relative_path, sha256,
                    size_bytes, mime_type, metadata_json, created_at
                ) VALUES (
                    'artifact-stage-invalido', 'run-1', 'stage-inexistente', 'work-1', 'script',
                    'script.md', 'hash', 1, 'text/markdown', '{}', '2026-01-01'
                )
                """
            )


def test_artifact_rejeita_work_item_inexistente(tmp_path):
    db = Database(tmp_path / "forge.db")
    init_db(db)

    with db.transaction(immediate=True) as conn:
        _insert_chain(conn, run_id="run-1", stage_run_id="stage-1", work_item_id="work-1")

        with pytest.raises(sqlite3.IntegrityError):
            conn.execute(
                """
                INSERT INTO artifacts (
                    id, run_id, stage_run_id, work_item_id, kind, relative_path, sha256,
                    size_bytes, mime_type, metadata_json, created_at
                ) VALUES (
                    'artifact-work-invalido', 'run-1', 'stage-1', 'work-inexistente', 'script',
                    'script.md', 'hash', 1, 'text/markdown', '{}', '2026-01-01'
                )
                """
            )


def test_command_rejeita_run_inexistente(tmp_path):
    db = Database(tmp_path / "forge.db")
    init_db(db)

    with (
        db.transaction(immediate=True) as conn,
        pytest.raises(sqlite3.IntegrityError),
    ):
        conn.execute(
            """
            INSERT INTO commands (
                id, run_id, type, idempotency_key, status, result_json, created_at
            ) VALUES (
                'command-invalido', 'run-inexistente', 'start', 'command-1', 'pending', '{}',
                '2026-01-01'
            )
            """
        )


def test_stage_run_rejeita_duplicidade_de_stage_e_attempt_por_run(tmp_path):
    db = Database(tmp_path / "forge.db")
    init_db(db)

    with db.transaction(immediate=True) as conn:
        _insert_chain(conn, run_id="run-1", stage_run_id="stage-1", work_item_id="work-1")

        with pytest.raises(sqlite3.IntegrityError):
            conn.execute(
                """
                INSERT INTO stage_runs (id, run_id, stage, attempt, status, created_at)
                VALUES ('stage-duplicado', 'run-1', 'research', 1, 'queued', '2026-01-01')
                """
            )


def test_work_item_rejeita_duplicidade_de_item_key_por_stage_run(tmp_path):
    db = Database(tmp_path / "forge.db")
    init_db(db)

    with db.transaction(immediate=True) as conn:
        _insert_chain(conn, run_id="run-1", stage_run_id="stage-1", work_item_id="work-1")

        with pytest.raises(sqlite3.IntegrityError):
            conn.execute(
                """
                INSERT INTO work_items (
                    id, stage_run_id, item_key, status, input_json, input_hash
                ) VALUES ('work-duplicado', 'stage-1', 'item', 'queued', '{}', 'hash')
                """
            )


def test_command_rejeita_duplicidade_de_idempotency_key_por_run(tmp_path):
    db = Database(tmp_path / "forge.db")
    init_db(db)

    with db.transaction(immediate=True) as conn:
        _insert_chain(conn, run_id="run-1", stage_run_id="stage-1", work_item_id="work-1")
        conn.execute(
            """
            INSERT INTO commands (
                id, run_id, type, idempotency_key, status, result_json, created_at
            ) VALUES ('command-1', 'run-1', 'start', 'command-1', 'pending', '{}', '2026-01-01')
            """
        )

        with pytest.raises(sqlite3.IntegrityError):
            conn.execute(
                """
                INSERT INTO commands (
                    id, run_id, type, idempotency_key, status, result_json, created_at
                ) VALUES (
                    'command-duplicado', 'run-1', 'start', 'command-1', 'pending', '{}',
                    '2026-01-01'
                )
                """
            )


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


def test_event_rejeita_run_inexistente_sem_stage_ou_work_item(tmp_path):
    db = Database(tmp_path / "forge.db")
    init_db(db)

    with (
        db.transaction(immediate=True) as conn,
        pytest.raises(sqlite3.IntegrityError),
    ):
        conn.execute(
            """
            INSERT INTO events (run_id, kind, level, message, payload_json, created_at)
            VALUES ('run-inexistente', 'started', 'info', 'mensagem', '{}', '2026-01-01')
            """
        )


def test_event_rejeita_stage_run_inexistente_com_run_valido(tmp_path):
    db = Database(tmp_path / "forge.db")
    init_db(db)

    with db.transaction(immediate=True) as conn:
        _insert_chain(conn, run_id="run-1", stage_run_id="stage-1", work_item_id="work-1")

        with pytest.raises(sqlite3.IntegrityError):
            conn.execute(
                """
                INSERT INTO events (
                    run_id, stage_run_id, kind, level, message, payload_json, created_at
                ) VALUES (
                    'run-1', 'stage-inexistente', 'started', 'info', 'mensagem', '{}',
                    '2026-01-01'
                )
                """
            )


def test_event_rejeita_work_item_inexistente_com_run_e_stage_validos(tmp_path):
    db = Database(tmp_path / "forge.db")
    init_db(db)

    with db.transaction(immediate=True) as conn:
        _insert_chain(conn, run_id="run-1", stage_run_id="stage-1", work_item_id="work-1")

        with pytest.raises(sqlite3.IntegrityError):
            conn.execute(
                """
                INSERT INTO events (
                    run_id, stage_run_id, work_item_id, kind, level, message, payload_json,
                    created_at
                ) VALUES (
                    'run-1', 'stage-1', 'work-inexistente', 'started', 'info', 'mensagem',
                    '{}', '2026-01-01'
                )
                """
            )


def test_event_rejeita_work_item_de_outro_stage_run(tmp_path):
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
                    'run-1', 'stage-1', 'work-2', 'started', 'info', 'mensagem', '{}',
                    '2026-01-01'
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
