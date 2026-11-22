"""Pauta aprovada no Board, como a execução a recebe."""
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, model_validator

TextoDecisao = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=1200)]


class PautaEpisodio(BaseModel):
    model_config = ConfigDict(extra="ignore")

    aprovacao_id: str = ""
    revisao: int = 0
    tema: str = ""
    titulo: str = ""
    pergunta: str = ""
    recorte: str = ""
    promessa: str = ""
    abertura: str = ""
    blocos: list[str] = Field(default_factory=list)
    desfecho: str = ""
    perguntas_pesquisa: list[str] = Field(default_factory=list)
    referencias: list[str] = Field(default_factory=list)

    def briefing_pesquisa(self) -> str:
        linhas = [f"Recorte aprovado: {self.recorte}" if self.recorte else "",
                  f"Promessa do episódio: {self.promessa}" if self.promessa else "",
                  *(f"Pergunta de pesquisa: {pergunta}" for pergunta in self.perguntas_pesquisa)]
        return "\n".join(linha for linha in linhas if linha)

    def diretrizes(self) -> str:
        secoes = [
            ("Título de trabalho", self.titulo), ("Público e pergunta central", self.pergunta),
            ("Recorte", self.recorte), ("Promessa", self.promessa), ("Abertura", self.abertura),
            ("Sequência de blocos", "\n".join(f"{i}. {b}" for i, b in enumerate(self.blocos, 1))),
            ("Desfecho", self.desfecho), ("Referências do criador", "; ".join(self.referencias)),
        ]
        corpo = "\n".join(f"{nome}: {valor}" for nome, valor in secoes if valor)
        return ("Siga a pauta aprovada pelo criador. Sustente as atribuições apenas no acervo; "
                "as referências do criador orientam o tema e não são fontes.\n" + corpo)


class ConferenciaPauta(BaseModel):
    model_config = ConfigDict(extra="forbid")

    compativel: bool
    explicacao: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=1200)]
    evidencias: list[str] = Field(default_factory=list, max_length=6)
    recorte_proposto: Annotated[str, StringConstraints(strip_whitespace=True, max_length=1200)] = ""
    promessa_proposta: Annotated[str, StringConstraints(strip_whitespace=True, max_length=1200)] = ""

    @model_validator(mode="after")
    def contradicao_traz_ajuste(self):
        if not self.compativel and not (self.recorte_proposto or self.promessa_proposta):
            raise ValueError("Uma contradição precisa propor recorte ou promessa")
        if not self.compativel and not self.evidencias:
            raise ValueError("Uma contradição precisa citar a evidência")
        return self


class ConflitoPauta(BaseModel):
    """O que o criador vê para decidir: a pauta, a evidência e o ajuste proposto."""
    promessa: str
    recorte: str
    explicacao: str
    evidencias: list[dict]
    recorte_proposto: str
    promessa_proposta: str


class DecisaoConflitoPauta(BaseModel):
    model_config = ConfigDict(extra="forbid")

    artefato_id: str = Field(min_length=1)
    acao: Literal["aceitar", "editar", "cancelar"]
    promessa: TextoDecisao | None = None
    recorte: TextoDecisao | None = None

    @model_validator(mode="after")
    def campos_da_acao(self):
        if self.acao == "editar" and not (self.promessa or self.recorte):
            raise ValueError("Edite a promessa ou o recorte")
        if self.acao != "editar" and (self.promessa or self.recorte):
            raise ValueError("Só a edição recebe promessa ou recorte")
        return self
