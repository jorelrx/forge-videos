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
from pathlib import Path
from typing import Callable, Iterator, Literal

from filelock import FileLock, Timeout

from forge.infrastructure.logging import get_logger

logger = get_logger(__name__)

Recurso = Literal["llm", "tts", "imagem"]


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
    ) -> None:
        self.lock_path = Path(lock_path)
        self.estado_path = Path(estado_path)
        self.liberadores = liberadores
        self.timeout_lock = timeout_lock
        # Recursos que declaram não usar a placa (TTS na CPU, por exemplo).
        # Eles não disputam o slot nem deslocam o residente.
        self.sem_gpu = sem_gpu

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
        if not self.estado_path.exists():
            return None
        try:
            return json.loads(self.estado_path.read_text(encoding="utf-8"))["recurso"]
        except (OSError, ValueError, KeyError):
            logger.warning("Estado do broker ilegível", path=str(self.estado_path))
            return ILEGIVEL

    def _trocar(self, recurso: str) -> None:
        atual = self.residente()
        if atual is ILEGIVEL:
            # Algo foi reivindicado e não sabemos o quê. Liberar todo mundo é
            # caro (paga reloads) mas é o único caminho seguro: o caro é um
            # reload, o inseguro é gerar imagem numa placa que ainda tem 6 GB
            # de LLM.
            logger.warning("Estado perdido; liberando todos os recursos",
                           para=recurso, liberadores=sorted(self.liberadores))
            for nome in sorted(self.liberadores):
                self.liberadores[nome]()
            self._gravar(recurso)
            return
        if atual == recurso:
            logger.debug("Recurso já residente", recurso=recurso)
            return
        if atual is not None:
            logger.info("Liberando GPU", de=atual, para=recurso)
            liberador = self.liberadores.get(atual)
            if liberador is not None:
                liberador()
        self._gravar(recurso)

    def _gravar(self, recurso: str) -> None:
        self.estado_path.parent.mkdir(parents=True, exist_ok=True)
        # Escrita atômica: este arquivo é reescrito exatamente quando um modelo
        # ESTÁ carregado, então um corte no meio da escrita o truncaria no pior
        # momento possível — e estado truncado força liberar tudo depois.
        temporario = self.estado_path.with_suffix(".json.tmp")
        temporario.write_text(json.dumps({"recurso": recurso}), encoding="utf-8")
        os.replace(temporario, self.estado_path)
