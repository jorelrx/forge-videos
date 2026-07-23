"""Orquestrador de ingestão: fonte -> estágios -> stores, ramificando por tipo.

As funções `enriquecer`/`persistir`/`ingerir_documentos` recebem model, embed_fn
e stores por injeção — dá para exercer o pipeline inteiro com fakes, sem LLM nem
Docker. As `ingerir_*` de topo montam as dependências reais a partir de Settings.
"""
from dataclasses import dataclass
from pathlib import Path

from forge.infrastructure.config import Settings
from forge.infrastructure.logging import get_logger
from forge.knowledge.domain.models import Chunk, Documento
from forge.knowledge.pipeline.chunk import chunk_documento
from forge.knowledge.pipeline.concepts import extrair_conceitos
from forge.knowledge.pipeline.embed import embed_chunks
from forge.knowledge.pipeline.entities import extrair_entidades
from forge.knowledge.pipeline.relations import extrair_relacionamentos
from forge.knowledge.pipeline.structure import aplicar_estrutura
from forge.knowledge.pipeline.summarize import resumir
from forge.knowledge.sources.remote import construir_fontes

logger = get_logger(__name__)


@dataclass
class Stores:
    """Trio de persistência. Qualquer objeto com a mesma interface serve (fakes)."""
    vector: object
    graph: object
    catalog: object

    def garantir_schema(self) -> None:
        self.catalog.garantir_schema()
        self.vector.garantir_colecao()
        self.graph.garantir_schema()


def _conceitos_por_unidade(model, doc: Documento) -> dict:
    """Uma chamada de conceitos por seção (ou uma para o doc inteiro se não há
    seções). Evita uma chamada LLM por chunk, que num livro seria centenas."""
    if doc.secoes:
        return {s.nome: [c.nome for c in extrair_conceitos(model, s.texto)] for s in doc.secoes}
    return {None: [c.nome for c in extrair_conceitos(model, doc.texto)]}


def enriquecer(
    model, doc: Documento, *, chunk_size: int, chunk_overlap: int
) -> tuple[Documento, list[Chunk]]:
    if doc.proveniencia.tipo == "livro":
        aplicar_estrutura(doc)  # web não tem estrutura de livro

    chunks = chunk_documento(doc, chunk_size=chunk_size, chunk_overlap=chunk_overlap)

    doc.resumo = resumir(model, doc.texto)
    doc.entidades = extrair_entidades(model, doc.texto)
    doc.relacionamentos = extrair_relacionamentos(model, doc.texto, doc.entidades)

    mapa = _conceitos_por_unidade(model, doc)
    for chunk in chunks:
        chunk.conceitos = mapa.get(chunk.secao, mapa.get(None, []))

    logger.info(
        "Documento enriquecido", doc=doc.id, tipo=doc.proveniencia.tipo,
        chunks=len(chunks), entidades=len(doc.entidades),
    )
    return doc, chunks


def persistir(stores: Stores, embed_fn, doc: Documento, chunks: list[Chunk], *, batch: int) -> None:
    embed_chunks(chunks, embed_fn, batch=batch)
    stores.catalog.upsert_documento(doc)
    stores.catalog.upsert_chunks(chunks)
    stores.vector.upsert_chunks(chunks)
    stores.graph.upsert_documento(doc)


def ingerir_documentos(docs: list[Documento], *, model, embed_fn, stores: Stores, settings: Settings) -> int:
    k = settings.knowledge
    total = 0
    for doc in docs:
        doc, chunks = enriquecer(model, doc, chunk_size=k.chunk_size, chunk_overlap=k.chunk_overlap)
        persistir(stores, embed_fn, doc, chunks, batch=k.embedding_batch)
        total += len(chunks)
    logger.info("Ingestão concluída", documentos=len(docs), chunks=total)
    return total


# --- topo: monta dependências reais a partir de Settings ---------------------

def _montar(settings: Settings):
    from forge.knowledge.pipeline.embed import build_embed_fn, sonda_semantica
    from forge.knowledge.stores.catalog import CatalogStore
    from forge.knowledge.stores.graph import GraphStore
    from forge.knowledge.stores.vector import VectorStore
    from forge.llms.model import build_chat_model

    model = build_chat_model(settings)
    embed_fn = build_embed_fn(settings)
    sonda_semantica(embed_fn)  # gate: aborta antes de tocar os stores

    k = settings.knowledge
    stores = Stores(
        vector=VectorStore(k.qdrant_url, k.qdrant_collection, k.embedding_dim),
        graph=GraphStore(k.neo4j_uri, k.neo4j_user, k.neo4j_password),
        catalog=CatalogStore(k.postgres_dsn),
    )
    stores.garantir_schema()
    return model, embed_fn, stores


def ingerir_caminho(caminho: Path, settings: Settings) -> int:
    """Ingere um arquivo de livro ou todos os suportados de um diretório."""
    from forge.knowledge.sources.book import EXTENSOES_SUPORTADAS, carregar_livro

    caminho = Path(caminho)
    arquivos = (
        [p for p in caminho.rglob("*") if p.suffix.lower() in EXTENSOES_SUPORTADAS]
        if caminho.is_dir()
        else [caminho]
    )
    model, embed_fn, stores = _montar(settings)
    docs = [carregar_livro(p, ocr_enabled=settings.knowledge.ocr_enabled) for p in arquivos]
    return ingerir_documentos(docs, model=model, embed_fn=embed_fn, stores=stores, settings=settings)


def ingerir_resultados_busca(resultados: list[dict], settings: Settings) -> int:
    """Aprendizado contínuo: resultados de web_search viram biblioteca."""
    from forge.knowledge.sources.web import documentos_de_busca

    docs = documentos_de_busca(resultados)
    if not docs:
        return 0
    model, embed_fn, stores = _montar(settings)
    return ingerir_documentos(docs, model=model, embed_fn=embed_fn, stores=stores, settings=settings)


def ingerir_busca_remota(
    nomes_fontes: list[str],
    query: str,
    settings: Settings,
    *,
    limite: int | None = None,
    sobrescrever: bool = False,
) -> int:
    """Busca por tema nas fontes remotas, baixa e ingere pelo pipeline padrão.

    Por padrão não reingere obra já na base: consulta o catálogo (Postgres) e
    pula os já ingeridos, seguindo para o próximo da lista. `sobrescrever=True`
    desliga a checagem e reingere (upsert idempotente pelos mesmos ids).
    """
    from forge.knowledge.sources.remote.base import buscar_e_baixar
    from forge.knowledge.sources.remote.http import Http

    k = settings.knowledge
    limite = limite or k.remote_top_n
    fontes = construir_fontes(nomes_fontes, settings=settings)
    http = Http(cache_dir=k.cache_dir, rate_delay=k.remote_rate_delay, timeout=k.remote_timeout)

    if sobrescrever:
        ja_ingerido = None
    else:
        from forge.knowledge.stores.catalog import CatalogStore

        catalog = CatalogStore(k.postgres_dsn)
        catalog.garantir_schema()  # tabela documentos precisa existir para consultar
        ja_ingerido = catalog.existe_documento

    # Tradutor só é montado se alguma fonte declara idioma_busca (ex: SEP só-inglês).
    traduzir_fn = None
    if any(getattr(f, "idioma_busca", None) for f in fontes):
        from forge.knowledge.pipeline.translate import traduzir as _traduzir
        from forge.llms.model import build_chat_model

        model = build_chat_model(settings)
        traduzir_fn = lambda texto, idioma: _traduzir(model, texto, idioma)

    docs = buscar_e_baixar(
        fontes, query, limite=limite, http=http,
        ja_ingerido=ja_ingerido if ja_ingerido is not None else (lambda _c: False),
        max_paginas=k.remote_max_pages,
        traduzir=traduzir_fn,
    )
    if not docs:
        logger.info("Busca remota sem documentos novos", fontes=nomes_fontes, query=query[:60])
        return 0
    model, embed_fn, stores = _montar(settings)
    return ingerir_documentos(docs, model=model, embed_fn=embed_fn, stores=stores, settings=settings)
