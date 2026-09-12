from __future__ import annotations

import sqlite3
import uuid

import pytest

from forge.domain.operacao import CommandStatus, CommandType, StageName
from forge.repositories.comandos import ComandosRepository, IdempotencyConflict
from forge.repositories.connection import Database
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


def test_create_idempotent_retorna_comando_existente_para_mesma_chave_tipo_e_etapa(db):
    with db.transaction(immediate=True) as conn:
        run = create_run(OperacaoRepository(conn), tema="Tema")
        repo = ComandosRepository(conn)

        first, created = repo.create_idempotent(
            run_id=run.id,
            type=CommandType.RETRY_STAGE,
            stage=StageName.ROTEIRO,
            idempotency_key="retry-roteiro-1",
            status=CommandStatus.PENDING,
        )
        repeated, repeated_created = repo.create_idempotent(
            run_id=run.id,
            type=CommandType.RETRY_STAGE,
            stage=StageName.ROTEIRO,
            idempotency_key="retry-roteiro-1",
            status=CommandStatus.ACCEPTED,
        )

        assert created is True
        assert repeated_created is False
        assert repeated == first
        assert uuid.UUID(first.id).version == 4
        assert first.result == {}
        assert first.created_at.utcoffset().total_seconds() == 0


@pytest.mark.parametrize(
    ("command_type", "stage"),
    [(CommandType.RESUME, None), (CommandType.PAUSE, StageName.AUDIO)],
)
def test_mesma_chave_com_tipo_ou_etapa_diferente_gera_conflito(db, command_type, stage):
    with db.transaction(immediate=True) as conn:
        run = create_run(OperacaoRepository(conn), tema="Tema")
        repo = ComandosRepository(conn)
        repo.create_idempotent(
            run_id=run.id,
            type=CommandType.PAUSE,
            stage=None,
            idempotency_key="control-1",
            status=CommandStatus.PENDING,
        )

        with pytest.raises(IdempotencyConflict) as error:
            repo.create_idempotent(
                run_id=run.id,
                type=command_type,
                stage=stage,
                idempotency_key="control-1",
                status=CommandStatus.PENDING,
            )

        expected = f"idempotency key 'control-1' already has another payload for run {run.id}"
        assert str(error.value) == expected
        assert str(IdempotencyConflict(run.id, "control-1")) == expected


@pytest.mark.parametrize("key", ["", "   ", "\t"])
def test_create_idempotent_rejeita_chave_em_branco(db, key):
    with db.transaction(immediate=True) as conn:
        run = create_run(OperacaoRepository(conn), tema="Tema")

        with pytest.raises(ValueError):
            ComandosRepository(conn).create_idempotent(
                run_id=run.id,
                type=CommandType.PAUSE,
                stage=None,
                idempotency_key=key,
                status=CommandStatus.PENDING,
            )


def test_get_desconhecido_retorna_none(db):
    with db.transaction(immediate=True) as conn:
        assert ComandosRepository(conn).get("missing-command") is None


def test_pending_filtra_exatamente_e_ordena_por_created_at_depois_id(db):
    with db.transaction(immediate=True) as conn:
        run = create_run(OperacaoRepository(conn), tema="Tema")
        repo = ComandosRepository(conn)
        first, _ = repo.create_idempotent(
            run_id=run.id,
            type=CommandType.PAUSE,
            stage=None,
            idempotency_key="first",
            status=CommandStatus.PENDING,
        )
        second, _ = repo.create_idempotent(
            run_id=run.id,
            type=CommandType.RESUME,
            stage=None,
            idempotency_key="second",
            status=CommandStatus.PENDING,
        )
        excluded, _ = repo.create_idempotent(
            run_id=run.id,
            type=CommandType.PAUSE,
            stage=None,
            idempotency_key="excluded",
            status=CommandStatus.ACCEPTED,
        )
        other_run = create_run(OperacaoRepository(conn), tema="Outro")
        other, _ = repo.create_idempotent(
            run_id=other_run.id,
            type=CommandType.PAUSE,
            stage=None,
            idempotency_key="other",
            status=CommandStatus.PENDING,
        )
        conn.execute(
            "UPDATE commands SET created_at = ? WHERE id = ?",
            ("2026-01-01T00:00:02+00:00", first.id),
        )
        conn.execute(
            "UPDATE commands SET created_at = ? WHERE id = ?",
            ("2026-01-01T00:00:01+00:00", second.id),
        )

        assert [command.id for command in repo.pending(run.id)] == [second.id, first.id]
        assert excluded.id not in [command.id for command in repo.pending(run.id)]
        assert [command.id for command in repo.pending(other_run.id)] == [other.id]


def test_set_status_persiste_resultado_e_applied_at_apenas_para_estado_terminal(db):
    with db.transaction(immediate=True) as conn:
        run = create_run(OperacaoRepository(conn), tema="Tema")
        repo = ComandosRepository(conn)
        accepted, _ = repo.create_idempotent(
            run_id=run.id,
            type=CommandType.PAUSE,
            stage=None,
            idempotency_key="accepted",
            status=CommandStatus.PENDING,
        )
        applied, _ = repo.create_idempotent(
            run_id=run.id,
            type=CommandType.RESUME,
            stage=None,
            idempotency_key="applied",
            status=CommandStatus.PENDING,
        )
        rejected, _ = repo.create_idempotent(
            run_id=run.id,
            type=CommandType.RETRY_STAGE,
            stage=StageName.ROTEIRO,
            idempotency_key="rejected",
            status=CommandStatus.PENDING,
        )
        pending, _ = repo.create_idempotent(
            run_id=run.id,
            type=CommandType.PAUSE,
            stage=None,
            idempotency_key="pending",
            status=CommandStatus.PENDING,
        )

        accepted = repo.set_status(
            accepted.id, CommandStatus.ACCEPTED, result={"z": 2, "a": "ok"}
        )
        applied = repo.set_status(applied.id, CommandStatus.APPLIED, result={"done": True})
        rejected = repo.set_status(rejected.id, CommandStatus.REJECTED, result={"reason": "gate"})
        pending = repo.set_status(pending.id, CommandStatus.PENDING, result={"retry": 1})

        for command, expected_status in (
            (accepted, CommandStatus.ACCEPTED),
            (applied, CommandStatus.APPLIED),
            (rejected, CommandStatus.REJECTED),
            (pending, CommandStatus.PENDING),
        ):
            assert command.status == expected_status
            fetched = repo.get(command.id)
            assert fetched is not None
            assert fetched.status == expected_status

        assert accepted.applied_at is None
        assert applied.applied_at is not None
        assert rejected.applied_at is not None
        assert pending.applied_at is None
        assert repo.get(accepted.id).result == {"a": "ok", "z": 2}
        assert repo.get(applied.id).result == {"done": True}
        assert repo.get(rejected.id).result == {"reason": "gate"}
        assert repo.get(pending.id).result == {"retry": 1}
        assert conn.execute(
            "SELECT result_json FROM commands WHERE id = ?", (accepted.id,)
        ).fetchone()[0] == '{"a": "ok", "z": 2}'


def test_set_status_desconhecido_gera_key_error(db):
    with db.transaction(immediate=True) as conn:
        with pytest.raises(KeyError) as error:
            ComandosRepository(conn).set_status(
                "missing-command", CommandStatus.APPLIED, result={}
            )

        assert error.value.args == ("missing-command",)


def test_create_idempotent_para_run_inexistente_propaga_integrity_error_sem_falso_sucesso(db):
    with db.transaction(immediate=True) as conn:
        run = create_run(OperacaoRepository(conn), tema="Tema")
        repo = ComandosRepository(conn)
        repo.create_idempotent(
            run_id=run.id,
            type=CommandType.PAUSE,
            stage=None,
            idempotency_key="shared-key",
            status=CommandStatus.PENDING,
        )

        with pytest.raises(sqlite3.IntegrityError):
            repo.create_idempotent(
                run_id="missing-run",
                type=CommandType.PAUSE,
                stage=None,
                idempotency_key="shared-key",
                status=CommandStatus.PENDING,
            )
