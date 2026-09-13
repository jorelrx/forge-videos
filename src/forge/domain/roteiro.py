"""Narrative contract shared by planning, writing and deterministic gates."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field


class NarrativeSection(BaseModel):
    """One of the nine stable narrative functions of a script.

    The object is frozen because changing the order or meaning halfway through
    a run would make old artifacts impossible to validate consistently.
    """

    model_config = ConfigDict(frozen=True)

    nome: str
    papel: str
    instrucao: str
    alvo_palavras: tuple[int, int] = Field(min_length=2)
    abre_loop: bool = False
    fecha_loop: bool = False
    rehook: bool = False
    pergunta_publico: bool = False


ARQUITETURA: tuple[NarrativeSection, ...] = (
    NarrativeSection(
        nome="Gancho", papel="tensão imediata",
        instrucao="Abra com uma imagem ou pergunta concreta, sem explicar o tema.",
        alvo_palavras=(20, 90), abre_loop=True, rehook=True,
    ),
    NarrativeSection(
        nome="Estake", papel="aposta do problema",
        instrucao="Mostre o que está em jogo para a vida de quem assiste.",
        alvo_palavras=(20, 110), abre_loop=True,
    ),
    NarrativeSection(
        nome="Tensao", papel="complicação",
        instrucao="Aumente o conflito com um caso ou contradição verificável.",
        alvo_palavras=(20, 110), abre_loop=True,
    ),
    NarrativeSection(
        nome="Virada", papel="mudança de lente",
        instrucao="Faça a virada que reorganiza o problema e a pergunta central.",
        alvo_palavras=(20, 110), abre_loop=True,
    ),
    NarrativeSection(
        nome="Filosofo", papel="ideia encarnada",
        instrucao="Apresente o filósofo por meio de uma ideia ancorada no acervo.",
        alvo_palavras=(20, 130), abre_loop=True,
    ),
    NarrativeSection(
        nome="Prova", papel="concretização",
        instrucao="Teste a tese com um exemplo, evidência ou situação observável.",
        alvo_palavras=(20, 110), abre_loop=True,
    ),
    NarrativeSection(
        nome="Espelho", papel="implicação pessoal",
        instrucao="Devolva o argumento ao público com uma pergunta final aberta.",
        alvo_palavras=(20, 100), abre_loop=True, pergunta_publico=True,
    ),
    NarrativeSection(
        nome="Aplicacao", papel="próximo gesto",
        instrucao="Converta a tese em uma ação pequena e praticável.",
        alvo_palavras=(20, 100), abre_loop=True,
    ),
    NarrativeSection(
        nome="Fecho", papel="retorno transformado",
        instrucao="Feche o loop do Gancho transformando a pergunta inicial.",
        alvo_palavras=(20, 90), fecha_loop=True,
    ),
)


SECOES_NOMES: list[str] = [section.nome for section in ARQUITETURA]


__all__ = ["ARQUITETURA", "SECOES_NOMES", "NarrativeSection"]
