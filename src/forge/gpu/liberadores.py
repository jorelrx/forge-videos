"""Como cada recurso devolve a VRAM, e como isso é confirmado.

Dois modos de falha, tratados de forma diferente de propósito:

- serviço no ar que não confirma a liberação -> LiberacaoFalhou. Seguir em
  frente aqui é gerar imagem numa placa cheia, que é o crash que este desenho
  existe para evitar.
- serviço fora do ar ou binário ausente -> aviso e segue. Não há o que liberar
  num serviço que não está rodando.
"""

from __future__ import annotations

import subprocess
import time
from pathlib import Path
from typing import Callable

import httpx

from forge.gpu.broker import Broker, LiberacaoFalhou
from forge.infrastructure.config import Settings
from forge.infrastructure.logging import get_logger

logger = get_logger(__name__)

INTERVALO_POLL = 0.5


def _base_lm_studio(settings: Settings) -> str:
    """`http://host/v1` -> `http://host`. A API de estado não fica sob /v1."""
    return settings.lm_studio_base_url.rstrip("/").removesuffix("/v1")


def liberar_llm(
    settings: Settings,
    *,
    executar: Callable[..., subprocess.CompletedProcess] = subprocess.run,
    cliente: httpx.Client | None = None,
) -> None:
    try:
        proc = executar(
            [settings.lms_bin, "unload", "--all"],
            capture_output=True, text=True, encoding="utf-8", errors="replace",
        )
    except (FileNotFoundError, OSError) as e:
        logger.warning("lms indisponível; nada a descarregar", error=str(e))
        return
    if proc.returncode != 0:
        logger.warning("lms unload falhou", returncode=proc.returncode)

    fechar = cliente is None
    cliente = cliente or httpx.Client(base_url=_base_lm_studio(settings), timeout=10.0)
    try:
        _esperar(
            settings,
            "llm",
            lambda: _nenhum_carregado(cliente),
        )
    finally:
        if fechar:
            cliente.close()


def _nenhum_carregado(cliente: httpx.Client) -> bool | None:
    """True liberado, False ainda carregado, None serviço fora do ar."""
    try:
        resp = cliente.get("/api/v0/models")
        resp.raise_for_status()
        modelos = resp.json().get("data", [])
    except (httpx.HTTPError, ValueError) as e:
        logger.warning("LM Studio não respondeu; seguindo", error=str(e))
        return None
    return all(m.get("state") != "loaded" for m in modelos)


def liberar_imagem(settings: Settings, *, cliente: httpx.Client | None = None) -> None:
    fechar = cliente is None
    cliente = cliente or httpx.Client(base_url=settings.comfy_url, timeout=10.0)
    try:
        try:
            resp = cliente.post(
                "/free", json={"unload_models": True, "free_memory": True}
            )
            resp.raise_for_status()
        except httpx.HTTPError as e:
            logger.warning("ComfyUI não respondeu ao /free; seguindo", error=str(e))
            return
        _esperar(settings, "imagem", lambda: _vram_livre(cliente, settings))
    finally:
        if fechar:
            cliente.close()


def _vram_livre(cliente: httpx.Client, settings: Settings) -> bool | None:
    try:
        resp = cliente.get("/system_stats")
        resp.raise_for_status()
        devices = resp.json().get("devices", [])
    except (httpx.HTTPError, ValueError) as e:
        logger.warning("ComfyUI não respondeu ao /system_stats", error=str(e))
        return None
    if not devices:
        return None
    livre = max(int(d.get("vram_free", 0)) for d in devices)
    logger.debug("VRAM livre", livre=livre, minimo=settings.comfy_vram_livre_min)
    return livre >= settings.comfy_vram_livre_min


def liberar_tts(settings: Settings) -> None:
    """O audiocpp_cli é um processo por trecho: sai e devolve a VRAM sozinho."""
    return None


def _esperar(settings: Settings, recurso: str, checar: Callable[[], bool | None]) -> None:
    limite = time.monotonic() + settings.gpu_liberacao_timeout
    while True:
        resultado = checar()
        if resultado is None:  # serviço fora do ar: não há o que confirmar
            return
        if resultado:
            logger.info("GPU liberada", recurso=recurso)
            return
        if time.monotonic() >= limite:
            raise LiberacaoFalhou(
                f"{recurso} não liberou a VRAM em {settings.gpu_liberacao_timeout}s"
            )
        time.sleep(INTERVALO_POLL)


def montar_liberadores(settings: Settings) -> dict[str, Callable[[], None]]:
    return {
        "llm": lambda: liberar_llm(settings),
        "imagem": lambda: liberar_imagem(settings),
        "tts": lambda: liberar_tts(settings),
    }


def montar_broker(settings: Settings, *, base: Path = Path("output")) -> Broker:
    """O broker real, montado a partir de Settings — contraparte do injetado."""
    sem_gpu = frozenset({"tts"}) if settings.tts_backend == "cpu" else frozenset()
    return Broker(
        lock_path=base / ".gpu.lock",
        estado_path=base / ".gpu-residente.json",
        liberadores=montar_liberadores(settings),
        timeout_lock=settings.gpu_lock_timeout,
        sem_gpu=sem_gpu,
    )
