"""Postgres: Nível 1 (documento original) + Nível 2 (árvore estrutural).

`tsvector` é gerado com o stemmer do idioma do documento. `CASE` com configs
literais é IMMUTABLE, que é o que uma generated column exige — passar o idioma
como coluna castada para regconfig não é.

Só o nível `paragrafo` tem `texto`: os outros derivam de `documentos.texto` pelos
offsets. Isso evita guardar o livro inteiro uma vez por nível e alinha o índice
léxico à granularidade do embedding.

`linha_documento` e `linha_chunk` são puras e testáveis sem servidor.
"""
from forge.infrastructure.logging import get_logger
from forge.knowledge.domain.models import Chunk, Documento

logger = get_logger(__name__)

_SCHEMA = """
CREATE TABLE IF NOT EXISTS documentos (
    id               TEXT PRIMARY KEY,
    hash_sha256      TEXT NOT NULL,
    chave_externa    TEXT,
    titulo           TEXT NOT NULL,
    texto            TEXT NOT NULL,
    tipo             TEXT NOT NULL,
    fonte            TEXT NOT NULL,
    autor            TEXT,
    obra             TEXT,
    edicao           TEXT,
    isbn             TEXT,
    licenca          TEXT,
    url              TEXT,
    idioma           TEXT,
    data_publicacao  TEXT,
    data_ingestao    TIMESTAMPTZ NOT NULL DEFAULT now(),
    autoridade       REAL NOT NULL
);
CREATE UNIQUE INDEX IF NOT EXISTS documentos_chave_externa_idx
    ON documentos (chave_externa) WHERE chave_externa IS NOT NULL;

CREATE TABLE IF NOT EXISTS chunks (
    id             TEXT PRIMARY KEY,
    documento_id   TEXT NOT NULL REFERENCES documentos(id) ON DELETE CASCADE,
    pai_id         TEXT REFERENCES chunks(id) ON DELETE CASCADE,
    nivel          TEXT NOT NULL,
    caminho        TEXT NOT NULL,
    ordem          INT  NOT NULL,
    titulo         TEXT,
    texto          TEXT,
    pagina         INT,
    offset_inicio  INT  NOT NULL,
    offset_fim     INT  NOT NULL,
    idioma         TEXT,
    tsv            tsvector GENERATED ALWAYS AS (
        CASE idioma
            WHEN 'en' THEN to_tsvector('english', coalesce(texto, ''))
            ELSE to_tsvector('portuguese', coalesce(texto, ''))
        END
    ) STORED
);
CREATE INDEX IF NOT EXISTS chunks_tsv_idx ON chunks USING GIN (tsv);
CREATE UNIQUE INDEX IF NOT EXISTS chunks_caminho_idx ON chunks (documento_id, caminho);
CREATE INDEX IF NOT EXISTS chunks_pai_idx ON chunks (pai_id);
"""

_UPSERT_DOC = """
INSERT INTO documentos (
    id, hash_sha256, chave_externa, titulo, texto, tipo, fonte, autor, obra,
    edicao, isbn, licenca, url, idioma, data_publicacao, autoridade
) VALUES (
    %(id)s, %(hash_sha256)s, %(chave_externa)s, %(titulo)s, %(texto)s, %(tipo)s,
    %(fonte)s, %(autor)s, %(obra)s, %(edicao)s, %(isbn)s, %(licenca)s, %(url)s,
    %(idioma)s, %(data_publicacao)s, %(autoridade)s
)
ON CONFLICT (id) DO NOTHING
"""

_UPSERT_CHUNK = """
INSERT INTO chunks (
    id, documento_id, pai_id, nivel, caminho, ordem, titulo, texto, pagina,
    offset_inicio, offset_fim, idioma
) VALUES (
    %(id)s, %(documento_id)s, %(pai_id)s, %(nivel)s, %(caminho)s, %(ordem)s,
    %(titulo)s, %(texto)s, %(pagina)s, %(offset_inicio)s, %(offset_fim)s, %(idioma)s
)
ON CONFLICT (id) DO NOTHING
"""


def linha_documento(doc: Documento) -> dict:
    p = doc.proveniencia
    return {
        "id": doc.id, "hash_sha256": doc.hash_sha256,
        "chave_externa": doc.chave_externa, "titulo": doc.titulo, "texto": doc.texto,
        "tipo": p.tipo, "fonte": p.fonte, "autor": p.autor, "obra": p.obra,
        "edicao": p.edicao, "isbn": p.isbn, "licenca": p.licenca, "url": p.url,
        "idioma": p.idioma, "data_publicacao": p.data_publicacao,
        "autoridade": p.autoridade,
    }


def linha_chunk(chunk: Chunk) -> dict:
    return {
        "id": chunk.id, "documento_id": chunk.documento_id, "pai_id": chunk.pai_id,
        "nivel": chunk.nivel, "caminho": chunk.caminho, "ordem": chunk.ordem,
        "titulo": chunk.titulo, "texto": chunk.texto, "pagina": chunk.pagina,
        "offset_inicio": chunk.offset_inicio, "offset_fim": chunk.offset_fim,
    }


class CatalogStore:
    def __init__(self, dsn: str):
        import psycopg

        self._conn = psycopg.connect(dsn, autocommit=True)

    def garantir_schema(self) -> None:
        with self._conn.cursor() as cur:
            cur.execute(_SCHEMA)
        logger.info("Schema Postgres garantido")

    def resetar(self) -> None:
        with self._conn.cursor() as cur:
            cur.execute("DROP TABLE IF EXISTS chunks, documentos CASCADE")
        logger.warning("Tabelas do catálogo removidas")
        self.garantir_schema()

    def upsert_documento(self, doc: Documento) -> None:
        with self._conn.cursor() as cur:
            cur.execute(_UPSERT_DOC, linha_documento(doc))

    def upsert_chunks(self, chunks: list[Chunk], *, idioma: str | None = None) -> int:
        if not chunks:
            return 0
        linhas = [{**linha_chunk(c), "idioma": idioma} for c in chunks]
        with self._conn.cursor() as cur:
            cur.executemany(_UPSERT_CHUNK, linhas)
        return len(chunks)

    def existe_chave_externa(self, chave: str) -> bool:
        """Dedup antes do download: a chave é conhecida pela referência da fonte,
        o hash só depois de baixar."""
        with self._conn.cursor() as cur:
            cur.execute(
                "SELECT 1 FROM documentos WHERE chave_externa = %(c)s", {"c": chave}
            )
            return cur.fetchone() is not None

    def contar_chunks(self) -> int:
        with self._conn.cursor() as cur:
            cur.execute("SELECT count(*) FROM chunks")
            return cur.fetchone()[0]

    def close(self) -> None:
        self._conn.close()
