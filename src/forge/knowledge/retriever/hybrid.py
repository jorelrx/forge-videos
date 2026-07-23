"""DORMENTE ATÉ K5. Nenhum chamador em K1-K4.

Retriever fino: vetorial + léxico com fusão RRF. A fusão RRF está correta e é
reaproveitada em K5 — por isso o módulo fica no repositório em vez de ser
apagado. O resto (query planner, perna de KG, metadados, recência, autoridade,
confiança, re-ranking por cross-encoder) é escopo de K5, depois que K1-K4
tiverem gravado esses sinais.

`retrieve` e `consultar` referenciam o schema anterior a K1 e não funcionam como
estão. Não chame nada daqui antes de K5.
"""
from forge.infrastructure.logging import get_logger

logger = get_logger(__name__)

_RRF_K = 60


def fundir(listas: list[list[dict]], *, k: int = _RRF_K, limite: int = 8) -> list[dict]:
    scores: dict[str, float] = {}
    registro: dict[str, dict] = {}
    for lista in listas:
        for rank, item in enumerate(lista):
            cid = item.get("id")
            if cid is None:
                continue
            scores[cid] = scores.get(cid, 0.0) + 1.0 / (k + rank)
            registro.setdefault(cid, item)
    ordenado = sorted(scores, key=lambda c: scores[c], reverse=True)
    return [{**registro[c], "rrf": scores[c]} for c in ordenado[:limite]]


def retrieve(query: str, *, embed_fn, vector, catalog, limite: int = 8) -> list[dict]:
    qv = embed_fn([query])[0]
    vetorial = vector.buscar(qv, limite)
    lexico = catalog.buscar_lexico(query, limite)
    fundidos = fundir([vetorial, lexico], limite=limite)
    logger.info("Retrieve", query=query[:60], vetorial=len(vetorial), lexico=len(lexico), fundidos=len(fundidos))
    return fundidos


def consultar(query: str, settings, *, limite: int = 8) -> list[dict]:
    """Monta embed_fn + stores reais a partir de Settings e roda o retrieve híbrido.

    Retrieval não precisa de LLM nem do grafo — só do embedder, do Qdrant e do
    índice léxico do Postgres. Imports preguiçosos: quem não consulta não paga.
    """
    from forge.knowledge.pipeline.embed import build_embed_fn
    from forge.knowledge.stores.catalog import CatalogStore
    from forge.knowledge.stores.vector import VectorStore

    k = settings.knowledge
    embed_fn = build_embed_fn(settings)
    vector = VectorStore(k.qdrant_url, k.qdrant_collection, k.embedding_dim)
    catalog = CatalogStore(k.postgres_dsn)
    return retrieve(query, embed_fn=embed_fn, vector=vector, catalog=catalog, limite=limite)
