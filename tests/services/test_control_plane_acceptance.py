from forge.domain.operacao import ETAPAS, RunStatus, StageName, dependentes_de
from forge.infrastructure.config import Settings
from forge.repositories.operacao import OperacaoRepository
from forge.services.control_plane import ControlPlaneService
from forge.services.studio import build_control_plane


def _enqueue(service: ControlPlaneService, *, tema: str, priority: int):
    return service.enqueue_video(
        tema=tema,
        tese=None,
        priority=priority,
        config_snapshot={"environment": "local"},
        workflow_version=1,
        git_commit="local-test-git",
    )


def _mark_failed(service: ControlPlaneService, run_id: str) -> None:
    with service.db.transaction(immediate=True) as conn:
        repository = OperacaoRepository(conn)
        run = repository.get_run(run_id)
        assert run is not None
        repository.save_run(run.model_copy(update={"status": RunStatus.FAILED}))


def test_control_plane_survives_restart_and_preserves_queue_commands_and_history(tmp_path):
    settings = Settings(_env_file=None, studio_db_path=tmp_path / "forge.db")
    first = build_control_plane(settings)
    _, a = _enqueue(first, tema="A", priority=10)
    _, b = _enqueue(first, tema="B", priority=90)
    _, c = _enqueue(first, tema="C", priority=50)

    restarted = build_control_plane(settings)
    assert [run.id for run in restarted.list_queue()] == [b.id, c.id, a.id]

    claimed = restarted.claim_next("worker-1", lease_seconds=15)
    assert claimed is not None
    assert claimed.id == b.id
    assert claimed.status is RunStatus.PREPARING

    _mark_failed(restarted, b.id)
    retried = restarted.request_retry_stage(
        b.id, StageName.ROTEIRO, idempotency_key="retry-b-roteiro-1"
    )
    duplicate = restarted.request_retry_stage(
        b.id, StageName.ROTEIRO, idempotency_key="retry-b-roteiro-1"
    )
    assert duplicate.id == retried.id

    retried_detail = restarted.get_run(b.id)
    retried_stages = {stage.stage: stage for stage in retried_detail.stages}
    assert retried_detail.run.status is RunStatus.QUEUED
    assert retried_stages[StageName.ROTEIRO].attempt == 2
    assert retried_stages[StageName.PESQUISA].attempt == 1
    with restarted.db.connection() as conn:
        command_count = conn.execute(
            "SELECT COUNT(*) FROM commands WHERE run_id = ? AND idempotency_key = ?",
            (b.id, "retry-b-roteiro-1"),
        ).fetchone()[0]
    assert command_count == 1

    third = build_control_plane(settings)
    assert [run.id for run in third.list_queue()] == [b.id, c.id, a.id]

    persisted_detail = third.get_run(b.id)
    persisted_stages = {stage.stage: stage for stage in persisted_detail.stages}
    assert persisted_detail.run.status is RunStatus.QUEUED
    assert persisted_stages[StageName.ROTEIRO].attempt == 2
    assert persisted_stages[StageName.PESQUISA].attempt == 1

    events = third.events_after(0, run_id=b.id)
    assert [event.kind for event in events] == [
        "run.queued",
        "run.claimed",
        "stages.invalidated",
        "run.queued",
    ]
    assert events[2].payload == {
        "stages": [stage.value for stage in dependentes_de(StageName.ROTEIRO)]
    }
    with third.db.connection() as conn:
        stage_run_count = conn.execute(
            "SELECT COUNT(*) FROM stage_runs WHERE run_id = ?", (b.id,)
        ).fetchone()[0]
    assert stage_run_count == len(ETAPAS) + len(dependentes_de(StageName.ROTEIRO))
