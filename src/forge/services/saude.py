"""Real service health probes with short deadlines and injectable defaults."""
from __future__ import annotations

import shutil
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from enum import StrEnum
from typing import Callable, Mapping

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
    # Habilitado: a configuração atual usa o serviço em alguma etapa (`usos`).
    enabled: bool = True
    usos: list[str] = Field(default_factory=list)


@dataclass(frozen=True)
class Leitura:
    """Resultado de uma sonda com mensagem própria (ex.: "Sem chave")."""

    state: ServiceState
    message: str


Sonda = Callable[[], "bool | Leitura"]

# Ordem de exibição: pipeline primeiro, depois provedores de modelo.
ORDEM = (
    "worker", "research", "lm_studio", "comfyui", "tts", "ffmpeg", "gpu",
    "codex", "claude", "anthropic", "openai", "youtube",
)

# Provider de texto (config) -> serviço sondado.
SERVICO_DO_PROVIDER = {
    "anthropic": "anthropic",
    "openai": "openai",
    "lm-studio": "lm_studio",
    "codex": "codex",
    "claude": "claude",
}
SERVICO_DE_IMAGEM = {"comfyui": "comfyui", "codex": "codex"}
CONSUMIDORES_GPU = ("lm_studio", "comfyui", "tts")


def usos_dos_servicos(settings: Settings) -> dict[str, tuple[str, ...]]:
    """Etapas em que cada serviço entra com a configuração atual.

    Habilitado é ter algum uso aqui; disponível é a sonda responder. Os dois
    eixos são independentes: um serviço fora de uso também é sondado, para o
    painel mostrar se trocar o provider funcionaria.
    """
    usos: dict[str, list[str]] = {
        "worker": ["execução da fila"],
        "research": ["pesquisa"],
        "tts": ["narração"],
        "ffmpeg": ["montagem"],
        "youtube": ["publicação"],
    }
    escritor = SERVICO_DO_PROVIDER[settings.provider]
    revisor = SERVICO_DO_PROVIDER[settings.review_provider or settings.provider]
    usos.setdefault(escritor, []).append("roteiro")
    usos.setdefault(revisor, []).append("revisão")
    usos.setdefault(SERVICO_DE_IMAGEM[settings.image_provider], []).append("imagens")
    if any(nome in usos for nome in CONSUMIDORES_GPU):
        usos["gpu"] = ["residente"]
    return {nome: tuple(lista) for nome, lista in usos.items()}


@dataclass(frozen=True)
class HealthProbes:
    research: Sonda
    lm_studio: Sonda
    comfyui: Sonda
    tts: Sonda
    ffmpeg: Sonda
    gpu: Callable[[], str | None | object]
    codex: Sonda | None = None
    claude: Sonda | None = None
    anthropic: Sonda | None = None
    openai: Sonda | None = None
    youtube: Sonda | None = None
    worker: Sonda | None = None
    # None: sem configuração conhecida, todo serviço sondado conta como habilitado.
    usos: Mapping[str, tuple[str, ...]] | None = None


# Leitura de serviço fora de uso vale por este tempo. O painel consulta a cada
# lote de eventos; sem isso, um LM Studio desligado custava ~4 s de timeout e o
# Claude/Codex abriam um processo de CLI por consulta sem ninguém usá-los.
TTL_FORA_DE_USO = 60.0


class StudioHealthService:
    def __init__(
        self,
        probes: HealthProbes | None = None,
        *,
        relogio: Callable[[], float] = time.monotonic,
    ) -> None:
        self.probes = probes or _default_probes()
        self._relogio = relogio
        self._cache: dict[str, tuple[float, ServiceHealth]] = {}
        self._trava = threading.Lock()

    def check_all(self) -> dict[str, ServiceHealth]:
        usos = self.probes.usos
        names = [name for name in ORDEM if getattr(self.probes, name) is not None]
        habilitado = {name: usos is None or bool(usos.get(name)) for name in names}
        agora = self._relogio()
        with self._trava:
            reuso = {
                name: item for name, (lido_em, item) in self._cache.items()
                if not habilitado.get(name, True) and agora - lido_em < TTL_FORA_DE_USO
            }
        pendentes = [name for name in names if name not in reuso]
        # Em paralelo: com todos os serviços sondados, timeouts de 2 s em série
        # passariam de 10 s por consulta do painel.
        lidos: dict[str, ServiceHealth] = dict(reuso)
        if pendentes:
            with ThreadPoolExecutor(max_workers=len(pendentes), thread_name_prefix="saude") as pool:
                for item in pool.map(self._ler, pendentes):
                    lidos[item.name] = item
            with self._trava:
                for name in pendentes:
                    if not habilitado[name]:
                        self._cache[name] = (agora, lidos[name])
        result: dict[str, ServiceHealth] = {}
        for name in names:
            item = lidos[name].model_copy()
            if usos is not None:
                item.usos = list(usos.get(name, ()))
                item.enabled = bool(item.usos)
            result[name] = item
        return result

    def _ler(self, name: str) -> ServiceHealth:
        try:
            probe = getattr(self.probes, name)
            start = time.perf_counter()
            value = probe()
            latency = int((time.perf_counter() - start) * 1000)
        except Exception as exc:
            logger.warning("Health probe failed", probe=name, error=str(exc))
            return ServiceHealth(
                name=name,
                state=ServiceState.UNAVAILABLE,
                message=f"{name.replace('_', ' ').title()} indisponível: {exc}",
            )
        if isinstance(value, Leitura):
            return ServiceHealth(name=name, state=value.state, message=value.message, latency_ms=latency)
        if isinstance(value, bool):
            if value:
                return ServiceHealth(name=name, state=ServiceState.AVAILABLE, message="OK", latency_ms=latency)
            return ServiceHealth(
                name=name, state=ServiceState.UNAVAILABLE,
                message=f"{name.replace('_', ' ').title()} não respondeu",
                latency_ms=latency,
            )
        # gpu probe returns str | None | ILEGIVEL
        if value is None:
            state, msg = ServiceState.AVAILABLE, "Sem residente"
        elif isinstance(value, str):
            state, msg = ServiceState.AVAILABLE, f"Residente: {value}"
        else:
            state, msg = ServiceState.DEGRADED, "Estado ilegível"
        return ServiceHealth(
            name=name, state=state, message=msg, latency_ms=latency,
            details={"resident": value if isinstance(value, str) else None},
        )


def _default_probes(settings=None) -> HealthProbes:
    settings = settings or get_settings()

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
            binary = settings.resolved_tts_server_binary
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

    def codex_probe() -> bool:
        from forge.services.codex import CodexCLI, CodexError

        try:
            if settings.codex_transport == "native":
                from forge.services.codex_auth import OAuthCredentials
                OAuthCredentials(settings.codex_auth_file).access_token()
            else:
                CodexCLI(settings).check_auth()
            return True
        except CodexError:
            return False

    def claude_probe() -> bool:
        # Só o login declarado: o painel consulta em laço, e uma chamada de
        # modelo por consulta gastaria a cota. A prova real fica no preflight.
        from forge.services.claude_cli import ClaudeCLI, ClaudeError

        try:
            ClaudeCLI(settings).check_auth()
            return True
        except ClaudeError:
            return False

    def chave_probe(provider: str, variavel: str) -> Callable[[], Leitura]:
        # Só a presença da chave: sondar a API a cada consulta do painel
        # gastaria cota. A chave genérica (`FORGE_API_KEY`) é do provider
        # principal e nunca serve a outro (ver `Settings.resolved_api_key`).
        def probe() -> Leitura:
            especifica = getattr(settings, f"{provider}_api_key")
            generica = settings.api_key if settings.provider == provider else None
            if especifica or generica:
                return Leitura(ServiceState.AVAILABLE, "Chave configurada (não sondada)")
            return Leitura(ServiceState.UNAVAILABLE, f"Sem {variavel}")

        return probe

    def youtube_probe() -> Leitura:
        from forge.services.youtube_canais import CanaisYouTube

        canais = CanaisYouTube(settings)
        if not canais.cliente_configurado():
            return Leitura(ServiceState.UNAVAILABLE, "Cliente OAuth do Google não configurado")
        vinculados = len(canais.listar())
        if vinculados == 0:
            return Leitura(ServiceState.DEGRADED, "Nenhum canal vinculado")
        return Leitura(
            ServiceState.AVAILABLE,
            "1 canal vinculado" if vinculados == 1 else f"{vinculados} canais vinculados",
        )

    def worker_probe() -> Leitura:
        from forge.services.batimento_worker import caminho_batimento, ler_batimento

        return ler_batimento(caminho_batimento(settings), intervalo=settings.worker_heartbeat_seconds)

    return HealthProbes(
        research=research_probe,
        lm_studio=lm_studio_probe,
        comfyui=comfyui_probe,
        tts=tts_probe,
        ffmpeg=ffmpeg_probe,
        gpu=gpu_probe,
        codex=codex_probe,
        claude=claude_probe,
        anthropic=chave_probe("anthropic", "FORGE_ANTHROPIC_API_KEY"),
        openai=chave_probe("openai", "FORGE_OPENAI_API_KEY"),
        youtube=youtube_probe,
        worker=worker_probe,
        usos=usos_dos_servicos(settings),
    )
