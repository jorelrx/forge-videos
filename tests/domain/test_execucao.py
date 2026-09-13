from pathlib import Path

import pytest
from pydantic import ValidationError

from forge.domain.execucao import (
    FailureClass, GateResult, RunSnapshot, StagePlan, StudioPreset, WorkItemPlan,
)
from forge.domain.operacao import StageName


def test_stage_plan_requires_stable_unique_item_keys():
    with pytest.raises(ValidationError, match="item_key"):
        StagePlan(
            stage=StageName.AUDIO,
            input_hash="a" * 64,
            items=[
                WorkItemPlan(item_key="b001", input={"texto": "A"}, input_hash="b" * 64),
                WorkItemPlan(item_key="b001", input={"texto": "B"}, input_hash="c" * 64),
            ],
        )


def test_gate_rejected_requires_findings():
    with pytest.raises(ValidationError, match="findings"):
        GateResult(approved=False, code="audio_incomplete")


def test_run_snapshot_rejects_run_dir_outside_output_root(tmp_path):
    with pytest.raises(ValidationError, match="run_dir"):
        RunSnapshot(
            run_id="r1", video_id="v1", tema="Tema", tese=None,
            stage=StageName.PREPARACAO, attempt=1,
            output_root=tmp_path / "runs", run_dir=Path("C:/escape"),
            config_snapshot={}, artifacts=[], work_items=[],
        )


def test_failure_classes_are_stable_strings():
    assert FailureClass.TRANSIENT.value == "transient"
    assert FailureClass.CAPACITY.value == "capacity"
    assert FailureClass.DETERMINISTIC.value == "deterministic"
    assert FailureClass.PROCESS.value == "process"
    assert FailureClass.USER.value == "user"
    assert FailureClass.ITEM.value == "item"


def test_recommended_preset_matches_approved_snapshot_and_rejects_secrets():
    preset = StudioPreset()
    assert preset.model_dump() == {
        "preset": "local-recomendado-v1", "model": "google/gemma-4-e4b",
        "context_length": 16384, "llm_max_tokens": 4000,
        "tts_backend": "vulkan", "tts_seed": 42,
        "tts_sampler": "model-defaults", "visual_style": "cosmos-interior",
        "image_width": 1024, "image_height": 576,
        "image_steps": 14, "image_cfg": 3.2,
    }
    with pytest.raises(ValidationError, match="api_key"):
        StudioPreset(api_key="secret")
