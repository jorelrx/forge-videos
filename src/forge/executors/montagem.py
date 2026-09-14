"""Montagem: Ken Burns por beat, concat do vídeo, mux da narração.

Só usa artefatos catalogados do snapshot — nunca descobre arquivo no disco.
`ffmpeg`/`ffprobe` entram por injeção (`runner`/`prober`) para que a unidade
prove a sequência de comandos sem gastar minutos de encode.
"""

from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any, Callable

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
from forge.domain.midia import Beat, PlanoMidia
from forge.domain.operacao import StageName
from forge.executors.base import StageImplementation
from forge.executors.ffmpeg import (
    LARGURA,
    ALTURA,
    RETRATO_LIMITE,
    MediaProbe,
    clip_from_image,
    concat_videos,
    concat_wavs,
    mux_audio,
    probe_media,
    run_ffmpeg,
)
from forge.infrastructure.config import Settings
from forge.services.persistencia import carregar_modelo
from forge.services.worker import EventSink

COMPOSE_FAILED = "compose_failed"
COMPOSE_INPUTS_INCOMPLETE = "compose_inputs_incomplete"

# Piso de duração por beat: narração muito curta viraria um flash ilegível.
MIN_SEGUNDOS_POR_BEAT = 0.8


class ComposeExecutor(StageImplementation):
    def __init__(
        self,
        *,
        settings: Settings | None = None,
        runner: Callable[..., Any] = run_ffmpeg,
        prober: Callable[[str | Path], MediaProbe] = probe_media,
    ) -> None:
        self.settings = settings or Settings()
        self.runner = runner
        self.prober = prober

    # ------------------------------------------------------------------
    # Plano
    # ------------------------------------------------------------------

    def _index(self, context: RunSnapshot) -> tuple[dict[str, str], dict[str, str]]:
        """Indexa os artefatos correntes pela chave do item.

        `Artifact` não carrega `item_key`; a chave é o stem do caminho, que é a
        convenção dos dois executores produtores (`video/images/<i>.png`,
        `video/audio/<b>.wav`). O índice vem do catálogo, nunca de varredura.
        """
        imagens: dict[str, str] = {}
        audios: dict[str, str] = {}
        for artifact in context.artifacts:
            if not artifact.is_current:
                continue
            chave = Path(artifact.relative_path).stem
            # O produtor de imagens registra `image.png`; `image/...` era a
            # convenção do stub e nunca casava com o catálogo real.
            if artifact.kind.startswith("image"):
                imagens[chave] = artifact.relative_path
            elif artifact.kind == "audio.wav":
                audios[chave] = artifact.relative_path
        return imagens, audios

    def _beats(self, context: RunSnapshot) -> list[Beat]:
        plano = carregar_modelo(context.run_dir / "video" / "midia.json", PlanoMidia)
        return list(plano.beats)

    def prepare(self, context: RunSnapshot) -> StagePlan:
        if context.stage is not StageName.MONTAGEM:
            raise ValueError("context stage must be montagem")

        imagens, audios = self._index(context)
        beats = self._beats(context)

        # Beats que dividem o mesmo bloco dividem a narração dele: sem isso o
        # vídeo teria o dobro da duração do áudio.
        divisor_por_bloco: dict[str, int] = {}
        for beat in beats:
            divisor_por_bloco[beat.bloco_id] = divisor_por_bloco.get(beat.bloco_id, 0) + 1

        items: list[WorkItemPlan] = []
        for beat in beats:
            imagem = imagens.get(beat.id)
            audio = audios.get(beat.bloco_id)
            payload = {
                "beat_id": beat.id,
                "bloco_id": beat.bloco_id,
                "image": imagem,
                "audio": audio,
                "divisor": divisor_por_bloco[beat.bloco_id],
            }
            items.append(
                WorkItemPlan(
                    item_key=beat.id,
                    input=payload,
                    input_hash=hashlib.sha256(
                        f"{imagem}|{audio}|{payload['divisor']}".encode("utf-8")
                    ).hexdigest(),
                )
            )

        return StagePlan(
            stage=StageName.MONTAGEM,
            input_hash=hashlib.sha256(
                "|".join(item.input_hash for item in items).encode("utf-8")
            ).hexdigest(),
            items=items,
        )

    # ------------------------------------------------------------------
    # Execução
    # ------------------------------------------------------------------

    def execute(
        self, context: RunSnapshot, plan: StagePlan, emit: EventSink
    ) -> StageExecutionResult:
        faltando = [
            item.item_key for item in plan.items if not item.input.get("image")
        ]
        if faltando:
            return StageExecutionResult(
                current_items=0,
                total_items=len(plan.items),
                artifacts=[],
                failure=FailureDetail(
                    code=COMPOSE_INPUTS_INCOMPLETE,
                    message=f"Beats sem imagem: {', '.join(faltando)}",
                    failure_class=FailureClass.DETERMINISTIC,
                    retriable=False,
                    recommended_action="Repetir a etapa de imagens antes de montar",
                    adapter="montagem",
                    attempt=context.attempt,
                    item_key=faltando[0],
                    services={"missing_images": faltando},
                ),
            )

        video_dir = context.run_dir / "video"
        clips_dir = video_dir / "clips"
        clips_dir.mkdir(parents=True, exist_ok=True)

        clipes: list[Path] = []
        blocos: list[str] = []
        for indice, item in enumerate(plan.items):
            imagem = context.run_dir / str(item.input["image"])
            audio_rel = item.input.get("audio")
            segundos = self._seconds_for(context, audio_rel, int(item.input["divisor"]))
            clipe = clips_dir / f"{indice:04d}-{item.item_key}.mp4"

            emit(
                kind="stage.progress",
                level="info",
                message="Clipe iniciado",
                payload={"item_key": item.item_key},
            )
            try:
                clip_from_image(
                    imagem,
                    clipe,
                    seconds=segundos,
                    index=indice,
                    portrait=self._is_portrait(imagem),
                    runner=self.runner,
                )
            except Exception as error:  # noqa: BLE001 - reporta sem mascarar causa
                return StageExecutionResult(
                    current_items=len(clipes),
                    total_items=len(plan.items),
                    artifacts=[],
                    failure=FailureDetail(
                        code=COMPOSE_FAILED,
                        message=f"Clipe de {item.item_key} falhou: {error}",
                        failure_class=FailureClass.PROCESS,
                        retriable=True,
                        recommended_action="Verificar FFmpeg e a imagem do beat",
                        adapter="montagem",
                        attempt=context.attempt,
                        item_key=item.item_key,
                    ),
                )
            clipes.append(clipe)
            if audio_rel and str(audio_rel) not in blocos:
                blocos.append(str(audio_rel))
            emit(
                kind="stage.progress",
                level="info",
                message="Clipe concluído",
                payload={"item_key": item.item_key},
            )

        try:
            self._compose(context, clipes, blocos)
        except Exception as error:  # noqa: BLE001
            return StageExecutionResult(
                current_items=len(clipes),
                total_items=len(plan.items),
                artifacts=[],
                failure=FailureDetail(
                    code=COMPOSE_FAILED,
                    message=f"Montagem falhou: {error}",
                    failure_class=FailureClass.PROCESS,
                    retriable=True,
                    recommended_action="Verificar FFmpeg e os insumos da montagem",
                    adapter="montagem",
                    attempt=context.attempt,
                    services={"clips": len(clipes), "blocks": len(blocos)},
                ),
            )

        final = video_dir / "final.mp4"
        output = ArtifactOutput(
            item_key=None,
            kind="video/final.mp4",
            relative_path=final.relative_to(context.run_dir).as_posix(),
            mime_type="video/mp4",
            metadata={
                "codec_video": "h264",
                "codec_audio": "aac",
                "resolution": f"{LARGURA}x{ALTURA}",
                "clips": len(clipes),
            },
        )
        emit(
            kind="artifact.created",
            level="info",
            message="Vídeo final criado",
            payload=output.model_dump(mode="json"),
        )
        return StageExecutionResult(
            current_items=len(clipes),
            total_items=len(plan.items),
            artifacts=[output],
        )

    def _compose(self, context: RunSnapshot, clipes: list[Path], blocos: list[str]) -> None:
        video_dir = context.run_dir / "video"
        mudo = video_dir / "silent.mp4"
        narracao = video_dir / "narration.wav"
        final = video_dir / "final.mp4"

        concat_videos(clipes, mudo, video_dir / ".clips.txt", runner=self.runner)
        concat_wavs(
            [context.run_dir / bloco for bloco in blocos],
            narracao,
            video_dir / ".wavs.txt",
            runner=self.runner,
        )
        mux_audio(mudo, narracao, final, runner=self.runner)

    def _seconds_for(self, context: RunSnapshot, audio_rel: Any, divisor: int) -> float:
        if not audio_rel:
            base = float(
                context.config_snapshot.get(
                    "midia_alvo_segundos", self.settings.midia_alvo_segundos
                )
            )
        else:
            base = self.prober(context.run_dir / str(audio_rel)).duration or 0.0
        return max(MIN_SEGUNDOS_POR_BEAT, round(base / max(1, divisor), 3))

    def _is_portrait(self, imagem: Path) -> bool:
        probe = self.prober(imagem)
        if not probe.width or not probe.height:
            return False
        return (probe.width / probe.height) < RETRATO_LIMITE

    # ------------------------------------------------------------------
    # Gate
    # ------------------------------------------------------------------

    def validate(
        self, context: RunSnapshot, plan: StagePlan, result: StageExecutionResult
    ) -> GateResult:
        findings: list[GateFinding] = []
        metrics = {"current_items": result.current_items, "total_items": len(plan.items)}

        finais = [a for a in result.artifacts if a.kind == "video/final.mp4"]
        if not finais:
            findings.append(
                GateFinding(
                    code="compose_output_missing",
                    message="Artefato de vídeo final não emitido",
                )
            )
            return GateResult(
                approved=False,
                code="compose_gate_failed",
                findings=findings,
                metrics=metrics,
            )

        caminho = context.run_dir / finais[0].relative_path
        if not caminho.is_file():
            findings.append(
                GateFinding(
                    code="video_output_missing",
                    message=f"Arquivo final do vídeo não encontrado: {finais[0].relative_path}",
                )
            )
            return GateResult(
                approved=False,
                code="compose_gate_failed",
                findings=findings,
                metrics=metrics,
            )

        probe = self.prober(caminho)
        if probe.codec != "h264":
            findings.append(
                GateFinding(
                    code="video_codec_invalid",
                    message=f"Codec de vídeo não é h264: {probe.codec}",
                    details={"codec": probe.codec},
                )
            )
        if probe.audio_codec != "aac":
            findings.append(
                GateFinding(
                    code="audio_codec_invalid",
                    message=f"Codec de áudio não é aac: {probe.audio_codec}",
                    details={"audio_codec": probe.audio_codec},
                )
            )
        if (probe.width, probe.height) != (LARGURA, ALTURA):
            findings.append(
                GateFinding(
                    code="video_resolution_invalid",
                    message=f"Resolução não é {LARGURA}x{ALTURA}: {probe.width}x{probe.height}",
                    details={"width": probe.width, "height": probe.height},
                )
            )
        if not probe.duration or probe.duration <= 0:
            findings.append(
                GateFinding(
                    code="video_duration_invalid",
                    message="Duração do vídeo não é positiva",
                    details={"duration": probe.duration},
                )
            )

        if result.current_items != len(plan.items):
            findings.append(
                GateFinding(
                    code="compose_items_incomplete",
                    message=f"Clipe por beat incompleto: {result.current_items}/{len(plan.items)}",
                    details={
                        "current_items": result.current_items,
                        "total_items": len(plan.items),
                    },
                )
            )

        if findings:
            return GateResult(
                approved=False,
                code="compose_gate_failed",
                findings=findings,
                metrics=metrics,
            )
        return GateResult(
            approved=True, code="compose_approved", findings=[], metrics=metrics
        )

    def run(self, context: RunSnapshot, emit: EventSink) -> StageChildResult:
        plan = self.prepare(context)
        execution = self.execute(context, plan, emit)
        gate = self.validate(context, plan, execution)
        return StageChildResult(**execution.model_dump(), gate=gate)


__all__ = ["ComposeExecutor"]
