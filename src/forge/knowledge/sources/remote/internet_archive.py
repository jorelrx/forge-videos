"""Internet Archive: advancedsearch para candidatos, metadata para o arquivo
de texto (*_djvu.txt / *.txt), download do texto. Parse puro; rede via http."""
from forge.infrastructure.logging import get_logger
from forge.knowledge.domain.models import (
    Documento,
    Proveniencia,
    hash_texto,
    id_deterministico,
)
from forge.knowledge.sources.remote.base import Referencia

logger = get_logger(__name__)

_SEARCH = "https://archive.org/advancedsearch.php"
_META = "https://archive.org/metadata/{id}"
_DOWNLOAD = "https://archive.org/download/{id}/{file}"
_AUTORIDADE = 1.0
_ROWS = 10  # candidatos por página do advancedsearch


def _primeiro(valor):
    if isinstance(valor, list):
        return valor[0] if valor else None
    return valor


def parse_busca(payload: dict) -> list[Referencia]:
    docs = payload.get("response", {}).get("docs", [])
    refs: list[Referencia] = []
    for d in docs:
        ident = d.get("identifier")
        if not ident:
            continue
        titulo = _primeiro(d.get("title")) or ident
        refs.append(
            Referencia(
                fonte="internet_archive",
                id_externo=ident,
                titulo=titulo if isinstance(titulo, str) else ident,
                autor=_primeiro(d.get("creator")),
                url=_META.format(id=ident),
                idioma=_primeiro(d.get("language")),
            )
        )
    return refs


def escolher_arquivo_texto(meta: dict) -> str | None:
    files = meta.get("files", [])
    for f in files:
        if f.get("name", "").endswith("_djvu.txt"):
            return f["name"]
    for f in files:
        if f.get("name", "").endswith(".txt"):
            return f["name"]
    return None


class InternetArchive:
    nome = "internet_archive"

    def buscar(self, query: str, *, http, pagina: int = 1) -> list[Referencia]:
        payload = http.get_json(
            _SEARCH,
            params={
                "q": query,
                "fl[]": ["identifier", "title", "creator", "language"],
                "sort[]": "downloads desc",
                "rows": _ROWS,
                "page": pagina,
                "output": "json",
            },
        )
        return parse_busca(payload)

    def baixar(self, ref: Referencia, *, http) -> Documento:
        meta = http.get_json(ref.url)
        arquivo = escolher_arquivo_texto(meta)
        if not arquivo:
            raise ValueError(f"sem arquivo de texto para {ref.id_externo}")
        url = _DOWNLOAD.format(id=ref.id_externo, file=arquivo)
        texto = http.get_text_cacheado(url, fonte="internet_archive", id_externo=ref.id_externo)
        prov = Proveniencia.de_fonte_remota(
            fonte="internet_archive", autor=ref.autor, obra=ref.titulo,
            url=url, idioma=ref.idioma, autoridade=_AUTORIDADE,
        )
        logger.info("Internet Archive baixado", id=ref.id_externo, chars=len(texto))
        return Documento(
            id=id_deterministico("documento", ref.chave_externa),
            hash_sha256=hash_texto(texto),
            titulo=ref.titulo,
            texto=texto,
            proveniencia=prov,
            chave_externa=ref.chave_externa,
        )
