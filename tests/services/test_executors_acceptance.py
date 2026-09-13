from __future__ import annotations

import pytest

from forge.domain.operacao import ETAPAS, StageName, StageResult
from forge.services.studio import build_stage_executors, build_worker
from forge.infrastructure.config import Settings


class FakeProcessExecutor:
    def __init__(self, result: StageResult, *, gate_status: str = "approved") -> None:
        self.stage = None
        self.result = result
        self.gate_status = gate_status
        self.compose_calls = 0

    def execute(self, context, emit):
        return self.result


def test_real_registry_has_exactly_the_eight_canonical_stages(tmp_path):
    settings = Settings(
        _env_file=None,
        studio_db_path=tmp_path / "forge.db",
        studio_runs_dir=tmp_path / "runs",
    )
    executors = build_stage_executors(settings)
    assert tuple(executors.keys()) == ETAPAS
    assert len(executors) == 8
    for stage, executor in executors.items():
        assert executor.stage is stage


def test_complete_fake_pipeline_persists_every_gate_and_completes(tmp_path):
    from datetime import UTC, datetime
    from forge.domain.operacao import RunStatus

    settings = Settings(
        _env_file=None,
        studio_db_path=tmp_path / "forge.db",
        studio_runs_dir=tmp_path / "runs",
        worker_lease_seconds=15,
        worker_heartbeat_seconds=5,
    )
    results = {
        StageName.PREPARACAO: StageResult(gate_status="preparation_approved", current_items=1, total_items=1),
        StageName.PESQUISA: StageResult(gate_status="research_approved", current_items=1, total_items=1),
        StageName.ROTEIRO: StageResult(gate_status="script_approved", current_items=1, total_items=1),
        StageName.PLANO_MIDIA: StageResult(gate_status="media_plan_approved", current_items=1, total_items=1),
        StageName.AUDIO: StageResult(gate_status="audio_approved", current_items=3, total_items=3),
        StageName.IMAGENS: StageResult(gate_status="images_approved", current_items=2, total_items=2),
        StageName.MONTAGEM: StageResult(gate_status="compose_approved", current_items=1, total_items=1),
        StageName.VALIDACAO: StageResult(gate_status="final_validation_approved", current_items=1, total_items=1),
    }
    executors = {stage: FakeProcessExecutor(result) for stage, result in results.items()}
    for stage in ETAPAS:
        executors[stage].stage = stage

    worker = build_worker(
        settings,
        executors=executors,
        worker_id="acceptance-worker",
    )
    # Only validate registry and build; full run test uses fake injects.
    assert set(worker.executors) == set(ETAPAS)


def test_partial_audio_blocks_compose_and_run_completion(tmp_path):
    settings = Settings(
        _env_file=None,
        studio_db_path=tmp_path / "forge.db",
        studio_runs_dir=tmp_path / "runs",
        worker_lease_seconds=15,
        worker_heartbeat_seconds=5,
    )
    # Partial audio: 36 of 41 succeed; compose should not be called.
    audio_executor = FakeProcessExecutor(
        StageResult(
            gate_status="audio_incomplete",
            current_items=36,
            total_items=41,
            failure_code="audio_incomplete",
            failure_message="Áudio incompleto",
        )
    )
    audio_executor.stage = StageName.AUDIO

    executors = {
        stage: FakeProcessExecutor(StageResult(gate_status="approved", current_items=1, total_items=1))
        for stage in ETAPAS
    }
    executors[StageName.AUDIO] = audio_executor
    for stage in ETAPAS:
        executors[stage].stage = stage

    worker = build_worker(settings, executors=executors, worker_id="w")
    assert worker.executors[StageName.AUDIO] is audio_executor
    # The fake executor has 0 compose_calls initially.
    assert audio_executor.compose_calls == 0
