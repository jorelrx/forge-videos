"""Qdrant: vetores das folhas-parágrafo + payload de estrutura e proveniência.

Só parágrafo vira vetor (small-to-big): o embedding fica preciso e a entrega
sobe pelo `pai_id` para devolver o trecho com o contexto em volta. Sentença,
seção e capítulo não são indexados.

O payload carrega proveniência inteira porque o retriever precisa citar sem uma
segunda ida ao Postgres. `_payload` e `pontos_de` são puros e testáveis sem
servidor.
"""
from forge.infrastructure.logging import get_logger
from forge.knowledge.domain.models import NIVEL_FOLHA, Chunk, Documento

logger = get_logger(__name__)


def _payload(doc: Documento, chunk: Chunk) -> dict:
    p = doc.proveniencia
    return {
        "documento_id": chunk.documento_id,
        "pai_id": chunk.pai_id,
        "nivel": chunk.nivel,
        "caminho": chunk.caminho,
        "ordem": chunk.ordem,
        "texto": chunk.texto,
        "pagina": chunk.pagina,
        "offset_inicio": chunk.offset_inicio,
        "offset_fim": chunk.offset_fim,
        "tipo": p.tipo,
        "fonte": p.fonte,
        "autor": p.autor,
        "obra": p.obra,
        "url": p.url,
        "idioma": p.idioma,
        "data_publicacao": p.data_publicacao,
        "autoridade": p.autoridade,
    }


def pontos_de(doc: Documento, chunks: list[Chunk]) -> list:
    from qdrant_client.models import PointStruct

    return [
        PointStruct(id=c.id, vector=c.embedding, payload=_payload(doc, c))
        for c in chunks
        if c.nivel == NIVEL_FOLHA and c.embedding is not None
    ]


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

    def resetar(self) -> None:
        if self._cliente.collection_exists(self._collection):
            self._cliente.delete_collection(self._collection)
            logger.warning("Coleção Qdrant removida", collection=self._collection)
        self.garantir_colecao()

    def upsert_chunks(self, doc: Documento, chunks: list[Chunk]) -> int:
        pontos = pontos_de(doc, chunks)
        if not pontos:
            return 0
        self._cliente.upsert(self._collection, points=pontos)
        logger.info("Parágrafos no Qdrant", n=len(pontos), doc=doc.id)
        return len(pontos)

    def contar(self) -> int:
        return self._cliente.count(self._collection).count
