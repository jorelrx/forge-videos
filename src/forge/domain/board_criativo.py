from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, StringConstraints


Tipo = Literal["continuacao", "publico", "experimento"]
Curto = Annotated[str, StringConstraints(strip_whitespace=True, max_length=200)]
Texto = Annotated[str, StringConstraints(strip_whitespace=True, max_length=1200)]
Obrigatorio = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=1200)]


class PautaInicial(BaseModel):
    model_config = ConfigDict(extra="forbid")
    titulo: Curto = ""
    tema: Curto = ""
    pergunta: Texto = ""
    recorte: Texto = ""
    promessa: Texto = ""


class FonteBoard(BaseModel):
    id: str
    tipo: Literal["catalogo", "desempenho", "comentario"]
    titulo: str
    url: str
    texto: str | None = None
    publicado_em: str | None = None
    observacao: dict | None = None
    amostra: int | None = None


class PropostaModelo(BaseModel):
    model_config = ConfigDict(extra="forbid")
    tipo: Tipo
    pauta: PautaInicial
    diferenca: Obrigatorio
    justificativa: Obrigatorio
    referencias: list[Curto] = Field(max_length=3)


class PropostasModelo(BaseModel):
    model_config = ConfigDict(extra="forbid")
    propostas: list[PropostaModelo] = Field(min_length=3, max_length=3)


class Ideia(BaseModel):
    id: str
    tipo: Tipo
    pauta: PautaInicial
    diferenca: str
    justificativa: str
    referencias: list[FonteBoard]
    hipotese: bool
    motivo_descarte: str | None = None


class RascunhoBoard(BaseModel):
    revisao: int = 0
    posicionamento: str = ""
    propostas: list[Ideia] = Field(default_factory=list)
    guardadas: list[Ideia] = Field(default_factory=list)
    candidata: Ideia | None = None
    pauta: PautaInicial | None = None
    origem_pauta: Ideia | None = None
    analisado_em: str | None = None
    erro: Literal["analise_indisponivel"] | None = None

    def ideia(self, ideia_id: str) -> Ideia:
        candidatas = [self.candidata] if self.candidata else []
        for ideia in [*self.propostas, *self.guardadas, *candidatas]:
            if ideia.id == ideia_id and ideia.motivo_descarte is None:
                return ideia
        raise ValueError("Ideia indisponível neste rascunho.")


class Revisao(BaseModel):
    model_config = ConfigDict(extra="forbid")
    revisao: int = Field(ge=0)


class Posicionamento(Revisao):
    acao: Literal["posicionamento"]
    texto: Obrigatorio


class PautaManual(Revisao):
    acao: Literal["pauta"]
    pauta: PautaInicial


class DecisaoIdeia(Revisao):
    acao: Literal["guardar", "descartar", "desenvolver"]
    ideia_id: Curto
    motivo: Curto = ""


Comando = Annotated[Posicionamento | PautaManual | DecisaoIdeia, Field(discriminator="acao")]


class GerarSugestoes(Revisao):
    tipo: Literal["sugestoes"]
    atualizar: bool = False


class CombinarIdeias(Revisao):
    tipo: Literal["combinacao"]
    ideias: tuple[Curto, Curto]


Analise = Annotated[GerarSugestoes | CombinarIdeias, Field(discriminator="tipo")]
