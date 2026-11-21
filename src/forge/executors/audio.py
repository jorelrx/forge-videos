"""Studio audio stage: synthesize, verify and gate every narration block."""

from __future__ import annotations

import hashlib
import shutil
from contextlib import nullcontext
from pathlib import Path
from statistics import median
from time import monotonic
from typing import Any

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
from forge.executors.audio_generate import AudioGenerateClient, AudioOutcome, AudioRequest
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
    ) -> None:
        self.settings = settings or Settings()
        self.client = client or AudioGenerateClient(self.settings)
        self.broker = broker

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

    def _retry_long_silences(
        self,
        context: RunSnapshot,
        plan: StagePlan,
        paths: dict[str, Path],
        artifacts: dict[str, ArtifactOutput],
        output_dir: Path,
        emit: EventSink,
    ) -> None:
        """Regenera, com outra semente, o bloco que saiu com um buraco mudo.

        Sem isto o defeito só aparecia na validação final, depois de imagens e
        montagem prontas, e repetir a etapa reaproveitava o mesmo arquivo.
        """
        by_key = {item.item_key: item for item in plan.items}
        for key in self._silence_keys(artifacts):
            for seed in self.alternate_seeds:
                outcomes = self.client.synthesize_batch(
                    [self._request(by_key[key], seed=seed)], output_dir
                )
                outcome = outcomes[0] if outcomes else None
                if outcome is None or not outcome.ok or outcome.path is None:
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
                if key not in self._silence_keys(artifacts):
                    break

    def _retry_voice_outliers(
        self,
        context: RunSnapshot,
        plan: StagePlan,
        paths: dict[str, Path],
        artifacts: dict[str, ArtifactOutput],
        output_dir: Path,
        emit: EventSink,
    ) -> None:
        by_key = {item.item_key: item for item in plan.items}
        for key in list(self._voice_outlier_keys(artifacts)):
            item = by_key[key]
            for seed in self.alternate_seeds:
                if key not in self._voice_outlier_keys(artifacts):
                    break
                outcomes = self.client.synthesize_batch([self._request(item, seed=seed)], output_dir)
                outcome = outcomes[0] if outcomes else None
                if outcome is None or not outcome.ok or outcome.path is None:
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

        with self._broker().exclusivo("tts"):
            retry: list[WorkItemPlan] = []

            def accept(
                item: WorkItemPlan, outcome: AudioOutcome | None, elapsed: int, backend: str,
                seed: int | None = None,
            ) -> bool:
                if outcome is None or not outcome.ok or outcome.path is None:
                    return False
                output, findings = self._artifact_for(
                    context, item.item_key, outcome.path,
                    seed=self.settings.tts_seed if seed is None else seed,
                )
                if output is None or findings:
                    return False
                paths[item.item_key], artifacts[item.item_key] = outcome.path, output
                emit(kind="artifact.created", level="info", message="Áudio criado", payload=output.model_dump(mode="json"))
                emit(kind="item.succeeded", level="info", message="Narração concluída", payload={
                    "item_key": item.item_key, "duration_ms": elapsed, "backend": backend,
                })
                return True

            for offset in range(0, len(pending), self.settings.tts_batch_size):
                batch = pending[offset : offset + self.settings.tts_batch_size]
                for item in batch:
                    emit(kind="item.started", level="info", message="Narração iniciada", payload={
                        "item_key": item.item_key, "duration_ms": 0,
                        "backend": self.settings.tts_backend,
                    })
                started = monotonic()
                outcomes = {
                    outcome.item_key: outcome
                    for outcome in self.client.synthesize_batch(
                        [self._request(item) for item in batch], output_dir
                    )
                }
                elapsed = round((monotonic() - started) * 1000)
                for item in batch:
                    outcome = outcomes.get(item.item_key)
                    if accept(item, outcome, elapsed, self.settings.tts_backend):
                        continue
                    failure = outcome.failure if outcome is not None else None
                    if (
                        failure is not None
                        and failure.code == "tts_max_tokens_before_eoc"
                        and self.settings.tts_backend == "vulkan"
                    ):
                        original_failure = failure
                        if len(batch) > 1:
                            logger.warning(
                                "tts_max_tokens_batch_item_isolation_started",
                                item_key=item.item_key, batch_item_keys=[x.item_key for x in batch],
                                backend="vulkan", failure_code=failure.code,
                            )
                            isolated_started = monotonic()
                            isolated = self.client.synthesize_batch(
                                [self._request(item)], output_dir
                            )
                            isolated_elapsed = round((monotonic() - isolated_started) * 1000)
                            outcome = isolated[0] if isolated else None
                            if accept(item, outcome, isolated_elapsed, "vulkan"):
                                continue
                            failure = outcome.failure if outcome is not None else None
                            if failure is None or failure.code != "tts_max_tokens_before_eoc":
                                if failure is not None and failure.retriable:
                                    retry.append(item)
                                else:
                                    detail = failure or self._failure_from_findings(item.item_key, [])
                                    emit(kind="item.failed", level="error", message=detail.message, payload={
                                        "item_key": item.item_key, "failure_code": detail.code,
                                        "failure_message": detail.message, "backend": "vulkan",
                                    })
                                continue
                            original_failure = failure

                        logger.warning(
                            "tts_max_tokens_cpu_fallback_started", item_key=item.item_key,
                            original_backend="vulkan", fallback_backend="cpu",
                            original_failure_code=original_failure.code,
                            original_failure_message=original_failure.message,
                            original_failure_services=original_failure.services,
                        )
                        emit(
                            kind="audio.recovery.started", level="warning",
                            message="Tentando somente este trecho na CPU após falha max_tokens na GPU",
                            payload={
                                "item_key": item.item_key, "backend": "cpu",
                                "fallback_from": "vulkan", "attempt": 1,
                                "original_failure_code": original_failure.code,
                                "original_failure_message": original_failure.message,
                                "original_failure_stderr": original_failure.services.get("stderr_tail", ""),
                            },
                        )
                        # A CPU é determinística: com a mesma semente, o trecho que
                        # não fecha (EOC) não fecha nunca, e repetir a etapa cai no
                        # mesmo lugar. Só outra semente muda a geração.
                        recovered = False
                        cpu_outcome = None
                        for cpu_seed in (None, *self.alternate_seeds):
                            cpu_started = monotonic()
                            cpu_outcomes = self.client.synthesize_batch(
                                [self._request(item, seed=cpu_seed)], output_dir, backend="cpu"
                            )
                            cpu_elapsed = round((monotonic() - cpu_started) * 1000)
                            cpu_outcome = cpu_outcomes[0] if cpu_outcomes else None
                            if accept(item, cpu_outcome, cpu_elapsed, "cpu", seed=cpu_seed):
                                recovered = True
                                break
                            cpu_code = (
                                cpu_outcome.failure.code
                                if cpu_outcome is not None and cpu_outcome.failure is not None
                                else None
                            )
                            if cpu_code != "tts_max_tokens_before_eoc":
                                break
                        if recovered:
                            logger.info(
                                "tts_max_tokens_cpu_fallback_succeeded", item_key=item.item_key,
                                original_backend="vulkan", fallback_backend="cpu",
                                original_failure_code=original_failure.code,
                            )
                            emit(
                                kind="audio.recovery.completed", level="info",
                                message="Trecho recuperado na CPU; próximos trechos seguem na GPU",
                                payload={
                                    "item_key": item.item_key, "backend": "cpu",
                                    "fallback_from": "vulkan", "status": "succeeded",
                                    "original_failure_code": original_failure.code,
                                },
                            )
                            continue
                        cpu_failure = (
                            cpu_outcome.failure
                            if cpu_outcome is not None and cpu_outcome.failure is not None
                            else self._failure_from_findings(item.item_key, [])
                        )
                        logger.error(
                            "tts_max_tokens_cpu_fallback_failed", item_key=item.item_key,
                            original_backend="vulkan", fallback_backend="cpu",
                            original_failure_code=original_failure.code,
                            cpu_failure_code=cpu_failure.code,
                            cpu_failure_message=cpu_failure.message,
                        )
                        emit(
                            kind="audio.recovery.completed", level="error",
                            message="Trecho também falhou na CPU",
                            payload={
                                "item_key": item.item_key, "backend": "cpu",
                                "fallback_from": "vulkan", "status": "failed",
                                "original_failure_code": original_failure.code,
                                "cpu_failure_code": cpu_failure.code,
                                "cpu_failure_message": cpu_failure.message,
                                "cpu_failure_stderr": cpu_failure.services.get("stderr_tail", ""),
                            },
                        )
                        emit(kind="item.failed", level="error", message=cpu_failure.message, payload={
                            "item_key": item.item_key, "failure_code": cpu_failure.code,
                            "failure_message": cpu_failure.message, "backend": "cpu",
                            "original_backend": "vulkan",
                            "original_failure_code": original_failure.code,
                            "original_failure_stderr": original_failure.services.get("stderr_tail", ""),
                            "fallback_backend": "cpu",
                            "fallback_failure_stderr": cpu_failure.services.get("stderr_tail", ""),
                        })
                        continue
                    if failure is not None and not failure.retriable:
                        emit(kind="item.failed", level="error", message=failure.message, payload={
                            "item_key": item.item_key, "failure_code": failure.code,
                            "failure_message": failure.message,
                            "backend": self.settings.tts_backend,
                        })
                    else:
                        retry.append(item)
            for item in retry:
                started = monotonic()
                outcomes = self.client.synthesize_batch([self._request(item)], output_dir)
                outcome = outcomes[0] if outcomes else None
                elapsed = round((monotonic() - started) * 1000)
                output, findings = (
                    self._artifact_for(context, item.item_key, outcome.path, seed=self.settings.tts_seed)
                    if outcome is not None and outcome.ok and outcome.path is not None
                    else (None, [])
                )
                if output is not None:
                    paths[item.item_key], artifacts[item.item_key] = outcome.path, output
                    emit(kind="artifact.created", level="info", message="Áudio criado", payload=output.model_dump(mode="json"))
                    emit(kind="item.succeeded", level="info", message="Narração concluída", payload={"item_key": item.item_key, "duration_ms": elapsed, "backend": self.settings.tts_backend})
                    continue
                failure = outcome.failure if outcome is not None and outcome.failure is not None else self._failure_from_findings(item.item_key, findings)
                emit(kind="item.failed", level="error", message=failure.message, payload={"item_key": item.item_key, "failure_code": failure.code, "failure_message": failure.message, "backend": self.settings.tts_backend})
            self._retry_long_silences(context, plan, paths, artifacts, output_dir, emit)
        self._retry_voice_outliers(context, plan, paths, artifacts, output_dir, emit)
        return StageExecutionResult(
            current_items=len(artifacts), total_items=len(plan.items), artifacts=list(artifacts.values())
        )

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
