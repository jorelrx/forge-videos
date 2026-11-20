"""Embalagem do vídeo: o que decide o clique e o que vai colado no YouTube.

Dois níveis. `EmbalagemProposta` é o que o modelo devolve — a parte criativa.
`Embalagem` é o artefato final: a proposta mais tudo que é fato e por isso sai
do código, não do modelo (capítulos com tempo, fontes, comentário fixado).
"""

from pydantic import BaseModel, Field


class TituloProposto(BaseModel):
    texto: str
    angulo: str = Field(
        default="",
        description="Ângulo do título: pergunta, contraintuitivo ou benefício.",
    )


class ThumbnailProposta(BaseModel):
    texto: str = Field(description="Até 4 palavras; complementa o título, não o repete.")
    prompt: str = Field(description="Prompt de imagem em inglês, 16:9, um sujeito focal.")


class RotuloCapitulo(BaseModel):
    secao: str = Field(description="Nome da seção do roteiro a que o rótulo pertence.")
    titulo: str = Field(description="Rótulo voltado ao espectador, até 40 caracteres.")


class EmbalagemProposta(BaseModel):
    titulos: list[TituloProposto] = Field(default_factory=list)
    thumbnail: ThumbnailProposta
    abertura: str = Field(description="Primeira linha da descrição, até 150 caracteres.")
    resumo: str = ""
    capitulos: list[RotuloCapitulo] = Field(default_factory=list)
    tags: list[str] = Field(default_factory=list)
    hashtags: list[str] = Field(default_factory=list)


class Capitulo(BaseModel):
    secao: str
    titulo: str
    inicio_segundos: int


class Embalagem(BaseModel):
    titulos: list[TituloProposto] = Field(default_factory=list)
    thumbnail: ThumbnailProposta
    descricao: str
    capitulos: list[Capitulo] = Field(default_factory=list)
    # Verdadeiro enquanto o tempo vier da contagem de palavras. A montagem troca
    # pelos tempos reais do áudio e desliga a marca.
    capitulos_estimados: bool = True
    tags: list[str] = Field(default_factory=list)
    hashtags: list[str] = Field(default_factory=list)
    comentario_fixado: str = ""
    fontes: list[str] = Field(default_factory=list)
    # Guardados para a montagem remontar a descrição com os tempos reais sem
    # chamar o modelo de novo. Vazios em embalagens gravadas antes disso.
    abertura: str = ""
    resumo: str = ""
    # Linha de crédito da trilha, quando a faixa escolhida traz uma.
    musica: str | None = None


__all__ = [
    "Capitulo", "Embalagem", "EmbalagemProposta", "RotuloCapitulo",
    "ThumbnailProposta", "TituloProposto",
]
