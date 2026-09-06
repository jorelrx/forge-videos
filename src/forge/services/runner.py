"""Consome os pendentes do manifesto, um grupo de cada vez.

Agrupar por tipo é o que torna o slot de GPU barato: o recurso é tomado uma vez
por grupo, não uma vez por item. Dentro do grupo, cada item grava o manifesto ao
terminar, e um item que estoura não interrompe os seguintes — quem decide o que
fazer com a falha é quem lê o manifesto depois.
"""

from __future__ import annotations

from pathlib import Path
from typing import Callable

from forge.infrastructure.logging import get_logger
from forge.services.manifesto import Item, Manifesto, gravar, pendentes

logger = get_logger(__name__)

# O executor preenche `saida` e `duracao_ms` no próprio item, por mutação: o
# item já pertence ao manifesto que será gravado, e devolver uma cópia criaria
# duas verdades sobre o mesmo id.
Executor = Callable[[Item, Path], None]

# Ordem fixa: o áudio primeiro porque as durações que ele mede são o que
# cronometra as imagens na montagem.
ORDEM: tuple[str, ...] = ("audio", "imagem")
RECURSO_DE: dict[str, str] = {"audio": "tts", "imagem": "imagem"}


def executar(
    run_dir: Path,
    manifesto: Manifesto,
    executores: dict[str, Executor],
    broker,
    *,
    so: str | None = None,
) -> Manifesto:
    for tipo in ORDEM:
        if so is not None and tipo != so:
            continue
        fila = pendentes(manifesto, tipo)
        if not fila:
            logger.debug("Nada pendente", tipo=tipo)
            continue
        executor = executores.get(tipo)
        if executor is None:
            logger.warning("Sem executor para o tipo", tipo=tipo)
            continue

        logger.info("Iniciando grupo", tipo=tipo, pendentes=len(fila))
        with broker.exclusivo(RECURSO_DE[tipo]):
            for item in fila:
                _um(run_dir, manifesto, item, executor)
    return manifesto


def _um(run_dir: Path, manifesto: Manifesto, item: Item, executor: Executor) -> None:
    item.tentativas += 1
    try:
        executor(item, run_dir)
    except Exception as e:
        item.estado = "falhou"
        item.erro = str(e)
        logger.error("Item falhou", id=item.id, tipo=item.tipo, error=str(e))
    else:
        item.estado = "ok"
        item.erro = ""
        logger.info("Item pronto", id=item.id, tipo=item.tipo, saida=item.saida)
    # Gravar por item é o ponto do manifesto: um crash custa um item, não o run.
    gravar(run_dir, manifesto)
