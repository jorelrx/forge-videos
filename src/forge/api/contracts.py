from __future__ import annotations
from enum import StrEnum
from pydantic import BaseModel, Field
from typing import Literal
from typing import Any as JSON_OBJECT

from forge.domain.operacao import (
    RunStatus,
    StageName,
    StageStatus,
    CommandType,
    CommandStatus,
    Video,
    Run,
    StageRun,
    Event,
    Command,
    Artifact,
    WorkItem,
    UtcDatetime,
)

class CreateVideoRequest(BaseModel):
    tema: str = Field(min_length=1, max_length=500)
    tese: str | None = Field(default=None, max_length=2000)
    priority: int = Field(default=50, ge=0, le=100)
    preset: Literal["local-recomendado-v1"] = "local-recomendado-v1"

class CreateVideoResponse(BaseModel):
    video: Video
    run: Run


class RunSummary(BaseModel):
    run: Run
    video: Video
    progress: float = Field(ge=0, le=1)
    current_stage: StageName | None


class StageView(BaseModel):
    stage_run: StageRun
    items: list[WorkItem]
    metrics: JSON_OBJECT = Field(default_factory=dict)


class RunView(RunSummary):
    stages: dict[StageName, StageView]
    artifacts: list[Artifact]

class RunPage(BaseModel):
    items: list[RunSummary]
    total: int
    limit: int
    offset: int

class CommandResponse(BaseModel):
    id: str
    run_id: str
    type: CommandType
    stage: StageName | None
    idempotency_key: str
    status: CommandStatus
    result: JSON_OBJECT
    created_at: UtcDatetime
    applied_at: UtcDatetime | None

class EventPage(BaseModel):
    items: list[Event]
    next_before_id: int | None = None

class ServiceHealth(BaseModel):
    name: str
    state: str
    message: str

class EffectiveConfig(BaseModel):
    api: dict
    worker: dict
    services: dict

class ArtifactListItem(BaseModel):
    id: str
    run_id: str
    stage_run_id: str
    work_item_id: str | None
    kind: str
    relative_path: str
    sha256: str
    size_bytes: int
    mime_type: str
    metadata: JSON_OBJECT
    is_current: bool
    created_at: UtcDatetime

class ArtifactPreview(BaseModel):
    id: str
    run_id: str
    kind: str
    relative_path: str
    mime_type: str
    size_bytes: int
    sha256: str
