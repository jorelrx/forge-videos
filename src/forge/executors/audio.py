"""Studio audio stage: synthesize, verify and gate every narration block."""

from __future__ import annotations

import hashlib
import shutil
from contextlib import ExitStack, nullcontext
from dataclasses import dataclass
from pathlib import Path
from statistics import median
from time import monotonic
from typing import Any, Callable, ContextManager, Literal

import numpy as np
import soundfile as sf

from forge.agents.midia import carregar_plano
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
from forge.domain.operacao import Artifact, ItemStatus, StageName, WorkItem
from forge.executors.abertura import artefato_aprovado
from forge.executors.audio_generate import (
    FALHAS_DE_SERVIDOR,
    SERVIDOR_INDISPONIVEL,
    AudioGenerateClient,
    AudioRequest,
)
from forge.executors.audiocpp_server import (
    ContratoServidorQuebrado,
    ServidorIndisponivel,
    montar_servidor,
)
from forge.executors.base import StageImplementation
from forge.executors.plano_midia import hash_json
from forge.gpu.liberadores import montar_broker
from forge.infrastructure.config import Settings
from forge.infrastructure.logging import get_logger
from forge.services.worker import EventSink

logger = get_logger(__name__)


# −35 dB em amplitude: o mesmo piso do `silencedetect` da validação final.
SILENCIO_PISO = 10 ** (-35 / 20)
# Abaixo dos 2 s da validação final: a cauda de um bloco soma com o começo do
# seguinte depois da concatenação.
SILENCIO_MAXIMO_SEGUNDOS = 1.5


def validate_wav(
    path: Path, *, expected_rate: int, expected_channels: int
) -> list[GateFinding]:
    """Return every detectable WAV gate failure for one run-local output."""
    path = Path(path)
    if not path.is_file() or path.stat().st_size == 0:
        return [GateFinding(code="audio_empty", message="Arquivo de áudio está vazio", item_key=path.stem)]
    try:
        info = sf.info(path)
    except (OSError, RuntimeError, ValueError) as error:
        return [GateFinding(
            code="audio_unreadable", message="Arquivo de áudio não pode ser lido",
            item_key=path.stem, details={"error": str(error)},
        )]
    findings: list[GateFinding] = []
    if info.frames <= 0:
        findings.append(GateFinding(code="audio_empty", message="Arquivo de áudio não contém frames", item_key=path.stem))
    if info.samplerate != expected_rate:
        findings.append(GateFinding(
            code="audio_sample_rate", message="Taxa de amostragem inválida", item_key=path.stem,
            details={"actual": info.samplerate, "expected": expected_rate},
        ))
    if info.channels != expected_channels:
        findings.append(GateFinding(
            code="audio_channels", message="Áudio deve ser mono", item_key=path.stem,
            details={"actual": info.channels, "expected": expected_channels},
        ))
    return findings


@dataclass
class _Tentativa:
    """Resultado do laço de sementes de um trecho num servidor.

    `classe` decide o destino: `trecho` pode ir para a fila de CPU, `servidor`
    reinicia o processo, `config` falha o trecho na hora (erro igual para todo
    trecho, esconder na CPU só atrasaria o diagnóstico).
    """

    classe: Literal["ok", "trecho", "servidor", "config"]
    artefato: ArtifactOutput | None = None
    path: Path | None = None
    seed: int | None = None
    falha: FailureDetail | None = None
    elapsed_ms: int = 0


class _Lado:
    """Um servidor de um backend e o reinício único que ele tem por etapa."""

    def __init__(self, servidor: Any, backend: str, *, motivo: str = "", contrato: bool = False):
        self.servidor = servidor
        self.backend = backend
        self.disponivel = servidor is not None
        self.reiniciou = False
        self.motivo = motivo
        self.contrato = contrato

    def falha_indisponivel(self, item_key: str) -> FailureDetail:
        if self.contrato:
            return _falha_contrato(self.motivo, item_key=item_key)
        return FailureDetail(
            code=SERVIDOR_INDISPONIVEL,
            message=f"Servidor de áudio ({self.backend}) indisponível",
            failure_class=FailureClass.PROCESS,
            retriable=True,
            recommended_action="Conferir o audiocpp_server e a VRAM livre, depois repetir a etapa",
            adapter="audio",
            attempt=1,
            item_key=item_key,
            services={"stderr_tail": self.motivo},
        )


def _falha_contrato(motivo: str, *, item_key: str | None = None) -> FailureDetail:
    return FailureDetail(
        code="tts_contrato_servidor",
        message="audiocpp_server não respeita o contrato de clonagem de voz",
        failure_class=FailureClass.DETERMINISTIC,
        retriable=False,
        recommended_action="Conferir a versão do audiocpp_server em runtime/bin",
        adapter="audio",
        attempt=1,
        item_key=item_key,
        services={"stderr_tail": motivo},
    )


class _NoopBroker:
    def exclusivo(self, resource: str):
        return nullcontext()


class AudioExecutor(StageImplementation):
    """Generate one canonical WAV per ``BlocoNarracao`` without shell execution."""

    alternate_seeds = (1042, 2042)

    def __init__(
        self,
        *,
        settings: Settings | None = None,
        client: AudioGenerateClient | Any | None = None,
        broker: Any | None = None,
        servidor_factory: Callable[[str, Path], ContextManager[Any]] | None = None,
    ) -> None:
        self.settings = settings or Settings()
        self.client = client or AudioGenerateClient(self.settings)
        self.broker = broker
        # Um servidor residente por backend durante a etapa; injetável nos
        # testes, que nunca sobem processo.
        self._servidor_factory = servidor_factory or (
            lambda backend, pasta: montar_servidor(self.settings, backend, pasta_log=pasta)
        )

    def prepare(self, context: RunSnapshot) -> StagePlan:
        if context.stage is not StageName.AUDIO:
            raise ValueError("context stage does not match audio executor")
        media = carregar_plano(context.run_dir)
        items = [
            WorkItemPlan(
                item_key=block.id,
                input=block.model_dump(mode="json"),
                # Provenance is carried through the plan, but never enters
                # TTS or invalidates an unchanged audio file.
                input_hash=hash_json({
                    "id": block.id, "secao": block.secao, "texto": block.texto,
                }),
            )
            for block in media.blocos
        ]
        return StagePlan(
            stage=StageName.AUDIO,
            input_hash=hash_json([{"item_key": item.item_key, "input_hash": item.input_hash} for item in items]),
            items=items,
        )

    def _broker(self):
        return self.broker if self.broker is not None else montar_broker(self.settings)

    @staticmethod
    def _f0(path: Path, sample_rate: int) -> float:
        samples, rate = sf.read(path, dtype="float32", always_2d=False)
        values = np.asarray(samples, dtype=np.float32)
        if values.ndim != 1 or not len(values) or not np.any(np.abs(values) > 1e-5):
            return 0.0
        # Zero crossings track spectral brightness, not fundamental pitch:
        # consonants alone could make the same narrator look like another voice.
        # Estimate periodicity in voiced frames using normalized autocorrelation.
        size = min(2048, len(values))
        low, high = max(2, rate // 500), min(rate // 60, size // 2)
        if high <= low:
            return 0.0
        length = size - high
        fft_size = 1 << (2 * size - 1).bit_length()
        pitches = []
        for start in range(0, len(values) - size + 1, max(1, rate // 10)):
            frame = values[start:start + size].astype(np.float64)
            frame -= frame.mean()
            reference = frame[:length]
            energy = float(np.dot(reference, reference))
            if energy / length < 1e-6:
                continue
            correlation = np.fft.irfft(
                np.fft.rfft(frame, fft_size) * np.conj(np.fft.rfft(reference, fft_size)),
                fft_size,
            )[:high + 1]
            cumulative = np.concatenate(([0.0], np.cumsum(frame * frame)))
            shifted_energy = cumulative[length:length + high + 1] - cumulative[:high + 1]
            coefficients = correlation / np.sqrt(np.maximum(energy * shifted_energy, 1e-20))
            peaks = [lag for lag in range(low, high)
                     if coefficients[lag] >= coefficients[lag - 1]
                     and coefficients[lag] > coefficients[lag + 1]]
            if not peaks:
                continue
            best = max(coefficients[lag] for lag in peaks)
            if best < 0.6:
                continue
            lag = next(lag for lag in peaks if coefficients[lag] >= best - 0.01)
            left, center, right = coefficients[lag - 1:lag + 2]
            denominator = left - 2 * center + right
            offset = 0.5 * (left - right) / denominator if denominator else 0.0
            pitches.append(rate / (lag + float(np.clip(offset, -0.5, 0.5))))
        return round(float(median(pitches)), 3) if pitches else 0.0

    @staticmethod
    def _silencio_max(path: Path) -> float:
        """Maior trecho mudo do bloco, em segundos.

        O TTS às vezes trava calado no meio da frase e o WAV continua válido.
        Mesmo piso do `silencedetect` da validação final (−35 dB), em janelas
        de 20 ms, para os dois gates enxergarem o mesmo silêncio.
        """
        samples, rate = sf.read(path, dtype="float32", always_2d=False)
        values = np.abs(np.asarray(samples, dtype=np.float32))
        janela = max(1, rate // 50)
        total = len(values) // janela
        if values.ndim != 1 or total == 0:
            return 0.0
        picos = values[: total * janela].reshape(total, janela).max(axis=1)
        maior = atual = 0
        for mudo in picos < SILENCIO_PISO:
            atual = atual + 1 if mudo else 0
            maior = max(maior, atual)
        return round(maior * janela / rate, 3)

    def _wav_metadata(
        self, path: Path, *, seed: int
    ) -> tuple[dict[str, Any] | None, list[GateFinding]]:
        findings = validate_wav(
            path,
            expected_rate=self.settings.tts_sample_rate,
            expected_channels=1,
        )
        if findings:
            return None, findings
        info = sf.info(path)
        return {
            "sample_rate": info.samplerate,
            "channels": info.channels,
            "duration": info.frames / info.samplerate,
            "F0": self._f0(path, info.samplerate),
            "silencio_max": self._silencio_max(path),
            "seed": seed,
        }, []

    @staticmethod
    def _resolved_artifact_path(context: RunSnapshot, artifact: Artifact) -> Path | None:
        try:
            path = (context.run_dir / artifact.relative_path).resolve(strict=True)
            path.relative_to(context.run_dir.resolve(strict=True))
        except (FileNotFoundError, ValueError):
            return None
        if not path.is_file() or path.stat().st_size != artifact.size_bytes:
            return None
        if hashlib.sha256(path.read_bytes()).hexdigest() != artifact.sha256:
            return None
        return path

    def _artifact_for(
        self, context: RunSnapshot, item_key: str, path: Path, *, seed: int
    ) -> tuple[ArtifactOutput | None, list[GateFinding]]:
        try:
            resolved = Path(path).resolve(strict=True)
            relative = resolved.relative_to(context.run_dir.resolve(strict=True)).as_posix()
        except (FileNotFoundError, ValueError):
            return None, [GateFinding(
                code="audio_path_outside_run", message="Saída de áudio fora da run",
                item_key=item_key,
            )]
        if not resolved.is_file():
            return None, [GateFinding(
                code="audio_unreadable", message="Saída de áudio não é arquivo regular",
                item_key=item_key,
            )]
        metadata, findings = self._wav_metadata(resolved, seed=seed)
        if findings:
            return None, [finding.model_copy(update={"item_key": item_key}) for finding in findings]
        return ArtifactOutput(
            item_key=item_key,
            kind="audio.wav",
            relative_path=relative,
            mime_type="audio/wav",
            metadata=metadata or {},
        ), []

    def _result_for_paths(
        self, context: RunSnapshot, plan: StagePlan, paths: dict[str, Path]
    ) -> StageExecutionResult:
        artifacts: list[ArtifactOutput] = []
        for item in plan.items:
            path = paths.get(item.item_key)
            if path is None:
                continue
            try:
                relative = Path(path).resolve(strict=True).relative_to(
                    context.run_dir.resolve(strict=True)
                ).as_posix()
            except (FileNotFoundError, ValueError):
                continue
            metadata, _ = self._wav_metadata(Path(path), seed=self.settings.tts_seed)
            artifacts.append(ArtifactOutput(
                item_key=item.item_key, kind="audio.wav", relative_path=relative,
                mime_type="audio/wav", metadata=metadata or {},
            ))
        return StageExecutionResult(
            current_items=len(artifacts), total_items=len(plan.items), artifacts=artifacts
        )

    @staticmethod
    def _failure_from_findings(item_key: str, findings: list[GateFinding]) -> FailureDetail:
        finding = findings[0] if findings else GateFinding(
            code="audio_unreadable", message="Saída de áudio ausente", item_key=item_key,
        )
        return FailureDetail(
            code=finding.code,
            message=finding.message,
            failure_class=FailureClass.ITEM,
            retriable=False,
            recommended_action="Corrigir a saída de áudio e tentar novamente",
            adapter="audio",
            attempt=1,
            item_key=item_key,
        )

    @staticmethod
    def _request(item: WorkItemPlan, *, seed: int | None = None) -> AudioRequest:
        return AudioRequest(item.item_key, str(item.input.get("texto", "")), seed=seed)

    @staticmethod
    def _current_item(context: RunSnapshot, item: WorkItemPlan) -> WorkItem | None:
        return next(
            (
                current for current in context.work_items
                if current.item_key == item.item_key and current.input_hash == item.input_hash
            ),
            None,
        )

    def _current_output(
        self, context: RunSnapshot, item: WorkItemPlan, work_item: WorkItem
    ) -> tuple[Path, ArtifactOutput] | None:
        for artifact in context.artifacts:
            if (
                artifact.is_current
                and artifact.work_item_id == work_item.id
                and artifact.kind == "audio.wav"
            ):
                path = self._resolved_artifact_path(context, artifact)
                if path is None:
                    continue
                seed = int(artifact.metadata.get("seed", self.settings.tts_seed))
                output, findings = self._artifact_for(context, item.item_key, path, seed=seed)
                if output is not None and not findings:
                    return path, output
        return None

    def _reusable_output(
        self, context: RunSnapshot, item: WorkItemPlan
    ) -> tuple[Path, ArtifactOutput] | None:
        for candidate in context.reusable_outputs:
            if candidate.input_hash != item.input_hash:
                continue
            artifact = candidate.artifact
            path = self._resolved_artifact_path(context, artifact)
            if path is None:
                continue
            seed = int(artifact.metadata.get("seed", self.settings.tts_seed))
            output, findings = self._artifact_for(context, item.item_key, path, seed=seed)
            if output is not None and not findings:
                return path, output
        return None

    def _voice_outlier_keys(self, artifacts: dict[str, ArtifactOutput]) -> list[str]:
        if len(artifacts) < 5:
            return []
        f0_by_key = {key: float(output.metadata["F0"]) for key, output in artifacts.items()}
        baseline = median(f0_by_key.values())
        mad = median(abs(value - baseline) for value in f0_by_key.values())
        # A stable narrator still changes pitch with intonation. Near-zero MAD
        # must not turn a small prosodic change into a different-voice verdict.
        tolerance = max(3.5 * mad, 0.20 * baseline)
        return [key for key, value in f0_by_key.items() if abs(value - baseline) > tolerance]

    @staticmethod
    def _silence_keys(artifacts: dict[str, ArtifactOutput]) -> list[str]:
        return [
            key for key, output in artifacts.items()
            if float(output.metadata.get("silencio_max", 0.0)) > SILENCIO_MAXIMO_SEGUNDOS
        ]

    # -- síntese ----------------------------------------------------------------

    def _seeds(self) -> list[int]:
        # A saída é determinística por semente (byte a byte na GPU): repetir a
        # mesma semente nunca muda o resultado.
        return list(dict.fromkeys((self.settings.tts_seed, *self.alternate_seeds)))

    def _tentar(
        self, context: RunSnapshot, item: WorkItemPlan, servidor: Any, *, output_dir: Path,
    ) -> _Tentativa:
        """Laço de sementes de um trecho num servidor. Sem efeito colateral
        além do WAV: roda tanto na thread principal quanto na de CPU."""
        started = monotonic()
        guardado: tuple[Path, ArtifactOutput, int] | None = None
        ultima: FailureDetail | None = None

        def elapsed() -> int:
            return round((monotonic() - started) * 1000)

        for seed in self._seeds():
            outcome = self.client.synthesize(self._request(item, seed=seed), servidor, output_dir)
            if outcome.failure is not None:
                code = outcome.failure.code
                if code in FALHAS_DE_SERVIDOR:
                    return _Tentativa("servidor", falha=outcome.failure, seed=seed, elapsed_ms=elapsed())
                if code != "tts_max_tokens_before_eoc":
                    return _Tentativa("config", falha=outcome.failure, seed=seed, elapsed_ms=elapsed())
                ultima = outcome.failure
                continue
            output, findings = self._artifact_for(context, item.item_key, outcome.path, seed=seed)
            if output is None:
                # O arquivo canônico agora tem esta saída inválida: um
                # artefato guardado de semente anterior já não corresponde.
                guardado = None
                ultima = self._failure_from_findings(item.item_key, findings)
                continue
            silencio = float(output.metadata.get("silencio_max", 0.0))
            if silencio > SILENCIO_MAXIMO_SEGUNDOS:
                guardado = (outcome.path, output, seed)
                ultima = FailureDetail(
                    code="audio_silence",
                    message="Bloco com silêncio longo no meio da fala",
                    failure_class=FailureClass.ITEM,
                    retriable=True,
                    recommended_action="Gerar o bloco com outra semente",
                    adapter="audio",
                    attempt=1,
                    item_key=item.item_key,
                    services={"silencio_max": silencio},
                )
                continue
            return _Tentativa("ok", artefato=output, path=outcome.path, seed=seed, elapsed_ms=elapsed())
        if guardado is not None:
            path, output, seed = guardado
            return _Tentativa("trecho", artefato=output, path=path, seed=seed, falha=ultima, elapsed_ms=elapsed())
        return _Tentativa("trecho", falha=ultima, elapsed_ms=elapsed())

    def _processar(
        self, context: RunSnapshot, item: WorkItemPlan, lado: _Lado, *, output_dir: Path,
    ) -> _Tentativa:
        """`_tentar` com a política de servidor: um reinício por backend."""
        if not lado.disponivel:
            return _Tentativa("servidor", falha=lado.falha_indisponivel(item.item_key))
        tentativa = self._tentar(context, item, lado.servidor, output_dir=output_dir)
        if tentativa.classe != "servidor":
            return tentativa
        if lado.reiniciou:
            lado.disponivel = False
            return tentativa
        lado.reiniciou = True
        try:
            lado.servidor.reiniciar()
        except (ServidorIndisponivel, ContratoServidorQuebrado) as error:
            lado.disponivel = False
            lado.motivo = str(error)
            return _Tentativa("servidor", falha=lado.falha_indisponivel(item.item_key))
        tentativa = self._tentar(context, item, lado.servidor, output_dir=output_dir)
        if tentativa.classe == "servidor":
            lado.disponivel = False
        return tentativa

    def _retry_voice_outliers(
        self,
        context: RunSnapshot,
        plan: StagePlan,
        paths: dict[str, Path],
        artifacts: dict[str, ArtifactOutput],
        lado: _Lado | None,
        output_dir: Path,
        emit: EventSink,
    ) -> None:
        by_key = {item.item_key: item for item in plan.items}
        for key in list(self._voice_outlier_keys(artifacts)):
            item = by_key[key]
            for seed in self.alternate_seeds:
                if key not in self._voice_outlier_keys(artifacts):
                    break
                if lado is None or not lado.disponivel:
                    logger.warning("Outlier de voz não regenerado: servidor indisponível", item_key=key)
                    return
                outcome = self.client.synthesize(self._request(item, seed=seed), lado.servidor, output_dir)
                if not outcome.ok or outcome.path is None:
                    if outcome.failure is not None and outcome.failure.code in FALHAS_DE_SERVIDOR:
                        lado.disponivel = False
                    continue
                output, findings = self._artifact_for(context, key, outcome.path, seed=seed)
                if output is None or findings:
                    continue
                paths[key] = outcome.path
                artifacts[key] = output
                emit(
                    kind="artifact.created", level="info", message="Áudio regenerado",
                    payload=output.model_dump(mode="json"),
                )

    def execute(
        self, context: RunSnapshot, plan: StagePlan, emit: EventSink
    ) -> StageExecutionResult:
        emit(
            kind="configuration.warning", level="warning",
            message="Higgs Audio possui licença não comercial",
            payload={"component": "higgs-audio", "license": "non-commercial"},
        )
        output_dir = context.run_dir / "video" / "audio"
        paths: dict[str, Path] = {}
        artifacts: dict[str, ArtifactOutput] = {}
        pending: list[WorkItemPlan] = []
        reusable: dict[str, tuple[Path, ArtifactOutput]] = {}
        for item in plan.items:
            current = self._current_item(context, item)
            if current is not None and current.status is ItemStatus.SUCCEEDED:
                found = self._current_output(context, item, current)
                if found is not None:
                    paths[item.item_key], artifacts[item.item_key] = found
                    continue
            found = self._reusable_output(context, item)
            aprovado = artefato_aprovado(
                context, "abertura.audio", item=item.item_key, input_hash=item.input_hash,
            )
            if aprovado is not None:
                path, metadata = aprovado
                output, findings = self._artifact_for(
                    context, item.item_key, path, seed=int(metadata["seed"]),
                )
                if output is not None and not findings:
                    found = path, output
            if found is not None:
                reusable[item.item_key] = found
            else:
                pending.append(item)

        for item in plan.items:
            if item.item_key not in reusable:
                continue
            source, output = reusable[item.item_key]
            destination = output_dir / f"{item.item_key}.wav"
            destination.parent.mkdir(parents=True, exist_ok=True)
            if source.resolve() != destination.resolve():
                shutil.copy2(source, destination)
            refreshed, findings = self._artifact_for(
                context, item.item_key, destination, seed=int(output.metadata["seed"])
            )
            if refreshed is None or findings:
                pending.append(item)
                continue
            paths[item.item_key], artifacts[item.item_key] = destination, refreshed
            emit(kind="item.started", level="info", message="Narração reutilizada", payload={"item_key": item.item_key, "duration_ms": 0})
            emit(kind="artifact.created", level="info", message="Áudio reutilizado", payload=refreshed.model_dump(mode="json"))
            emit(kind="item.succeeded", level="info", message="Narração concluída", payload={"item_key": item.item_key, "duration_ms": 0})

        principal = self.settings.tts_backend
        recuperacao = "cpu" if principal != "cpu" else None

        def aceitar(item: WorkItemPlan, tentativa: _Tentativa, backend: str) -> None:
            paths[item.item_key], artifacts[item.item_key] = tentativa.path, tentativa.artefato
            emit(kind="artifact.created", level="info", message="Áudio criado",
                 payload=tentativa.artefato.model_dump(mode="json"))
            emit(kind="item.succeeded", level="info", message="Narração concluída", payload={
                "item_key": item.item_key, "duration_ms": tentativa.elapsed_ms, "backend": backend,
            })

        def falhar(item: WorkItemPlan, falha: FailureDetail, backend: str, **extra: Any) -> None:
            emit(kind="item.failed", level="error", message=falha.message, payload={
                "item_key": item.item_key, "failure_code": falha.code,
                "failure_message": falha.message, "backend": backend, **extra,
            })

        def concluir(item: WorkItemPlan, tentativa: _Tentativa, backend: str, **extra: Any) -> None:
            """Destino final de um trecho que não vai a mais lugar nenhum."""
            if tentativa.artefato is not None:
                # Só achados (silêncio): o artefato fica e o gate reprova.
                aceitar(item, tentativa, backend)
                return
            falha = tentativa.falha or self._failure_from_findings(item.item_key, [])
            falhar(item, falha, backend, **extra)

        with self._broker().exclusivo("tts"), ExitStack() as pilha:
            try:
                lado_principal = _Lado(
                    pilha.enter_context(self._servidor_factory(principal, output_dir)), principal,
                )
            except ContratoServidorQuebrado as error:
                logger.error("Contrato do servidor TTS quebrado", backend=principal, error=str(error))
                return StageExecutionResult(
                    current_items=len(artifacts), total_items=len(plan.items),
                    artifacts=list(artifacts.values()),
                    failure=_falha_contrato(str(error)),
                )
            except ServidorIndisponivel as error:
                logger.error("Servidor TTS não subiu", backend=principal, error=str(error))
                lado_principal = _Lado(None, principal, motivo=str(error))

            fila_cpu: list[tuple[WorkItemPlan, FailureDetail]] = []
            for item in pending:
                emit(kind="item.started", level="info", message="Narração iniciada", payload={
                    "item_key": item.item_key, "duration_ms": 0, "backend": principal,
                })
                tentativa = self._processar(context, item, lado_principal, output_dir=output_dir)
                if tentativa.classe == "ok":
                    aceitar(item, tentativa, principal)
                    continue
                if tentativa.classe == "trecho" and recuperacao is not None:
                    original = tentativa.falha or self._failure_from_findings(item.item_key, [])
                    logger.warning(
                        "tts_trecho_enviado_para_cpu", item_key=item.item_key,
                        original_backend=principal, original_failure_code=original.code,
                    )
                    emit(
                        kind="audio.recovery.started", level="warning",
                        message="Trecho esgotou as sementes na GPU; entrou na fila de CPU",
                        payload={
                            "item_key": item.item_key, "backend": recuperacao,
                            "fallback_from": principal, "queued": True,
                            "original_failure_code": original.code,
                            "original_failure_message": original.message,
                            "original_failure_stderr": original.services.get("stderr_tail", ""),
                        },
                    )
                    fila_cpu.append((item, original))
                    continue
                concluir(item, tentativa, principal)

            lado_cpu: _Lado | None = None
            for item, original in fila_cpu:
                if lado_cpu is None:
                    lado_cpu = self._subir_lado(pilha, recuperacao, output_dir)
                tentativa = self._processar(context, item, lado_cpu, output_dir=output_dir)
                sucesso = tentativa.classe == "ok"
                final = tentativa.falha or self._failure_from_findings(item.item_key, [])
                emit(
                    kind="audio.recovery.completed",
                    level="info" if sucesso else "error",
                    message="Trecho recuperado na CPU" if sucesso else "Trecho também falhou na CPU",
                    payload={
                        "item_key": item.item_key, "backend": recuperacao,
                        "fallback_from": principal,
                        "status": "succeeded" if sucesso else "failed",
                        "original_failure_code": original.code,
                        **({} if sucesso else {
                            "cpu_failure_code": final.code,
                            "cpu_failure_message": final.message,
                        }),
                    },
                )
                if sucesso:
                    aceitar(item, tentativa, recuperacao)
                else:
                    concluir(
                        item, tentativa, recuperacao,
                        original_backend=principal, original_failure_code=original.code,
                    )

            self._retry_voice_outliers(
                context, plan, paths, artifacts, lado_principal, output_dir, emit,
            )
        return StageExecutionResult(
            current_items=len(artifacts), total_items=len(plan.items), artifacts=list(artifacts.values())
        )

    def _subir_lado(self, pilha: ExitStack, backend: str, output_dir: Path) -> _Lado:
        try:
            return _Lado(pilha.enter_context(self._servidor_factory(backend, output_dir)), backend)
        except ContratoServidorQuebrado as error:
            logger.error("Contrato do servidor TTS quebrado", backend=backend, error=str(error))
            return _Lado(None, backend, motivo=str(error), contrato=True)
        except ServidorIndisponivel as error:
            logger.error("Servidor TTS não subiu", backend=backend, error=str(error))
            return _Lado(None, backend, motivo=str(error))

    def validate(
        self, context: RunSnapshot, plan: StagePlan, result: StageExecutionResult
    ) -> GateResult:
        expected = {item.item_key for item in plan.items}
        artifacts = {artifact.item_key: artifact for artifact in result.artifacts if artifact.item_key}
        findings: list[GateFinding] = []
        for item in plan.items:
            artifact = artifacts.get(item.item_key)
            if artifact is None:
                continue
            path = context.run_dir / artifact.relative_path
            findings.extend(
                finding.model_copy(update={"item_key": item.item_key})
                for finding in validate_wav(
                    path,
                    expected_rate=self.settings.tts_sample_rate,
                    expected_channels=1,
                )
            )
        if set(artifacts) != expected:
            findings.insert(0, GateFinding(code="audio_incomplete", message="Nem todos os blocos possuem áudio válido"))
        for key in self._silence_keys(artifacts):
            findings.append(GateFinding(
                code="audio_silence", message="Bloco com silêncio longo no meio da fala",
                item_key=key, details={
                    "silencio_max": artifacts[key].metadata["silencio_max"],
                    "limite": SILENCIO_MAXIMO_SEGUNDOS,
                    "alternate_seeds": list(self.alternate_seeds),
                },
            ))
        for key in self._voice_outlier_keys(artifacts):
            output = artifacts[key]
            f0_values = [float(value.metadata["F0"]) for value in artifacts.values()]
            baseline = median(f0_values)
            mad = median(abs(value - baseline) for value in f0_values)
            findings.append(GateFinding(
                code="audio_voice_divergence", message="F0 diverge da voz de referência",
                item_key=key, details={"F0": output.metadata["F0"], "median_F0": baseline, "mad": mad, "alternate_seeds": list(self.alternate_seeds)},
            ))
        if findings:
            incomplete = any(finding.code == "audio_incomplete" for finding in findings)
            return GateResult(
                approved=False, code="audio_incomplete" if incomplete else "audio_gate_failed",
                findings=findings, metrics={"current_items": len(artifacts), "total_items": len(plan.items)},
            )
        return GateResult(
            approved=True, code="audio_approved",
            metrics={"current_items": len(artifacts), "total_items": len(plan.items)},
        )

    def run(self, context: RunSnapshot, emit: EventSink) -> StageChildResult:
        plan = self.prepare(context)
        for item in plan.items:
            current = self._current_item(context, item)
            if current is None or current.input_hash != item.input_hash:
                emit(
                    kind="item.planned", level="info", message="Item de áudio planejado",
                    payload={**item.model_dump(mode="json"), "kind": "audio", "stage": "audio"},
                )
        execution = self.execute(context, plan, emit)
        return StageChildResult(**execution.model_dump(), gate=self.validate(context, plan, execution))


__all__ = ["AudioExecutor", "validate_wav"]
