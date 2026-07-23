"""Modelos da camada Knowledge — Níveis 1 e 2 de docs/knowledge.md.

Duas árvores que nunca se misturam. Esta é a estrutural: derivada só do texto,
imutável, sem LLM. O grafo semântico (Conceito/Ideia/Argumento/Afirmação) vive
no Neo4j, referencia `chunk_id` e é escrito a partir de K3.

`Proveniencia` acompanha o documento e é o que separa citação de livro (fonte
primária) de snippet de web. Sem ela a biblioteca reintroduz o problema de fonte
não-rastreável que existe para resolver.
"""
from __future__ import annotations

import hashlib
import uuid
from typing import Literal

from pydantic import BaseModel, Field

TipoFonte = Literal["livro", "web"]
Nivel = Literal["livro", "capitulo", "subcapitulo", "secao", "paragrafo", "sentenca"]
TipoEntidade = Literal["filosofo", "escola", "obra", "ideia", "conceito", "outro"]

# Único nível embedado e com `texto` persistido (small-to-big). Os demais níveis
# guardam offsets e derivam o texto de `documentos.texto`.
NIVEL_FOLHA: Nivel = "paragrafo"

# Autoridade padrão por tipo de fonte. Livro é fonte primária controlada;
# web é ponto de partida, não prova.
_AUTORIDADE_LIVRO = 1.0
_AUTORIDADE_WEB = 0.4

_NAMESPACE = uuid.UUID("6f9b2c1e-0d3a-4a1b-9c7e-2f8a1b3c4d5e")

# Largura do segmento no caminho materializado. 4 dígitos deixam a ordem
# lexicográfica coincidir com a numérica até 9999 filhos por nó.
_LARGURA_CAMINHO = 4


def id_deterministico(*partes: str) -> str:
    """UUID estável a partir das partes — mesma entrada, mesmo id."""
    return str(uuid.uuid5(_NAMESPACE, "::".join(partes)))


def hash_texto(texto: str) -> str:
    return hashlib.sha256(texto.encode("utf-8")).hexdigest()


def id_de_chunk(documento_id: str, texto: str, ocorrencia: int) -> str:
    """Identidade por conteúdo, nunca por posição.

    A camada semântica acumula anotações sobre `chunk_id`. Se o id viesse da
    ordem, inserir um parágrafo no capítulo 1 invalidaria tudo que veio depois.
    `ocorrencia` desempata texto repetido no mesmo documento ('Ibid.').
    """
    return id_deterministico(documento_id, hash_texto(texto), str(ocorrencia))


def caminho_filho(caminho_pai: str, ordem: int) -> str:
    segmento = str(ordem).zfill(_LARGURA_CAMINHO)
    return f"{caminho_pai}.{segmento}" if caminho_pai else segmento


class Proveniencia(BaseModel):
    tipo: TipoFonte
    fonte: str
    autor: str | None = None
    obra: str | None = None
    edicao: str | None = None
    isbn: str | None = None
    licenca: str | None = None
    url: str | None = None
    data_publicacao: str | None = None
    idioma: str | None = None
    autoridade: float = Field(ge=0.0, le=1.0)

    @classmethod
    def de_livro(
        cls,
        fonte: str,
        autor: str | None = None,
        obra: str | None = None,
        edicao: str | None = None,
        isbn: str | None = None,
        licenca: str | None = None,
        idioma: str | None = None,
        data_publicacao: str | None = None,
    ) -> Proveniencia:
        return cls(
            tipo="livro", fonte=fonte, autor=autor, obra=obra, edicao=edicao,
            isbn=isbn, licenca=licenca, idioma=idioma,
            data_publicacao=data_publicacao, autoridade=_AUTORIDADE_LIVRO,
        )

    @classmethod
    def de_web(
        cls, url: str, titulo: str | None = None, data_publicacao: str | None = None
    ) -> Proveniencia:
        return cls(
            tipo="web", fonte="web_search", obra=titulo, url=url,
            data_publicacao=data_publicacao, autoridade=_AUTORIDADE_WEB,
        )

    @classmethod
    def de_fonte_remota(
        cls,
        *,
        fonte: str,
        autor: str | None = None,
        obra: str | None = None,
        url: str | None = None,
        idioma: str | None = None,
        licenca: str | None = None,
        autoridade: float,
    ) -> Proveniencia:
        return cls(
            tipo="livro", fonte=fonte, autor=autor, obra=obra, url=url,
            idioma=idioma, licenca=licenca, autoridade=autoridade,
        )


class Conceito(BaseModel):
    nome: str
    descricao: str | None = None


class Entidade(BaseModel):
    nome: str
    tipo: TipoEntidade = "outro"


class Relacionamento(BaseModel):
    origem: str
    tipo: str
    destino: str


class Documento(BaseModel):
    """Nível 1 — fonte da verdade. `texto` é a extração crua, nunca alterada.

    `chave_externa` identifica a obra na fonte de origem (`gutenberg::1234`) e
    permite pular o download de algo já ingerido, antes de existir hash.
    """
    id: str
    hash_sha256: str
    titulo: str
    texto: str
    proveniencia: Proveniencia
    chave_externa: str | None = None


class Chunk(BaseModel):
    """Nível 2 — nó da árvore estrutural.

    Sem proveniência própria: ela é do documento e é resolvida por join. O
    capítulo de um chunk é o ancestral de nível capítulo, resolvido pelo
    `caminho` — não é campo duplicado.
    """
    id: str
    documento_id: str
    pai_id: str | None = None
    nivel: Nivel
    caminho: str
    ordem: int
    titulo: str | None = None
    texto: str | None = None
    pagina: int | None = None
    offset_inicio: int
    offset_fim: int
    embedding: list[float] | None = None
