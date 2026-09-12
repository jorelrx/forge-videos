from __future__ import annotations

import re
from datetime import datetime, timedelta
from enum import StrEnum
from typing import Annotated, Self

from pydantic import (
    AfterValidator,
    AwareDatetime,
    BaseModel,
    Field,
    JsonValue,
    field_validator,
    model_validator,
)


class RunStatus(StrEnum):
    QUEUED = "queued"
    PREPARING = "preparing"
    RUNNING = "running"
    PAUSING = "pausing"
    PAUSED = "paused"
    VALIDATING = "validating"
    COMPLETED = "completed"
    FAILED = "failed"
    INTERRUPTED = "interrupted"
    CANCELLED = "cancelled"


class StageName(StrEnum):
    PREPARACAO = "preparacao"
    PESQUISA = "pesquisa"
    ROTEIRO = "roteiro"
    PLANO_MIDIA = "plano_midia"
    AUDIO = "audio"
    IMAGENS = "imagens"
    MONTAGEM = "montagem"
    VALIDACAO = "validacao"


class StageStatus(StrEnum):
    PENDING = "pending"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    PAUSING = "pausing"
    PAUSED = "paused"
    INTERRUPTED = "interrupted"
    INVALIDATED = "invalidated"


class ItemStatus(StrEnum):
    PENDING = "pending"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    INVALIDATED = "invalidated"


class CommandType(StrEnum):
    PAUSE = "pause"
    RESUME = "resume"
    RETRY_STAGE = "retry_stage"


class CommandStatus(StrEnum):
    PENDING = "pending"
    ACCEPTED = "accepted"
    APPLIED = "applied"
    REJECTED = "rejected"


ETAPAS = tuple(StageName)
JSON_OBJECT = dict[str, JsonValue]
WINDOWS_DRIVE_PREFIX = re.compile(r"^[A-Za-z]:")


def _require_utc(value: datetime) -> datetime:
    if value.utcoffset() != timedelta(0):
        raise ValueError("timestamp must use UTC")
    return value


UtcDatetime = Annotated[AwareDatetime, AfterValidator(_require_utc)]


def dependentes_de(stage: StageName) -> tuple[StageName, ...]:
    return ETAPAS[ETAPAS.index(stage) :]


class Video(BaseModel):
    id: str
    tema: str = Field(min_length=1, max_length=500)
    tese: str | None = Field(default=None, max_length=2000)
    created_at: UtcDatetime
    updated_at: UtcDatetime


class Run(BaseModel):
    id: str
    video_id: str
    status: RunStatus
    priority: int = Field(ge=0, le=100)
    queue_position: int = Field(ge=1)
    config_snapshot: JSON_OBJECT
    workflow_version: int = Field(ge=1)
    git_commit: str
    lease_owner: str | None = None
    lease_expires_at: UtcDatetime | None = None
    pause_requested_at: UtcDatetime | None = None
    created_at: UtcDatetime
    started_at: UtcDatetime | None = None
    finished_at: UtcDatetime | None = None
    failure_code: str | None = None
    failure_message: str | None = None


class StageRun(BaseModel):
    id: str
    run_id: str
    stage: StageName
    attempt: int = Field(ge=1)
    status: StageStatus
    current_items: int = Field(default=0, ge=0)
    total_items: int = Field(default=0, ge=0)
    progress: float = Field(default=0, ge=0, le=1)
    gate_status: str | None = None
    input_hash: str | None = None
    created_at: UtcDatetime
    started_at: UtcDatetime | None = None
    finished_at: UtcDatetime | None = None
    failure_code: str | None = None
    failure_message: str | None = None

    @model_validator(mode="after")
    def current_items_do_not_exceed_total_items(self) -> Self:
        if self.current_items > self.total_items:
            raise ValueError("current_items cannot exceed total_items")
        return self


class WorkItem(BaseModel):
    id: str
    stage_run_id: str
    item_key: str
    status: ItemStatus
    input: JSON_OBJECT
    input_hash: str
    attempts: int = Field(default=0, ge=0)
    duration_ms: int | None = Field(default=None, ge=0)
    failure_code: str | None = None
    failure_message: str | None = None


class Artifact(BaseModel):
    id: str
    run_id: str
    stage_run_id: str
    work_item_id: str | None = None
    kind: str
    relative_path: str
    sha256: str
    size_bytes: int = Field(ge=0)
    mime_type: str
    metadata: JSON_OBJECT
    is_current: bool
    created_at: UtcDatetime

    @field_validator("relative_path")
    @classmethod
    def relative_path_stays_within_run_output(cls, value: str) -> str:
        normalized = value.replace("\\", "/")
        if (
            not normalized
            or normalized.startswith("/")
            or WINDOWS_DRIVE_PREFIX.match(normalized)
            or ".." in normalized.split("/")
        ):
            raise ValueError("relative_path must stay within the run output")
        return normalized


class Event(BaseModel):
    id: int
    run_id: str | None = None
    stage_run_id: str | None = None
    work_item_id: str | None = None
    kind: str
    level: str
    message: str
    payload: JSON_OBJECT
    created_at: UtcDatetime


class Command(BaseModel):
    id: str
    run_id: str
    type: CommandType
    stage: StageName | None = None
    idempotency_key: str
    status: CommandStatus
    result: JSON_OBJECT
    created_at: UtcDatetime
    applied_at: UtcDatetime | None = None
