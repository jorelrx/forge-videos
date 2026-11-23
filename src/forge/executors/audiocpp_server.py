"""Ciclo de vida do `audiocpp_server`: um processo residente por backend.

O `audiocpp_cli` é um processo por lote e paga ~8 s de carga do Higgs a cada
chamada. O servidor carrega o modelo uma vez e atende um pedido HTTP por
trecho; a saída é idêntica byte a byte à do CLI com a mesma semente (medido em
2026-11-23 na RX 580).

O contrato do servidor não tem documentação local. Ele foi descoberto num
spike e tem uma armadilha: os campos de clonagem (`voice_ref`,
`reference_text`) precisam ir no nível de cima do JSON. Dentro de `options`
são ignorados em silêncio e a resposta é 200 com uma voz não clonada. Por isso
cada subida faz uma sonda: um `voice_ref` que não existe tem de voltar 500.
"""

from __future__ import annotations

import json
import socket
import subprocess
import time
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import IO, Callable, Literal

import httpx
from filelock import FileLock

from forge.infrastructure.config import Settings
from forge.infrastructure.logging import get_logger

logger = get_logger(__name__)

Backend = Literal["vulkan", "cpu"]
MODELO_ID = "higgs"
SONDA_ESPERADA = "could not open WAV input"
INTERVALO_HEALTH = 0.5
ESPERA_ENCERRAR = 10.0
_MAX_LOG_BYTES = 4 * 1024


class ServidorIndisponivel(RuntimeError):
    """O servidor não subiu, não respondeu ou caiu."""


class ContratoServidorQuebrado(RuntimeError):
    """O servidor responde, mas não lê `voice_ref` no nível de cima."""


def caminho_registro(settings: Settings) -> Path:
    # Mesma raiz que o lock do broker usa: `output_dir` é `output/roteiros` e
    # um literal relativo daria arquivos diferentes por diretório de trabalho.
    return settings.output_dir.parent / ".tts-servidor.json"


def ler_registro(caminho: Path) -> list[dict]:
    try:
        dados = json.loads(caminho.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []
    return [d for d in dados if isinstance(d, dict)] if isinstance(dados, list) else []


def gravar_registro(caminho: Path, entradas: list[dict]) -> None:
    caminho.parent.mkdir(parents=True, exist_ok=True)
    caminho.write_text(json.dumps(entradas), encoding="utf-8")


def _alterar_registro(caminho: Path, alterar: Callable[[list[dict]], list[dict]]) -> None:
    caminho.parent.mkdir(parents=True, exist_ok=True)
    with FileLock(str(caminho) + ".lock", timeout=30):
        gravar_registro(caminho, alterar(ler_registro(caminho)))


def _porta_livre() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def _fim_do_arquivo(caminho: Path) -> str:
    try:
        bruto = caminho.read_bytes()
    except OSError:
        return ""
    return bruto[-_MAX_LOG_BYTES:].decode("utf-8", errors="replace").strip()


class ServidorTTS:
    """Context manager de um `audiocpp_server`; `url` vale enquanto vive."""

    def __init__(
        self,
        settings: Settings,
        backend: Backend,
        *,
        pasta_log: Path,
        popen: Callable[..., subprocess.Popen] = subprocess.Popen,
        http: httpx.Client | None = None,
    ) -> None:
        self.settings = settings
        self.backend = backend
        self.pasta_log = Path(pasta_log)
        self._popen = popen
        self._http = http or httpx.Client()
        self._proc: subprocess.Popen | None = None
        self._temp: TemporaryDirectory | None = None
        self._saida: IO[bytes] | None = None
        self.url = ""

    # -- ciclo de vida -------------------------------------------------------

    def __enter__(self) -> "ServidorTTS":
        self._subir()
        return self

    def __exit__(self, *exc) -> None:
        self._parar()

    def reiniciar(self) -> None:
        logger.warning("Reiniciando servidor TTS", backend=self.backend)
        self._parar()
        self._subir()

    @property
    def vivo(self) -> bool:
        return self._proc is not None and self._proc.poll() is None

    def _subir(self) -> None:
        self.pasta_log.mkdir(parents=True, exist_ok=True)
        self._temp = TemporaryDirectory(prefix="forge-tts-")
        porta = _porta_livre()
        config = Path(self._temp.name) / "server.json"
        config.write_text(json.dumps({
            "host": "127.0.0.1",
            "port": porta,
            "models": [{
                "id": MODELO_ID,
                "task": "tts",
                "family": self.settings.tts_family,
                # A chave é `path`; com `model` o servidor recusa o config.
                "path": str(self.settings.resolved_tts_model),
            }],
        }), encoding="utf-8")
        argv = [
            str(self.settings.resolved_tts_server_binary),
            "--config", str(config),
            "--backend", self.backend,
            "--no-ui",
            "--log-file", str(self.pasta_log / f".servidor-{self.backend}.log"),
        ]
        if self.backend == "cpu":
            argv += ["--threads", str(self.settings.tts_cpu_threads)]
        self._saida_path = self.pasta_log / f".servidor-{self.backend}.stdout.log"
        self._saida = self._saida_path.open("wb")
        self.url = f"http://127.0.0.1:{porta}"
        try:
            self._proc = self._popen(
                argv,
                cwd=str(self.settings.audio_generate_dir),
                shell=False,
                stdout=self._saida,
                stderr=subprocess.STDOUT,
            )
        except OSError as error:
            self._limpar_temporarios()
            raise ServidorIndisponivel(f"audiocpp_server não iniciou: {error}") from error
        _alterar_registro(
            caminho_registro(self.settings),
            lambda e: [*e, {"pid": self._proc.pid, "backend": self.backend}],
        )
        logger.info("Servidor TTS iniciando", backend=self.backend, pid=self._proc.pid, porta=porta)
        try:
            self._esperar_health()
            self._sondar_contrato()
        except BaseException:
            self._parar()
            raise
        logger.info("Servidor TTS pronto", backend=self.backend, pid=self._proc.pid)

    def _esperar_health(self) -> None:
        limite = time.monotonic() + self.settings.tts_server_start_timeout
        while True:
            if self._proc.poll() is not None:
                raise ServidorIndisponivel(
                    f"audiocpp_server ({self.backend}) saiu na subida: "
                    f"{_fim_do_arquivo(self._saida_path)}"
                )
            try:
                resposta = self._http.get(self.url + "/health", timeout=2.0)
                if resposta.status_code == 200 and int(resposta.json().get("models", 0)) >= 1:
                    return
            except (httpx.HTTPError, ValueError):
                pass
            if time.monotonic() >= limite:
                raise ServidorIndisponivel(
                    f"audiocpp_server ({self.backend}) não respondeu em "
                    f"{self.settings.tts_server_start_timeout}s"
                )
            time.sleep(INTERVALO_HEALTH)

    def _sondar_contrato(self) -> None:
        inexistente = Path(self._temp.name) / "voz-que-nao-existe.wav"
        try:
            resposta = self._http.post(
                self.url + "/v1/audio/speech",
                json={
                    "model": MODELO_ID,
                    "input": "sonda",
                    "response_format": "wav",
                    "voice_ref": str(inexistente),
                    "reference_text": self.settings.tts_reference_text,
                },
                timeout=30.0,
            )
        except httpx.HTTPError as error:
            raise ServidorIndisponivel(f"sonda de contrato falhou: {error}") from error
        if resposta.status_code == 500 and SONDA_ESPERADA in resposta.text:
            return
        raise ContratoServidorQuebrado(
            "audiocpp_server não leu voice_ref no nível de cima do pedido "
            f"(sonda respondeu {resposta.status_code})"
        )

    def _parar(self) -> None:
        proc, self._proc = self._proc, None
        if proc is not None:
            if proc.poll() is None:
                proc.terminate()
                try:
                    proc.wait(timeout=ESPERA_ENCERRAR)
                except subprocess.TimeoutExpired:
                    proc.kill()
                    proc.wait(timeout=ESPERA_ENCERRAR)
            pid = proc.pid
            _alterar_registro(
                caminho_registro(self.settings),
                lambda e: [d for d in e if d.get("pid") != pid],
            )
            logger.info("Servidor TTS encerrado", backend=self.backend, pid=pid)
        self._limpar_temporarios()

    def _limpar_temporarios(self) -> None:
        if self._saida is not None:
            self._saida.close()
            self._saida = None
        if self._temp is not None:
            self._temp.cleanup()
            self._temp = None


def montar_servidor(settings: Settings, backend: str, *, pasta_log: Path) -> ServidorTTS:
    return ServidorTTS(settings, backend, pasta_log=pasta_log)  # type: ignore[arg-type]


__all__ = [
    "ContratoServidorQuebrado",
    "ServidorIndisponivel",
    "ServidorTTS",
    "caminho_registro",
    "gravar_registro",
    "ler_registro",
    "montar_servidor",
]
