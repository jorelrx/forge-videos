from __future__ import annotations

from enum import StrEnum
from pathlib import Path
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, model_validator

from forge.domain.fluxo_geracao import FluxoGeracao
from forge.domain.operacao import Artifact, JSON_OBJECT, StageName, WorkItem

Sha256 = Annotated[str, StringConstraints(pattern=r"^[0-9a-f]{64}$")]


class FailureClass(StrEnum):
    TRANSIENT = "transient"
    CAPACITY = "capacity"
    DETERMINISTIC = "deterministic"
    PROCESS = "process"
    USER = "user"
    ITEM = "item"


class StudioPreset(BaseModel):
    model_config = ConfigDict(extra="forbid")

    preset: Literal["local-recomendado-v1"] = "local-recomendado-v1"
    model: str = "google/gemma-4-e4b"
    context_length: int = 16384
    llm_max_tokens: int = 4000
    tts_backend: Literal["vulkan", "cpu"] = "vulkan"
    tts_seed: int = 42
    tts_sampler: Literal["model-defaults"] = "model-defaults"
    visual_style: Literal["cosmos-interior"] = "cosmos-interior"
    image_width: int = 1024
    image_height: int = 576
    image_steps: int = 14
    image_cfg: float = 3.2


class FailureDetail(BaseModel):
    code: str = Field(min_length=1)
    message: str = Field(min_length=1)
    failure_class: FailureClass
    retriable: bool
    recommended_action: str = Field(min_length=1)
    adapter: str
    command: list[str] = Field(default_factory=list)
    attempt: int = Field(ge=1)
    item_key: str | None = None
    stack_trace: str = ""
    services: JSON_OBJECT = Field(default_factory=dict)
    gpu: JSON_OBJECT = Field(default_factory=dict)


class WorkItemPlan(BaseModel):
    item_key: str = Field(min_length=1, max_length=200)
    input: JSON_OBJECT
    input_hash: Sha256


class StagePlan(BaseModel):
    stage: StageName
    input_hash: Sha256
    items: list[WorkItemPlan] = Field(default_factory=list)

    @model_validator(mode="after")
    def unique_item_keys(self):
        keys = [item.item_key for item in self.items]
        if len(keys) != len(set(keys)):
            raise ValueError("item_key must be unique within a stage plan")
        return self


class ArtifactOutput(BaseModel):
    item_key: str | None = None
    kind: str = Field(min_length=1)
    relative_path: str = Field(min_length=1)
    mime_type: str = Field(min_length=1)
    metadata: JSON_OBJECT = Field(default_factory=dict)


class GateFinding(BaseModel):
    code: str = Field(min_length=1)
    message: str = Field(min_length=1)
    item_key: str | None = None
    details: JSON_OBJECT = Field(default_factory=dict)


class GateResult(BaseModel):
    approved: bool
    code: str = Field(min_length=1)
    findings: list[GateFinding] = Field(default_factory=list)
    metrics: JSON_OBJECT = Field(default_factory=dict)

    @model_validator(mode="after")
    def rejected_has_evidence(self):
        if not self.approved and not self.findings:
            raise ValueError("rejected gate requires findings")
        return self


class StageExecutionResult(BaseModel):
    current_items: int = Field(ge=0)
    total_items: int = Field(ge=0)
    artifacts: list[ArtifactOutput] = Field(default_factory=list)
    failure: FailureDetail | None = None

    @property
    def failure_class(self) -> FailureClass | None:
        return self.failure.failure_class if self.failure is not None else None


class StageChildResult(StageExecutionResult):
    gate: GateResult


class ReusableOutput(BaseModel):
    """A parent-verified prior-stage artifact safe for child reuse."""

    artifact: Artifact
    input_hash: Sha256


class RunSnapshot(BaseModel):
    run_id: str
    video_id: str
    tema: str
    tese: str | None
    stage: StageName
    attempt: int = Field(ge=1)
    output_root: Path
    run_dir: Path
    config_snapshot: JSON_OBJECT
    artifacts: list[Artifact]
    work_items: list[WorkItem]
    reusable_outputs: list[ReusableOutput] = Field(default_factory=list)

    @property
    def fluxo_geracao(self) -> FluxoGeracao | None:
        if "fluxo_geracao" in self.config_snapshot:
            return FluxoGeracao.model_validate(self.config_snapshot["fluxo_geracao"])
        return None

    @model_validator(mode="after")
    def run_dir_is_canonical(self):
        expected = (self.output_root / self.run_id).resolve()
        if self.run_dir.resolve() != expected:
            raise ValueError("run_dir must equal output_root/run_id")
        return self


ChildEventKind = Literal[
    "item.planned", "item.started", "item.succeeded", "item.failed",
    "artifact.created", "stage.progress", "stage.result",
]
