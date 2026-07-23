"""Arquivo de livro -> (Documento de Nível 1, TextoExtraido).

Responsabilidade única: montar o registro do documento original. A extração por
formato é de `sources.extract`; a árvore é de `pipeline.arvore`. Aqui não se
interpreta estrutura nenhuma.

O id vem da chave_externa (caminho absoluto do arquivo), não do hash do texto:
`chave_externa` é a identidade estável da obra, com índice UNIQUE no Postgres,
e reprocessar o mesmo arquivo precisa reaproveitar a linha de documento já
existente — nada do que já foi acumulado sobre ela (anotações semânticas de
K2-K4) pode ser perdido. `hash_sha256` continua sendo a coluna que revela se o
conteúdo mudou entre processamentos; ela não participa do id.
"""
from pathlib import Path

from forge.infrastructure.logging import get_logger
from forge.knowledge.domain.models import (
    Documento,
    Proveniencia,
    hash_texto,
    id_deterministico,
)
from forge.knowledge.sources.extract import (
    EXTENSOES_SUPORTADAS,
    TextoExtraido,
    extrair_arquivo,
)

logger = get_logger(__name__)

__all__ = ["EXTENSOES_SUPORTADAS", "carregar_livro"]


def carregar_livro(
    path: Path, *, ocr_enabled: bool = False
) -> tuple[Documento, TextoExtraido]:
    path = Path(path)
    extraido = extrair_arquivo(path, ocr_enabled=ocr_enabled)
    digest = hash_texto(extraido.texto)
    chave_externa = f"arquivo::{path.resolve()}"

    doc = Documento(
        id=id_deterministico("documento", chave_externa),
        hash_sha256=digest,
        titulo=path.stem,
        texto=extraido.texto,
        proveniencia=Proveniencia.de_livro(fonte=path.name, idioma=extraido.idioma),
        chave_externa=chave_externa,
    )
    logger.info("Livro carregado", fonte=path.name, chars=len(extraido.texto), doc=doc.id)
    return doc, extraido
