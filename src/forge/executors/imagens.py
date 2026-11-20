"""Executor de imagens: um beat por item, arquivo dentro da run, gate 100%.

O prompt visual de cada beat já vem escrito pelo plano de mídia. O cliente de
imagem é injetável: ComfyUI local ou geração nativa pelo Codex remoto.
"""

from __future__ import annotations

import hashlib
import json
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
from forge.domain.embalagem import Embalagem
from forge.domain.midia import PlanoMidia
from forge.domain.operacao import StageName
from forge.executors.base import StageImplementation
from forge.executors.comfy import ComfyClient
from forge.executors.estilo_visual import COSMOS_INTERIOR
from forge.gpu.liberadores import montar_broker
from forge.infrastructure.config import Settings
from forge.services.codex import CodexUsageLimitError
from forge.infrastructure.logging import get_logger
from forge.services.persistencia import carregar_modelo
from forge.services.thumbnail import ALTURA as THUMB_ALTURA
from forge.services.thumbnail import LARGURA as THUMB_LARGURA
from forge.services.thumbnail import compor_thumbnail
from forge.services.worker import EventSink

logger = get_logger(__name__)

GENERATION_FAILED = "image_generation_failed"
THUMBNAIL_KIND = "thumbnail.jpg"
THUMBNAIL_AUSENTE = "thumbnail_ausente"


class ImageExecutor(StageImplementation):
    def __init__(
        self,
        *,
        client: Any | None = None,
        settings: Settings | None = None,
        broker: Any | None = None,
    ) -> None:
        self.settings = settings or Settings()
        if client is not None:
            self.client = client
        elif self.settings.image_provider == "codex":
            if self.settings.codex_transport == "native":
                from forge.executors.codex_native_images import NativeCodexImageClient
                self.client = NativeCodexImageClient(self.settings)
            else:
                from forge.executors.codex_images import CodexImageClient
                self.client = CodexImageClient(self.settings)
        else:
            self.client = ComfyClient(self.settings)
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
                input_hash=hashlib.sha256(
                    (beat.id + self.client.cache_key(beat.prompt, self.settings.image_seed, COSMOS_INTERIOR, [])).encode("utf-8")
                ).hexdigest(),
            )
            for beat in media.beats
        ]
        # A thumbnail não é item do plano — o gate dos beats é 100% e ela é
        # acabamento —, mas entra no hash da etapa: embalagem refeita com outro
        # texto precisa invalidar o resultado reaproveitado.
        partes = [item.input_hash for item in items]
        proposta = self._thumbnail_proposta(context)
        if proposta is not None:
            partes.append(f"thumbnail|{proposta[0]}|{proposta[1]}|{self.settings.fonte_thumbnail}")
        return StagePlan(
            stage=StageName.IMAGENS,
            input_hash=hashlib.sha256(json.dumps(partes).encode("utf-8")).hexdigest(),
            items=items,
        )

    def _thumbnail_proposta(self, context: RunSnapshot) -> tuple[str, str] | None:
        """(prompt, texto) da embalagem; None em run sem embalagem legível."""
        caminho = context.run_dir / "video" / "embalagem.json"
        if not caminho.is_file():
            return None
        try:
            embalagem = carregar_modelo(caminho, Embalagem)
        except Exception as error:  # noqa: BLE001 - embalagem ruim não derruba imagens
            logger.warning("Embalagem ilegível para a thumbnail", error=str(error))
            return None
        prompt = embalagem.thumbnail.prompt.strip()
        if not prompt:
            return None
        return prompt, embalagem.thumbnail.texto.strip()

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
        quota_failure: FailureDetail | None = None

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
                quota_exhausted = isinstance(error, CodexUsageLimitError)
                emit(
                    kind="item.failed",
                    level="error",
                    message=detail,
                    payload={
                        "item_key": item.item_key,
                        "failure_code": "codex_usage_limit" if quota_exhausted else GENERATION_FAILED,
                        "failure_message": detail,
                        "duration_ms": elapsed,
                    },
                )
                failures.append((item.item_key, detail))
                if quota_exhausted:
                    quota_failure = FailureDetail(
                        code="codex_usage_limit",
                        message=detail,
                        failure_class=FailureClass.CAPACITY,
                        retriable=False,
                        recommended_action=(
                            "Aguardar renovação da cota Codex ou verificar créditos em "
                            "https://chatgpt.com/codex/settings/usage; depois retomar a etapa"
                        ),
                        adapter="imagens",
                        attempt=context.attempt,
                        item_key=item.item_key,
                        services={"failed": [key for key, _ in failures]},
                    )
                    break
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
                    "image_provider": self.settings.image_provider,
                    **(self.client.artifact_metadata(destino) if hasattr(self.client, "artifact_metadata") else {}),
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

        failure = quota_failure or (
            FailureDetail(
                code=GENERATION_FAILED,
                message=f"Beats sem imagem: {', '.join(key for key, _ in failures)}",
                failure_class=FailureClass.ITEM,
                retriable=True,
                recommended_action=(
                    "Verificar Codex CLI e sessão ChatGPT; repetir a etapa"
                    if self.settings.image_provider == "codex"
                    else "Verificar o ComfyUI (VRAM, checkpoint) e repetir a etapa"
                ),
                adapter="imagens",
                attempt=context.attempt,
                item_key=failures[0][0],
                services={"failed": [key for key, _ in failures]},
            )
            if failures
            else None
        )

        beats = len(artifacts)
        if failure is None:
            thumbnail = self._thumbnail(context, seed, emit)
            if thumbnail is not None:
                artifacts.append(thumbnail)

        return StageExecutionResult(
            current_items=beats,
            total_items=len(plan.items),
            artifacts=artifacts,
            failure=failure,
        )

    def _thumbnail(self, context: RunSnapshot, seed: int, emit: EventSink) -> ArtifactOutput | None:
        """Gera a base e compõe a thumbnail; qualquer erro vira aviso.

        Só roda com todos os beats prontos: etapa que vai falhar de qualquer
        jeito não gasta cota com acabamento. A base leva o hash do prompt no
        nome, então repetir a etapa não gera de novo a mesma imagem — só a
        composição, que é local e barata, é refeita.
        """
        proposta = self._thumbnail_proposta(context)
        if proposta is None:
            return None
        prompt, texto = proposta
        video_dir = context.run_dir / "video"
        marca = hashlib.sha256(f"{prompt}|{seed}".encode("utf-8")).hexdigest()[:12]
        base = video_dir / "thumbnail" / f"base-{marca}.png"
        saida = video_dir / "thumbnail.jpg"
        try:
            if not base.is_file():
                base.parent.mkdir(parents=True, exist_ok=True)
                self._generate(context, prompt, seed, base)
            info = compor_thumbnail(base, texto, saida, fonte=self.settings.fonte_thumbnail)
        except Exception as error:  # noqa: BLE001 - thumbnail nunca derruba a etapa
            logger.warning("Thumbnail não gerada", error=str(error) or type(error).__name__)
            emit(
                kind="stage.progress",
                level="warning",
                message="Thumbnail não gerada",
                payload={"error": str(error) or type(error).__name__},
            )
            return None
        output = ArtifactOutput(
            item_key=None,
            kind=THUMBNAIL_KIND,
            relative_path=saida.relative_to(context.run_dir).as_posix(),
            mime_type="image/jpeg",
            metadata={
                "prompt": prompt,
                "texto": texto,
                "com_texto": info.com_texto,
                "bytes": info.bytes,
                "image_provider": self.settings.image_provider,
            },
        )
        emit(
            kind="artifact.created",
            level="info",
            message="Thumbnail criada",
            payload=output.model_dump(mode="json"),
        )
        return output

    def _generate(self, context: RunSnapshot, prompt: str, seed: int, destino: Path) -> Path:
        """Geração sob o slot de GPU — troca de residente acontece por fase."""
        if self.settings.image_provider == "codex":
            return self.client.generate(prompt, seed=seed, dest=destino)
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
        imagens = [a for a in result.artifacts if a.kind != THUMBNAIL_KIND]
        thumbnails = [a for a in result.artifacts if a.kind == THUMBNAIL_KIND]
        obtidos = {artifact.item_key for artifact in imagens}

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

        for artifact in imagens:
            findings.extend(self._inspect(context, artifact))

        metrics = {
            "current_items": len(imagens),
            "total_items": len(plan.items),
            "thumbnail": bool(thumbnails),
        }
        if findings:
            return GateResult(
                approved=False,
                code="images_gate_failed",
                findings=findings,
                metrics=metrics,
            )
        avisos: list[GateFinding] = []
        if not thumbnails and self._thumbnail_proposta(context) is not None:
            # Aviso, não reprovação: o vídeo não depende da thumbnail, e a aba
            # de publicação mostra a ausência.
            avisos.append(
                GateFinding(
                    code=THUMBNAIL_AUSENTE,
                    message="Thumbnail não gerada; repita a etapa ou crie a capa à mão",
                )
            )
        elif thumbnails:
            avisos.extend(self._inspect_thumbnail(context, thumbnails[0]))
        return GateResult(
            approved=True, code="images_approved", findings=avisos, metrics=metrics
        )

    def _inspect_thumbnail(self, context: RunSnapshot, artifact: ArtifactOutput) -> list[GateFinding]:
        caminho = context.run_dir / artifact.relative_path
        try:
            from PIL import Image

            with Image.open(str(caminho)) as imagem:
                tamanho = imagem.size
        except Exception as error:  # noqa: BLE001
            return [GateFinding(code=THUMBNAIL_AUSENTE, message=f"Thumbnail ilegível: {error}")]
        if tamanho != (THUMB_LARGURA, THUMB_ALTURA):
            return [
                GateFinding(
                    code="thumbnail_resolucao",
                    message=f"Thumbnail fora de {THUMB_LARGURA}x{THUMB_ALTURA}: {tamanho}",
                )
            ]
        return []

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
