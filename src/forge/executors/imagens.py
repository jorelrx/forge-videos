"""Executor de imagens: um beat por item, arquivo dentro da run, gate 100%.

O prompt visual de cada beat já vem escrito pelo plano de mídia; aqui não há
LLM. O cliente ComfyUI entra por injeção para que a unidade rode sem GPU.
"""

from __future__ import annotations

import hashlib
from pathlib import Path
from time import monotonic
from typing import Any

from forge.domain.execucao import (
    ArtifactOutput,
    FailureClass,
    FailureDetail,
    GateFinding,
    GateResult,
    RunSnapshot,
    StageChildResult,
    StageExecutionResult,
    StagePlan,
    WorkItemPlan,
)
from forge.domain.midia import PlanoMidia
from forge.domain.operacao import StageName
from forge.executors.base import StageImplementation
from forge.executors.comfy import ComfyClient
from forge.executors.estilo_visual import COSMOS_INTERIOR
from forge.gpu.liberadores import montar_broker
from forge.infrastructure.config import Settings
from forge.services.persistencia import carregar_modelo
from forge.services.worker import EventSink

GENERATION_FAILED = "image_generation_failed"


class ImageExecutor(StageImplementation):
    def __init__(
        self,
        *,
        client: Any | None = None,
        settings: Settings | None = None,
        broker: Any | None = None,
    ) -> None:
        self.settings = settings or Settings()
        self.client = client or ComfyClient(self.settings)
        self.broker = broker

    # ------------------------------------------------------------------
    # Plano
    # ------------------------------------------------------------------

    def prepare(self, context: RunSnapshot) -> StagePlan:
        if context.stage is not StageName.IMAGENS:
            raise ValueError("context stage does not match image executor")
        media = carregar_modelo(context.run_dir / "video" / "midia.json", PlanoMidia)
        items = [
            WorkItemPlan(
                item_key=beat.id,
                input={"beat": beat.model_dump(mode="json")},
                input_hash=hashlib.sha256((beat.id + beat.prompt).encode("utf-8")).hexdigest(),
            )
            for beat in media.beats
        ]
        return StagePlan(
            stage=StageName.IMAGENS,
            input_hash=hashlib.sha256(
                str([beat.id for beat in media.beats]).encode("utf-8")
            ).hexdigest(),
            items=items,
        )

    # ------------------------------------------------------------------
    # Execução
    # ------------------------------------------------------------------

    def execute(
        self, context: RunSnapshot, plan: StagePlan, emit: EventSink
    ) -> StageExecutionResult:
        output_dir = context.run_dir / "video" / "images"
        output_dir.mkdir(parents=True, exist_ok=True)
        seed = int(
            context.config_snapshot.get("image_seed", self.settings.image_seed)
            or self.settings.image_seed
        )

        artifacts: list[ArtifactOutput] = []
        failures: list[tuple[str, str]] = []

        for item in plan.items:
            prompt = str((item.input.get("beat") or {}).get("prompt") or "")
            emit(
                kind="item.started",
                level="info",
                message="Imagem iniciada",
                payload={"item_key": item.item_key, "duration_ms": 0},
            )
            started = monotonic()
            destino = output_dir / f"{item.item_key}.png"
            try:
                generated = self._generate(context, prompt, seed, destino)
            except Exception as error:  # noqa: BLE001 - o item falho não derruba o lote
                elapsed = round((monotonic() - started) * 1000)
                detail = str(error) or type(error).__name__
                emit(
                    kind="item.failed",
                    level="error",
                    message=detail,
                    payload={
                        "item_key": item.item_key,
                        "failure_code": GENERATION_FAILED,
                        "failure_message": detail,
                        "duration_ms": elapsed,
                    },
                )
                failures.append((item.item_key, detail))
                continue

            elapsed = round((monotonic() - started) * 1000)
            relative = Path(generated).resolve().relative_to(
                context.run_dir.resolve()
            ).as_posix()
            output = ArtifactOutput(
                item_key=item.item_key,
                kind="image.png",
                relative_path=relative,
                mime_type="image/png",
                metadata={
                    "prompt": prompt,
                    "seed": seed,
                    "preset": COSMOS_INTERIOR.name,
                    "source": "generated",
                    "cache_key": self.client.cache_key(
                        prompt, seed, COSMOS_INTERIOR, []
                    ),
                },
            )
            emit(
                kind="artifact.created",
                level="info",
                message="Imagem criada",
                payload=output.model_dump(mode="json"),
            )
            emit(
                kind="item.succeeded",
                level="info",
                message="Beat concluído",
                payload={"item_key": item.item_key, "duration_ms": elapsed},
            )
            artifacts.append(output)

        failure = (
            FailureDetail(
                code=GENERATION_FAILED,
                message=f"Beats sem imagem: {', '.join(key for key, _ in failures)}",
                failure_class=FailureClass.ITEM,
                retriable=True,
                recommended_action=(
                    "Verificar o ComfyUI (VRAM, checkpoint) e repetir a etapa"
                ),
                adapter="imagens",
                attempt=context.attempt,
                item_key=failures[0][0],
                services={"failed": [key for key, _ in failures]},
            )
            if failures
            else None
        )

        return StageExecutionResult(
            current_items=len(artifacts),
            total_items=len(plan.items),
            artifacts=artifacts,
            failure=failure,
        )

    def _generate(self, context: RunSnapshot, prompt: str, seed: int, destino: Path) -> Path:
        """Geração sob o slot de GPU — troca de residente acontece por fase."""
        with self._broker().exclusivo("imagem"):
            return self.client.generate(prompt, seed=seed, dest=destino)

    def _broker(self) -> Any:
        if self.broker is None:
            self.broker = montar_broker(self.settings)
        return self.broker

    # ------------------------------------------------------------------
    # Gate
    # ------------------------------------------------------------------

    def validate(
        self, context: RunSnapshot, plan: StagePlan, result: StageExecutionResult
    ) -> GateResult:
        findings: list[GateFinding] = []
        esperados = {item.item_key for item in plan.items}
        obtidos = {artifact.item_key for artifact in result.artifacts}

        for faltando in sorted(esperados - obtidos):
            findings.append(
                GateFinding(
                    code="images_incomplete",
                    message=f"Beat sem imagem: {faltando}",
                    item_key=faltando,
                )
            )
        for extra in sorted(obtidos - esperados):
            findings.append(
                GateFinding(
                    code="images_unexpected",
                    message=f"Imagem sem beat correspondente: {extra}",
                    item_key=extra,
                )
            )

        for artifact in result.artifacts:
            findings.extend(self._inspect(context, artifact))

        metrics = {
            "current_items": len(result.artifacts),
            "total_items": len(plan.items),
        }
        if findings:
            return GateResult(
                approved=False,
                code="images_gate_failed",
                findings=findings,
                metrics=metrics,
            )
        return GateResult(
            approved=True, code="images_approved", findings=[], metrics=metrics
        )

    def _inspect(self, context: RunSnapshot, artifact: ArtifactOutput) -> list[GateFinding]:
        caminho = context.run_dir / artifact.relative_path
        if not caminho.is_file():
            return [
                GateFinding(
                    code="image_unreadable",
                    message=f"Imagem ausente no disco: {artifact.relative_path}",
                    item_key=artifact.item_key,
                )
            ]
        try:
            from PIL import Image

            with Image.open(str(caminho)) as imagem:
                tamanho = imagem.size
        except Exception as error:  # noqa: BLE001 - arquivo ilegível é finding
            return [
                GateFinding(
                    code="image_unreadable",
                    message=f"Imagem não legível: {error}",
                    item_key=artifact.item_key,
                )
            ]

        esperado = (self.settings.image_width, self.settings.image_height)
        if tamanho != esperado:
            return [
                GateFinding(
                    code="image_resolution",
                    message=f"Resolução incorreta: {tamanho}",
                    item_key=artifact.item_key,
                    details={"expected": list(esperado), "actual": list(tamanho)},
                )
            ]
        return []

    def run(self, context: RunSnapshot, emit: EventSink) -> StageChildResult:
        plan = self.prepare(context)
        for item in plan.items:
            emit(
                kind="item.planned",
                level="info",
                message="Beat planejado",
                # `stage` e `kind` são o contrato do projetor de eventos: um
                # `kind` divergente é recusado como protocolo inválido.
                payload={**item.model_dump(mode="json"), "kind": "imagem", "stage": "imagens"},
            )
        execution = self.execute(context, plan, emit)
        gate = self.validate(context, plan, execution)
        return StageChildResult(**execution.model_dump(), gate=gate)


__all__ = ["ImageExecutor"]
