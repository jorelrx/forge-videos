"""Detecção de cabeçalho em texto puro (TXT/MD) e em texto vindo de fonte remota.

Duas famílias: markdown (`#` a `######`, o nível é a contagem de cerquilhas) e
prosa (`Capítulo 3`, `Parte II`), sempre linha inteira — cerquilha ou palavra no
meio da frase não é cabeçalho.
"""
import re

from forge.knowledge.sources.extract.tipos import Marca, TextoExtraido

_MARKDOWN = re.compile(r"^(#{1,6})\s+(.+?)\s*$")
_PROSA = re.compile(
    r"^((?:cap[íi]tulo|chapter|parte|part|se[çc][ãa]o)\s+[\dIVXLC]+.*?)\s*$",
    re.IGNORECASE,
)


def marcas_de_texto(texto: str) -> list[Marca]:
    marcas: list[Marca] = []
    offset = 0
    for linha in texto.splitlines(keepends=True):
        despida = linha.strip()
        comprimento = len(linha.rstrip("\r\n"))
        md = _MARKDOWN.match(despida)
        if md:
            marcas.append(
                Marca(offset=offset, nivel=len(md.group(1)), titulo=md.group(2),
                      comprimento=comprimento)
            )
        else:
            prosa = _PROSA.match(despida)
            if prosa:
                marcas.append(
                    Marca(offset=offset, nivel=1, titulo=prosa.group(1),
                          comprimento=comprimento)
                )
        offset += len(linha)
    return marcas


def extrair_texto(texto: str) -> TextoExtraido:
    """TXT/MD e texto de fonte remota: sem páginas, marcas por cabeçalho."""
    return TextoExtraido(texto=texto, marcas=marcas_de_texto(texto), paginas=[])
