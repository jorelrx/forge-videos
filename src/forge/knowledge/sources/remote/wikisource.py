"""Wikisource via MediaWiki API, multi-subdomínio (um por idioma).

id_externo = "<lang>:<título>" para o baixar saber a qual wiki voltar. `langs`
vem de settings.knowledge.wikisource_langs — adicionar idiomas amplia a varredura.
"""
from forge.infrastructure.logging import get_logger
from forge.knowledge.domain.models import (
    Documento,
    Proveniencia,
    hash_texto,
    id_deterministico,
)
from forge.knowledge.sources.remote.base import Referencia

logger = get_logger(__name__)

_API = "https://{lang}.wikisource.org/w/api.php"
_AUTORIDADE = 1.0
_SRLIMIT = 10  # resultados por lang por página


def parse_busca(payload: dict, lang: str) -> list[Referencia]:
    hits = payload.get("query", {}).get("search", [])
    refs: list[Referencia] = []
    for h in hits:
        titulo = h.get("title")
        if not titulo:
            continue
        refs.append(
            Referencia(
                fonte="wikisource",
                id_externo=f"{lang}:{titulo}",
                titulo=titulo,
                url=_API.format(lang=lang),
                idioma=lang,
            )
        )
    return refs


def extrair_plaintext(payload: dict) -> str:
    pages = payload.get("query", {}).get("pages", {})
    for page in pages.values():
        return page.get("extract", "")
    return ""


class Wikisource:
    nome = "wikisource"

    def __init__(self, langs: list[str]):
        self._langs = langs

    def buscar(self, query: str, *, http, pagina: int = 1) -> list[Referencia]:
        sroffset = (pagina - 1) * _SRLIMIT
        refs: list[Referencia] = []
        for lang in self._langs:
            payload = http.get_json(
                _API.format(lang=lang),
                params={
                    "action": "query", "list": "search", "srsearch": query,
                    "srlimit": _SRLIMIT, "sroffset": sroffset, "format": "json",
                },
            )
            refs.extend(parse_busca(payload, lang))
        return refs

    def baixar(self, ref: Referencia, *, http) -> Documento:
        lang, titulo = ref.id_externo.split(":", 1)
        payload = http.get_json(
            _API.format(lang=lang),
            params={
                "action": "query", "prop": "extracts", "explaintext": "1",
                "titles": titulo, "format": "json",
            },
        )
        texto = extrair_plaintext(payload)
        prov = Proveniencia.de_fonte_remota(
            fonte="wikisource", obra=ref.titulo, url=ref.url,
            idioma=lang, autoridade=_AUTORIDADE,
        )
        logger.info("Wikisource baixado", id=ref.id_externo, chars=len(texto))
        return Documento(
            id=id_deterministico("documento", ref.chave_externa),
            hash_sha256=hash_texto(texto),
            titulo=ref.titulo,
            texto=texto,
            proveniencia=prov,
            chave_externa=ref.chave_externa,
        )
