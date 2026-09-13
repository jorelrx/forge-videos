"""Image executor: checkpoint per beat, 100% gate, reusable library."""

from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any

from forge.domain.execucao import (
    ArtifactOutput,
    GateFinding,
    GateResult,
    RunSnapshot,
    StageChildResult,
    StageExecutionResult,
    StagePlan,
    WorkItemPlan,
)
from forge.domain.midia import Beat, PlanoMidia
from forge.domain.operacao import StageName
from forge.executors.base import StageImplementation
from forge.executors.estilo_visual import COSMOS_INTERIOR, inspect_lora
from forge.executors.comfy import ComfyClient
from forge.gpu.liberadores import montar_broker
from forge.infrastructure.config import Settings
from forge.services.persistencia import carregar_modelo
from forge.services.worker import EventSink


class ImageExecutor(StageImplementation):
    def __init__(
        self,
        *,
        client: ComfyClient | None = None,
        settings: Settings | None = None,
        broker: Any | None = None,
    ) -> None:
        self.client = client or ComfyClient(settings)
        self.settings = settings or Settings()
        self.broker = broker

    def prepare(self, context: RunSnapshot) -> StagePlan:
        if context.stage is not StageName.IMAGENS:
            raise ValueError("context stage does not match image executor")
        media = carregar_modelo(context.run_dir / "video" / "midia.json", PlanoMidia)
        items = [
            WorkItemPlan(
                item_key=beat.id,
                input={"beat": beat.model_dump(mode="json")},
                input_hash=hashlib.sha256(
                    (beat.id + beat.prompt).encode()
                ).hexdigest(),
            )
            for beat in media.beats
        ]
        return StagePlan(
            stage=StageName.IMAGENS,
            input_hash=hashlib.sha256(str([b.id for b in media.beats]).encode()).hexdigest(),
            items=items,
        )

    def execute(
        self, context: RunSnapshot, plan: StagePlan, emit: EventSink
    ) -> StageExecutionResult:
        output_dir = context.run_dir / "video" / "images"
        output_dir.mkdir(parents=True, exist_ok=True)
        artifacts: list[ArtifactOutput] = []
        for item in plan.items:
            path = self.client.generate(item.input.get("beat", {}).get("prompt", "cosmic interior"), seed=42)
            relative = path.as_posix()
            artifacts.append(
                ArtifactOutput(
                    item_key=item.item_key,
                    kind="image.png",
                    relative_path=relative,
                    mime_type="image/png",
                    metadata={
                        "prompt": item.input.get("beat", {}).get("prompt", ""),
                        "seed": 42,
                        "preset": COSMOS_INTERIOR.name,
                        "source": "generated",
                        "cache_key": self.client.cache_key(
                            item.input.get("beat", {}).get("prompt", ""), 42, COSMOS_INTERIOR, []
                        ),
                    },
                )
            )
            emit(
                kind="artifact.created",
                level="info",
                message="Imagem criada",
                payload={"item_key": item.item_key, "relative_path": relative},
            )
            emit(
                kind="item.succeeded",
                level="info",
                message="Beat concluído",
                payload={"item_key": item.item_key},
            )
        return StageExecutionResult(
            current_items=len(artifacts), total_items=len(plan.items), artifacts=artifacts
        )

    def validate(
        self, context: RunSnapshot, plan: StagePlan, result: StageExecutionResult
    ) -> GateResult:
        findings: list[GateFinding] = []
        expected = {item.item_key for item in plan.items}
        artifacts = {a.item_key: a for a in result.artifacts if a.item_key}
        if artifacts.keys() != expected:
            findings.append(
                GateFinding(
                    code="images_incomplete",
                    message="Nem todos os beats possuem imagem",
                )
            )
        for art in result.artifacts:
            path = context.run_dir / art.relative_path
            try:
                from PIL import Image
                with Image.open(str(path)) as img:
                    if img.size != (self.settings.image_width, self.settings.image_height):
                        findings.append(
                            GateFinding(
                                code="image_resolution",
                                message=f"Resolução incorreta: {img.size}",
                                item_key=art.item_key,
                                details={"expected": (1024, 576), "actual": img.size},
                            )
                        )
            except Exception as exc:
                findings.append(
                    GateFinding(
                        code="image_unreadable",
                        message=f"Imagem não legível: {exc}",
                        item_key=art.item_key,
                    )
                )
        if findings:
            return GateResult(
                approved=False, code="images_incomplete", findings=findings,
                metrics={"current_items": len(result.artifacts), "total_items": len(plan.items)},
            )
        return GateResult(
            approved=True,
            code="images_approved",
            metrics={"current_items": len(result.artifacts), "total_items": len(plan.items)},
        )

    def run(self, context: RunSnapshot, emit: EventSink) -> StageChildResult:
        plan = self.prepare(context)
        for item in plan.items:
            emit(
                kind="item.planned", level="info", message="Beat planejado",
                payload={**item.model_dump(mode="json"), "kind": "image"},
            )
        execution = self.execute(context, plan, emit)
        return StageChildResult(**execution.model_dump(), gate=self.validate(context, plan, execution))


__all__ = ["ImageExecutor"]
