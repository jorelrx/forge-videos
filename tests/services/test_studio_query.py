from __future__ import annotations

import pytest
from forge.domain.operacao import RunStatus, StageName, StageStatus
from forge.services.studio_query import StudioQueryService
from forge.repositories.connection import Database
from forge.repositories.operacao import OperacaoRepository
from forge.repositories.schema import init_db


def _setup_db_with_data(db: Database):
    with db.connection() as conn:
        repo = OperacaoRepository(conn)
        video1, run1 = repo.create_video_and_run(
            tema="Tema prioritário",
            tese=None,
            priority=90,
            config_snapshot={},
            workflow_version=1,
            git_commit="abc",
        )
        video2, run2 = repo.create_video_and_run(
            tema="Tema normal",
            tese=None,
            priority=50,
            config_snapshot={},
            workflow_version=1,
            git_commit="abc",
        )
        # Run2 fica em RUNNING com stages avançados
        stages2 = repo.current_stages(run2.id)
        # Primeiro e segundo stages (PREPARACAO, PESQUISA) -> SUCCEEDED, progress 1.0
        for s in stages2[:2]:
            repo.save_stage(
                s.model_copy(update={"status": StageStatus.SUCCEEDED, "progress": 1.0})
            )
        # Terceiro stage (ROTEIRO) -> RUNNING, progress 0.5
        roteiro_stage = stages2[2]
        repo.save_stage(
            roteiro_stage.model_copy(update={"status": StageStatus.RUNNING, "progress": 0.5})
        )
        repo.save_run(run2.model_copy(update={"status": RunStatus.RUNNING}))
        # Run1 fica em QUEUED (todos stages PENDING, progress 0)
    return db, run1, run2


def test_queue_and_history_include_video_identity_and_stable_global_progress(db):
    db, run1, run2 = _setup_db_with_data(db)
    queries = StudioQueryService(db)

    # Verificar queue (apenas runs QUEUED)
    queue = queries.list_queue()
    assert len(queue) >= 1
    # O primeiro da queue é o run1 (Tema prioritário, priority 90)
    assert queue[0].video.tema == "Tema prioritário"
    # Run1 está QUEUED com todos os stages em PENDING (progress=0)
    assert queue[0].progress == pytest.approx(0.0)
    # Verificar runs list (inclui todos os runs)
    page = queries.list_runs(limit=10, offset=0)
    assert page.total >= 2
    # O run2 está em RUNNING com progress parcial
    run2_items = [r for r in page.items if r.run.id == run2.id]
    assert len(run2_items) > 0
    assert run2_items[0].progress == pytest.approx((1 + 1 + 0.5) / 8)


def test_run_view_uses_only_current_attempt_and_exposes_items_metrics_and_artifacts(db):
    db, run1, _ = _setup_db_with_data(db)
    queries = StudioQueryService(db)
    detail = queries.get_run(run1.id)

    assert len(detail.stages) == 8
    audio_stage_view = detail.stages[StageName.AUDIO]
    # O stage de audio está em PENDING com attempt=1 (criado por create_video_and_run)
    assert audio_stage_view.stage_run.attempt == 1
    assert audio_stage_view.stage_run.status == StageStatus.PENDING
    assert [item.item_key for item in audio_stage_view.items] == []
    assert audio_stage_view.metrics == {}
    assert all(artifact.is_current for artifact in detail.artifacts)


def test_unknown_run_and_artifact_raise_key_error(db):
    db, _, _ = _setup_db_with_data(db)
    queries = StudioQueryService(db)

    with pytest.raises(KeyError):
        queries.get_run("missing")
    with pytest.raises(KeyError):
        queries.get_artifact("missing")
