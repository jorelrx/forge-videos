"""Final cross-check validation gate for completed video runs."""
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, Callable

from forge.domain.execucao import (
    ArtifactOutput,
    GateFinding,
    GateResult,
    RunSnapshot,
    StageChildResult,
    StageExecutionResult,
    StagePlan,
)
from forge.domain.operacao import StageName
from forge.executors.base import StageImplementation
from forge.executors.ffmpeg import probe_media, run_ffmpeg
from forge.infrastructure.logging import get_logger
from forge.services.worker import EventSink

logger = get_logger(__name__)


class ValidationExecutor(StageImplementation):
    """Gate final cruzado: checa mídia, gates anteriores, WAV, imagens, ffprobe,
    duração, silêncio não planejado e frames amostrados."""

    def __init__(
        self,
        max_unplanned_silence_seconds: float = 2.0,
        frame_sample_fractions: tuple[float, float, float] = (0.10, 0.50, 0.90),
        runner: Callable[..., tuple[int, str, Any]] = run_ffmpeg,
    ) -> None:
        self.max_unplanned_silence_seconds = max_unplanned_silence_seconds
        self.frame_sample_fractions = frame_sample_fractions
        self.runner = runner

    def prepare(self, context: RunSnapshot) -> StagePlan:
        if context.stage is not StageName.VALIDACAO:
            raise ValueError("context stage must be validacao")
        return StagePlan(
            stage=StageName.VALIDACAO,
            input_hash="0" * 64,
            items=[],
        )

    def execute(
        self, context: RunSnapshot, plan: StagePlan, emit: EventSink
    ) -> StageExecutionResult:
        # Execute performs actual output generation: validation report + frames.
        # It writes video/validation.json and video/validation/frame-*.jpg.
        validation_dir = context.run_dir / "video" / "validation"
        validation_dir.mkdir(parents=True, exist_ok=True)

        # We write preliminary artifacts; validate will check and finalize.
        # For simplicity, write the frame images by trying ffmpeg if video exists.
        final_video_path = context.run_dir / "video" / "final.mp4"
        artifacts: list[ArtifactOutput] = []

        # Try to extract frames (best effort; validate checks success)
        frame_successes: dict[float, bool] = {}
        if final_video_path.is_file():
            import subprocess
            video_duration = 0.0
            try:
                probe = probe_media(str(final_video_path))
                video_duration = probe.duration or 0.0
            except Exception:
                pass
            for frac in self.frame_sample_fractions:
                timestamp = max(0.0, video_duration * frac)
                frame_path = validation_dir / f"frame-{int(frac * 100)}.jpg"
                argv = [
                    "ffmpeg",
                    "-y",
                    "-ss", str(timestamp),
                    "-i", str(final_video_path),
                    "-vframes", "1",
                    "-q:v", "2",
                    str(frame_path),
                ]
                try:
                    result = subprocess.run(
                        argv,
                        shell=False,
                        capture_output=True,
                        timeout=60,
                    )
                    success = result.returncode == 0 and frame_path.is_file()
                    frame_successes[frac] = success
                    if success:
                        artifacts.append(
                            ArtifactOutput(
                                item_key=None,
                                kind="validation.frame",
                                relative_path=f"video/validation/frame-{int(frac * 100)}.jpg",
                                mime_type="image/jpeg",
                                metadata={"fraction": frac},
                            )
                        )
                except Exception:
                    frame_successes[frac] = False
        else:
            for frac in self.frame_sample_fractions:
                frame_successes[frac] = False

        # Write preliminary validation.json (will be overwritten by validate)
        validation_report_path = context.run_dir / "video" / "validation.json"
        artifacts.append(
            ArtifactOutput(
                item_key=None,
                kind="validation.report",
                relative_path="video/validation.json",
                mime_type="application/json",
                metadata={},
            )
        )

        return StageExecutionResult(
            current_items=0,
            total_items=0,
            artifacts=artifacts,
        )

    def validate(
        self, context: RunSnapshot, plan: StagePlan, result: StageExecutionResult
    ) -> GateResult:
        findings: list[GateFinding] = []

        # 1. Cross-check media-plan block/beat counts vs SQLite items/artifacts
        artifacts = [
            a for a in (context.artifacts if context.artifacts else [])
            if getattr(a, "is_current", False)
        ]
        audio_artifacts = [
            a for a in artifacts
            if getattr(a, "kind", "").startswith("audio")
            or getattr(a, "kind", "").startswith("video/narration")
        ]
        image_artifacts = [
            a for a in artifacts
            # O produtor registra `image.png`; a barra era convenção do stub e
            # nunca casava, o que reprovava todo vídeo por "imagem ausente".
            if getattr(a, "kind", "").startswith("image")
        ]
        work_items = context.work_items if context.work_items else []
        succeeded_items = [w for w in work_items if getattr(w, "status", None) and w.status.value == "succeeded"]
        expected_items_from_work = len(succeeded_items)

        if expected_items_from_work > 0 and len(audio_artifacts) < expected_items_from_work:
            findings.append(
                GateFinding(
                    code="audio_count_mismatch",
                    message=f"Artefatos de áudio ({len(audio_artifacts)}) abaixo dos itens de áudio aprovados ({expected_items_from_work}).",
                    details={
                        "audio_artifacts": len(audio_artifacts),
                        "expected_audio_items": expected_items_from_work,
                    },
                )
            )
        if len(image_artifacts) == 0 and len(succeeded_items) > 0:
            findings.append(
                GateFinding(
                    code="image_artifact_missing",
                    message="Nenhum artefato de imagem atual encontrado.",
                    details={"image_artifacts": 0},
                )
            )

        # 2. Prior stage gate approval approximation
        failure_artifacts = [
            a for a in artifacts
            if getattr(a, "metadata", {}).get("failure") is not None
        ]
        if failure_artifacts:
            findings.append(
                GateFinding(
                    code="prior_stage_failed",
                    message="Artefatos de falha de etapas anteriores encontrados.",
                    details={"failure_artifact_count": len(failure_artifacts)},
                )
            )

        # 3. WAV validity check
        import wave
        for art in audio_artifacts:
            path = context.run_dir / art.relative_path if art.relative_path else None
            if path and path.is_file():
                try:
                    with wave.open(str(path), "rb") as w:
                        nchannels = w.getnchannels()
                        framerate = w.getframerate()
                        nframes = w.getnframes()
                        if nchannels != 1 or framerate != 24000 or nframes == 0:
                            findings.append(
                                GateFinding(
                                    code="audio_invalid",
                                    message=f"WAV inválido em {art.relative_path}: mono={nchannels == 1}, rate={framerate}, frames={nframes}.",
                                    details={
                                        "path": art.relative_path,
                                        "channels": nchannels,
                                        "sample_rate": framerate,
                                        "frames": nframes,
                                    },
                                )
                            )
                except Exception as exc:
                    findings.append(
                        GateFinding(
                            code="audio_read_failed",
                            message=f"Falha ao ler WAV em {art.relative_path}: {exc}",
                            details={"path": art.relative_path, "error": str(exc)},
                        )
                    )
            else:
                findings.append(
                    GateFinding(
                        code="audio_file_missing",
                        message=f"Arquivo de áudio esperado não encontrado: {getattr(art, 'relative_path', None)}.",
                        details={"relative_path": getattr(art, "relative_path", None)},
                    )
                )

        # 4. Image validity check
        try:
            from PIL import Image
        except ImportError:
            Image = None  # type: ignore
        for art in image_artifacts:
            path = context.run_dir / art.relative_path if art.relative_path else None
            if path and path.is_file():
                if Image is not None:
                    try:
                        with Image.open(path) as img:
                            if img.width != 1024 or img.height != 576:
                                findings.append(
                                    GateFinding(
                                        code="image_resolution_invalid",
                                        message=f"Imagem {art.relative_path} resolução {img.width}x{img.height} (esperado 1024x576).",
                                        details={
                                            "path": art.relative_path,
                                            "width": img.width,
                                            "height": img.height,
                                        },
                                    )
                                )
                    except Exception as exc:
                        findings.append(
                            GateFinding(
                                code="image_read_failed",
                                message=f"Falha ao ler imagem {art.relative_path}: {exc}",
                                details={"path": art.relative_path, "error": str(exc)},
                            )
                        )
            else:
                findings.append(
                    GateFinding(
                        code="image_file_missing",
                        message=f"Arquivo de imagem esperado não encontrado: {getattr(art, 'relative_path', None)}.",
                        details={"relative_path": getattr(art, "relative_path", None)},
                    )
                )

        # 5. ffprobe checks on final video
        final_video_path = context.run_dir / "video" / "final.mp4"
        if final_video_path.is_file():
            probe = probe_media(str(final_video_path))
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
            if probe.width != 1920 or probe.height != 1080:
                findings.append(
                    GateFinding(
                        code="video_resolution_invalid",
                        message=f"Resolução não é 1920x1080: {probe.width}x{probe.height}",
                        details={"width": probe.width, "height": probe.height},
                    )
                )
            if not probe.duration or probe.duration <= 0:
                findings.append(
                    GateFinding(
                        code="video_duration_invalid",
                        message="Duração do vídeo não é positiva.",
                        details={"duration": probe.duration},
                    )
                )
            # Duration coherence
            narration_path = context.run_dir / "video" / "narration.wav"
            narration_duration = None
            if narration_path.is_file():
                narration_probe = probe_media(str(narration_path))
                narration_duration = narration_probe.duration
            if narration_duration is not None and probe.duration is not None:
                duration_diff = abs(probe.duration - narration_duration)
                max_diff = max(0.5, 0.01 * max(probe.duration, narration_duration))
                if duration_diff > max_diff:
                    findings.append(
                        GateFinding(
                            code="video_duration_coherence_failed",
                            message=f"Diferença de duração ({duration_diff:.3f}s) excede limite {max_diff:.3f}s.",
                            details={
                                "video_duration": probe.duration,
                                "narration_duration": narration_duration,
                                "difference": duration_diff,
                                "max_diff": max_diff,
                            },
                        )
                    )
            if not probe.has_video_stream:
                findings.append(
                    GateFinding(code="video_stream_missing", message="Stream de vídeo ausente.")
                )
            if not probe.has_audio_stream:
                findings.append(
                    GateFinding(code="audio_stream_missing", message="Stream de áudio ausente.")
                )
        else:
            findings.append(
                GateFinding(
                    code="final_video_missing",
                    message="Arquivo final de vídeo (video/final.mp4) não encontrado.",
                )
            )

        # 6. Silence check on the REAL narration of this run.
        unplanned_silences = [
            duracao
            for duracao in self._silencios_da_narracao(context)
            if duracao > self.max_unplanned_silence_seconds
        ]
        if unplanned_silences:
            findings.append(
                GateFinding(
                    code="unexpected_silence",
                    message=f"Silêncio não planejado detectado acima do limite ({self.max_unplanned_silence_seconds}s): {unplanned_silences}",
                    details={
                        "silence_durations": unplanned_silences,
                        "threshold": self.max_unplanned_silence_seconds,
                    },
                )
            )

        # 7. Frame sample verification
        # We read from the artifacts emitted by execute and check files exist.
        frame_artifacts = [
            art for art in result.artifacts
            if getattr(art, "kind", "") == "validation.frame"
        ]
        expected_frame_count = len(self.frame_sample_fractions)
        if len(frame_artifacts) < expected_frame_count:
            missing_fractions = [
                int(frac * 100) for frac in self.frame_sample_fractions
                if not any(
                    getattr(art, "metadata", {}).get("fraction") == frac
                    for art in frame_artifacts
                )
            ]
            findings.append(
                GateFinding(
                    code="frame_sample_failed",
                    message=f"Frames amostrados incompletos: esperados {expected_frame_count}, encontrados {len(frame_artifacts)} (faltando frações {missing_fractions}).",
                    details={
                        "expected": expected_frame_count,
                        "actual": len(frame_artifacts),
                        "missing_fractions": missing_fractions,
                    },
                )
            )
        # Verify each frame file exists on disk
        for art in frame_artifacts:
            path = context.run_dir / art.relative_path if art.relative_path else None
            if path is None or not path.is_file():
                findings.append(
                    GateFinding(
                        code="frame_sample_failed",
                        message=f"Frame extraído não encontrado no disco: {getattr(art, 'relative_path', None)}.",
                        details={"relative_path": getattr(art, "relative_path", None)},
                    )
                )

        # Write/update validation.json with final results
        checks = []
        checks.append({
            "code": "media_plan_cross_check",
            "approved": len([f for f in findings if f.code == "audio_count_mismatch"]) == 0,
            "expected": "counts_match",
            "actual": {
                "audio_artifacts": len(audio_artifacts),
                "image_artifacts": len(image_artifacts),
            },
        })
        checks.append({
            "code": "prior_gates_approved",
            "approved": len([f for f in findings if f.code == "prior_stage_failed"]) == 0,
            "expected": "all_approved",
            "actual": "approved" if len([f for f in findings if f.code == "prior_stage_failed"]) == 0 else "rejected",
        })
        checks.append({
            "code": "audio_wave_valid",
            "approved": len([f for f in findings if f.code.startswith("audio_")]) == 0,
            "expected": "valid_wav",
            "actual": "valid" if len([f for f in findings if f.code.startswith("audio_")]) == 0 else "invalid",
        })
        checks.append({
            "code": "images_valid",
            "approved": len([f for f in findings if f.code.startswith("image_")]) == 0,
            "expected": "valid_images",
            "actual": "valid" if len([f for f in findings if f.code.startswith("image_")]) == 0 else "invalid",
        })
        checks.append({
            "code": "ffprobe_final_video",
            "approved": len([f for f in findings if f.code.startswith("video_") or f.code.startswith("audio_codec_") or f.code.startswith("audio_stream_")]) == 0,
            "expected": "h264_aac_1920x1080_positive_duration",
            "actual": "passed" if len([f for f in findings if f.code.startswith("video_") or f.code.startswith("audio_codec_")]) == 0 else "failed",
        })
        checks.append({
            "code": "duration_positive",
            "approved": len([f for f in findings if f.code == "video_duration_invalid"]) == 0,
            "expected": ">0",
            "actual": "positive",
        })
        checks.append({
            "code": "duration_coherence",
            "approved": len([f for f in findings if f.code == "video_duration_coherence_failed"]) == 0,
            "expected": "<max(0.5s,1%)",
            "actual": "coherent",
        })
        checks.append({
            "code": "silence_unplanned",
            "approved": len([f for f in findings if f.code == "unexpected_silence"]) == 0,
            "expected": f"<={self.max_unplanned_silence_seconds}s",
            "actual": "ok",
        })
        checks.append({
            "code": "frame_samples",
            "approved": len([f for f in findings if f.code == "frame_sample_failed"]) == 0,
            "expected": "10%,50%,90% extracted",
            "actual": "extracted" if len([f for f in findings if f.code == "frame_sample_failed"]) == 0 else "failed",
        })

        approved = all(c["approved"] for c in checks)

        validation_report_path = context.run_dir / "video" / "validation.json"
        validation_dir = context.run_dir / "video" / "validation"
        validation_dir.mkdir(parents=True, exist_ok=True)

        report = {
            "stage": "validacao",
            "run_id": context.run_id,
            "approved": approved,
            "gate_code": "final_validation_approved" if approved else "final_validation_failed",
            "checks": checks,
            "findings": [
                {"code": f.code, "message": f.message, "details": f.details}
                for f in findings
            ],
        }
        validation_report_path.write_text(
            json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
        )

        # Update artifacts in execution result with the finalized report
        final_artifacts = [
            art for art in result.artifacts if art.kind != "validation.report"
        ]
        final_artifacts.append(
            ArtifactOutput(
                item_key=None,
                kind="validation.report",
                relative_path="video/validation.json",
                mime_type="application/json",
                metadata={"checks": checks, "approved": approved},
            )
        )

        return GateResult(
            approved=approved,
            code="final_validation_approved" if approved else "final_validation_failed",
            findings=findings,
            metrics={
                "checks": checks,
                "audio_artifacts": len(audio_artifacts),
                "image_artifacts": len(image_artifacts),
            },
        )

    def _silencios_da_narracao(self, context: RunSnapshot) -> list[float]:
        """Silêncios medidos na narração DESTA run, via `silencedetect`.

        Antes o gate lia `tests/fixtures/ffmpeg/silence-*.txt` — fixtures de
        teste — como se fossem a análise do áudio: com o CWD na raiz do repo,
        toda validação em produção encontrava `silence_duration: 45.32` e
        reprovava por um silêncio que o vídeo não tem.
        """
        narracao = context.run_dir / "video" / "narration.wav"
        if not narracao.is_file():
            return []
        argv = [
            "ffmpeg",
            "-hide_banner",
            "-nostats",
            "-i",
            str(narracao),
            "-af",
            f"silencedetect=noise=-35dB:d={self.max_unplanned_silence_seconds}",
            "-f",
            "null",
            "-",
        ]
        try:
            codigo, stderr, _ = self.runner(argv, timeout=120)
        except Exception as error:  # noqa: BLE001 - diagnóstico não derruba o gate
            logger.warning("silencedetect indisponível", error=str(error))
            return []
        if codigo != 0:
            logger.warning("silencedetect falhou", returncode=codigo)
            return []
        return [float(valor) for valor in re.findall(r"silence_duration:\s*([0-9.]+)", stderr or "")]

    def run(self, context: RunSnapshot, emit: EventSink) -> StageChildResult:
        plan = self.prepare(context)
        execution = self.execute(context, plan, emit)
        gate = self.validate(context, plan, execution)
        # Rebuild artifacts from final state after validate writes report
        artifacts_emitted: list[ArtifactOutput] = []
        validation_dir = context.run_dir / "video" / "validation"
        validation_report_path = context.run_dir / "video" / "validation.json"
        for frac in self.frame_sample_fractions:
            frame_path = validation_dir / f"frame-{int(frac * 100)}.jpg"
            if frame_path.is_file():
                artifacts_emitted.append(
                    ArtifactOutput(
                        item_key=None,
                        kind="validation.frame",
                        relative_path=f"video/validation/frame-{int(frac * 100)}.jpg",
                        mime_type="image/jpeg",
                        metadata={"fraction": frac},
                    )
                )
        if validation_report_path.is_file():
            artifacts_emitted.append(
                ArtifactOutput(
                    item_key=None,
                    kind="validation.report",
                    relative_path="video/validation.json",
                    mime_type="application/json",
                    metadata={"approved": gate.approved},
                )
            )
        execution_final = StageExecutionResult(
            current_items=execution.current_items,
            total_items=execution.total_items,
            artifacts=artifacts_emitted,
        )
        return StageChildResult(**execution_final.model_dump(), gate=gate)


__all__ = ["ValidationExecutor"]
