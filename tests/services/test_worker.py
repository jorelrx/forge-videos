from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from forge.domain.operacao import CommandStatus, RunStatus, StageName, StageStatus
from forge.repositories.comandos import ComandosRepository
from forge.repositories.connection import Database
from forge.repositories.operacao import OperacaoRepository
from forge.repositories.schema import init_db
from forge.services.control_plane import ControlPlaneService
from forge.services.redacao import Redactor
from forge.services.worker import LeaseHeartbeat, StageResult, StudioWorker

FIXED_NOW = datetime(2026, 9, 12, 15, 30, tzinfo=UTC)


class FakeExecutor:
    def __init__(self, result: StageResult, *, event_payload: dict | None = None) -> None:
        self.result = result
        self.contexts = []
        self.event_payload = event_payload or {"current_items": 1}

    def execute(self, context, emit):
        self.contexts.append(context)
        emit(
            kind="executor.progress",
            level="info",
            message="Item processado",
            payload=self.event_payload,
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


def test_run_once_applies_pause_between_stages_before_starting_pending_executor(
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
    command = control_plane.request_pause(run.id, idempotency_key="pause-between-stages")
    worker.run_once()

    detail = control_plane.get_run(run.id)
    pending_stage = stage_for(control_plane, run.id, StageName.PESQUISA)
    with db.connection() as conn:
        persisted_command = ComandosRepository(conn).get(command.id)

    assert detail.run.status is RunStatus.PAUSED
    assert detail.run.lease_owner is None
    assert detail.run.lease_expires_at is None
    assert pending_stage.status is StageStatus.PENDING
    assert research_executor.contexts == []
    assert persisted_command is not None
    assert persisted_command.status is CommandStatus.APPLIED
    assert persisted_command.applied_at is not None
    assert [event.kind for event in control_plane.events_after(0, run_id=run.id)] == [
        "run.queued",
        "run.claimed",
        "stage.started",
        "executor.progress",
        "stage.succeeded",
        "command.pause_requested",
        "run.paused",
    ]


def test_run_once_does_not_start_stage_when_pause_arrives_after_boundary_check(
    db, control_plane, monkeypatch
):
    run = enqueue(control_plane)
    executor = FakeExecutor(StageResult(current_items=1, total_items=1))
    worker = StudioWorker(
        db,
        worker_id="worker-a",
        lease_seconds=45,
        executors={StageName.PREPARACAO: executor},
        now=lambda: FIXED_NOW,
    )
    pause_before_stage = worker._pause_before_stage

    def request_pause_after_boundary_check(run, stage):
        paused = pause_before_stage(run, stage)
        if paused is None:
            control_plane.request_pause(
                run.id, idempotency_key="pause-after-boundary-check"
            )
        return paused

    monkeypatch.setattr(worker, "_pause_before_stage", request_pause_after_boundary_check)

    worker.run_once()

    detail = control_plane.get_run(run.id)
    stage = stage_for(control_plane, run.id, StageName.PREPARACAO)
    assert detail.run.status is RunStatus.PAUSED
    assert stage.status is StageStatus.PENDING
    assert executor.contexts == []


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


def test_run_once_persists_sanitized_failure_evidence_on_stage_failed(
    db, control_plane
):
    run = enqueue(control_plane)
    evidence = {
        "adapter": "tts",
        "command": ["tts", "--token", "secret-token"],
        "attempt": 3,
        "item_key": "b001",
        "stack_trace": "RuntimeError: secret-token",
        "services": {"status": "down"},
        "gpu": {"memory_free_mb": 12},
        "retriable": False,
        "recommended_action": "liberar GPU e tentar novamente",
    }
    worker = StudioWorker(
        db,
        worker_id="worker-a",
        lease_seconds=45,
        executors={
            StageName.PREPARACAO: FakeExecutor(
                StageResult(
                    failure_code="tts_vulkan_oom",
                    failure_message="Memória insuficiente",
                    outputs={"failure": evidence},
                ),
                event_payload={"stack_trace": "secret-token", "argv": ["secret-token"]},
            )
        },
        redactor=Redactor(secrets=["secret-token"]),
        now=lambda: FIXED_NOW,
    )

    worker.run_once()

    failed_event = next(
        event
        for event in control_plane.events_after(0, run_id=run.id)
        if event.kind == "stage.failed"
    )
    failure = failed_event.payload["failure"]
    assert failure["adapter"] == "tts"
    assert failure["command"] == ["tts", "--token", "[REDACTED]"]
    assert failure["attempt"] == 3
    assert failure["item_key"] == "b001"
    assert failure["stack_trace"] == "RuntimeError: [REDACTED]"
    assert failure["services"] == {"status": "down"}
    assert failure["gpu"] == {"memory_free_mb": 12}
    assert failure["retriable"] is False
    assert failure["recommended_action"] == "liberar GPU e tentar novamente"
    progress_event = next(
        event
        for event in control_plane.events_after(0, run_id=run.id)
        if event.kind == "executor.progress"
    )
    assert progress_event.payload == {
        "stack_trace": "[REDACTED]",
        "argv": ["[REDACTED]"],
    }


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


class LeaseLossWaitingExecutor:
    def __init__(self, db) -> None:
        self.db = db
        self.cancel_seen = False

    def execute(self, context, emit):
        with self.db.transaction(immediate=True) as conn:
            conn.execute(
                "UPDATE runs SET lease_owner = ? WHERE id = ?",
                ("worker-b", context.run.id),
            )
        self.cancel_seen = context.cancel_event.wait(timeout=1)
        return StageResult(current_items=1, total_items=1)


def test_worker_fences_executor_when_lease_ownership_is_lost(db, control_plane):
    run = enqueue(control_plane)
    executor = LeaseLossWaitingExecutor(db)
    worker = StudioWorker(
        db,
        worker_id="worker-a",
        lease_seconds=45,
        heartbeat_seconds=0.01,
        executors={StageName.PREPARACAO: executor},
        now=lambda: FIXED_NOW,
    )

    worker.run_once()

    assert executor.cancel_seen is True
    assert control_plane.get_run(run.id).run.status is RunStatus.RUNNING
    assert stage_for(control_plane, run.id, StageName.PREPARACAO).status is StageStatus.RUNNING


def test_successful_final_validation_completes_run_and_emits_terminal_events(db, control_plane):
    run = enqueue(control_plane)
    with db.transaction(immediate=True) as conn:
        repo = OperacaoRepository(conn)
        for stage in repo.current_stages(run.id):
            if stage.stage is not StageName.VALIDACAO:
                repo.save_stage(stage.model_copy(update={"status": StageStatus.SUCCEEDED}))

    worker = StudioWorker(
        db,
        worker_id="worker-a",
        lease_seconds=45,
        executors={StageName.VALIDACAO: FakeExecutor(StageResult(gate_status="approved"))},
        now=lambda: FIXED_NOW,
    )

    processed = worker.run_once()

    assert processed is not None
    assert processed.status is RunStatus.COMPLETED
    detail = control_plane.get_run(run.id)
    assert detail.run.status is RunStatus.COMPLETED
    assert detail.run.finished_at == FIXED_NOW
    assert detail.run.lease_owner is None
    assert detail.run.lease_expires_at is None
    assert stage_for(control_plane, run.id, StageName.VALIDACAO).status is StageStatus.SUCCEEDED
    assert [event.kind for event in control_plane.events_after(0, run_id=run.id)][-3:] == [
        "stage.succeeded",
        "run.validating",
        "run.completed",
    ]
