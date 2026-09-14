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

import json
import os
import subprocess
import time
import urllib.parse
from pathlib import Path
from typing import Callable

import httpx

from forge.gpu.broker import Broker, LiberacaoFalhou
from forge.infrastructure.config import Settings
from forge.infrastructure.logging import get_logger

logger = get_logger(__name__)

INTERVALO_POLL = 0.5

# Só um launcher que passou por este módulo pode autorizar encerramento. Um
# processo Python grande detectado na máquina é evidência para o operador, não
# licença para derrubar trabalho alheio.
_COMFY_LAUNCHED_PIDS: set[int] = set()

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
            # morreria com GPUOcupada.
            timeout=settings.gpu_liberacao_timeout,
        )
    except OSError as e:
        # Binário ausente ou não executável (`FileNotFoundError` é um `OSError`):
        # o LM Studio não está instalado nem no PATH, então não há modelo
        # carregado e não há o que confirmar.
        logger.warning("lms indisponível; nada a descarregar", error=str(e))
        return
    except subprocess.TimeoutExpired as e:
        # O oposto do caso acima: o comando existe e não voltou, então o LM
        # Studio muito provavelmente está NO AR e travado — com o modelo ainda
        # residente. Retornar aqui declararia a liberação feita sem confirmar
        # nada, e o próximo consumidor carregaria numa placa cheia. Cair para o
        # `_esperar` faz o estado ser conferido de verdade: modelo ainda
        # carregado vira LiberacaoFalhou no prazo.
        logger.warning("lms unload não retornou; confirmando o estado mesmo assim",
                       error=str(e))
    else:
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


def liberar_para_tts(
    settings: Settings,
    *,
    cliente: httpx.Client | None = None,
    shutdown: Callable[[], None] | None = None,
) -> None:
    """Prepara Vulkan para TTS sem assumir que o Comfy veio do broker.

    `/free` sozinho nem sempre desfaz o heap Vulkan. Só nesta transição o
    Comfy é encerrado, e somente pelo callback que conhece um PID lançado pelo
    forge; sem esse PID, registramos diagnóstico em vez de matar Python amplo.
    """
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
            logger.warning("ComfyUI não respondeu ao /free; conferindo a VRAM",
                           error=str(e))

        if _vram_livre(cliente, settings) is False:
            (shutdown or (lambda: shutdown_comfy(settings)))()
    finally:
        if fechar:
            cliente.close()


def garantir_comfy(
    settings: Settings,
    *,
    probe: Callable[[], bool] | None = None,
    launcher: Callable[..., object] | None = None,
    registrar: Callable[[int], None] | None = None,
) -> bool:
    """Sobe o ComfyUI se ele não estiver no ar.

    Necessário porque o broker encerra o ComfyUI antes do TTS: o processo segura
    o heap Vulkan mesmo depois de `/free`. Como o áudio roda antes das imagens,
    sem isto a etapa de imagem encontraria o servidor morto em todo run.
    """
    conferir = probe or (lambda: probe_comfy(settings))
    if conferir():
        return True

    lançar = launcher or subprocess.Popen
    python = settings.resolved_comfy_python
    main = Path(settings.comfy_dir) / "main.py"
    if not python.is_file() or not main.is_file():
        logger.warning(
            "ComfyUI ausente; não há o que subir",
            python=str(python),
            main=str(main),
        )
        return False

    Path(settings.comfy_output_dir).mkdir(parents=True, exist_ok=True)
    processo = lançar(
        [str(python), str(main), *settings.comfy_args_list,
         "--port", _porta_de(settings.comfy_url),
         "--disable-auto-launch",
         "--output-directory", str(settings.comfy_output_dir)],
        cwd=str(settings.comfy_dir),
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    )
    pid = int(getattr(processo, "pid", 0) or 0)
    if pid > 0:
        # Só a árvore que o forge abriu pode ser encerrada por ele depois.
        (registrar or registrar_comfy_lancado)(pid)

    if _esperar_comfy(settings, conferir):
        logger.info("ComfyUI no ar", pid=pid)
        return True
    logger.warning("ComfyUI não subiu a tempo", pid=pid, timeout=settings.comfy_boot_timeout)
    return False


def _porta_de(url: str) -> str:
    partes = urllib.parse.urlsplit(url)
    return str(partes.port or 8188)


def _esperar_comfy(settings: Settings, conferir: Callable[[], bool]) -> bool:
    limite = time.monotonic() + settings.comfy_boot_timeout
    while time.monotonic() < limite:
        if conferir():
            return True
        time.sleep(INTERVALO_POLL)
    return False


def registrar_comfy_lancado(pid: int) -> None:
    """Registra a única árvore que o forge pode encerrar automaticamente."""
    if pid <= 0:
        raise ValueError("PID do ComfyUI deve ser positivo")
    _COMFY_LAUNCHED_PIDS.add(pid)


def shutdown_comfy(
    settings: Settings,
    *,
    pid: int | None = None,
    executar: Callable[..., subprocess.CompletedProcess] = subprocess.run,
) -> bool:
    """Encerra exclusivamente uma árvore previamente lançada pelo forge."""
    alvo = pid if pid is not None else next(iter(_COMFY_LAUNCHED_PIDS), None)
    if alvo is None or alvo not in _COMFY_LAUNCHED_PIDS:
        diagnose_gpu_orphans(settings, executar=executar)
        return False
    try:
        if os.name == "nt":
            executar(
                ["taskkill", "/PID", str(alvo), "/T", "/F"],
                capture_output=True,
                text=True,
                timeout=settings.comfy_process_timeout,
            )
        else:
            os.killpg(os.getpgid(alvo), 15)
    except (OSError, subprocess.TimeoutExpired) as e:
        logger.warning("Falha ao encerrar ComfyUI lançado pelo forge",
                       pid=alvo, error=str(e))
        return False
    _COMFY_LAUNCHED_PIDS.discard(alvo)
    logger.info("ComfyUI encerrado para TTS", pid=alvo)
    return True


def diagnose_gpu_orphans(
    settings: Settings,
    *,
    executar: Callable[..., subprocess.CompletedProcess] = subprocess.run,
) -> list[dict[str, object]]:
    """Lista consumidores grandes para diagnóstico; nunca termina processos."""
    try:
        if os.name == "nt":
            proc = executar(
                [
                    "powershell", "-NoProfile", "-Command",
                    "Get-CimInstance Win32_Process | Select-Object ProcessId,CommandLine,WorkingSetSize | ConvertTo-Json -Compress",
                ],
                capture_output=True,
                text=True,
                timeout=settings.comfy_process_timeout,
            )
            registros = json.loads(proc.stdout or "[]")
            if isinstance(registros, dict):
                registros = [registros]
            candidatos = [
                {
                    "pid": item.get("ProcessId"),
                    "command_line": item.get("CommandLine") or "",
                    "working_set_mb": int(item.get("WorkingSetSize") or 0) // 1_000_000,
                }
                for item in registros
            ]
        else:
            proc = executar(
                ["ps", "-eo", "pid=,rss=,args="], capture_output=True,
                text=True, timeout=settings.comfy_process_timeout,
            )
            candidatos = []
            for linha in proc.stdout.splitlines():
                partes = linha.strip().split(maxsplit=2)
                if len(partes) == 3:
                    candidatos.append({
                        "pid": int(partes[0]),
                        "working_set_mb": int(partes[1]) // 1024,
                        "command_line": partes[2],
                    })
    except (OSError, ValueError, json.JSONDecodeError, subprocess.TimeoutExpired) as e:
        logger.warning("Diagnóstico de órfãos GPU indisponível", error=str(e))
        return []

    orfaos = [
        item for item in candidatos
        if item["working_set_mb"] >= settings.gpu_orphan_diagnostic_threshold_mb
    ]
    for item in orfaos:
        logger.warning("Possível órfão de GPU", **item)
    return orfaos


def probe_lm_studio(settings: Settings, *, cliente: httpx.Client | None = None) -> bool:
    """Serviço que responde (mesmo com erro HTTP) pode reter VRAM."""
    fechar = cliente is None
    cliente = cliente or httpx.Client(base_url=_base_lm_studio(settings), timeout=2.0)
    try:
        try:
            cliente.get("/api/v0/models")
        except FORA_DO_AR:
            return False
        except httpx.HTTPError:
            return True
        return True
    finally:
        if fechar:
            cliente.close()


def probe_comfy(settings: Settings, *, cliente: httpx.Client | None = None) -> bool:
    fechar = cliente is None
    cliente = cliente or httpx.Client(base_url=settings.comfy_url, timeout=2.0)
    try:
        try:
            cliente.get("/system_stats")
        except FORA_DO_AR:
            return False
        except httpx.HTTPError:
            return True
        return True
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
        probes={
            "llm": lambda: probe_lm_studio(settings),
            "imagem": lambda: probe_comfy(settings),
        },
        preparadores={
            "tts": lambda: liberar_para_tts(settings),
            # O áudio roda antes das imagens e pode ter encerrado o ComfyUI:
            # reclamar o slot de imagem é o ponto certo para subi-lo de novo.
            "imagem": lambda: (
                garantir_comfy(settings) if settings.comfy_auto_start else None
            ),
        },
    )
