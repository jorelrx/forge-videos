"""Montagem: Ken Burns por beat, crossfade, trilha, cartões, legenda e mux.

Só usa artefatos catalogados do snapshot — nunca descobre arquivo no disco. A
exceção é a pasta de trilhas, que é biblioteca do usuário e não produto da run.

O acabamento (trilha, cartões de fonte, capítulos reais) nunca derruba a etapa:
cada um falha para um aviso e o vídeo sai sem ele. A legenda é diferente — sai
do mesmo texto e dos mesmos tempos do vídeo, então legenda errada indica
montagem errada e reprova.
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
from forge.agents.embalagem import aplicar_tempos_reais, gravar_embalagem
from forge.domain.embalagem import Embalagem
from forge.domain.editorial import AberturaAprovada
from forge.domain.midia import BlocoNarracao, PlanoMidia
from forge.domain.operacao import StageName
from forge.executors.base import StageImplementation
from forge.executors.ffmpeg import (
    LARGURA,
    ALTURA,
    FADE_PADRAO,
    RETRATO_LIMITE,
    MediaProbe,
    clip_from_image,
    concat_wavs,
    crossfade_videos,
    mix_audio,
    mux_audio,
    probe_media,
    run_ffmpeg,
)
from forge.infrastructure.config import Settings
from forge.infrastructure.logging import get_logger
from forge.services.artefatos import ler_eixo
from forge.services.cartoes import gerar_ass, planejar_cartoes
from forge.services.citacoes import ARQUIVO as CITACOES_ARQUIVO
from forge.services.citacoes import carregar_citacoes
from forge.services.legendas import conferir_deixas, formatar_srt, gerar_deixas
from forge.services.linha_tempo import TrechoTempo, linha_do_tempo
from forge.services.persistencia import carregar_modelo, gravar_modelo
from forge.services.trilha import Trilha, escolher_trilha
from forge.services.worker import EventSink

logger = get_logger(__name__)

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

    def _plano(self, context: RunSnapshot) -> PlanoMidia:
        return carregar_modelo(context.run_dir / "video" / "midia.json", PlanoMidia)

    def prepare(self, context: RunSnapshot) -> StagePlan:
        if context.stage is not StageName.MONTAGEM:
            raise ValueError("context stage must be montagem")

        imagens, audios = self._index(context)
        plano = self._plano(context)
        beats = plano.beats
        por_secao: dict[str, list[str]] = {}
        for block in plano.blocos:
            por_secao.setdefault(block.secao, []).append(block.id)
        atribuicoes: dict[str, tuple[list[str], int]] = {}
        for secao, ids in por_secao.items():
            beats_secao = [beat for beat in beats if beat.bloco_id in ids]
            indices = {block_id: index for index, block_id in enumerate(ids)}
            beats_secao.sort(key=lambda beat: indices[beat.bloco_id])
            anchors = sorted({indices[beat.bloco_id] for beat in beats_secao})
            for beat in beats_secao:
                inicio = indices[beat.bloco_id]
                fim = next((index for index in anchors if index > inicio), len(ids))
                span = ids[inicio:fim] or [beat.bloco_id]
                repetidos = sum(other.bloco_id == beat.bloco_id for other in beats_secao)
                atribuicoes[beat.id] = (span, repetidos)

        items: list[WorkItemPlan] = []
        for beat in beats:
            imagem = imagens.get(beat.id)
            block_ids, divisor = atribuicoes.get(beat.id, ([beat.bloco_id], 1))
            audio_paths = [audios[block_id] for block_id in block_ids if block_id in audios]
            audio = audio_paths[0] if audio_paths else None
            payload = {
                "beat_id": beat.id,
                "bloco_id": beat.bloco_id,
                "image": imagem,
                "audio": audio,
                "audios": audio_paths,
                "divisor": divisor,
            }
            items.append(
                WorkItemPlan(
                    item_key=beat.id,
                    input=payload,
                    input_hash=hashlib.sha256(
                        f"{imagem}|{'|'.join(audio_paths)}|{payload['divisor']}".encode("utf-8")
                    ).hexdigest(),
                )
            )

        return StagePlan(
            stage=StageName.MONTAGEM,
            input_hash=hashlib.sha256(
                "|".join(
                    [item.input_hash for item in items] + self._acabamento_hash(context)
                ).encode("utf-8")
            ).hexdigest(),
            items=items,
        )

    def _crossfade(self, context: RunSnapshot) -> float:
        return float(
            context.config_snapshot.get(
                "crossfade_segundos", self.settings.crossfade_segundos
            )
        )

    def _trilha(self, context: RunSnapshot) -> Trilha | None:
        """Faixa da run: a mesma a cada tentativa, pela semente do id."""
        try:
            eixo = None
            plano = context.run_dir / "02-plan.md"
            if plano.is_file():
                eixo = ler_eixo(plano.read_text(encoding="utf-8"))
            return escolher_trilha(
                self.settings.trilhas_dir, semente=context.run_id, eixo=eixo
            )
        except Exception as error:  # noqa: BLE001 - trilha é acabamento
            logger.warning("Trilha indisponível", error=str(error))
            return None

    def _acabamento_hash(self, context: RunSnapshot) -> list[str]:
        """O que muda o vídeo final sem mudar imagem nem áudio de nenhum beat.

        Sem isto, trocar a trilha, ligar os cartões ou refazer a embalagem
        deixaria a etapa reaproveitar um `final.mp4` que não reflete a mudança.
        """
        partes = [
            f"crossfade={self._crossfade(context)}",
            f"volume={self.settings.trilha_volume_db}",
            f"fonte={self.settings.fonte_video}",
        ]
        trilha = self._trilha(context)
        partes.append(f"trilha={trilha.caminho.name if trilha else ''}|{trilha.credito if trilha else ''}")
        # `embalagem.json` fica de fora de propósito: a montagem o regrava com
        # os tempos reais, e um hash que inclui a própria saída nunca se repete.
        caminho = context.run_dir / CITACOES_ARQUIVO
        marca = hashlib.sha256(caminho.read_bytes()).hexdigest() if caminho.is_file() else ""
        partes.append(f"citacoes={marca}")
        return partes

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

        crossfade = self._crossfade(context)
        ultimo = len(plan.items) - 1
        nominais = self._duracoes_nominais(context, plan)
        clipes: list[Path] = []
        duracoes: list[float] = []
        blocos: list[str] = []
        for indice, item in enumerate(plan.items):
            imagem = context.run_dir / str(item.input["image"])
            audio_rels = item.input.get("audios") or [item.input.get("audio")]
            audio_rels = [path for path in audio_rels if path]
            segundos = nominais[indice]
            clipe = clips_dir / f"{indice:04d}-{item.item_key}.mp4"

            emit(
                kind="stage.progress",
                level="info",
                message="Clipe iniciado",
                payload={"item_key": item.item_key},
            )
            try:
                # O arquivo leva o crossfade a mais (menos o último): é a
                # sobra que a transição consome, de modo que a linha do tempo
                # continua igual à soma das durações nominais — a da narração.
                # Preto só na abertura e no fim; no meio, imagem sobre imagem.
                clip_from_image(
                    imagem,
                    clipe,
                    seconds=segundos + (crossfade if indice < ultimo else 0.0),
                    index=indice,
                    portrait=self._is_portrait(imagem),
                    fade_in=FADE_PADRAO if indice == 0 else 0.0,
                    fade_out=FADE_PADRAO if indice == ultimo else 0.0,
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
            duracoes.append(segundos)
            for audio_rel in audio_rels:
                if audio_rel and str(audio_rel) not in blocos:
                    blocos.append(str(audio_rel))
            emit(
                kind="stage.progress",
                level="info",
                message="Clipe concluído",
                payload={"item_key": item.item_key},
            )

        try:
            acabamento = self._compose(context, clipes, duracoes, blocos, crossfade)
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
                **acabamento["metadata"],
            },
        )
        outputs = [output, *acabamento["artifacts"]]
        sha_previa = context.config_snapshot.get("previa_aprovada_sha256")
        if sha_previa:
            destino = "video/abertura-aprovada.json"
            gravar_modelo(context.run_dir / destino, AberturaAprovada(previa_sha256=sha_previa))
            outputs.append(ArtifactOutput(
                kind="abertura.aprovacao", relative_path=destino, mime_type="application/json",
            ))
        for criado in outputs:
            emit(
                kind="artifact.created",
                level="info",
                message="Vídeo final criado" if criado is output else "Acabamento criado",
                payload=criado.model_dump(mode="json"),
            )
        return StageExecutionResult(
            current_items=len(clipes),
            total_items=len(plan.items),
            artifacts=outputs,
        )

    def _compose(
        self,
        context: RunSnapshot,
        clipes: list[Path],
        duracoes: list[float],
        blocos: list[str],
        crossfade: float,
    ) -> dict[str, Any]:
        video_dir = context.run_dir / "video"
        mudo = video_dir / "silent.mp4"
        narracao = video_dir / "narration.wav"
        mixado = video_dir / "mix.wav"
        final = video_dir / "final.mp4"
        artifacts: list[ArtifactOutput] = []

        # `narration.wav` continua sendo a voz pura: a validação mede silêncio
        # e coerência de duração nela, não na mixagem com trilha.
        concat_wavs(
            [context.run_dir / bloco for bloco in blocos],
            narracao,
            video_dir / ".wavs.txt",
            runner=self.runner,
        )

        narrados, tempos = self._linha_do_tempo(context, blocos)
        duracao = tempos[-1].fim if tempos else sum(duracoes)

        legendas = self._legendas(context, narrados, tempos)
        if legendas["artifact"] is not None:
            artifacts.append(legendas["artifact"])
        cartoes_ass, cartoes = self._cartoes(context, narrados, tempos)
        trilha = self._trilha(context)

        if trilha is not None:
            try:
                mix_audio(
                    narracao, trilha.caminho, mixado,
                    duracao=duracao, volume_db=self.settings.trilha_volume_db,
                    runner=self.runner,
                )
            except Exception as error:  # noqa: BLE001 - trilha é acabamento
                # Faixa corrompida ou com DRM. A escolha é determinística, então
                # sem este desvio a run cairia na mesma faixa a cada tentativa.
                logger.warning(
                    "Trilha ilegível; vídeo segue só com a narração",
                    trilha=trilha.caminho.name, error=str(error),
                )
                trilha = None
        if trilha is None:
            mix_audio(
                narracao, None, mixado,
                duracao=duracao, volume_db=self.settings.trilha_volume_db,
                runner=self.runner,
            )
        crossfade_videos(
            clipes, duracoes, mudo,
            crossfade=crossfade, legendas_ass=cartoes_ass, runner=self.runner,
        )
        mux_audio(mudo, mixado, final, runner=self.runner)

        capitulos_reais, embalagem_artifacts = self._embalagem(context, tempos, trilha)
        falados = {bloco.id for bloco in narrados}
        sem_narracao = [
            bloco.id for bloco in self._plano(context).blocos if bloco.id not in falados
        ]
        artifacts.extend(embalagem_artifacts)
        return {
            "artifacts": artifacts,
            "metadata": {
                "trilha": trilha.caminho.name if trilha else None,
                "cartoes": cartoes,
                "legendas": legendas["deixas"],
                "legendas_problemas": legendas["problemas"],
                "capitulos_reais": capitulos_reais,
                "blocos_sem_narracao": sem_narracao,
            },
        }

    def _linha_do_tempo(
        self, context: RunSnapshot, blocos: list[str]
    ) -> tuple[list[BlocoNarracao], list[TrechoTempo]]:
        """Blocos na ordem em que entram na narração, com o tempo real de cada.

        A ordem é a de `blocos` — os WAVs efetivamente concatenados —, não a do
        plano: bloco que nenhum beat cobre não foi narrado e não pode empurrar
        a legenda dos seguintes.
        """
        por_id = {bloco.id: bloco for bloco in self._plano(context).blocos}
        narrados: list[BlocoNarracao] = []
        duracoes: dict[str, float] = {}
        for relativo in blocos:
            bloco = por_id.get(Path(relativo).stem)
            if bloco is None:
                continue
            narrados.append(bloco)
            duracoes[bloco.id] = self.prober(context.run_dir / relativo).duration or 0.0
        return narrados, linha_do_tempo(narrados, duracoes)

    def _legendas(
        self, context: RunSnapshot, narrados: list[BlocoNarracao], tempos: list[TrechoTempo]
    ) -> dict[str, Any]:
        deixas = gerar_deixas(narrados, tempos)
        problemas = conferir_deixas(deixas)
        if not deixas:
            return {"artifact": None, "deixas": 0, "problemas": problemas}
        destino = context.run_dir / "video" / "legendas.srt"
        destino.write_text(formatar_srt(deixas), encoding="utf-8")
        return {
            "artifact": ArtifactOutput(
                item_key=None,
                kind="legendas.srt",
                relative_path=destino.relative_to(context.run_dir).as_posix(),
                mime_type="application/x-subrip",
                metadata={"deixas": len(deixas), "idioma": "pt-BR"},
            ),
            "deixas": len(deixas),
            "problemas": problemas,
        }

    def _cartoes(
        self, context: RunSnapshot, narrados: list[BlocoNarracao], tempos: list[TrechoTempo]
    ) -> tuple[Path | None, int]:
        try:
            cartoes = planejar_cartoes(narrados, tempos, carregar_citacoes(context.run_dir))
            if not cartoes:
                return None, 0
            destino = context.run_dir / "video" / "cartoes.ass"
            destino.write_text(
                gerar_ass(cartoes, fonte=self.settings.fonte_video, largura=LARGURA, altura=ALTURA),
                encoding="utf-8",
            )
            return destino, len(cartoes)
        except Exception as error:  # noqa: BLE001 - cartão é acabamento
            logger.warning("Cartões de fonte não gerados", error=str(error))
            return None, 0

    def _embalagem(
        self, context: RunSnapshot, tempos: list[TrechoTempo], trilha: Trilha | None
    ) -> tuple[bool | None, list[ArtifactOutput]]:
        """Regrava a embalagem com os tempos reais.

        `None` quando a run não tem embalagem (nada a avisar); `False` quando
        tem e os capítulos ficaram estimados.
        """
        caminho = context.run_dir / "video" / "embalagem.json"
        if not caminho.is_file():
            return None, []
        try:
            real = aplicar_tempos_reais(
                carregar_modelo(caminho, Embalagem),
                tempos,
                musica=trilha.credito if trilha else None,
                aviso_ia=bool(
                    context.config_snapshot.get("aviso_ia", self.settings.aviso_ia)
                ),
            )
            if real.capitulos_estimados:
                return False, []
            estruturado, legivel = gravar_embalagem(context.run_dir, real)
        except Exception as error:  # noqa: BLE001 - embalagem é acabamento
            logger.warning("Embalagem não atualizada com tempos reais", error=str(error))
            return False, []
        return True, [
            ArtifactOutput(
                item_key=None,
                kind="embalagem",
                relative_path=estruturado.relative_to(context.run_dir).as_posix(),
                mime_type="application/json",
                metadata={"capitulos_estimados": False, "capitulos": len(real.capitulos)},
            ),
            ArtifactOutput(
                item_key=None,
                kind="embalagem_markdown",
                relative_path=legivel.relative_to(context.run_dir).as_posix(),
                mime_type="text/markdown",
                metadata={},
            ),
        ]

    def _duracoes_nominais(self, context: RunSnapshot, plan: StagePlan) -> list[float]:
        """Duração de cada clipe, somando exatamente a duração da narração.

        O piso por beat (`MIN_SEGUNDOS_POR_BEAT`) estica clipes de narração
        curta; sem compensar, o vídeo fica mais longo que a voz, toda imagem
        seguinte entra atrasada e o `-shortest` do mux corta o fade final. O
        tempo a mais é devolvido pelos clipes seguintes que têm folga acima do
        piso — o mais cedo possível, para a imagem voltar a casar com a fala.
        """
        brutas: list[float] = []
        narrados: dict[str, float] = {}
        for item in plan.items:
            audio_rels = [
                path for path in (item.input.get("audios") or [item.input.get("audio")]) if path
            ]
            divisor = int(item.input["divisor"])
            if not audio_rels:
                brutas.append(self._seconds_for(context, None, divisor))
                continue
            brutas.append(
                sum(self._seconds_for(context, audio_rel, divisor) for audio_rel in audio_rels)
            )
            for audio_rel in audio_rels:
                if str(audio_rel) not in narrados:
                    narrados[str(audio_rel)] = (
                        self.prober(context.run_dir / str(audio_rel)).duration or 0.0
                    )
        if not narrados:
            return brutas
        divida = sum(brutas) - sum(narrados.values())
        ajustadas: list[float] = []
        for bruta in brutas:
            folga = bruta - MIN_SEGUNDOS_POR_BEAT
            if divida > 0 and folga > 0:
                devolvido = min(divida, folga)
                bruta = round(bruta - devolvido, 3)
                divida -= devolvido
            ajustadas.append(bruta)
        if divida > 0.05:
            # Todos os clipes já estão no piso: não há de onde tirar.
            logger.warning("Vídeo mais longo que a narração", excesso=round(divida, 3))
        return ajustadas

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

        # Metadados ausentes = resultado montado fora de `execute`: sem como
        # julgar o acabamento, não se inventa achado.
        acabamento = finais[0].metadata
        if "legendas" in acabamento:
            if not acabamento["legendas"]:
                findings.append(
                    GateFinding(code="subtitles_missing", message="Legenda não gerada")
                )
            elif acabamento.get("legendas_problemas"):
                findings.append(
                    GateFinding(
                        code="subtitles_invalid",
                        message="Legenda com tempo fora de ordem ou deixa inválida",
                        details={"problemas": acabamento["legendas_problemas"]},
                    )
                )

        if findings:
            return GateResult(
                approved=False,
                code="compose_gate_failed",
                findings=findings,
                metrics=metrics,
            )

        avisos: list[GateFinding] = []
        if "trilha" in acabamento and not acabamento["trilha"]:
            avisos.append(
                GateFinding(
                    code="trilha_ausente",
                    message="Vídeo sem trilha: nenhuma faixa na pasta de trilhas",
                )
            )
        if "cartoes" in acabamento and not acabamento["cartoes"]:
            avisos.append(
                GateFinding(
                    code="cartoes_ausentes",
                    message="Nenhum cartão de fonte na tela: roteiro sem citação rastreável",
                )
            )
        if acabamento.get("blocos_sem_narracao"):
            avisos.append(
                GateFinding(
                    code="blocos_sem_narracao",
                    message="Blocos do roteiro ficaram fora do vídeo: nenhum beat os cobre",
                    details={"blocos": acabamento["blocos_sem_narracao"]},
                )
            )
        if acabamento.get("capitulos_reais") is False:
            avisos.append(
                GateFinding(
                    code="capitulos_estimados",
                    message="Capítulos da descrição seguem estimados; confira antes de publicar",
                )
            )
        return GateResult(
            approved=True, code="compose_approved", findings=avisos, metrics=metrics
        )

    def run(self, context: RunSnapshot, emit: EventSink) -> StageChildResult:
        plan = self.prepare(context)
        execution = self.execute(context, plan, emit)
        gate = self.validate(context, plan, execution)
        return StageChildResult(**execution.model_dump(), gate=gate)


__all__ = ["ComposeExecutor"]
