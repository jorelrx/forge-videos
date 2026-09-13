from __future__ import annotations

from datetime import UTC, datetime, timedelta

from forge.domain.operacao import RunStatus, StageName, StageStatus, StageResult
from forge.infrastructure.config import Settings
from forge.services.studio import build_worker


def _enqueue(worker, *, tema: str):
    return worker.control_plane.enqueue_video(
        tema=tema,
        tese=None,
        priority=50,
        config_snapshot={"environment": "test"},
        workflow_version=1,
        git_commit="test-git",
    )[1]


class SuccessExecutor:
    def __init__(self) -> None:
        self.calls = 0

    def execute(self, context, emit):
        self.calls += 1
        return StageResult(gate_status="approved", current_items=1, total_items=1)


def test_worker_recovery_interrupts_expired_run_and_allows_only_one_followup_claim(
    tmp_path,
):
    settings = Settings(
        _env_file=None,
        studio_db_path=tmp_path / "forge.db",
        worker_lease_seconds=15,
        worker_heartbeat_seconds=5,
    )
    first_worker = build_worker(settings, executors={}, worker_id="worker-dead")
    first = _enqueue(first_worker, tema="Primeira")
    second = _enqueue(first_worker, tema="Segunda")

    claimed_first = first_worker.control_plane.claim_next(
        "worker-dead", lease_seconds=settings.worker_lease_seconds
    )
    assert claimed_first is not None
    with first_worker.db.transaction(immediate=True) as conn:
        conn.execute(
            "UPDATE runs SET lease_expires_at = ? WHERE id = ?",
            ((datetime.now(UTC) - timedelta(seconds=1)).isoformat(), first.id),
        )

    restarted = build_worker(settings, executors={}, worker_id="worker-restarted")
    interrupted = restarted.control_plane.interrupt_expired()

    assert [run.id for run in interrupted] == [first.id]
    assert restarted.control_plane.get_run(first.id).run.status is RunStatus.INTERRUPTED
    assert restarted.control_plane.get_run(second.id).run.status is RunStatus.QUEUED
    interrupted_stage = next(
        stage
        for stage in restarted.control_plane.get_run(first.id).stages
        if stage.stage is StageName.PREPARACAO
    )
    assert interrupted_stage.status is StageStatus.INTERRUPTED

    executor = SuccessExecutor()
    resumed = build_worker(
        settings,
        executors={StageName.PREPARACAO: executor},
        worker_id="worker-restarted",
    )
    resumed.control_plane.request_resume(first.id, idempotency_key="resume-first")
    claimed_after_resume = resumed.run_once()
    competing_claim = build_worker(
        settings, executors={}, worker_id="worker-competing"
    ).run_once()

    assert claimed_after_resume is not None
    assert claimed_after_resume.id == first.id
    assert executor.calls == 1
    resumed_stage = next(
        stage
        for stage in resumed.control_plane.get_run(first.id).stages
        if stage.stage is StageName.PREPARACAO
    )
    assert resumed_stage.status is StageStatus.SUCCEEDED
    future_stage = next(
        stage
        for stage in resumed.control_plane.get_run(first.id).stages
        if stage.stage is StageName.PESQUISA
    )
    assert future_stage.status is StageStatus.PENDING
    assert competing_claim is None
    with restarted.db.connection() as conn:
        claimed_events = conn.execute(
            "SELECT COUNT(*) FROM events WHERE run_id = ? AND kind = ?",
            (first.id, "run.claimed"),
        ).fetchone()[0]
    assert claimed_events == 2
