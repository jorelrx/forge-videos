"""Embeddings via sentence-transformers + gate de validação semântica.

Por que o gate existe: modelo errado, dimensão trocada ou pesos corrompidos
podem devolver vetor sem sinal nenhum sem levantar erro. Validar por 'não-nulo'
não pega isso. A sonda mede o que importa: texto idêntico tem que colar (cos~1)
e texto distinto tem que separar (cos baixo). Falhou, aborta a ingestão em vez
de encher a biblioteca de vetores lixo. Validar por sonda semântica, nunca por
métrica cega de magnitude.
"""
import math
from collections.abc import Callable

from forge.infrastructure.config import Settings
from forge.infrastructure.logging import get_logger
from forge.knowledge.domain.models import Chunk

logger = get_logger(__name__)

EmbedFn = Callable[[list[str]], list[list[float]]]

# Limiares da sonda. Idêntico deve colar forte; distinto deve separar claro.
_COS_IDENTICO_MIN = 0.98
_COS_DISTINTO_MAX = 0.95

_SONDA = ["o gato dorme no telhado", "o gato dorme no telhado", "teoria quântica de campos"]

class EmbeddingInvalido(RuntimeError):
    """Embeddings falharam a validação — vetores não carregam sinal semântico."""


def _norma(v: list[float]) -> float:
    return math.sqrt(sum(x * x for x in v))

def _cos(a: list[float], b: list[float]) -> float:
    na, nb = _norma(a), _norma(b)
    if na == 0 or nb == 0:
        return 0.0
    return sum(x * y for x, y in zip(a, b)) / (na * nb)

def _degenerado(vetores: list[list[float]]) -> bool:
    """Vetor nulo ou constante não carrega informação."""
    for v in vetores:
        if _norma(v) == 0:
            return True
        if len(set(v)) == 1:
            return True
    return False

_DICA = (
    "Embeddings inválidos. Confira FORGE_KNOWLEDGE__EMBEDDING_MODEL e "
    "EMBEDDING_DIM — modelo errado ou dimensão trocada é a causa comum."
)

def sonda_semantica(embed_fn: EmbedFn) -> None:
    """Gate de startup: roda antes de embedar o corpus. Levanta se o embedder mente."""
    vecs = embed_fn(_SONDA)
    if len(vecs) != len(_SONDA):
        raise EmbeddingInvalido(f"{_DICA} (contagem: {len(vecs)} != {len(_SONDA)})")
    if _degenerado(vecs):
        raise EmbeddingInvalido(f"{_DICA} (vetor nulo/constante)")

    cos_identico = _cos(vecs[0], vecs[1])
    cos_distinto = _cos(vecs[0], vecs[2])
    if cos_identico < _COS_IDENTICO_MIN:
        raise EmbeddingInvalido(
            f"{_DICA} (texto idêntico não colou: cos={cos_identico:.3f})"
        )
    if cos_distinto > _COS_DISTINTO_MAX:
        raise EmbeddingInvalido(
            f"{_DICA} (colapso: distinto ~ idêntico, cos={cos_distinto:.3f})"
        )
    logger.info(
        "Sonda de embeddings ok", cos_identico=round(cos_identico, 3),
        cos_distinto=round(cos_distinto, 3),
    )

def embed_chunks(chunks: list[Chunk], embed_fn: EmbedFn, *, batch: int) -> list[Chunk]:
    """Preenche `chunk.embedding` em lotes. Aborta se algum lote sair degenerado."""
    for inicio in range(0, len(chunks), batch):
        lote = chunks[inicio : inicio + batch]
        vetores = embed_fn([c.texto for c in lote])
        if len(vetores) != len(lote) or _degenerado(vetores):
            raise EmbeddingInvalido(f"{_DICA} (lote em offset {inicio})")
        for chunk, vetor in zip(lote, vetores):
            chunk.embedding = vetor
    logger.info("Chunks embedados", total=len(chunks))
    return chunks

def build_embed_fn(settings: Settings) -> EmbedFn:
    """Embedder via sentence-transformers na CPU. Modelo local, sem serviço externo.

    O gate `sonda_semantica` roda depois — modelo/dimensão trocados são pegos
    lá antes de sujar os stores.
    """
    from sentence_transformers import SentenceTransformer

    st = SentenceTransformer(settings.knowledge.embedding_model, device="cpu")
    return lambda textos: [v.tolist() for v in st.encode(list(textos))]
