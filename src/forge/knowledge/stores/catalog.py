"""Postgres: metadados + índice léxico (tsvector) + proveniência.

O índice léxico é a perna BM25-like do retriever híbrido: `tsvector` +
`ts_rank`. `linha_documento` e `linha_chunk` são puros e testáveis sem servidor.
"""
from forge.infrastructure.logging import get_logger
from forge.knowledge.domain.models import Chunk, Documento

logger = get_logger(__name__)

_SCHEMA = """
CREATE TABLE IF NOT EXISTS documentos (
    id           TEXT PRIMARY KEY,
    titulo       TEXT NOT NULL,
    tipo         TEXT NOT NULL,
    fonte        TEXT NOT NULL,
    autor        TEXT,
    obra         TEXT,
    url          TEXT,
    autoridade   REAL NOT NULL,
    resumo       TEXT
);
CREATE TABLE IF NOT EXISTS chunks (
    id            TEXT PRIMARY KEY,
    documento_id  TEXT NOT NULL REFERENCES documentos(id) ON DELETE CASCADE,
    ordem         INT  NOT NULL,
    texto         TEXT NOT NULL,
    secao         TEXT,
    capitulo      TEXT,
    autoridade    REAL NOT NULL,
    tsv           tsvector GENERATED ALWAYS AS (to_tsvector('portuguese', texto)) STORED
);
CREATE INDEX IF NOT EXISTS chunks_tsv_idx ON chunks USING GIN (tsv);
"""

_UPSERT_DOC = """
INSERT INTO documentos (id, titulo, tipo, fonte, autor, obra, url, autoridade, resumo)
VALUES (%(id)s, %(titulo)s, %(tipo)s, %(fonte)s, %(autor)s, %(obra)s, %(url)s, %(autoridade)s, %(resumo)s)
ON CONFLICT (id) DO UPDATE SET
    titulo = EXCLUDED.titulo, resumo = EXCLUDED.resumo, autoridade = EXCLUDED.autoridade
"""

_UPSERT_CHUNK = """
INSERT INTO chunks (id, documento_id, ordem, texto, secao, capitulo, autoridade)
VALUES (%(id)s, %(documento_id)s, %(ordem)s, %(texto)s, %(secao)s, %(capitulo)s, %(autoridade)s)
ON CONFLICT (id) DO UPDATE SET texto = EXCLUDED.texto, secao = EXCLUDED.secao
"""

_BUSCA_LEXICA = """
SELECT id, documento_id, texto, secao, capitulo, autoridade,
       ts_rank(tsv, plainto_tsquery('portuguese', %(q)s)) AS score
FROM chunks
WHERE tsv @@ plainto_tsquery('portuguese', %(q)s)
ORDER BY score DESC
LIMIT %(limite)s
"""


def linha_documento(doc: Documento) -> dict:
    p = doc.proveniencia
    return {
        "id": doc.id, "titulo": doc.titulo, "tipo": p.tipo, "fonte": p.fonte,
        "autor": p.autor, "obra": p.obra, "url": p.url,
        "autoridade": p.autoridade, "resumo": doc.resumo,
    }


def linha_chunk(chunk: Chunk) -> dict:
    return {
        "id": chunk.id, "documento_id": chunk.documento_id, "ordem": chunk.ordem,
        "texto": chunk.texto, "secao": chunk.secao,
        "capitulo": chunk.proveniencia.capitulo, "autoridade": chunk.proveniencia.autoridade,
    }


class CatalogStore:
    def __init__(self, dsn: str):
        import psycopg

        self._conn = psycopg.connect(dsn, autocommit=True)

    def garantir_schema(self) -> None:
        with self._conn.cursor() as cur:
            cur.execute(_SCHEMA)
        logger.info("Schema Postgres garantido")

    def upsert_documento(self, doc: Documento) -> None:
        with self._conn.cursor() as cur:
            cur.execute(_UPSERT_DOC, linha_documento(doc))

    def upsert_chunks(self, chunks: list[Chunk]) -> int:
        if not chunks:
            return 0
        with self._conn.cursor() as cur:
            cur.executemany(_UPSERT_CHUNK, [linha_chunk(c) for c in chunks])
        return len(chunks)

    def existe_documento(self, doc_id: str) -> bool:
        with self._conn.cursor() as cur:
            cur.execute("SELECT 1 FROM documentos WHERE id = %(id)s", {"id": doc_id})
            return cur.fetchone() is not None

    def buscar_lexico(self, query: str, limite: int = 8) -> list[dict]:
        with self._conn.cursor() as cur:
            cur.execute(_BUSCA_LEXICA, {"q": query, "limite": limite})
            colunas = [d.name for d in cur.description]
            return [dict(zip(colunas, linha)) for linha in cur.fetchall()]

    def close(self) -> None:
        self._conn.close()
