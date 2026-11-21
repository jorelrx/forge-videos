"""Preparation stage: freeze run input before any expensive work."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

from pydantic import BaseModel, ConfigDict, ValidationError

from forge.domain.execucao import (
    ArtifactOutput,
    GateFinding,
    GateResult,
    RunSnapshot,
    StageChildResult,
    StageExecutionResult,
    StagePlan,
    StudioPreset,
)
from forge.domain.fluxo_geracao import FluxoGeracao
from forge.domain.operacao import StageName
from forge.executors.base import StageImplementation
from forge.services.persistencia import carregar_modelo, gravar_modelo
from forge.services.worker import EventSink


class PreparationInput(BaseModel):
    """Canonical input persisted for the rest of a Studio run."""

    model_config = ConfigDict(extra="forbid")

    run_id: str
    video_id: str
    tema: str
    tese: str | None
    workflow_version: int
    preset: StudioPreset
    fluxo_geracao: FluxoGeracao | None = None


class PreparationExecutor(StageImplementation):
    def _snapshot_input(self, context: RunSnapshot) -> PreparationInput:
        raw = dict(context.config_snapshot)
        # The workflow version belongs to the run envelope, not the preset.
        # Older snapshots do not carry it, so they use the first version.
        workflow_version = raw.pop("workflow_version", 1)
        raw.pop("fluxo_geracao", None)
        return PreparationInput(
            run_id=context.run_id,
            video_id=context.video_id,
            tema=context.tema,
            tese=context.tese,
            workflow_version=workflow_version,
            preset=StudioPreset.model_validate(raw),
            fluxo_geracao=context.fluxo_geracao,
        )

    @staticmethod
    def _hash_input(value: PreparationInput) -> str:
        canonical = json.dumps(
            value.model_dump(
                mode="json",
                exclude={"fluxo_geracao"} if value.fluxo_geracao is None else None,
            ),
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
        return hashlib.sha256(canonical).hexdigest()

    def prepare(self, context: RunSnapshot) -> StagePlan:
        if context.stage is not StageName.PREPARACAO:
            raise ValueError("context stage does not match preparation executor")
        snapshot = self._snapshot_input(context)
        return StagePlan(
            stage=StageName.PREPARACAO,
            input_hash=self._hash_input(snapshot),
            items=[],
        )

    def execute(
        self, context: RunSnapshot, plan: StagePlan, emit: EventSink
    ) -> StageExecutionResult:
        snapshot = self._snapshot_input(context)
        destination = context.run_dir.resolve() / "video" / "input.json"
        destination.parent.mkdir(parents=True, exist_ok=True)
        gravar_modelo(destination, snapshot)
        output = ArtifactOutput(
            item_key="",
            kind="input",
            relative_path="video/input.json",
            mime_type="application/json",
            metadata={},
        )
        emit(
            kind="artifact.created",
            level="info",
            message="Artefato criado",
            payload=output.model_dump(mode="json"),
        )
        return StageExecutionResult(
            current_items=0,
            total_items=0,
            artifacts=[output],
        )

    def validate(
        self,
        context: RunSnapshot,
        plan: StagePlan,
        result: StageExecutionResult,
    ) -> GateResult:
        try:
            expected = self._snapshot_input(context)
            persisted = carregar_modelo(
                context.run_dir.resolve() / "video" / "input.json",
                PreparationInput,
            )
            if persisted != expected:
                raise ValueError("snapshot persistido não corresponde à entrada")
        except (OSError, ValidationError, ValueError, TypeError) as error:
            return GateResult(
                approved=False,
                code="preparation_snapshot_invalid",
                findings=[
                    GateFinding(
                        code="preparation_snapshot_invalid",
                        message="Snapshot da preparação inválido",
                        details={"error": str(error)},
                    )
                ],
            )
        if result.failure is not None:
            return GateResult(
                approved=False,
                code=result.failure.code,
                findings=[
                    GateFinding(
                        code=result.failure.code,
                        message=result.failure.message,
                    )
                ],
            )
        return GateResult(
            approved=True,
            code="preparation_ready",
            metrics={"artifacts": len(result.artifacts)},
        )

    def run(self, context: RunSnapshot, emit: EventSink) -> StageChildResult:
        # Base.run validates only after execute. Preparation must fail closed
        # before creating its canonical directory or writing input.json.
        try:
            self._snapshot_input(context)
        except (ValidationError, ValueError, TypeError) as error:
            execution = StageExecutionResult(current_items=0, total_items=0)
            gate = GateResult(
                approved=False,
                code="preparation_snapshot_invalid",
                findings=[
                    GateFinding(
                        code="preparation_snapshot_invalid",
                        message="Snapshot da preparação inválido",
                        details={"error": str(error)},
                    )
                ],
            )
            return StageChildResult(**execution.model_dump(), gate=gate)
        return super().run(context, emit)


__all__ = ["PreparationExecutor", "PreparationInput"]
