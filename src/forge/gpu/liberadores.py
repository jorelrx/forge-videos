"""Como cada recurso devolve a VRAM, e como isso é confirmado.

Três modos de falha, tratados de forma diferente de propósito:

- serviço no ar que não confirma a liberação -> LiberacaoFalhou. Seguir em
  frente aqui é gerar imagem numa placa cheia, que é o crash que este desenho
  existe para evitar.
- serviço no ar que não RESPONDE (timeout, HTTP quebrado) -> também não é
  liberação confirmada. Um LM Studio ocupado responde com ReadTimeout, e ler
  isso como "fora do ar" é justamente declarar livre uma placa cheia.
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

# Falha de conexão: o serviço não está no ar. `ConnectTimeout` entra aqui por
# semântica, não por hierarquia — no httpx ela é subclasse de
# `TimeoutException`, mas significa "nem cheguei a abrir a conexão", que é o
# mesmo que `ConnectError`. Todo o resto de `HTTPError` (ReadTimeout,
# HTTPStatusError, ...) veio de um serviço que ACEITOU a conexão: está vivo.
FORA_DO_AR = (httpx.ConnectError, httpx.ConnectTimeout)


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
            # Sem prazo aqui, um `lms.exe` travado (já visto duas vezes, 10 e
            # 12 min sem retorno) pendura esta chamada DENTRO do lock da GPU:
            # todo outro processo do forge esperaria `gpu_lock_timeout` e
            # morreria com GPUOcupada. `FileNotFoundError` saiu do except por
            # ser subclasse de `OSError`, que já está aqui.
            timeout=settings.gpu_liberacao_timeout,
        )
    except (OSError, subprocess.TimeoutExpired) as e:
        logger.warning("lms indisponível ou travado; seguindo", error=str(e))
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
    """True liberado, False não confirmado, None serviço fora do ar."""
    try:
        resp = cliente.get("/api/v0/models")
        resp.raise_for_status()
        modelos = resp.json().get("data", [])
    except FORA_DO_AR as e:
        logger.warning("LM Studio fora do ar; nada a descarregar", error=str(e))
        return None
    except (httpx.HTTPError, ValueError) as e:
        # Aceitou a conexão e não respondeu direito: está VIVO e ocupado. Isso
        # não é liberação confirmada — seguir aqui é carregar o SDXL por cima
        # de 6 GB de Qwen.
        logger.warning("LM Studio não confirmou a liberação", error=str(e))
        return False
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
        except FORA_DO_AR as e:
            logger.warning("ComfyUI fora do ar; nada a liberar", error=str(e))
            return
        except httpx.HTTPError as e:
            # ComfyUI vivo que engasgou no /free: a confirmação abaixo é quem
            # decide, não este erro.
            logger.warning("ComfyUI não respondeu ao /free; conferindo a VRAM",
                           error=str(e))
        _esperar(settings, "imagem", lambda: _vram_livre(cliente, settings))
    finally:
        if fechar:
            cliente.close()


def _vram_livre(cliente: httpx.Client, settings: Settings) -> bool | None:
    try:
        resp = cliente.get("/system_stats")
        resp.raise_for_status()
        devices = resp.json().get("devices", [])
    except FORA_DO_AR as e:
        logger.warning("ComfyUI fora do ar; nada a conferir", error=str(e))
        return None
    except (httpx.HTTPError, ValueError) as e:
        logger.warning("ComfyUI não confirmou a liberação", error=str(e))
        return False
    if not devices:
        return None
    # `min`, não `max`: se o ComfyUI listar um segundo device respaldado por RAM
    # do sistema, o `max` sempre passaria do limiar e a confirmação viraria
    # no-op. O gargalo é o device mais apertado.
    livre = min(int(d.get("vram_free", 0)) for d in devices)
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


def montar_broker(settings: Settings, *, base: Path | None = None) -> Broker:
    """O broker real, montado a partir de Settings — contraparte do injetado."""
    sem_gpu: set[str] = set()
    if settings.tts_backend == "cpu":
        sem_gpu.add("tts")
    if settings.provider != "lm-studio":
        # LLM na nuvem não ocupa um byte da placa. Reivindicar o slot aqui
        # despejaria um TTS ou um SDXL residente por nada, e ainda serializaria
        # um run na nuvem contra o trabalho local de GPU.
        sem_gpu.add("llm")
    # Um literal relativo ("output") daria arquivos de lock diferentes para
    # processos iniciados de diretórios diferentes, e cada um acharia que é dono
    # da placa. `output_dir.parent` é a mesma raiz que `criar_run_dir` usa.
    raiz = settings.output_dir.parent if base is None else Path(base)
    return Broker(
        lock_path=raiz / ".gpu.lock",
        estado_path=raiz / ".gpu-residente.json",
        liberadores=montar_liberadores(settings),
        timeout_lock=settings.gpu_lock_timeout,
        sem_gpu=frozenset(sem_gpu),
    )
