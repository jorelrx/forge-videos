from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from forge.domain.operacao import RunStatus, StageName, StageStatus
from forge.repositories.connection import Database
from forge.repositories.schema import init_db
from forge.services.control_plane import ControlPlaneService
from forge.services.worker import StageResult, StudioWorker

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
