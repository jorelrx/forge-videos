"""Orquestrador de ingestão: fonte -> árvore estrutural -> stores.

Sem LLM. K1 monta os Níveis 1 e 2 de docs/knowledge.md de forma determinística;
a análise semântica é de K2 em diante e escreve no Neo4j, não aqui.

`ingerir_entradas` recebe `embed_fn` e `stores` por injeção — o pipeline inteiro
roda com fakes, sem Docker. As `ingerir_*` de topo montam as dependências reais
a partir de Settings.
"""
from dataclasses import dataclass
from pathlib import Path

from forge.infrastructure.config import Settings
from forge.infrastructure.logging import get_logger
from forge.knowledge.domain.models import NIVEL_FOLHA, Documento
from forge.knowledge.pipeline.arvore import construir_arvore
from forge.knowledge.pipeline.embed import embed_chunks
from forge.knowledge.sources.extract import TextoExtraido, extrair_texto
from forge.knowledge.sources.remote import construir_fontes

logger = get_logger(__name__)

Entrada = tuple[Documento, TextoExtraido]


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

    def resetar(self) -> None:
        self.catalog.resetar()
        self.vector.resetar()
        self.graph.resetar()


def entrada_de_documento(doc: Documento) -> Entrada:
    """Documento sem arquivo (web, fonte remota): marcas vêm do próprio texto."""
    return doc, extrair_texto(doc.texto)


def ingerir_entradas(
    entradas: list[Entrada], *, embed_fn, stores: Stores, settings: Settings
) -> int:
    k = settings.knowledge
    total = 0
    for doc, extraido in entradas:
        chunks = construir_arvore(
            doc.id, extraido, paragrafo_min_chars=k.paragrafo_min_chars
        )
        folhas = [c for c in chunks if c.nivel == NIVEL_FOLHA]
        embed_chunks(folhas, embed_fn, batch=k.embedding_batch)

        stores.catalog.upsert_documento(doc)
        stores.catalog.upsert_chunks(chunks, idioma=doc.proveniencia.idioma)
        stores.vector.upsert_chunks(doc, chunks)

        total += len(folhas)
        logger.info(
            "Documento ingerido", doc=doc.id, nos=len(chunks),
            paragrafos=len(folhas), chars=len(doc.texto),
        )
    logger.info("Ingestão concluída", documentos=len(entradas), paragrafos=total)
    return total


# --- topo: monta dependências reais a partir de Settings ---------------------

def _montar(settings: Settings) -> tuple[object, Stores]:
    """Sem modelo de linguagem: K1 não faz nenhuma chamada de LLM."""
    from forge.knowledge.pipeline.embed import build_embed_fn, sonda_semantica
    from forge.knowledge.stores.catalog import CatalogStore
    from forge.knowledge.stores.graph import GraphStore
    from forge.knowledge.stores.vector import VectorStore

    embed_fn = build_embed_fn(settings)
    sonda_semantica(embed_fn)  # gate: aborta antes de tocar os stores

    k = settings.knowledge
    stores = Stores(
        vector=VectorStore(k.qdrant_url, k.qdrant_collection, k.embedding_dim),
        graph=GraphStore(k.neo4j_uri, k.neo4j_user, k.neo4j_password),
        catalog=CatalogStore(k.postgres_dsn),
    )
    stores.garantir_schema()
    return embed_fn, stores


def resetar_stores(settings: Settings) -> None:
    """Derruba e recria os três stores. Destrutivo e irreversível."""
    _, stores = _montar(settings)
    stores.resetar()
    logger.warning("Stores resetados")


def ingerir_caminho(caminho: Path, settings: Settings) -> int:
    """Write-once: um arquivo cuja `chave_externa` já está no catálogo é pulado,
    exatamente como a busca remota — nunca reingerido."""
    from forge.knowledge.sources.book import EXTENSOES_SUPORTADAS, carregar_livro

    caminho = Path(caminho)
    arquivos = (
        [p for p in caminho.rglob("*") if p.suffix.lower() in EXTENSOES_SUPORTADAS]
        if caminho.is_dir()
        else [caminho]
    )
    embed_fn, stores = _montar(settings)
    entradas = []
    for p in arquivos:
        doc, extraido = carregar_livro(p, ocr_enabled=settings.knowledge.ocr_enabled)
        if stores.catalog.existe_chave_externa(doc.chave_externa):
            logger.info("Arquivo já ingerido, pulando", fonte=p.name, doc=doc.id)
            continue
        entradas.append((doc, extraido))
    return ingerir_entradas(entradas, embed_fn=embed_fn, stores=stores, settings=settings)


def ingerir_busca_remota(
    nomes_fontes: list[str],
    query: str,
    settings: Settings,
    *,
    limite: int | None = None,
) -> int:
    """Busca por tema nas fontes remotas, baixa e ingere pelo pipeline padrão.

    Write-once: uma obra já na base nunca é reingerida. A dedup pré-download
    usa `chave_externa` (conhecida pela referência da fonte), não o id — o id
    vem da `chave_externa`, e o hash do texto só existe depois de baixar.
    """
    from forge.knowledge.sources.remote.base import buscar_e_baixar
    from forge.knowledge.sources.remote.http import Http
    from forge.knowledge.stores.catalog import CatalogStore

    k = settings.knowledge
    limite = limite or k.remote_top_n
    fontes = construir_fontes(nomes_fontes, settings=settings)
    http = Http(cache_dir=k.cache_dir, rate_delay=k.remote_rate_delay, timeout=k.remote_timeout)

    catalog = CatalogStore(k.postgres_dsn)
    catalog.garantir_schema()
    ja_ingerido = catalog.existe_chave_externa

    # Tradutor só é montado se alguma fonte declara idioma_busca (ex: SEP só-inglês).
    # É a única chamada de LLM que resta na camada, e traduz a query, nunca o conteúdo.
    traduzir_fn = None
    if any(getattr(f, "idioma_busca", None) for f in fontes):
        from forge.knowledge.pipeline.translate import traduzir as _traduzir
        from forge.llms.model import build_chat_model

        model = build_chat_model(settings)
        traduzir_fn = lambda texto, idioma: _traduzir(model, texto, idioma)

    docs = buscar_e_baixar(
        fontes, query, limite=limite, http=http,
        ja_ingerido=ja_ingerido,
        max_paginas=k.remote_max_pages,
        traduzir=traduzir_fn,
    )
    if not docs:
        logger.info("Busca remota sem documentos novos", fontes=nomes_fontes, query=query[:60])
        return 0
    embed_fn, stores = _montar(settings)
    entradas = [entrada_de_documento(d) for d in docs]
    return ingerir_entradas(entradas, embed_fn=embed_fn, stores=stores, settings=settings)
