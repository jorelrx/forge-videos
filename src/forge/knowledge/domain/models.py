"""Modelos da camada de conhecimento.

`Proveniencia` é o eixo do design: acompanha todo chunk e todo nó do grafo,
e é o que permite ao writer separar citação de livro (autoridade alta, fonte
primária real) de snippet de web (autoridade variável). Sem proveniência, a
biblioteca reintroduz o problema de fonte não-rastreável que ela existe para
resolver.
"""
from __future__ import annotations

import uuid
from typing import Literal

from pydantic import BaseModel, Field

TipoFonte = Literal["livro", "web"]
TipoEntidade = Literal["filosofo", "escola", "obra", "ideia", "conceito", "outro"]

# Autoridade padrão por tipo de fonte. Livro é fonte primária controlada;
# web é ponto de partida, não prova. O retriever usa isso para ordenar.
_AUTORIDADE_LIVRO = 1.0
_AUTORIDADE_WEB = 0.4

_NAMESPACE = uuid.UUID("6f9b2c1e-0d3a-4a1b-9c7e-2f8a1b3c4d5e")


def id_deterministico(*partes: str) -> str:
    """UUID estável a partir das partes — mesma entrada, mesmo id.

    Ingestão idempotente depende disso: reingerir o mesmo documento sobrescreve
    os mesmos pontos no Qdrant em vez de duplicar.
    """
    return str(uuid.uuid5(_NAMESPACE, "::".join(partes)))


class Proveniencia(BaseModel):
    tipo: TipoFonte
    fonte: str
    autor: str | None = None
    obra: str | None = None
    capitulo: str | None = None
    url: str | None = None
    data: str | None = None
    idioma: str | None = None
    autoridade: float = Field(ge=0.0, le=1.0)

    @classmethod
    def de_livro(
        cls,
        fonte: str,
        autor: str | None = None,
        obra: str | None = None,
        capitulo: str | None = None,
    ) -> Proveniencia:
        return cls(
            tipo="livro", fonte=fonte, autor=autor, obra=obra,
            capitulo=capitulo, autoridade=_AUTORIDADE_LIVRO,
        )

    @classmethod
    def de_web(
        cls, url: str, titulo: str | None = None, data: str | None = None
    ) -> Proveniencia:
        return cls(
            tipo="web", fonte="web_search", obra=titulo, url=url,
            data=data, autoridade=_AUTORIDADE_WEB,
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
        autoridade: float,
    ) -> Proveniencia:
        return cls(
            tipo="livro", fonte=fonte, autor=autor, obra=obra,
            url=url, idioma=idioma, autoridade=autoridade,
        )


class Secao(BaseModel):
    """Capítulo ou subcapítulo — só livro tem. `nivel`: 1=capítulo, 2=subcapítulo."""
    nome: str
    nivel: int = 1
    texto: str = ""


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
    id: str
    titulo: str
    texto: str
    proveniencia: Proveniencia
    secoes: list[Secao] = Field(default_factory=list)
    resumo: str | None = None
    entidades: list[Entidade] = Field(default_factory=list)
    relacionamentos: list[Relacionamento] = Field(default_factory=list)


class Chunk(BaseModel):
    documento_id: str
    ordem: int
    texto: str
    proveniencia: Proveniencia
    secao: str | None = None
    conceitos: list[str] = Field(default_factory=list)
    embedding: list[float] | None = None

    @property
    def id(self) -> str:
        return id_deterministico(self.documento_id, str(self.ordem))
