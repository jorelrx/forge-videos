"""Real service health probes with short deadlines and injectable defaults."""
from __future__ import annotations

import shutil
from dataclasses import dataclass
from enum import StrEnum
from typing import Callable

import httpx

from pydantic import BaseModel, Field
from forge.infrastructure.config import Settings, get_settings
from forge.infrastructure.logging import get_logger

logger = get_logger(__name__)


class ServiceState(StrEnum):
    AVAILABLE = "available"
    UNAVAILABLE = "unavailable"
    DEGRADED = "degraded"


class ServiceHealth(BaseModel):
    name: str
    state: ServiceState
    message: str
    latency_ms: int | None = None
    details: dict = Field(default_factory=dict)


@dataclass(frozen=True)
class HealthProbes:
    research: Callable[[], bool]
    lm_studio: Callable[[], bool]
    comfyui: Callable[[], bool]
    tts: Callable[[], bool]
    ffmpeg: Callable[[], bool]
    gpu: Callable[[], str | None | object]


class StudioHealthService:
    def __init__(self, probes: HealthProbes | None = None) -> None:
        self.probes = probes or _default_probes()

    def check_all(self) -> dict[str, ServiceHealth]:
        result: dict[str, ServiceHealth] = {}
        names = ["research", "lm_studio", "comfyui", "tts", "ffmpeg", "gpu"]
        for name in names:
            try:
                probe = getattr(self.probes, name)  # type: ignore[attr-defined]
                start = __import__("time").time()
                value = probe()
                latency = int((__import__("time").time() - start) * 1000)
                if isinstance(value, bool):
                    if value:
                        result[name] = ServiceHealth(
                            name=name, state=ServiceState.AVAILABLE, message="OK", latency_ms=latency
                        )
                    else:
                        result[name] = ServiceHealth(
                            name=name, state=ServiceState.UNAVAILABLE,
                            message=f"{name.replace('_', ' ').title()} não respondeu",
                            latency_ms=latency,
                        )
                else:
                    # gpu probe returns str | None | ILEGIVEL
                    if value is None:
                        state = ServiceState.AVAILABLE
                        msg = "Sem residente"
                    elif isinstance(value, str):
                        state = ServiceState.AVAILABLE
                        msg = f"Residente: {value}"
                    else:
                        state = ServiceState.DEGRADED
                        msg = "Estado ilegível"
                    result[name] = ServiceHealth(
                        name=name, state=state, message=msg, latency_ms=latency,
                        details={"resident": value if isinstance(value, str) else None},
                    )
            except Exception as exc:
                logger.warning("Health probe failed", probe=name, error=str(exc))
                result[name] = ServiceHealth(
                    name=name,
                    state=ServiceState.UNAVAILABLE,
                    message=f"{name.replace('_', ' ').title()} indisponível: {exc}",
                )
        return result


def _default_probes() -> HealthProbes:
    settings = get_settings()

    def research_probe() -> bool:
        try:
            resp = httpx.get(f"{settings.acervo_url}/health", timeout=2.0)
            return resp.status_code == 200
        except Exception:
            return False

    def lm_studio_probe() -> bool:
        try:
            resp = httpx.get(f"{settings.lm_studio_base_url}/models", timeout=2.0)
            return resp.status_code == 200
        except Exception:
            return False

    def comfyui_probe() -> bool:
        try:
            resp = httpx.get(f"{settings.comfy_url}/system_stats", timeout=2.0)
            return resp.status_code == 200
        except Exception:
            return False

    def tts_probe() -> bool:
        try:
            binary = settings.resolved_tts_binary
            model = settings.resolved_tts_model
            voice = settings.resolved_tts_voice_reference
            return binary.exists() and model.exists() and voice.exists()
        except Exception:
            return False

    def ffmpeg_probe() -> bool:
        try:
            return shutil.which("ffmpeg") is not None and shutil.which("ffprobe") is not None
        except Exception:
            return False

    def gpu_probe() -> str | None | object:
        try:
            from forge.gpu.broker import Broker

            # Precisa ser o MESMO estado que `montar_broker` grava: com um
            # caminho temporário próprio o probe nunca via residente nenhum e o
            # painel anunciava "Sem residente" com o LLM carregado na placa.
            raiz = settings.output_dir.parent
            broker = Broker(
                lock_path=raiz / ".gpu.lock",
                estado_path=raiz / ".gpu-residente.json",
                liberadores={},
                timeout_lock=settings.gpu_lock_timeout,
            )
            # `residente_ativo` porque o estado sobrevive ao filho que o gravou:
            # um PID morto não pode aparecer como modelo residente.
            return broker.residente_ativo()
        except Exception:
            return None

    return HealthProbes(
        research=research_probe,
        lm_studio=lm_studio_probe,
        comfyui=comfyui_probe,
        tts=tts_probe,
        ffmpeg=ffmpeg_probe,
        gpu=gpu_probe,
    )
