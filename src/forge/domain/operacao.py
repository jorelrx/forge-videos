from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, Field


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


def dependentes_de(stage: StageName) -> tuple[StageName, ...]:
    return ETAPAS[ETAPAS.index(stage):]


class Video(BaseModel):
    id: str
    tema: str = Field(min_length=1, max_length=500)
    tese: str | None = Field(default=None, max_length=2000)
    created_at: datetime
    updated_at: datetime


class Run(BaseModel):
    id: str
    video_id: str
    status: RunStatus
    priority: int = Field(ge=0, le=100)
    queue_position: int = Field(ge=1)
    config_snapshot: dict[str, Any]
    workflow_version: int = Field(ge=1)
    git_commit: str
    lease_owner: str | None = None
    lease_expires_at: datetime | None = None
    pause_requested_at: datetime | None = None
    created_at: datetime
    started_at: datetime | None = None
    finished_at: datetime | None = None
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
    created_at: datetime
    started_at: datetime | None = None
    finished_at: datetime | None = None
    failure_code: str | None = None
    failure_message: str | None = None


class WorkItem(BaseModel):
    id: str
    stage_run_id: str
    item_key: str
    status: ItemStatus
    input: dict[str, Any]
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
    metadata: dict[str, Any]
    is_current: bool
    created_at: datetime


class Event(BaseModel):
    id: int
    run_id: str | None = None
    stage_run_id: str | None = None
    work_item_id: str | None = None
    kind: str
    level: str
    message: str
    payload: dict[str, Any]
    created_at: datetime


class Command(BaseModel):
    id: str
    run_id: str
    type: CommandType
    stage: StageName | None = None
    idempotency_key: str
    status: CommandStatus
    result: dict[str, Any]
    created_at: datetime
    applied_at: datetime | None = None
