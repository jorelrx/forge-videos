from __future__ import annotations

import sqlite3

import pytest

from forge.repositories.connection import Database
from forge.repositories.eventos import EventosRepository
from forge.repositories.operacao import OperacaoRepository
from forge.repositories.schema import init_db


@pytest.fixture
def db(tmp_path):
    database = Database(tmp_path / "forge.db")
    init_db(database)
    return database


def create_run(repo: OperacaoRepository, *, tema: str):
    return repo.create_video_and_run(
        tema=tema,
        tese="Tese",
        priority=50,
        config_snapshot={"locale": "pt-BR"},
        workflow_version=2,
        git_commit="abc123",
    )[1]


def test_append_gera_ids_monotonicos_e_after_pagina_sem_eventos_extras(db):
    with db.transaction(immediate=True) as conn:
        run = create_run(OperacaoRepository(conn), tema="Tema")
        repo = EventosRepository(conn)

        assert repo.after(0, limit=1000) == []

        first = repo.append(
            kind="run.created",
            level="info",
            message="Run criada",
            payload={"position": 1},
        )
        second = repo.append(
            kind="run.started",
            level="info",
            message="Run iniciada",
            payload={"worker": "worker-1"},
            run_id=run.id,
        )

        assert second.id == first.id + 1
        assert [event.id for event in repo.after(0)] == [first.id, second.id]
        assert repo.after(first.id, limit=1) == [second]
        assert repo.after(second.id) == []


def test_after_filtra_run_sem_mudar_semantica_do_cursor_global(db):
    with db.transaction(immediate=True) as conn:
        operacao = OperacaoRepository(conn)
        run_a = create_run(operacao, tema="A")
        run_b = create_run(operacao, tema="B")
        repo = EventosRepository(conn)

        event_a1 = repo.append(
            kind="a.1", level="info", message="A1", payload={}, run_id=run_a.id
        )
        event_b1 = repo.append(
            kind="b.1", level="info", message="B1", payload={}, run_id=run_b.id
        )
        event_a2 = repo.append(
            kind="a.2", level="info", message="A2", payload={}, run_id=run_a.id
        )

        assert [event.id for event in repo.after(event_a1.id, run_id=run_a.id)] == [event_a2.id]
        assert [event.id for event in repo.after(event_b1.id, run_id=run_a.id)] == [event_a2.id]
        assert repo.after(event_a2.id, run_id=run_b.id) == []


def test_append_serializa_json_unicode_ordenado_e_reconstroi_payload(db):
    with db.transaction(immediate=True) as conn:
        repo = EventosRepository(conn)
        event = repo.append(
            kind="log",
            level="info",
            message="ação concluída",
            payload={"zeta": "ação", "alpha": {"b": 2, "a": 1}},
        )

        raw_payload = conn.execute(
            "SELECT payload_json FROM events WHERE id = ?", (event.id,)
        ).fetchone()[0]

        assert raw_payload == '{"alpha": {"a": 1, "b": 2}, "zeta": "ação"}'
        assert event.payload == {"alpha": {"a": 1, "b": 2}, "zeta": "ação"}
        assert event.created_at.utcoffset().total_seconds() == 0


@pytest.mark.parametrize("limit", [0, -1, 1001])
def test_after_rejeita_limit_fora_do_intervalo(db, limit):
    with db.transaction(immediate=True) as conn:
        repo = EventosRepository(conn)

        with pytest.raises(ValueError):
            repo.after(0, limit=limit)


def test_after_rejeita_cursor_negativo(db):
    with db.transaction(immediate=True) as conn:
        repo = EventosRepository(conn)

        with pytest.raises(ValueError):
            repo.after(-1)


def test_append_com_run_inexistente_propaga_integrity_error(db):
    with db.transaction(immediate=True) as conn:
        repo = EventosRepository(conn)

        with pytest.raises(sqlite3.IntegrityError):
            repo.append(
                kind="invalid.run",
                level="error",
                message="Run ausente",
                payload={},
                run_id="missing-run",
            )
