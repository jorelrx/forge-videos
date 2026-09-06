"""Consome os pendentes do manifesto, um grupo de cada vez.

Agrupar por tipo é o que torna o slot de GPU barato: o recurso é tomado uma vez
por grupo, não uma vez por item. Dentro do grupo, cada item grava o manifesto ao
terminar, e um item que estoura não interrompe os seguintes — quem decide o que
fazer com a falha é quem lê o manifesto depois.
"""

from __future__ import annotations

from pathlib import Path
from typing import Callable

# Import de tipo, não de implementação: o runner continua recebendo o broker
# por injeção e nunca constrói um.
from forge.gpu.broker import GPUOcupada, LiberacaoFalhou
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
    # Um valor de `so` fora de ORDEM não bate com nenhum tipo do loop, então o
    # loop inteiro faria `continue` em silêncio: nenhum pendentes(), nenhum log,
    # broker nunca aberto, manifesto devolvido intacto — indistinguível de um
    # run que legitimamente não tinha nada a fazer. Isso é erro de programador
    # ou de CLI (ex.: "imagens" no lugar de "imagem"), não condição de runtime,
    # então falha alto na fronteira em vez de devolver silêncio indepurável.
    if so is not None and so not in ORDEM:
        raise ValueError(f"grupo desconhecido: {so!r} (válidos: {ORDEM})")

    for tipo in ORDEM:
        if so is not None and tipo != so:
            continue
        fila = pendentes(manifesto, tipo)
        if not fila:
            logger.debug("Nada pendente", tipo=tipo)
            continue
        executor = executores.get(tipo)
        if executor is None:
            # Só logar deixaria os itens `pendente` com tentativas 0 e erro
            # vazio — em disco, idênticos a um grupo que ainda nem chegou a
            # rodar. Um supervisor esperando pendentes()==[] giraria para
            # sempre por causa de um dicionário de executores incompleto.
            _falhar_grupo(run_dir, manifesto, fila,
                          f"sem executor para o tipo {tipo!r}")
            logger.error("Sem executor para o tipo", tipo=tipo, itens=len(fila))
            continue

        logger.info("Iniciando grupo", tipo=tipo, pendentes=len(fila))
        try:
            with broker.exclusivo(RECURSO_DE[tipo]):
                for item in fila:
                    _um(run_dir, manifesto, item, executor)
        except (LiberacaoFalhou, GPUOcupada) as e:
            # Falha de broker na fronteira do grupo: sem isso a exceção sobe e
            # aborta o `executar` inteiro deixando os pendentes intocados. Numa
            # noite sem ninguém olhando isso é um liberador quebrado que faz
            # cada iteração queimar o timeout e reencontrar os mesmos pendentes
            # — sem contador, sem estado terminal, para sempre. Marcar `falhou`
            # dá ao supervisor um estado que ele consegue ler.
            _falhar_grupo(run_dir, manifesto, fila, str(e))
            logger.error("Grupo abortado pelo broker", tipo=tipo,
                         recurso=RECURSO_DE[tipo], itens=len(fila), error=str(e))
            continue
    return manifesto


def _falhar_grupo(run_dir: Path, manifesto: Manifesto, fila: list[Item],
                  motivo: str) -> None:
    """Marca como `falhou` o que sobrou pendente do grupo e grava.

    Só o que sobrou: se o broker estourou depois de alguns itens rodarem, o
    resultado deles é verdade e não pode ser sobrescrito.
    """
    for item in fila:
        if item.estado != "pendente":
            continue
        item.tentativas += 1
        item.estado = "falhou"
        item.erro = motivo
        item.saida = ""
        item.duracao_ms = None
    gravar(run_dir, manifesto)


def _um(run_dir: Path, manifesto: Manifesto, item: Item, executor: Executor) -> None:
    item.tentativas += 1
    try:
        executor(item, run_dir)
    except Exception as e:
        item.estado = "falhou"
        item.erro = str(e)
        # O executor pode ter preenchido `saida` antes de estourar, e o arquivo
        # apontado está truncado. Manifesto com estado `falhou` ao lado de um
        # caminho é convite para a montagem consumir meio WAV.
        item.saida = ""
        item.duracao_ms = None
        logger.error("Item falhou", id=item.id, tipo=item.tipo, error=str(e))
    else:
        item.estado = "ok"
        item.erro = ""
        logger.info("Item pronto", id=item.id, tipo=item.tipo, saida=item.saida)
    # Gravar por item é o ponto do manifesto: um crash custa um item, não o run.
    gravar(run_dir, manifesto)
