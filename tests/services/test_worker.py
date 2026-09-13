from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from forge.domain.operacao import CommandStatus, RunStatus, StageName, StageStatus
from forge.repositories.comandos import ComandosRepository
from forge.repositories.connection import Database
from forge.repositories.schema import init_db
from forge.services.control_plane import ControlPlaneService
from forge.services.worker import LeaseHeartbeat, StageResult, StudioWorker

FIXED_NOW = datetime(2026, 9, 12, 15, 30, tzinfo=UTC)


class FakeExecutor:
    def __init__(self, result: StageResult) -> None:
        self.result = result
        self.contexts = []

    def execute(self, context, emit):
        self.contexts.append(context)
        emit(
            kind="executor.progress",
            level="info",
            message="Item processado",
            payload={"current_items": 1},
        )
        return self.result


@pytest.fixture
def db(tmp_path):
    database = Database(tmp_path / "forge.db")
    init_db(database)
    return database


@pytest.fixture
def control_plane(db):
    return ControlPlaneService(db, now=lambda: FIXED_NOW)


def enqueue(control_plane: ControlPlaneService, *, tema: str = "Tema"):
    return control_plane.enqueue_video(
        tema=tema,
        tese="Tese",
        priority=50,
        config_snapshot={"locale": "pt-BR"},
        workflow_version=2,
        git_commit="abc123",
    )[1]


def stage_for(control_plane: ControlPlaneService, run_id: str, stage: StageName):
    return next(item for item in control_plane.get_run(run_id).stages if item.stage is stage)


def test_run_once_marks_the_current_pending_stage_succeeded_and_persists_events(
    db, control_plane
):
    run = enqueue(control_plane)
    executor = FakeExecutor(
        StageResult(gate_status="approved", current_items=2, total_items=2)
    )
    worker = StudioWorker(
        db,
        worker_id="worker-a",
        lease_seconds=45,
        executors={StageName.PREPARACAO: executor},
        now=lambda: FIXED_NOW,
    )

    processed = worker.run_once()

    stage = stage_for(control_plane, run.id, StageName.PREPARACAO)
    assert processed is not None
    assert processed.id == run.id
    assert control_plane.get_run(run.id).run.status is RunStatus.RUNNING
    assert stage.status is StageStatus.SUCCEEDED
    assert (stage.current_items, stage.total_items, stage.progress) == (2, 2, 1)
    assert stage.gate_status == "approved"
    assert executor.contexts[0].run.id == run.id
    assert executor.contexts[0].stage_run.id == stage.id
    assert [event.kind for event in control_plane.events_after(0, run_id=run.id)] == [
        "run.queued",
        "run.claimed",
        "stage.started",
        "executor.progress",
        "stage.succeeded",
    ]


def test_run_once_resumes_its_owned_run_for_the_next_pending_stage(
    db, control_plane
):
    run = enqueue(control_plane)
    preparation_executor = FakeExecutor(StageResult(current_items=1, total_items=1))
    research_executor = FakeExecutor(StageResult(current_items=1, total_items=1))
    worker = StudioWorker(
        db,
        worker_id="worker-a",
        lease_seconds=45,
        executors={
            StageName.PREPARACAO: preparation_executor,
            StageName.PESQUISA: research_executor,
        },
        now=lambda: FIXED_NOW,
    )

    worker.run_once()
    worker.run_once()

    assert stage_for(control_plane, run.id, StageName.PREPARACAO).status is StageStatus.SUCCEEDED
    assert stage_for(control_plane, run.id, StageName.PESQUISA).status is StageStatus.SUCCEEDED
    assert [context.stage_run.stage for context in research_executor.contexts] == [
        StageName.PESQUISA
    ]


def test_run_once_marks_run_and_stage_failed_for_a_failed_executor_result(db, control_plane):
    run = enqueue(control_plane)
    worker = StudioWorker(
        db,
        worker_id="worker-a",
        lease_seconds=45,
        executors={
            StageName.PREPARACAO: FakeExecutor(
                StageResult(
                    failure_code="gate_rejected",
                    failure_message="A etapa não passou no gate",
                )
            )
        },
        now=lambda: FIXED_NOW,
    )

    worker.run_once()

    detail = control_plane.get_run(run.id)
    stage = stage_for(control_plane, run.id, StageName.PREPARACAO)
    assert detail.run.status is RunStatus.FAILED
    assert (detail.run.failure_code, detail.run.failure_message) == (
        "gate_rejected",
        "A etapa não passou no gate",
    )
    assert detail.run.lease_owner is None
    assert detail.run.lease_expires_at is None
    assert stage.status is StageStatus.FAILED
    assert (stage.failure_code, stage.failure_message) == (
        "gate_rejected",
        "A etapa não passou no gate",
    )
    assert [event.kind for event in control_plane.events_after(0, run_id=run.id)] == [
        "run.queued",
        "run.claimed",
        "stage.started",
        "executor.progress",
        "stage.failed",
    ]


def test_run_once_records_missing_executor_without_advancing_the_pending_stage(
    db, control_plane
):
    run = enqueue(control_plane)
    worker = StudioWorker(
        db,
        worker_id="worker-a",
        lease_seconds=45,
        executors={},
        now=lambda: FIXED_NOW,
    )

    worker.run_once()

    assert control_plane.get_run(run.id).run.status is RunStatus.PREPARING
    assert stage_for(control_plane, run.id, StageName.PREPARACAO).status is StageStatus.PENDING
    events = control_plane.events_after(0, run_id=run.id)
    assert events[-1].kind == "executor_missing"
    assert events[-1].payload == {"stage": "preparacao"}


def test_run_once_interrupts_expired_runs_before_claiming_the_next_queued_run(
    db, control_plane
):
    expired = enqueue(control_plane, tema="Expirada")
    queued = enqueue(control_plane, tema="Nova")
    claimed = control_plane.claim_next("dead-worker", lease_seconds=45)
    assert claimed is not None
    with db.transaction(immediate=True) as conn:
        conn.execute(
            "UPDATE runs SET lease_expires_at = ? WHERE id = ?",
            ((FIXED_NOW - timedelta(seconds=1)).isoformat(), expired.id),
        )

    worker = StudioWorker(
        db,
        worker_id="worker-a",
        lease_seconds=45,
        executors={},
        now=lambda: FIXED_NOW,
    )

    processed = worker.run_once()

    assert control_plane.get_run(expired.id).run.status is RunStatus.INTERRUPTED
    assert processed is not None
    assert processed.id == queued.id


def test_lease_heartbeat_tick_renews_an_owned_active_lease(db, control_plane):
    run = enqueue(control_plane)
    claimed = control_plane.claim_next("worker-a", lease_seconds=45)
    assert claimed is not None

    heartbeat = LeaseHeartbeat(
        db,
        run_id=run.id,
        worker_id="worker-a",
        lease_seconds=45,
    )

    assert heartbeat.tick() is True
    renewed = control_plane.get_run(run.id).run
    assert renewed.lease_owner == "worker-a"
    assert renewed.lease_expires_at is not None
    assert claimed.lease_expires_at is not None
    assert renewed.lease_expires_at > claimed.lease_expires_at


class OwnershipLosingExecutor:
    def __init__(self, db) -> None:
        self.db = db

    def execute(self, context, emit):
        with self.db.transaction(immediate=True) as conn:
            conn.execute(
                "UPDATE runs SET lease_owner = ? WHERE id = ?",
                ("worker-b", context.run.id),
            )
        return StageResult(current_items=1, total_items=1)


def test_run_once_does_not_finish_a_stage_after_losing_lease_ownership(
    db, control_plane
):
    run = enqueue(control_plane)
    worker = StudioWorker(
        db,
        worker_id="worker-a",
        lease_seconds=45,
        executors={StageName.PREPARACAO: OwnershipLosingExecutor(db)},
        now=lambda: FIXED_NOW,
    )

    worker.run_once()

    detail = control_plane.get_run(run.id)
    assert detail.run.lease_owner == "worker-b"
    assert detail.run.status is RunStatus.RUNNING
    assert stage_for(control_plane, run.id, StageName.PREPARACAO).status is StageStatus.RUNNING
    assert [event.kind for event in control_plane.events_after(0, run_id=run.id)] == [
        "run.queued",
        "run.claimed",
        "stage.started",
    ]


class LeaseExpiringExecutor:
    def __init__(self, db) -> None:
        self.db = db
        self.completed = False

    def execute(self, context, emit):
        with self.db.transaction(immediate=True) as conn:
            conn.execute(
                "UPDATE runs SET lease_expires_at = ? WHERE id = ?",
                ((FIXED_NOW - timedelta(seconds=1)).isoformat(), context.run.id),
            )
        self.completed = True
        return StageResult(current_items=1, total_items=1)


def test_run_once_interrupts_an_expired_lease_only_after_executor_returns(
    db, control_plane
):
    run = enqueue(control_plane)
    executor = LeaseExpiringExecutor(db)
    worker = StudioWorker(
        db,
        worker_id="worker-a",
        lease_seconds=45,
        executors={StageName.PREPARACAO: executor},
        now=lambda: FIXED_NOW,
    )

    worker.run_once()

    assert executor.completed is True
    assert control_plane.get_run(run.id).run.status is RunStatus.INTERRUPTED
    assert stage_for(control_plane, run.id, StageName.PREPARACAO).status is StageStatus.INTERRUPTED
    assert [event.kind for event in control_plane.events_after(0, run_id=run.id)] == [
        "run.queued",
        "run.claimed",
        "stage.started",
        "run.interrupted",
    ]


class PauseDuringExecutionExecutor:
    def __init__(self, control_plane: ControlPlaneService) -> None:
        self.control_plane = control_plane
        self.stage_status_after_pause = None
        self.command_id = None

    def execute(self, context, emit):
        self.command_id = self.control_plane.request_pause(
            context.run.id, idempotency_key="pause-at-boundary"
        ).id
        self.stage_status_after_pause = stage_for(
            self.control_plane, context.run.id, context.stage_run.stage
        ).status
        return StageResult(current_items=1, total_items=2)


def test_run_once_applies_accepted_pause_only_after_executor_returns(db, control_plane):
    run = enqueue(control_plane)
    executor = PauseDuringExecutionExecutor(control_plane)
    worker = StudioWorker(
        db,
        worker_id="worker-a",
        lease_seconds=45,
        executors={StageName.PREPARACAO: executor},
        now=lambda: FIXED_NOW,
    )

    worker.run_once()

    detail = control_plane.get_run(run.id)
    stage = stage_for(control_plane, run.id, StageName.PREPARACAO)
    with db.connection() as conn:
        command = ComandosRepository(conn).get(executor.command_id)

    assert executor.stage_status_after_pause is StageStatus.RUNNING
    assert detail.run.status is RunStatus.PAUSED
    assert detail.run.lease_owner is None
    assert detail.run.lease_expires_at is None
    assert stage.status is StageStatus.PAUSED
    assert (stage.current_items, stage.total_items, stage.progress) == (1, 2, 0.5)
    assert command is not None
    assert command.status is CommandStatus.APPLIED
    assert command.applied_at is not None
    assert [event.kind for event in control_plane.events_after(0, run_id=run.id)] == [
        "run.queued",
        "run.claimed",
        "stage.started",
        "command.pause_requested",
        "run.paused",
    ]
