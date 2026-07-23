"""Resultado de web_search -> Documento(tipo=web).

É o motor do 'aprende continuamente': cada busca do research vira material
ingerível. Autoridade fica baixa por padrão (ver Proveniencia.de_web) — web é
ponto de partida, não prova de citação.
"""
from forge.infrastructure.logging import get_logger
from forge.knowledge.domain.models import Documento, Proveniencia, id_deterministico

logger = get_logger(__name__)


def documento_de_resultado(resultado: dict) -> Documento | None:
    url = resultado.get("url") or resultado.get("href")
    if not url:
        logger.debug("Resultado de busca sem url, ignorado", resultado=resultado)
        return None
    texto = resultado.get("snippet") or resultado.get("body") or ""
    titulo = resultado.get("title") or url
    prov = Proveniencia.de_web(url=url, titulo=titulo)
    return Documento(
        id=id_deterministico("web", url),
        titulo=titulo,
        texto=texto,
        proveniencia=prov,
    )


def documentos_de_busca(resultados: list[dict]) -> list[Documento]:
    docs = [documento_de_resultado(r) for r in resultados]
    return [d for d in docs if d is not None]
