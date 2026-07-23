"""Stanford Encyclopedia of Philosophy: sem API. Busca via endpoint interno de
search (HTML), artigo via scraping da página da entrada. bs4 confinado aqui."""
import re

from bs4 import BeautifulSoup

from forge.infrastructure.logging import get_logger
from forge.knowledge.domain.models import (
    Documento,
    Proveniencia,
    hash_texto,
    id_deterministico,
)
from forge.knowledge.sources.remote.base import Referencia

logger = get_logger(__name__)

_SEARCH = "https://plato.stanford.edu/search/searcher.py"
_ENTRY = "https://plato.stanford.edu/entries/{slug}/"
_AUTORIDADE = 0.9
# O link de resultado é um redirect: /search/r?entry=/entries/<slug>/&...
# O slug vem do parâmetro `entry`, não do path — por isso busca livre, não âncora.
_RE_SLUG = re.compile(r"/entries/([^/&#?\"]+)/")


def parse_busca(html: str) -> list[Referencia]:
    sopa = BeautifulSoup(html, "html.parser")
    vistos: list[str] = []
    refs: list[Referencia] = []
    for bloco in sopa.select("div.result_listing"):
        titulo_el = bloco.select_one(".result_title a")
        link = titulo_el or bloco.select_one(".result_url a")
        if link is None:
            continue
        m = _RE_SLUG.search(link.get("href", ""))
        if not m:
            continue
        slug = m.group(1)
        if slug in vistos:
            continue
        vistos.append(slug)
        autor_el = bloco.select_one(".result_author")
        refs.append(
            Referencia(
                fonte="sep",
                id_externo=slug,
                titulo=(titulo_el.get_text(strip=True) if titulo_el else slug) or slug,
                autor=(autor_el.get_text(strip=True) if autor_el else "") or None,
                url=_ENTRY.format(slug=slug),
                idioma="en",
            )
        )
    return refs


def extrair_artigo(html: str) -> str:
    sopa = BeautifulSoup(html, "html.parser")
    art = sopa.find(id="article-content") or sopa.find(id="aueditable")
    if art is None:
        return ""
    return art.get_text(separator="\n").strip()


class SEP:
    nome = "sep"
    idioma_busca = "en"  # SEP é só-inglês: a query é traduzida antes de buscar

    def buscar(self, query: str, *, http, pagina: int = 1) -> list[Referencia]:
        html = http.get_text(_SEARCH, params={"query": query, "page": pagina})
        return parse_busca(html)

    def baixar(self, ref: Referencia, *, http) -> Documento:
        html = http.get_text_cacheado(ref.url, fonte="sep", id_externo=ref.id_externo, ext="html")
        texto = extrair_artigo(html)
        prov = Proveniencia.de_fonte_remota(
            fonte="sep", autor=ref.autor, obra=ref.titulo, url=ref.url,
            idioma="en", autoridade=_AUTORIDADE,
        )
        logger.info("SEP baixado", slug=ref.id_externo, chars=len(texto))
        return Documento(
            id=id_deterministico("documento", ref.chave_externa),
            hash_sha256=hash_texto(texto),
            titulo=ref.titulo,
            texto=texto,
            proveniencia=prov,
            chave_externa=ref.chave_externa,
        )
