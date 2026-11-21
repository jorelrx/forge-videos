from typing import Annotated

from pydantic import BaseModel, ConfigDict, StringConstraints

FluxoId = Annotated[str, StringConstraints(pattern=r"^[a-z0-9-]{1,64}$")]
NomeFluxo = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=80)]
DescricaoFluxo = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=240)]
InstrucoesFluxo = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=4000)]

FLUXO_PADRAO = "padrao"


class NovoFluxoGeracao(BaseModel):
    model_config = ConfigDict(extra="forbid")

    nome: NomeFluxo
    descricao: DescricaoFluxo
    instrucoes: InstrucoesFluxo


class FluxoGeracao(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    id: FluxoId
    nome: NomeFluxo
    descricao: DescricaoFluxo
    instrucoes: InstrucoesFluxo | None = None


FLUXOS_INICIAIS = (
    FluxoGeracao(
        id=FLUXO_PADRAO,
        nome="Padrão",
        descricao="Roteiro atual com tese, evidências do acervo e fechamento reflexivo.",
    ),
    FluxoGeracao(
        id="comentarios",
        nome="Comentários",
        descricao="Apresenta um dilema e convida o público a compartilhar uma escolha ou experiência.",
        instrucoes=(
            "Planeje um dilema concreto com duas reações plausíveis e explore o que está em jogo. "
            "No Espelho, termine com uma pergunta específica sobre a decisão ou a experiência do público. "
            "No Fecho, resolva o gancho e convide o público uma única vez a responder nos comentários. "
            "Evite perguntas genéricas, pedidos de palavras-chave e polêmica fabricada. "
            "Na revisão, confira se o convite decorre da tese e se a pergunta pode ser respondida "
            "com um exemplo ou uma escolha justificada."
        ),
    ),
    FluxoGeracao(
        id="gancho-inicial",
        nome="Gancho inicial",
        descricao="Começa com tensão na primeira frase e cumpre a promessa da abertura no Fecho.",
        instrucoes=(
            "Planeje uma cena em andamento, uma decisão difícil ou uma contradição específica "
            "que exponha a tensão na primeira frase falada. No Gancho, corte saudações e preâmbulos "
            "e deixe clara a pergunta que o vídeo vai responder. No Estake, mostre logo a consequência "
            "concreta. No Fecho, cumpra a promessa com uma resposta sustentada pela pesquisa. "
            "Na revisão, confira a primeira frase, a relação da abertura com a tese e a resolução "
            "no Fecho. Evite promessas exageradas e suspense artificial."
        ),
    ),
)
