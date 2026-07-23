"""Project Gutenberg via API Gutendex. Parse puro; rede via http injetado."""
import re

import httpx

from forge.infrastructure.logging import get_logger
from forge.knowledge.domain.models import Documento, Proveniencia, id_deterministico
from forge.knowledge.sources.remote.base import Referencia

logger = get_logger(__name__)

_API = "https://gutendex.com/books"
_AUTORIDADE = 1.0
_RE_START = re.compile(
    r"\*\*\* ?START OF TH(E|IS) PROJECT GUTENBERG[^*]*\*\*\*", re.IGNORECASE
)
_RE_END = re.compile(
    r"\*\*\* ?END OF TH(E|IS) PROJECT GUTENBERG.*", re.IGNORECASE | re.DOTALL
)


def _url_texto_plano(formats: dict) -> str | None:
    preferidos = (
        "text/plain; charset=utf-8",
        "text/plain; charset=us-ascii",
        "text/plain",
    )
    for mime in preferidos:
        url = formats.get(mime)
        if url and not url.endswith(".zip"):
            return url
    for mime, url in formats.items():
        if mime.startswith("text/plain") and not url.endswith(".zip"):
            return url
    return None


def parse_busca(payload: dict) -> list[Referencia]:
    refs: list[Referencia] = []
    for item in payload.get("results", []):
        url = _url_texto_plano(item.get("formats", {}))
        if not url:
            continue
        autores = item.get("authors") or []
        idiomas = item.get("languages") or []
        refs.append(
            Referencia(
                fonte="gutenberg",
                id_externo=str(item["id"]),
                titulo=item.get("title", "sem título"),
                autor=autores[0]["name"] if autores else None,
                url=url,
                idioma=idiomas[0] if idiomas else None,
            )
        )
    return refs


def limpar_boilerplate(texto: str) -> str:
    m = _RE_START.search(texto)
    if m:
        texto = texto[m.end():]
    texto = _RE_END.sub("", texto)
    return texto.strip()


class Gutenberg:
    nome = "gutenberg"

    def buscar(self, query: str, *, http, pagina: int = 1) -> list[Referencia]:
        # Gutendex responde 404 quando a página passa da última — é "esgotou",
        # não erro: devolve lista vazia para o orquestrador parar limpo.
        try:
            payload = http.get_json(_API, params={"search": query, "page": pagina})
        except httpx.HTTPStatusError as e:
            if e.response.status_code == 404:
                return []
            raise
        return parse_busca(payload)

    def baixar(self, ref: Referencia, *, http) -> Documento:
        bruto = http.get_text_cacheado(ref.url, fonte="gutenberg", id_externo=ref.id_externo)
        texto = limpar_boilerplate(bruto)
        prov = Proveniencia.de_fonte_remota(
            fonte="gutenberg", autor=ref.autor, obra=ref.titulo,
            url=ref.url, idioma=ref.idioma, autoridade=_AUTORIDADE,
        )
        logger.info("Gutenberg baixado", id=ref.id_externo, chars=len(texto))
        return Documento(
            id=id_deterministico("gutenberg", ref.id_externo),
            titulo=ref.titulo, texto=texto, proveniencia=prov,
        )
