"""Batimento do worker: prova de vida que a API lê para o painel de serviços.

O worker não tem registro próprio no banco: o lease só existe enquanto há run
em execução, e um worker ocioso é indistinguível de um parado. O batimento é um
arquivo na mesma raiz do estado da GPU (`output_dir.parent`), regravado por uma
thread própria — `run_once` bloqueia durante uma etapa inteira (TTS leva
horas), então o laço principal não serve de relógio.

Três leituras distintas, porque pedem ações distintas:
- sem arquivo: o worker não foi iniciado ou encerrou limpo;
- PID morto: caiu sem encerrar (o arquivo sobreviveu ao dono);
- PID vivo sem batimento recente: travado.
"""
from __future__ import annotations

import json
import os
from datetime import UTC, datetime
from pathlib import Path
from threading import Event, Thread
from typing import Callable, Protocol

from forge.infrastructure.logging import get_logger
from forge.services.saude import Leitura, ServiceState

logger = get_logger(__name__)

NOME_ARQUIVO = ".worker-batimento.json"
# Batimentos perdidos antes de o worker contar como travado.
TOLERANCIA = 3


class _Inspector(Protocol):
    def is_alive(self, pid: int) -> bool: ...


def caminho_batimento(settings) -> Path:
    # Mesma raiz que `.gpu-residente.json`: API e worker já precisam concordar nela.
    return Path(settings.output_dir).parent / NOME_ARQUIVO


class BatimentoWorker:
    def __init__(
        self,
        caminho: Path,
        *,
        worker_id: str,
        intervalo: float,
        agora: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        self.caminho = Path(caminho)
        self.worker_id = worker_id
        self.intervalo = intervalo
        self._agora = agora
        self._pid = os.getpid()
        self._iniciado_em = agora()
        self._parar = Event()
        self._thread: Thread | None = None

    def bater(self) -> None:
        dados = {
            "worker_id": self.worker_id,
            "pid": self._pid,
            "iniciado_em": self._iniciado_em.isoformat(),
            "visto_em": self._agora().isoformat(),
        }
        temporario = self.caminho.with_name(self.caminho.name + ".tmp")
        try:
            self.caminho.parent.mkdir(parents=True, exist_ok=True)
            temporario.write_text(json.dumps(dados), encoding="utf-8")
            os.replace(temporario, self.caminho)
        except OSError as exc:
            # No Windows a troca falha se a API estiver lendo o arquivo nesse
            # instante. O próximo batimento corrige; o worker nunca cai por isso.
            logger.warning("Batimento do worker não gravado", erro=str(exc))

    def iniciar(self) -> None:
        self.bater()
        self._thread = Thread(target=self._laco, name="batimento-worker", daemon=True)
        self._thread.start()

    def parar(self) -> None:
        self._parar.set()
        if self._thread is not None:
            self._thread.join()
        try:
            self.caminho.unlink(missing_ok=True)
        except OSError as exc:
            logger.warning("Batimento do worker não removido", erro=str(exc))

    def _laco(self) -> None:
        while not self._parar.wait(self.intervalo):
            self.bater()

    def __enter__(self) -> BatimentoWorker:
        self.iniciar()
        return self

    def __exit__(self, *_exc: object) -> None:
        self.parar()


def ler_batimento(
    caminho: Path,
    *,
    intervalo: float,
    agora: datetime | None = None,
    inspector: _Inspector | None = None,
) -> Leitura:
    if inspector is None:
        from forge.gpu.broker import ProcessInspector

        inspector = ProcessInspector()
    agora = agora or datetime.now(UTC)
    try:
        dados = json.loads(Path(caminho).read_text(encoding="utf-8"))
        pid = int(dados["pid"])
        visto_em = datetime.fromisoformat(dados["visto_em"])
    except FileNotFoundError:
        return Leitura(ServiceState.UNAVAILABLE, "Worker não está rodando")
    except (OSError, ValueError, KeyError, TypeError):
        return Leitura(ServiceState.DEGRADED, "Batimento do worker ilegível")
    if not inspector.is_alive(pid):
        return Leitura(ServiceState.UNAVAILABLE, f"Worker parou sem encerrar (pid {pid})")
    atraso = int((agora - visto_em).total_seconds())
    if atraso > intervalo * TOLERANCIA:
        return Leitura(ServiceState.DEGRADED, f"Sem batimento há {atraso} s (pid {pid})")
    return Leitura(ServiceState.AVAILABLE, f"Ativo · pid {pid}")
