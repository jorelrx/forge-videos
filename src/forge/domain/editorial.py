from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, model_validator


TextoEditorial = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=400)]


class PropostaEditorial(BaseModel):
    model_config = ConfigDict(extra="forbid")

    titulo: TextoEditorial
    situacao: TextoEditorial
    pergunta: TextoEditorial
    virada: TextoEditorial
    fecho: TextoEditorial
    thumbnail: TextoEditorial
    fonte: TextoEditorial

    def diretrizes(self) -> str:
        return (
            "Desenvolva a proposta escolhida e sustente as atribuições no acervo.\n"
            f"Título de trabalho: {self.titulo}\n"
            f"Situação de abertura: {self.situacao}\n"
            f"Pergunta que o vídeo responde: {self.pergunta}\n"
            f"Virada filosófica: {self.virada}\n"
            f"Retorno à abertura no fecho: {self.fecho}\n"
            f"Direção de thumbnail: {self.thumbnail}\n"
            f"Caminho no acervo: {self.fonte}"
        )


class PropostasEditoriais(BaseModel):
    propostas: list[PropostaEditorial] = Field(min_length=2, max_length=3)

    @model_validator(mode="after")
    def recortes_distintos(self):
        if len({p.pergunta.casefold() for p in self.propostas}) != len(self.propostas):
            raise ValueError("Cada proposta precisa de uma pergunta diferente")
        return self


class EscolhaEditorial(BaseModel):
    artefato_id: str = Field(min_length=1)
    indice: int = Field(ge=0, le=2)


class AberturaAprovada(BaseModel):
    previa_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")


class DecisaoAbertura(BaseModel):
    artefato_id: str = Field(min_length=1)
    acao: Literal["aprovar", "audio", "imagem"]
    item: str | None = Field(default=None, pattern=r"^[bi][0-9]+$")
    orientacao: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=1000)] | None = None

    @model_validator(mode="after")
    def alvo_valido(self):
        if self.acao == "aprovar" and (self.item is not None or self.orientacao is not None):
            raise ValueError("A aprovação não recebe ajustes")
        if self.acao == "audio" and (not (self.item or "").startswith("b") or self.orientacao is not None):
            raise ValueError("Selecione um bloco de narração para gerar outra leitura")
        if self.acao == "imagem" and not (self.item or "").startswith("i"):
            raise ValueError("Selecione uma imagem da abertura")
        return self
