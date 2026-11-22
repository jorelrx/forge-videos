from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, field_validator


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


class Pauta(PautaInicial):
    """A pauta editável do episódio. Campos novos têm padrão: rascunhos antigos continuam válidos."""
    abertura: Texto = ""
    blocos: list[Texto] = Field(default_factory=list, max_length=12)
    desfecho: Texto = ""
    perguntas_pesquisa: list[Curto] = Field(default_factory=list, max_length=8)
    referencias: list[Curto] = Field(default_factory=list, max_length=10)

    @field_validator("blocos", "perguntas_pesquisa", "referencias")
    @classmethod
    def sem_itens_vazios(cls, itens: list[str]) -> list[str]:
        return [item for item in itens if item]

    def vazia(self) -> bool:
        return not any(self.model_dump().values())


CAMPOS_PAUTA = ("tema", "titulo", "pergunta", "recorte", "promessa", "abertura", "blocos", "desfecho",
                "perguntas_pesquisa", "referencias")
CAMPOS_LISTA = frozenset({"blocos", "perguntas_pesquisa", "referencias"})
CampoPauta = Literal["tema", "titulo", "pergunta", "recorte", "promessa", "abertura", "blocos", "desfecho",
                     "perguntas_pesquisa", "referencias"]
ValorCampo = str | list[str]


class AlteracaoCampo(BaseModel):
    campo: CampoPauta
    anterior: ValorCampo
    valor: ValorCampo


class MensagemBoard(BaseModel):
    id: str
    autor: Literal["criador", "ia"]
    texto: str
    criada_em: str
    base_revisao: int | None = None
    alteracoes: list[AlteracaoCampo] = Field(default_factory=list)
    aplicadas: list[str] = Field(default_factory=list)


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
    pauta: Pauta | None = None
    origem_pauta: Ideia | None = None
    fluxo_id: str | None = None
    conversa: list[MensagemBoard] = Field(default_factory=list)
    analisado_em: str | None = None
    erro: Literal["analise_indisponivel"] | None = None

    def ideia(self, ideia_id: str) -> Ideia:
        candidatas = [self.candidata] if self.candidata else []
        for ideia in [*self.propostas, *self.guardadas, *candidatas]:
            if ideia.id == ideia_id and ideia.motivo_descarte is None:
                return ideia
        raise ValueError("Ideia indisponível neste rascunho.")

    def mensagem(self, mensagem_id: str) -> MensagemBoard:
        for mensagem in self.conversa:
            if mensagem.id == mensagem_id and mensagem.autor == "ia":
                return mensagem
        raise ValueError("Sugestão indisponível nesta conversa.")


class Revisao(BaseModel):
    model_config = ConfigDict(extra="forbid")
    revisao: int = Field(ge=0)


class Posicionamento(Revisao):
    acao: Literal["posicionamento"]
    texto: Obrigatorio


class PautaManual(Revisao):
    acao: Literal["pauta"]
    pauta: Pauta


class DecisaoIdeia(Revisao):
    acao: Literal["guardar", "descartar", "desenvolver"]
    ideia_id: Curto
    motivo: Curto = ""


class EscolhaFluxo(Revisao):
    acao: Literal["fluxo"]
    fluxo_id: Curto


class RemoverGuardada(Revisao):
    acao: Literal["remover_guardada"]
    ideia_id: Curto


class AplicarSugestao(Revisao):
    acao: Literal["aplicar_sugestao"]
    mensagem_id: Curto
    campos: list[CampoPauta] = Field(min_length=1)


Comando = Annotated[Posicionamento | PautaManual | DecisaoIdeia | EscolhaFluxo | RemoverGuardada | AplicarSugestao,
                    Field(discriminator="acao")]


class GerarSugestoes(Revisao):
    tipo: Literal["sugestoes"]
    atualizar: bool = False


class CombinarIdeias(Revisao):
    tipo: Literal["combinacao"]
    ideias: tuple[Curto, Curto]


class Conversar(Revisao):
    tipo: Literal["conversa"]
    mensagem: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=2000)]


Analise = Annotated[GerarSugestoes | CombinarIdeias | Conversar, Field(discriminator="tipo")]
