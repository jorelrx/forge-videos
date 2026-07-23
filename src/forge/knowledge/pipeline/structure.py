"""Estágio SÓ de livro: texto -> capítulos/subcapítulos.

Web não tem estrutura de livro; este estágio nunca roda no ramo web. Detecção
por heurística de cabeçalho — não perfeita, mas o suficiente para ancorar chunk
ao capítulo e registrar `capitulo` na proveniência da citação.
"""
import re

from forge.knowledge.domain.models import Documento, Secao

# Cabeçalhos comuns em livros PT/EN e markdown. Linha inteira, não trecho no meio.
_CABECALHO = re.compile(
    r"^(?:"
    r"#{1,6}\s+.+"                                  # markdown: # Título
    r"|(?:cap[íi]tulo|chapter|parte|part|se[çc][ãa]o)\s+[\dIVXLC]+.*"  # Capítulo 3
    r")$",
    re.IGNORECASE,
)

def _nivel(cabecalho: str) -> int:
    m = re.match(r"^(#{1,6})\s", cabecalho)
    if m:
        return len(m.group(1))
    return 1

def detectar_secoes(texto: str) -> list[Secao]:
    linhas = texto.splitlines()
    marcas = [i for i, linha in enumerate(linhas) if _CABECALHO.match(linha.strip())]
    if not marcas:
        return []

    secoes: list[Secao] = []
    for pos, inicio in enumerate(marcas):
        fim = marcas[pos + 1] if pos + 1 < len(marcas) else len(linhas)
        nome = linhas[inicio].strip().lstrip("#").strip()
        corpo = "\n".join(linhas[inicio + 1 : fim]).strip()
        secoes.append(Secao(nome=nome, nivel=_nivel(linhas[inicio].strip()), texto=corpo))
    return secoes

def aplicar_estrutura(doc: Documento) -> Documento:
    """Preenche `doc.secoes` in-place a partir de `doc.texto`. Devolve o mesmo doc."""
    doc.secoes = detectar_secoes(doc.texto)
    return doc
