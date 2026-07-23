"""Contrato da extração: texto cru + onde estão os cabeçalhos e as páginas.

A extração não interpreta a estrutura, só marca onde ela começa. Quem monta a
árvore é `pipeline.arvore`. Separar os dois deixa o detector de cabeçalho
testável sem PDF e a árvore testável sem extrator.
"""
from bisect import bisect_right
from dataclasses import dataclass, field


@dataclass(frozen=True)
class Marca:
    """Cabeçalho encontrado no texto. `nivel`: 1=capítulo, 2=subcapítulo, 3=seção.

    `comprimento` é quanto o cabeçalho ocupa a partir de `offset`. A árvore usa
    isso para achar o início do corpo — `titulo` não serve, porque não inclui as
    cerquilhas do markdown.
    """
    offset: int
    nivel: int
    titulo: str
    comprimento: int


@dataclass
class TextoExtraido:
    texto: str
    marcas: list[Marca] = field(default_factory=list)
    # Offset inicial de cada página, em ordem. Vazio quando o formato não tem
    # páginas (EPUB, TXT, MD) — nesse caso o chunk fica com página nula.
    paginas: list[int] = field(default_factory=list)
    idioma: str | None = None


def pagina_de_offset(paginas: list[int], offset: int) -> int | None:
    """Número de página (base 1) que contém o offset, ou None se não há páginas."""
    if not paginas:
        return None
    return bisect_right(paginas, offset)
