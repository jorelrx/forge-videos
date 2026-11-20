"""Linha do tempo da narração: onde cada bloco começa e termina no vídeo.

Cartões de fonte, legenda e capítulos precisam da mesma resposta — em que
segundo o bloco N é falado. Uma conta só, aqui, para que os três nunca
discordem entre si nem do áudio. A duração vem do WAV real de cada bloco, não
de estimativa por palavra.
"""

from __future__ import annotations

from pydantic import BaseModel

from forge.domain.midia import BlocoNarracao


class TrechoTempo(BaseModel):
    bloco_id: str
    secao: str
    inicio: float
    fim: float


def linha_do_tempo(
    blocos: list[BlocoNarracao], duracoes: dict[str, float],
) -> list[TrechoTempo]:
    """Acumula as durações na ordem recebida, que é a ordem da narração.

    Bloco sem duração levanta `KeyError`: pular o bloco deslocaria tudo que vem
    depois, e legenda fora de sincronia é pior que montagem que para.
    """
    tempos: list[TrechoTempo] = []
    cursor = 0.0
    for bloco in blocos:
        fim = round(cursor + float(duracoes[bloco.id]), 3)
        tempos.append(TrechoTempo(
            bloco_id=bloco.id, secao=bloco.secao, inicio=cursor, fim=fim,
        ))
        cursor = fim
    return tempos


def inicio_das_secoes(tempos: list[TrechoTempo]) -> dict[str, float]:
    """Início do primeiro bloco de cada seção, na ordem em que aparecem."""
    inicios: dict[str, float] = {}
    for trecho in tempos:
        inicios.setdefault(trecho.secao, trecho.inicio)
    return inicios


__all__ = ["TrechoTempo", "inicio_das_secoes", "linha_do_tempo"]
