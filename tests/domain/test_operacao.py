import json
from datetime import UTC, datetime, timedelta, timezone
from typing import Any

import pytest
from pydantic import ValidationError

from forge.domain.operacao import (
    ETAPAS,
    Artifact,
    Command,
    CommandStatus,
    CommandType,
    Event,
    Run,
    RunStatus,
    StageName,
    StageRun,
    StageStatus,
    Video,
    WorkItem,
    dependentes_de,
)

UTC_NOW = datetime(2026, 9, 12, 15, 30, tzinfo=UTC)


def build_model(model_type: type[Any], **overrides: Any) -> Any:
    payloads = {
        Video: {
            "id": "v1",
            "tema": "Tema",
            "created_at": UTC_NOW,
            "updated_at": UTC_NOW,
        },
        Run: {
            "id": "r1",
            "video_id": "v1",
            "status": RunStatus.QUEUED,
            "priority": 50,
            "queue_position": 1,
            "config_snapshot": {"render": {"resolution": "1080p"}},
            "workflow_version": 1,
            "git_commit": "abc",
            "lease_expires_at": UTC_NOW,
            "pause_requested_at": UTC_NOW,
            "created_at": UTC_NOW,
            "started_at": UTC_NOW,
            "finished_at": UTC_NOW,
        },
        StageRun: {
            "id": "sr1",
            "run_id": "r1",
            "stage": StageName.ROTEIRO,
            "attempt": 1,
            "status": StageStatus.PENDING,
            "created_at": UTC_NOW,
            "started_at": UTC_NOW,
            "finished_at": UTC_NOW,
        },
        Artifact: {
            "id": "a1",
            "run_id": "r1",
            "stage_run_id": "sr1",
            "kind": "video",
            "relative_path": "video/final.mp4",
            "sha256": "abc",
            "size_bytes": 1,
            "mime_type": "video/mp4",
            "metadata": {"codec": {"name": "h264"}},
            "is_current": True,
            "created_at": UTC_NOW,
        },
        Event: {
            "id": 1,
            "kind": "stage.started",
            "level": "info",
            "message": "Started",
            "payload": {"stage": {"name": "roteiro"}},
            "created_at": UTC_NOW,
        },
        Command: {
            "id": "c1",
            "run_id": "r1",
            "type": CommandType.PAUSE,
            "idempotency_key": "pause-r1",
            "status": CommandStatus.PENDING,
            "result": {"accepted": {"value": True}},
            "created_at": UTC_NOW,
            "applied_at": UTC_NOW,
        },
        WorkItem: {
            "id": "wi1",
            "stage_run_id": "sr1",
            "item_key": "scene-1",
            "status": "pending",
            "input": {"scene": {"index": 1}},
            "input_hash": "abc",
        },
    }
    payload = payloads[model_type] | overrides
    return model_type(**payload)


def test_ordem_canônica_põe_audio_antes_de_imagens():
    assert ETAPAS == (
        StageName.PREPARACAO,
        StageName.PESQUISA,
        StageName.ROTEIRO,
        StageName.PLANO_MIDIA,
        StageName.AUDIO,
        StageName.IMAGENS,
        StageName.MONTAGEM,
        StageName.VALIDACAO,
    )
    assert ETAPAS.index(StageName.AUDIO) < ETAPAS.index(StageName.IMAGENS)


def test_dependentes_de_roteiro_inclui_tudo_apos_roteiro():
    assert dependentes_de(StageName.ROTEIRO) == (
        StageName.ROTEIRO,
        StageName.PLANO_MIDIA,
        StageName.AUDIO,
        StageName.IMAGENS,
        StageName.MONTAGEM,
        StageName.VALIDACAO,
    )


def test_run_recusa_prioridade_fora_de_0_a_100():
    with pytest.raises(ValidationError):
        build_model(Run, priority=101)


def test_enums_serializam_com_valores_estaveis():
    assert RunStatus.PAUSING.value == "pausing"
    assert StageStatus.INVALIDATED.value == "invalidated"
    assert CommandType.RETRY_STAGE.value == "retry_stage"
    assert CommandStatus.PENDING.value == "pending"

    serialized_run = json.loads(build_model(Run).model_dump_json())
    serialized_command = json.loads(build_model(Command).model_dump_json())

    assert serialized_run["status"] == "queued"
    assert serialized_command["type"] == "pause"
    assert serialized_command["status"] == "pending"


@pytest.mark.parametrize(
    ("model_type", "field_name"),
    [
        (Run, "config_snapshot"),
        (WorkItem, "input"),
        (Artifact, "metadata"),
        (Event, "payload"),
        (Command, "result"),
    ],
)
def test_json_fields_accept_nested_json_values(model_type: type[Any], field_name: str):
    value = {"nested": ["text", 1, True, None, {"leaf": 2.5}]}

    model = build_model(model_type, **{field_name: value})

    assert getattr(model, field_name) == value


@pytest.mark.parametrize(
    ("model_type", "field_name"),
    [
        (Run, "config_snapshot"),
        (WorkItem, "input"),
        (Artifact, "metadata"),
        (Event, "payload"),
        (Command, "result"),
    ],
)
def test_json_fields_reject_non_json_serializable_values(
    model_type: type[Any], field_name: str
):
    with pytest.raises(ValidationError):
        build_model(model_type, **{field_name: {"not_json": object()}})


@pytest.mark.parametrize(
    ("model_type", "field_name"),
    [
        (Video, "created_at"),
        (Video, "updated_at"),
        (Run, "created_at"),
        (Run, "lease_expires_at"),
        (Run, "pause_requested_at"),
        (Run, "started_at"),
        (Run, "finished_at"),
        (StageRun, "created_at"),
        (StageRun, "started_at"),
        (StageRun, "finished_at"),
        (Artifact, "created_at"),
        (Event, "created_at"),
        (Command, "created_at"),
        (Command, "applied_at"),
    ],
)
def test_timestamps_accept_utc_datetimes(model_type: type[Any], field_name: str):
    model = build_model(model_type, **{field_name: datetime.now(UTC)})

    assert getattr(model, field_name).tzinfo == UTC


@pytest.mark.parametrize(
    "invalid_timestamp",
    [
        datetime.fromisoformat("2026-09-12T15:30:00"),
        datetime(2026, 9, 12, 15, 30, tzinfo=timezone(-timedelta(hours=3))),
    ],
)
def test_timestamps_reject_naive_and_non_utc_offsets(invalid_timestamp: datetime):
    for model_type, field_name in [
        (Video, "created_at"),
        (Video, "updated_at"),
        (Run, "created_at"),
        (Run, "lease_expires_at"),
        (Run, "pause_requested_at"),
        (Run, "started_at"),
        (Run, "finished_at"),
        (StageRun, "created_at"),
        (StageRun, "started_at"),
        (StageRun, "finished_at"),
        (Artifact, "created_at"),
        (Event, "created_at"),
        (Command, "created_at"),
        (Command, "applied_at"),
    ]:
        with pytest.raises(ValidationError):
            build_model(model_type, **{field_name: invalid_timestamp})


@pytest.mark.parametrize(
    ("current_items", "total_items"),
    [(0, 0), (1, 1)],
)
def test_stage_run_accepts_current_items_up_to_total_items(
    current_items: int, total_items: int
):
    stage_run = build_model(
        StageRun, current_items=current_items, total_items=total_items
    )

    assert (stage_run.current_items, stage_run.total_items) == (
        current_items,
        total_items,
    )


def test_stage_run_rejects_current_items_above_total_items():
    with pytest.raises(ValidationError):
        build_model(StageRun, current_items=2, total_items=1)


@pytest.mark.parametrize(
    ("relative_path", "expected_path"),
    [
        ("video/final.mp4", "video/final.mp4"),
        ("video\\final.mp4", "video/final.mp4"),
    ],
)
def test_artifact_accepts_safe_relative_paths(
    relative_path: str, expected_path: str
):
    artifact = build_model(Artifact, relative_path=relative_path)

    assert artifact.relative_path == expected_path


@pytest.mark.parametrize(
    "relative_path",
    [
        "",
        "../secret.mp4",
        "video/../secret.mp4",
        "/var/output.mp4",
        "C:/output.mp4",
        "C:\\output.mp4",
        "C:output.mp4",
        "\\\\server\\share\\output.mp4",
    ],
)
def test_artifact_rejects_unsafe_relative_paths(relative_path: str):
    with pytest.raises(ValidationError):
        build_model(Artifact, relative_path=relative_path)
