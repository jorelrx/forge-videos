"""Escolha da trilha de fundo a partir de uma pasta de faixas do usuário.

A trilha é opcional e licenciada por quem a coloca na pasta: o forge não baixa
nem gera música. Aqui só se decide *qual* faixa toca e *de quem* é o crédito,
de forma determinística — a mesma run (mesma semente) sempre pega a mesma faixa,
então remontar o vídeo não troca a música sem aviso, e runs diferentes variam.
"""

from __future__ import annotations

import hashlib
from pathlib import Path

from pydantic import BaseModel

from forge.infrastructure.logging import get_logger

logger = get_logger(__name__)

EXTENSOES = (".mp3", ".wav", ".flac", ".ogg", ".m4a")


class Trilha(BaseModel):
    caminho: Path
    credito: str | None = None  # primeira linha não vazia de <faixa>.txt


def _faixas(pasta: Path) -> list[Path]:
    """Faixas de áudio diretamente em `pasta`, ordenadas por nome.

    Sem recursão e com ordenação fixa: o índice sorteado só significa a mesma
    faixa se a lista for a mesma, qualquer que seja a ordem do sistema de
    arquivos. A extensão é comparada em minúsculas (`.MP3` também vale).
    """
    if not pasta.is_dir():
        return []
    return sorted(
        (p for p in pasta.iterdir()
         if p.is_file() and p.suffix.lower() in EXTENSOES),
        key=lambda p: p.name,
    )


def _credito(faixa: Path) -> str | None:
    """Primeira linha não vazia de `<nome-da-faixa>.txt`, se existir.

    Licenças como CC BY exigem atribuição; o texto vai para a descrição do
    vídeo. Arquivo ilegível equivale a não ter crédito — não derruba a run.
    """
    arquivo = faixa.with_suffix(".txt")
    try:
        for linha in arquivo.read_text(encoding="utf-8").splitlines():
            if linha.strip():
                return linha.strip()
    except (OSError, UnicodeDecodeError):
        logger.warning("trilha_credito_ilegivel", arquivo=str(arquivo))
    return None


def escolher_trilha(
    pasta: Path, *, semente: str, eixo: str | None = None,
) -> Trilha | None:
    """Escolhe a faixa de `pasta` por hash da `semente`.

    A subpasta `eixo`, quando tem faixas, tem preferência (música própria do
    eixo editorial); vazia ou ausente, cai na raiz. Outras subpastas nunca são
    lidas. Pasta ausente ou sem faixas devolve `None`.
    """
    faixas: list[Path] = []
    if eixo:
        faixas = _faixas(pasta / eixo)
    if not faixas:
        faixas = _faixas(pasta)
    if not faixas:
        logger.info("trilha_ausente", pasta=str(pasta), eixo=eixo)
        return None

    indice = int(hashlib.sha256(semente.encode("utf-8")).hexdigest(), 16) % len(faixas)
    escolhida = faixas[indice]
    logger.info("trilha_escolhida", faixa=escolhida.name, candidatas=len(faixas))
    return Trilha(caminho=escolhida, credito=_credito(escolhida))


__all__ = ["EXTENSOES", "Trilha", "escolher_trilha"]
