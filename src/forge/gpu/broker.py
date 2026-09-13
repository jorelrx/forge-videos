"""Slot exclusivo de GPU.

Uma RX 580 de 8 GB, três consumidores que não cabem juntos: o LLM do LM Studio,
o TTS via Vulkan e o SDXL do ComfyUI. O broker garante um residente por vez e
descarrega o anterior ao trocar.

A troca acontece por FASE, não por item: trocar a cada item pagaria um reload de
modelo por item. Quem entra e sai do mesmo recurso em sequência não paga nada.
"""

from __future__ import annotations

import json
import os
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import Callable, Iterator, Literal

from filelock import FileLock, Timeout
from pydantic import BaseModel, Field, ValidationError

from forge.infrastructure.logging import get_logger

logger = get_logger(__name__)

Recurso = Literal["llm", "tts", "imagem"]


class GPUState(BaseModel):
    """Reivindicação persistida do consumidor que carregou a GPU."""

    recurso: Recurso
    pid: int = Field(gt=0)
    claimed_at: datetime


class ProcessInspector:
    """Consulta conservadora de processo: dúvida nunca vira PID morto."""

    def is_alive(self, pid: int) -> bool:
        try:
            if os.name == "nt":
                return self._is_alive_windows(pid)
            os.kill(pid, 0)
        except ProcessLookupError:
            return False
        except Exception:
            # Falha de permissão, API indisponível ou diagnóstico incompleto não
            # autoriza roubar um claim que ainda pode ser válido.
            return True
        return True

    @staticmethod
    def _is_alive_windows(pid: int) -> bool:
        import ctypes

        process_query_limited_information = 0x1000
        invalid_parameter = 87
        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        handle = kernel32.OpenProcess(process_query_limited_information, False, pid)
        if handle:
            kernel32.CloseHandle(handle)
            return True
        # ERROR_INVALID_PARAMETER é a resposta documentada para PID inexistente.
        # Todo outro erro (especialmente acesso negado) é dono possivelmente vivo.
        return ctypes.get_last_error() != invalid_parameter


class GPUOcupada(RuntimeError):
    """Outro processo segura o slot há mais tempo que o timeout."""


class LiberacaoFalhou(RuntimeError):
    """O serviço respondeu mas não confirmou a VRAM livre."""


class _Ilegivel:
    """Sentinela: o arquivo de estado existe mas não diz quem é o residente.

    Distinta de `None` de propósito. `None` significa "ninguém reivindicou a
    placa" — nada a liberar. Esta significa "alguém reivindicou e perdemos o
    registro de quem", que é o caso perigoso: um modelo pode estar carregado.
    """

    __slots__ = ()

    def __repr__(self) -> str:  # pragma: no cover - só ajuda em log/debug
        return "<ilegivel>"


ILEGIVEL = _Ilegivel()


class Broker:
    def __init__(
        self,
        *,
        lock_path: Path,
        estado_path: Path,
        liberadores: dict[str, Callable[[], None]],
        timeout_lock: float = 900.0,
        sem_gpu: frozenset[str] = frozenset(),
        inspector: ProcessInspector | None = None,
        probes: dict[str, Callable[[], bool]] | None = None,
        preparadores: dict[str, Callable[[], None]] | None = None,
    ) -> None:
        self.lock_path = Path(lock_path)
        self.estado_path = Path(estado_path)
        self.liberadores = liberadores
        self.timeout_lock = timeout_lock
        # Recursos que declaram não usar a placa (TTS na CPU, por exemplo).
        # Eles não disputam o slot nem deslocam o residente.
        self.sem_gpu = sem_gpu
        self.inspector = inspector or ProcessInspector()
        # Serviços iniciados fora do forge não deixam estado no broker. As probes
        # impedem que um Comfy/LM Studio manual sobreviva ao próximo claim.
        self.probes = probes or {}
        self.preparadores = preparadores or {}

    @contextmanager
    def exclusivo(self, recurso: Recurso) -> Iterator[None]:
        if recurso in self.sem_gpu:
            logger.debug("Recurso não usa GPU", recurso=recurso)
            yield
            return

        self.lock_path.parent.mkdir(parents=True, exist_ok=True)
        lock = FileLock(str(self.lock_path), timeout=self.timeout_lock)
        try:
            lock.acquire()
        except Timeout as e:
            raise GPUOcupada(
                f"outro processo segura a GPU há mais de {self.timeout_lock}s"
            ) from e
        try:
            self._trocar(recurso)
            yield
        finally:
            # Solta o lock mesmo se a liberação ou o corpo estourarem: um
            # liberador quebrado não pode trancar a placa para sempre.
            lock.release()

    def residente(self) -> str | None | _Ilegivel:
        """Quem ocupa a placa: o recurso, `None` se ninguém, `ILEGIVEL` se o
        arquivo existe e não pôde ser lido.

        Os dois últimos casos não podem virar um só. Não existe "próximo
        liberador" que cubra uma liberação perdida: `_trocar` só chama o
        liberador do residente REGISTRADO, então tratar estado corrompido como
        placa vazia deixaria o modelo carregado para sempre.
        """
        estado = self._estado()
        if isinstance(estado, GPUState):
            return estado.recurso
        return estado

    def _estado(self) -> GPUState | None | _Ilegivel:
        if not self.estado_path.exists():
            return None
        try:
            return GPUState.model_validate_json(
                self.estado_path.read_text(encoding="utf-8")
            )
        except (OSError, ValidationError, ValueError):
            logger.warning("Estado do broker ilegível", path=str(self.estado_path))
            return ILEGIVEL

    def _trocar(self, recurso: str) -> None:
        atual = self._estado()
        ativos = self._probar_servicos()
        if atual is ILEGIVEL:
            # Algo foi reivindicado e não sabemos o quê. Liberar todo mundo é
            # caro (paga reloads) mas é o único caminho seguro: o caro é um
            # reload, o inseguro é gerar imagem numa placa que ainda tem 6 GB
            # de LLM.
            logger.warning("Estado perdido; liberando todos os recursos",
                           para=recurso, liberadores=sorted(self.liberadores))
            self._liberar_todos()
            self._gravar(recurso)
            return
        if atual is not None and not self.inspector.is_alive(atual.pid):
            logger.warning(
                "Dono morto; liberando todos os recursos",
                recurso=atual.recurso,
                pid=atual.pid,
                para=recurso,
            )
            self._liberar_todos()
            self._gravar(recurso)
            return

        preparador = self.preparadores.get(recurso)
        if preparador is not None:
            preparador()

        atual_recurso = atual.recurso if atual is not None else None
        self._liberar_servicos_externos(recurso, atual_recurso, ativos)
        if atual_recurso == recurso:
            logger.debug("Recurso já residente", recurso=recurso)
            return
        if atual_recurso is not None:
            logger.info("Liberando GPU", de=atual_recurso, para=recurso)
            liberador = self.liberadores.get(atual_recurso)
            if liberador is not None:
                liberador()
        self._gravar(recurso)

    def _liberar_todos(self) -> None:
        for nome in sorted(self.liberadores):
            self.liberadores[nome]()

    def _probar_servicos(self) -> dict[str, bool]:
        ativos = {}
        for nome, probe in self.probes.items():
            try:
                ativos[nome] = probe()
            except Exception as e:  # uma probe não confiável não declara VRAM livre
                logger.warning("Probe de GPU falhou; tratando serviço como ativo",
                               recurso=nome, error=str(e))
                ativos[nome] = True
        return ativos

    def _liberar_servicos_externos(
        self, recurso: str, registrado: str | None, ativos: dict[str, bool]
    ) -> None:
        for nome, ativo in ativos.items():
            if ativo and nome != recurso and nome != registrado:
                logger.info("Liberando serviço externo", de=nome, para=recurso)
                liberador = self.liberadores.get(nome)
                if liberador is not None:
                    liberador()

    def _gravar(self, recurso: str) -> None:
        self.estado_path.parent.mkdir(parents=True, exist_ok=True)
        # Escrita atômica: este arquivo é reescrito exatamente quando um modelo
        # ESTÁ carregado, então um corte no meio da escrita o truncaria no pior
        # momento possível — e estado truncado força liberar tudo depois.
        temporario = self.estado_path.with_suffix(".json.tmp")
        estado = GPUState(
            recurso=recurso,
            pid=os.getpid(),
            claimed_at=datetime.now(UTC),
        )
        temporario.write_text(
            json.dumps({
                "recurso": estado.recurso,
                "pid": estado.pid,
                "claimed_at": estado.claimed_at.isoformat(),
            }),
            encoding="utf-8",
        )
        os.replace(temporario, self.estado_path)
