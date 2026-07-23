"""EPUB -> texto + marcas.

O spine é o melhor sinal estrutural dos três formatos: ele diz onde cada
capítulo começa, sem heurística nenhuma. Dentro do capítulo, <h2>-<h6> dão
subcapítulo e seção. Hoje esse sinal é jogado fora por um get_text() no arquivo
inteiro.
"""
from pathlib import Path

from forge.infrastructure.logging import get_logger
from forge.knowledge.sources.extract.tipos import Marca, TextoExtraido

logger = get_logger(__name__)

_SEPARADOR = "\n\n"
_HEADINGS = ["h1", "h2", "h3", "h4", "h5", "h6"]


def _nivel_do_heading(nome: str) -> int:
    """<h2> vira nível 2, <h3> vira 3. <h1> dentro do item é nível 2: o nível 1
    já é o capítulo do spine, e dois capítulos aninhados não fazem sentido."""
    numero = int(nome[1])
    return max(2, numero)


def montar_itens(itens: list[tuple[str, str]]) -> TextoExtraido:
    """(titulo do spine, html) -> texto concatenado + marcas com offsets reais."""
    from bs4 import BeautifulSoup

    partes: list[str] = []
    marcas: list[Marca] = []
    posicao = 0

    for titulo, html in itens:
        if partes:
            partes.append(_SEPARADOR)
            posicao += len(_SEPARADOR)

        marcas.append(
            Marca(offset=posicao, nivel=1, titulo=titulo, comprimento=len(titulo))
        )
        partes.append(titulo)
        posicao += len(titulo)

        sopa = BeautifulSoup(html, "html.parser")
        for elemento in sopa.find_all(_HEADINGS + ["p"]):
            if elemento.find_parent(_HEADINGS + ["p"]):
                continue
            texto = elemento.get_text(separator=" ", strip=True)
            if not texto:
                continue
            partes.append(_SEPARADOR)
            posicao += len(_SEPARADOR)
            if elemento.name in _HEADINGS:
                marcas.append(
                    Marca(
                        offset=posicao, nivel=_nivel_do_heading(elemento.name),
                        titulo=texto, comprimento=len(texto),
                    )
                )
            partes.append(texto)
            posicao += len(texto)

    return TextoExtraido(texto="".join(partes), marcas=marcas, paginas=[])


def _titulo_e_html(item) -> tuple[str, str]:
    titulo = getattr(item, "title", None) or Path(item.get_name()).stem
    return titulo, item.get_content().decode("utf-8", errors="replace")


def itens_do_spine(livro, tipo_documento=None) -> list[tuple[str, str]]:
    """Ordem de leitura real do EPUB: segue o spine, não o manifesto.

    O spine é a lista (idref, linear) que o próprio livro declara como ordem
    de leitura; get_items_of_type devolve os itens na ordem interna do
    manifesto, que não é garantida bater com o spine. Cai para o manifesto
    quando o spine está vazio ou nenhum idref resolve — malformado ingere
    algo em vez de nada.

    `tipo_documento` é o valor repassado a get_items_of_type no fallback
    (em produção, `ebooklib.ITEM_DOCUMENT`, passado por extrair_epub); fica
    duck-typed aqui para permitir testar esta função sem o ebooklib
    instalado.
    """
    itens: list[tuple[str, str]] = []
    for idref, _linear in getattr(livro, "spine", None) or []:
        item = livro.get_item_with_id(idref)
        if item is None:
            continue
        itens.append(_titulo_e_html(item))

    if itens:
        return itens

    return [
        _titulo_e_html(item)
        for item in livro.get_items_of_type(tipo_documento)
    ]


def extrair_epub(path: Path) -> TextoExtraido:
    import ebooklib
    from ebooklib import epub

    livro = epub.read_epub(str(path))
    itens = itens_do_spine(livro, tipo_documento=ebooklib.ITEM_DOCUMENT)

    extraido = montar_itens(itens)
    logger.info("EPUB extraído", fonte=path.name, itens=len(itens), chars=len(extraido.texto))
    return extraido
