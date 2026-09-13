from __future__ import annotations

import sqlite3
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime

import pytest

from forge.domain.operacao import ETAPAS, Artifact, RunStatus, StageName, StageStatus
from forge.repositories.connection import Database
from forge.repositories.operacao import OperacaoRepository
from forge.repositories.schema import init_db


@pytest.fixture
def db(tmp_path):
    database = Database(tmp_path / "forge.db", busy_timeout_ms=2_000)
    init_db(database)
    return database


def create_run(repo: OperacaoRepository, *, tema: str = "Tema", priority: int = 50):
    return repo.create_video_and_run(
        tema=tema,
        tese="Tese",
        priority=priority,
        config_snapshot={"render": {"quality": "alta"}, "locale": "pt-BR"},
        workflow_version=2,
        git_commit="abc123",
    )


def artifact_for(run_id: str, stage_run_id: str, *, artifact_id: str = "artifact-1") -> Artifact:
    return Artifact(
        id=artifact_id,
        run_id=run_id,
        stage_run_id=stage_run_id,
        kind="roteiro",
        relative_path=f"artefatos/{artifact_id}.md",
        sha256="a" * 64,
        size_bytes=123,
        mime_type="text/markdown",
        metadata={"language": "pt-BR", "sections": 9},
        is_current=True,
        created_at=datetime.now(UTC),
    )


def test_create_video_and_run_inicializa_todas_etapas_e_persiste_json(db):
    with db.transaction(immediate=True) as conn:
        repo = OperacaoRepository(conn)
        video, run = create_run(repo)

        assert video.tema == "Tema"
        assert video.tese == "Tese"
        assert video.created_at == video.updated_at
        assert run.video_id == video.id
        assert run.status is RunStatus.QUEUED
        assert run.priority == 50
        assert run.queue_position == 1
        assert run.config_snapshot == {
            "render": {"quality": "alta"},
            "locale": "pt-BR",
        }
        assert run.workflow_version == 2
        assert run.git_commit == "abc123"
        assert conn.execute(
            "SELECT config_snapshot_json FROM runs WHERE id = ?", (run.id,)
        ).fetchone()[0] == (
            '{"locale": "pt-BR", "render": {"quality": "alta"}}'
        )

        stages = repo.current_stages(run.id)

    assert [(stage.stage, stage.attempt, stage.status) for stage in stages] == [
        (stage, 1, StageStatus.PENDING) for stage in ETAPAS
    ]


def test_queue_ordena_prioridade_posicao_e_list_runs_tem_paginacao_deterministica(db):
    with db.transaction(immediate=True) as conn:
        repo = OperacaoRepository(conn)
        _, low = create_run(repo, tema="low", priority=10)
        _, high_first = create_run(repo, tema="high-first", priority=90)
        _, high_second = create_run(repo, tema="high-second", priority=90)
        conn.execute(
            "UPDATE runs SET created_at = ? WHERE id = ?",
            ("2026-01-01T00:00:00+00:00", low.id),
        )
        conn.execute(
            "UPDATE runs SET created_at = ? WHERE id = ?",
            ("2026-01-02T00:00:00+00:00", high_first.id),
        )
        conn.execute(
            "UPDATE runs SET created_at = ? WHERE id = ?",
            ("2026-01-03T00:00:00+00:00", high_second.id),
        )

        assert [run.id for run in repo.list_queue()] == [high_first.id, high_second.id, low.id]
        assert [run.id for run in repo.list_runs(limit=2, offset=0)] == [
            high_second.id,
            high_first.id,
        ]
        assert [run.id for run in repo.list_runs(limit=2, offset=2)] == [low.id]
        with pytest.raises(ValueError):
            repo.list_runs(limit=-1)
        with pytest.raises(ValueError):
            repo.list_runs(offset=-1)


def test_claim_next_eh_atomico_e_valida_entrada(db):
    with db.transaction(immediate=True) as conn:
        repo = OperacaoRepository(conn)
        _, run = create_run(repo)
        prior_start = "2026-01-01T12:00:00+00:00"
        conn.execute("UPDATE runs SET started_at = ? WHERE id = ?", (prior_start, run.id))

    def claim(worker_id: str):
        with db.transaction(immediate=True) as conn:
            return OperacaoRepository(conn).claim_next(worker_id, lease_seconds=60)

    with ThreadPoolExecutor(max_workers=2) as executor:
        claimed = list(executor.map(claim, ["worker-a", "worker-b"]))

    claimed_runs = [run for run in claimed if run is not None]
    assert len(claimed_runs) == 1
    assert claimed_runs[0].id == run.id
    assert claimed_runs[0].status is RunStatus.PREPARING
    assert claimed_runs[0].lease_owner in {"worker-a", "worker-b"}
    assert claimed_runs[0].lease_expires_at is not None
    assert claimed_runs[0].started_at.isoformat() == prior_start

    with db.transaction(immediate=True) as conn:
        repo = OperacaoRepository(conn)
        assert repo.claim_next("worker-c", lease_seconds=60) is None
        assert repo.list_queue() == []
        with pytest.raises(ValueError):
            repo.claim_next("   ", lease_seconds=60)
        with pytest.raises(ValueError):
            repo.claim_next("worker-c", lease_seconds=0)


def test_current_stages_usa_maior_attempt_em_ordem_canonica_e_mutacoes_desconhecidas_falham(db):
    with db.transaction(immediate=True) as conn:
        repo = OperacaoRepository(conn)
        _, run = create_run(repo)
        conn.execute(
            "UPDATE stage_runs SET gate_status = ?, input_hash = ? "
            "WHERE run_id = ? AND stage = ?",
            ("approved", "input-roteiro", run.id, StageName.ROTEIRO.value),
        )
        created = repo.invalidate_from_stage(run.id, StageName.ROTEIRO)
        current = repo.current_stages(run.id)

        assert [stage.stage for stage in created] == list(ETAPAS[2:])
        assert (created[0].gate_status, created[0].input_hash) == (None, None)
        assert [(stage.stage, stage.attempt, stage.status) for stage in current] == [
            (stage, 1 if stage in ETAPAS[:2] else 2, StageStatus.PENDING)
            for stage in ETAPAS
        ]
        old_dependent = conn.execute(
            "SELECT stage, attempt, status, gate_status, input_hash FROM stage_runs "
            "WHERE run_id = ? AND attempt = 1 AND stage IN (?, ?, ?, ?, ?, ?) "
            "ORDER BY CASE stage "
            "WHEN 'roteiro' THEN 1 WHEN 'plano_midia' THEN 2 WHEN 'audio' THEN 3 "
            "WHEN 'imagens' THEN 4 WHEN 'montagem' THEN 5 WHEN 'validacao' THEN 6 END",
            (run.id, *(stage.value for stage in ETAPAS[2:])),
        ).fetchall()
        assert [(row[0], row[1], row[2]) for row in old_dependent] == [
            (stage.value, 1, StageStatus.INVALIDATED.value) for stage in ETAPAS[2:]
        ]
        assert (old_dependent[0][3], old_dependent[0][4]) == (
            "approved",
            "input-roteiro",
        )
        assert repo.current_stages("missing") == []
        with pytest.raises(KeyError):
            repo.invalidate_from_stage("missing", StageName.ROTEIRO)
        with pytest.raises(KeyError):
            repo.save_run(run.model_copy(update={"id": "missing"}))


def test_save_run_persiste_apenas_campos_mutaveis(db):
    with db.transaction(immediate=True) as conn:
        repo = OperacaoRepository(conn)
        _, original = create_run(repo)
        changed = original.model_copy(
            update={
                "status": RunStatus.PAUSED,
                "priority": 80,
                "queue_position": 9,
                "config_snapshot": {"locale": "en-US"},
                "workflow_version": 3,
                "git_commit": "def456",
                "lease_owner": "worker",
                "lease_expires_at": datetime(2026, 1, 1, tzinfo=UTC),
                "pause_requested_at": datetime(2026, 1, 2, tzinfo=UTC),
                "started_at": datetime(2026, 1, 3, tzinfo=UTC),
                "finished_at": datetime(2026, 1, 4, tzinfo=UTC),
                "failure_code": "stopped",
                "failure_message": "manual pause",
            }
        )

        assert repo.save_run(changed) == changed
        persisted = repo.get_run(original.id)

    assert persisted == changed
    assert persisted.video_id == original.video_id
    assert persisted.created_at == original.created_at


def test_artifacts_registro_invalidacao_e_filtro_current_only(db):
    with db.transaction(immediate=True) as conn:
        repo = OperacaoRepository(conn)
        _, run = create_run(repo)
        roteiro_stage = next(
            stage for stage in repo.current_stages(run.id) if stage.stage is StageName.ROTEIRO
        )
        artifact = repo.register_artifact(artifact_for(run.id, roteiro_stage.id))

        assert artifact.metadata == {"language": "pt-BR", "sections": 9}
        assert repo.invalidate_artifacts(run.id, (StageName.ROTEIRO,)) == 1
        assert repo.invalidate_artifacts(run.id, ()) == 0
        assert repo.list_artifacts(run.id) == []
        all_artifacts = repo.list_artifacts(run.id, current_only=False)

        assert [(item.id, item.is_current) for item in all_artifacts] == [(artifact.id, False)]
        assert repo.register_artifact(
            artifact_for(run.id, roteiro_stage.id, artifact_id="artifact-2")
        ).is_current
        assert [item.id for item in repo.list_artifacts(run.id)] == ["artifact-2"]


def test_artifact_tardio_de_etapa_invalidada_eh_persistido_como_nao_atual(db):
    with db.transaction(immediate=True) as conn:
        repo = OperacaoRepository(conn)
        _, run = create_run(repo)
        roteiro_attempt1 = next(
            stage for stage in repo.current_stages(run.id) if stage.stage is StageName.ROTEIRO
        )
        repo.invalidate_from_stage(run.id, StageName.ROTEIRO)

        late_artifact = repo.register_artifact(
            artifact_for(run.id, roteiro_attempt1.id, artifact_id="late-roteiro")
        )
        roteiro_attempt2 = next(
            stage for stage in repo.current_stages(run.id) if stage.stage is StageName.ROTEIRO
        )
        current_artifact = repo.register_artifact(
            artifact_for(run.id, roteiro_attempt2.id, artifact_id="current-roteiro")
        )

        assert late_artifact.is_current is False
        assert current_artifact.is_current is True
        assert [item.id for item in repo.list_artifacts(run.id)] == [current_artifact.id]
        assert [(item.id, item.is_current) for item in repo.list_artifacts(
            run.id, current_only=False
        )] == [
            (late_artifact.id, False),
            (current_artifact.id, True),
        ]


def test_invalidate_artifacts_falha_para_run_desconhecida_com_ou_sem_etapas(db):
    with db.transaction(immediate=True) as conn:
        repo = OperacaoRepository(conn)

        with pytest.raises(KeyError) as nonempty_error:
            repo.invalidate_artifacts("missing-nonempty-run", (StageName.ROTEIRO,))
        assert nonempty_error.value.args == ("missing-nonempty-run",)

        with pytest.raises(KeyError) as empty_error:
            repo.invalidate_artifacts("missing-empty-run", ())
        assert empty_error.value.args == ("missing-empty-run",)


def test_get_unknown_e_none_e_artifact_ids_desconhecidos_falham(db):
    with db.transaction(immediate=True) as conn:
        repo = OperacaoRepository(conn)
        assert repo.get_run("missing") is None
        _, run = create_run(repo)
        roteiro_stage = next(
            stage for stage in repo.current_stages(run.id) if stage.stage is StageName.ROTEIRO
        )

        with pytest.raises(KeyError) as run_error:
            repo.register_artifact(
                artifact_for("missing-run", roteiro_stage.id, artifact_id="missing-run-artifact")
            )
        assert run_error.value.args == ("missing-run",)

        with pytest.raises(KeyError) as stage_error:
            repo.register_artifact(
                artifact_for(run.id, "missing-stage", artifact_id="missing-stage-artifact")
            )
        assert stage_error.value.args == ("missing-stage",)

        with pytest.raises(KeyError) as work_item_error:
            repo.register_artifact(
                artifact_for(run.id, roteiro_stage.id, artifact_id="missing-work-item-artifact").model_copy(
                    update={"work_item_id": "missing-work-item"}
                )
            )
        assert work_item_error.value.args == ("missing-work-item",)


def test_artifact_fk_invalida_propaga_integrity_error(db):
    with db.transaction(immediate=True) as conn:
        repo = OperacaoRepository(conn)
        _, first = create_run(repo, tema="first")
        _, second = create_run(repo, tema="second")
        second_stage = repo.current_stages(second.id)[0]

        with pytest.raises(sqlite3.IntegrityError):
            repo.register_artifact(artifact_for(first.id, second_stage.id, artifact_id="bad-fk"))
