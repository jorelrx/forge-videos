from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from forge.domain.operacao import (
    ETAPAS,
    Artifact,
    CommandStatus,
    RunStatus,
    StageName,
    StageStatus,
    dependentes_de,
)
from forge.repositories.comandos import IdempotencyConflict
from forge.repositories.connection import Database
from forge.repositories.eventos import EventosRepository
from forge.repositories.operacao import OperacaoRepository
from forge.repositories.schema import init_db
from forge.services.control_plane import ControlPlaneService
from forge.services.maquina_estados import TransicaoInvalida

FIXED_NOW = datetime(2026, 9, 12, 15, 30, tzinfo=UTC)


@pytest.fixture
def db(tmp_path):
    database = Database(tmp_path / "forge.db")
    init_db(database)
    return database


@pytest.fixture
def control_plane(db):
    return ControlPlaneService(db, now=lambda: FIXED_NOW)


def enqueue(control_plane: ControlPlaneService, *, tema: str = "Tema", priority: int = 50):
    return control_plane.enqueue_video(
        tema=tema,
        tese="Tese",
        priority=priority,
        config_snapshot={"locale": "pt-BR", "render": {"quality": "alta"}},
        workflow_version=2,
        git_commit="abc123",
    )


def save_run_status(
    db: Database,
    run_id: str,
    status: RunStatus,
    **updates: object,
):
    with db.transaction(immediate=True) as conn:
        repo = OperacaoRepository(conn)
        run = repo.get_run(run_id)
        assert run is not None
        return repo.save_run(run.model_copy(update={"status": status, **updates}))


def stage_for(db: Database, run_id: str, name: StageName):
    with db.connection() as conn:
        stages = OperacaoRepository(conn).current_stages(run_id)
    return next(stage for stage in stages if stage.stage is name)


def artifact_for(run_id: str, stage_run_id: str, *, artifact_id: str) -> Artifact:
    return Artifact(
        id=artifact_id,
        run_id=run_id,
        stage_run_id=stage_run_id,
        kind="roteiro",
        relative_path=f"artefatos/{artifact_id}.md",
        sha256="a" * 64,
        size_bytes=12,
        mime_type="text/markdown",
        metadata={"language": "pt-BR"},
        is_current=True,
        created_at=FIXED_NOW,
    )


def count_rows(db: Database, table: str, run_id: str) -> int:
    with db.connection() as conn:
        return conn.execute(f"SELECT COUNT(*) FROM {table} WHERE run_id = ?", (run_id,)).fetchone()[0]


def test_enqueue_is_atomic_and_detail_has_eight_stages_and_queued_event(control_plane, db):
    video, run = enqueue(control_plane)

    detail = control_plane.get_run(run.id)
    events = control_plane.events_after(0, run_id=run.id)

    assert detail.run == run
    assert detail.run.video_id == video.id
    assert [stage.stage for stage in detail.stages] == list(ETAPAS)
    assert len(detail.stages) == 8
    assert detail.artifacts == []
    assert [(event.kind, event.run_id) for event in events] == [("run.queued", run.id)]


def test_getters_delegate_read_projections_and_unknown_run_is_key_error(control_plane, db):
    _, low = enqueue(control_plane, tema="low", priority=10)
    _, high = enqueue(control_plane, tema="high", priority=90)
    roteiro = stage_for(db, high.id, StageName.ROTEIRO)
    with db.transaction(immediate=True) as conn:
        OperacaoRepository(conn).register_artifact(
            artifact_for(high.id, roteiro.id, artifact_id="high-roteiro")
        )
        EventosRepository(conn).append(
            kind="stage.started",
            level="info",
            message="started",
            payload={"stage": "roteiro"},
            run_id=high.id,
            stage_run_id=roteiro.id,
        )

    assert [run.id for run in control_plane.list_queue()] == [high.id, low.id]
    assert [run.id for run in control_plane.list_runs(limit=1, offset=1)] == [low.id]
    assert [artifact.id for artifact in control_plane.get_run(high.id).artifacts] == ["high-roteiro"]
    assert [event.kind for event in control_plane.events_after(0, run_id=high.id)] == [
        "run.queued",
        "stage.started",
    ]
    with pytest.raises(KeyError) as error:
        control_plane.get_run("missing-run")
    assert error.value.args == ("missing-run",)


def test_claim_emits_exact_event_payload_and_empty_queue_has_no_event(control_plane):
    _, run = enqueue(control_plane)

    claimed = control_plane.claim_next("worker-a", lease_seconds=45)
    empty = control_plane.claim_next("worker-b", lease_seconds=45)
    events = control_plane.events_after(0, run_id=run.id)

    assert claimed is not None
    assert claimed.id == run.id
    assert claimed.status is RunStatus.PREPARING
    assert empty is None
    assert [(event.kind, event.payload) for event in events] == [
        ("run.queued", {}),
        ("run.claimed", {"worker_id": "worker-a", "lease_seconds": 45}),
    ]


@pytest.mark.parametrize(
    ("worker_id", "lease_seconds"),
    [("   ", 45), ("worker-a", 0)],
)
def test_claim_validation_errors_propagate_without_events(control_plane, worker_id, lease_seconds):
    _, run = enqueue(control_plane)

    with pytest.raises(ValueError):
        control_plane.claim_next(worker_id, lease_seconds=lease_seconds)

    assert [event.kind for event in control_plane.events_after(0, run_id=run.id)] == ["run.queued"]


@pytest.mark.parametrize(
    "initial_status",
    [RunStatus.PREPARING, RunStatus.RUNNING, RunStatus.VALIDATING],
)
def test_pause_valid_paths_set_timestamp_and_are_idempotent(control_plane, db, initial_status):
    _, run = enqueue(control_plane)
    save_run_status(db, run.id, initial_status)

    command = control_plane.request_pause(run.id, idempotency_key="pause-1")
    duplicate = control_plane.request_pause(run.id, idempotency_key="pause-1")
    paused = control_plane.get_run(run.id).run
    events = control_plane.events_after(0, run_id=run.id)

    assert command.status is CommandStatus.ACCEPTED
    assert duplicate.id == command.id
    assert paused.status is RunStatus.PAUSING
    assert paused.pause_requested_at == FIXED_NOW
    assert [event.kind for event in events] == ["run.queued", "command.pause_requested"]


@pytest.mark.parametrize("status", [RunStatus.PAUSED, RunStatus.QUEUED])
def test_pause_invalid_transition_rolls_back_new_command_and_side_effects(control_plane, db, status):
    _, run = enqueue(control_plane)
    save_run_status(db, run.id, status)
    before_events = control_plane.events_after(0, run_id=run.id)

    with pytest.raises(TransicaoInvalida):
        control_plane.request_pause(run.id, idempotency_key=f"pause-{status.value}")

    persisted = control_plane.get_run(run.id).run
    assert persisted.status is status
    assert persisted.pause_requested_at is None
    assert count_rows(db, "commands", run.id) == 0
    assert control_plane.events_after(0, run_id=run.id) == before_events


@pytest.mark.parametrize("status", [RunStatus.PAUSED, RunStatus.FAILED, RunStatus.INTERRUPTED])
def test_resume_requeues_clears_fields_and_duplicate_wins(control_plane, db, status):
    _, run = enqueue(control_plane)
    save_run_status(
        db,
        run.id,
        status,
        lease_owner="worker-a",
        lease_expires_at=FIXED_NOW + timedelta(minutes=1),
        failure_code="boom",
        failure_message="failure",
    )

    command = control_plane.request_resume(run.id, idempotency_key=f"resume-{status.value}")
    duplicate = control_plane.request_resume(run.id, idempotency_key=f"resume-{status.value}")
    resumed = control_plane.get_run(run.id).run

    assert command.status is CommandStatus.APPLIED
    assert duplicate.id == command.id
    assert resumed.status is RunStatus.QUEUED
    assert resumed.lease_owner is None
    assert resumed.lease_expires_at is None
    assert resumed.failure_code is None
    assert resumed.failure_message is None
    assert [event.kind for event in control_plane.events_after(0, run_id=run.id)] == [
        "run.queued",
        "run.queued",
    ]


def test_resume_invalid_transition_rolls_back_command_and_side_effects(control_plane, db):
    _, run = enqueue(control_plane)
    save_run_status(db, run.id, RunStatus.RUNNING, lease_owner="worker-a")
    before_events = control_plane.events_after(0, run_id=run.id)

    with pytest.raises(TransicaoInvalida):
        control_plane.request_resume(run.id, idempotency_key="resume-invalid")

    persisted = control_plane.get_run(run.id).run
    assert persisted.status is RunStatus.RUNNING
    assert persisted.lease_owner == "worker-a"
    assert count_rows(db, "commands", run.id) == 0
    assert control_plane.events_after(0, run_id=run.id) == before_events


@pytest.mark.parametrize("initial_status", [RunStatus.FAILED, RunStatus.COMPLETED])
def test_retry_invalidates_exact_downstream_artifacts_and_preserves_history(
    control_plane, db, initial_status
):
    _, run = enqueue(control_plane)
    save_run_status(db, run.id, initial_status)
    roteiro = stage_for(db, run.id, StageName.ROTEIRO)
    pesquisa = stage_for(db, run.id, StageName.PESQUISA)
    with db.transaction(immediate=True) as conn:
        repo = OperacaoRepository(conn)
        repo.register_artifact(artifact_for(run.id, roteiro.id, artifact_id="roteiro-old"))
        repo.register_artifact(artifact_for(run.id, pesquisa.id, artifact_id="pesquisa-current"))

    command = control_plane.request_retry_stage(
        run.id, StageName.ROTEIRO, idempotency_key=f"retry-{initial_status.value}"
    )
    duplicate = control_plane.request_retry_stage(
        run.id, StageName.ROTEIRO, idempotency_key=f"retry-{initial_status.value}"
    )
    detail = control_plane.get_run(run.id)
    all_artifacts = []
    with db.connection() as conn:
        repo = OperacaoRepository(conn)
        all_artifacts = repo.list_artifacts(run.id, current_only=False)
        history = conn.execute(
            "SELECT stage, attempt, status FROM stage_runs WHERE run_id = ? ORDER BY stage, attempt",
            (run.id,),
        ).fetchall()

    dependent = dependentes_de(StageName.ROTEIRO)
    current_by_stage = {stage.stage: stage for stage in detail.stages}
    attempts_by_stage = {
        row["stage"]: [item[1:] for item in history if item[0] == row["stage"]]
        for row in history
    }

    assert command.status is CommandStatus.APPLIED
    assert duplicate.id == command.id
    assert detail.run.status is RunStatus.QUEUED
    assert [current_by_stage[stage].attempt for stage in dependent] == [2] * len(dependent)
    assert [current_by_stage[stage].attempt for stage in ETAPAS[:2]] == [1, 1]
    assert all(attempts_by_stage[stage.value][0] == (1, StageStatus.INVALIDATED.value) for stage in dependent)
    assert {(artifact.id, artifact.is_current) for artifact in all_artifacts} == {
        ("roteiro-old", False),
        ("pesquisa-current", True),
    }
    events = control_plane.events_after(0, run_id=run.id)
    assert [event.kind for event in events[-2:]] == ["stages.invalidated", "run.queued"]
    assert events[-2].payload == {"stages": [stage.value for stage in dependent]}
    assert count_rows(db, "stage_runs", run.id) == 8 + len(dependent)


def test_retry_invalid_transition_keeps_commands_attempts_artifacts_and_events_unchanged(control_plane, db):
    _, run = enqueue(control_plane)
    save_run_status(db, run.id, RunStatus.RUNNING)
    roteiro = stage_for(db, run.id, StageName.ROTEIRO)
    with db.transaction(immediate=True) as conn:
        OperacaoRepository(conn).register_artifact(
            artifact_for(run.id, roteiro.id, artifact_id="roteiro-current")
        )
    before_events = control_plane.events_after(0, run_id=run.id)
    before_stages = control_plane.get_run(run.id).stages

    with pytest.raises(TransicaoInvalida):
        control_plane.request_retry_stage(run.id, StageName.ROTEIRO, idempotency_key="retry-invalid")

    assert count_rows(db, "commands", run.id) == 0
    assert control_plane.get_run(run.id).stages == before_stages
    assert [artifact.id for artifact in control_plane.get_run(run.id).artifacts] == ["roteiro-current"]
    assert control_plane.events_after(0, run_id=run.id) == before_events


def test_retry_rolls_back_every_partial_write_when_event_append_fails(control_plane, db, monkeypatch):
    _, run = enqueue(control_plane)
    save_run_status(db, run.id, RunStatus.FAILED)
    roteiro = stage_for(db, run.id, StageName.ROTEIRO)
    with db.transaction(immediate=True) as conn:
        OperacaoRepository(conn).register_artifact(
            artifact_for(run.id, roteiro.id, artifact_id="roteiro-current")
        )
    before_events = control_plane.events_after(0, run_id=run.id)

    def fail_append(self, **kwargs):
        raise RuntimeError("event store unavailable")

    monkeypatch.setattr(EventosRepository, "append", fail_append)
    with pytest.raises(RuntimeError, match="event store unavailable"):
        control_plane.request_retry_stage(run.id, StageName.ROTEIRO, idempotency_key="retry-fails")

    detail = control_plane.get_run(run.id)
    assert detail.run.status is RunStatus.FAILED
    assert [(stage.stage, stage.attempt) for stage in detail.stages] == [
        (stage, 1) for stage in ETAPAS
    ]
    assert [artifact.id for artifact in detail.artifacts] == ["roteiro-current"]
    assert count_rows(db, "commands", run.id) == 0
    assert control_plane.events_after(0, run_id=run.id) == before_events


def test_cross_payload_idempotency_conflict_propagates_without_side_effects(control_plane, db):
    _, run = enqueue(control_plane)
    save_run_status(db, run.id, RunStatus.RUNNING)
    control_plane.request_pause(run.id, idempotency_key="same-key")
    before_events = control_plane.events_after(0, run_id=run.id)

    with pytest.raises(IdempotencyConflict):
        control_plane.request_retry_stage(run.id, StageName.ROTEIRO, idempotency_key="same-key")

    assert control_plane.get_run(run.id).run.status is RunStatus.PAUSING
    assert count_rows(db, "commands", run.id) == 1
    assert control_plane.events_after(0, run_id=run.id) == before_events
