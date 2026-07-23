"""Qdrant: vetores dos chunks + payload de proveniência.

O payload carrega proveniência inteira porque o retriever precisa citar sem uma
segunda ida ao Postgres: o que sai da busca vetorial já tem autor/obra/capítulo/
url/autoridade. `_payload` é puro e testável sem servidor.
"""
from forge.infrastructure.logging import get_logger
from forge.knowledge.domain.models import Chunk

logger = get_logger(__name__)


def _payload(chunk: Chunk) -> dict:
    p = chunk.proveniencia
    return {
        "documento_id": chunk.documento_id,
        "ordem": chunk.ordem,
        "texto": chunk.texto,
        "secao": chunk.secao,
        "conceitos": chunk.conceitos,
        "tipo": p.tipo,
        "fonte": p.fonte,
        "autor": p.autor,
        "obra": p.obra,
        "capitulo": p.capitulo,
        "url": p.url,
        "autoridade": p.autoridade,
    }


class VectorStore:
    def __init__(self, url: str, collection: str, dim: int):
        from qdrant_client import QdrantClient

        self._cliente = QdrantClient(url=url)
        self._collection = collection
        self._dim = dim

    def garantir_colecao(self) -> None:
        from qdrant_client.models import Distance, VectorParams

        if self._cliente.collection_exists(self._collection):
            return
        self._cliente.create_collection(
            self._collection,
            vectors_config=VectorParams(size=self._dim, distance=Distance.COSINE),
        )
        logger.info("Coleção Qdrant criada", collection=self._collection, dim=self._dim)

    def upsert_chunks(self, chunks: list[Chunk]) -> int:
        from qdrant_client.models import PointStruct

        pontos = [
            PointStruct(id=c.id, vector=c.embedding, payload=_payload(c))
            for c in chunks
            if c.embedding is not None
        ]
        if not pontos:
            return 0
        self._cliente.upsert(self._collection, points=pontos)
        logger.info("Chunks no Qdrant", n=len(pontos))
        return len(pontos)

    def buscar(self, vetor: list[float], limite: int = 8) -> list[dict]:
        resp = self._cliente.query_points(self._collection, query=vetor, limit=limite)
        return [{"id": str(a.id), "score": a.score, **(a.payload or {})} for a in resp.points]

    def contar(self) -> int:
        return self._cliente.count(self._collection).count
