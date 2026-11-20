"""Narrative contract shared by planning, writing and deterministic gates."""

from __future__ import annotations

import unicodedata

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


# Alvos em palavras para um vídeo de 11 a 16 minutos (150 palavras/min): a soma
# dos mínimos é 1.600 e a dos máximos 2.450. Os alvos antigos (20-130 por seção)
# rendiam ~1.200 palavras, abaixo dos 8 minutos que o YouTube exige para anúncio
# no meio do vídeo. Desenvolvimento (Filosofo, Prova) leva a maior fatia; Gancho
# fica curto de propósito — é onde a retenção cai mais rápido.
ARQUITETURA: tuple[NarrativeSection, ...] = (
    NarrativeSection(
        nome="Gancho", papel="tensão imediata",
        instrucao=(
            "Entre direto numa cena ou tensão concreta dirigida a \"você\", sem "
            "saudação nem apresentação do tema. Prometa o que a pessoa leva ao "
            "final, sem entregar."
        ),
        alvo_palavras=(60, 110), abre_loop=True, rehook=True,
    ),
    NarrativeSection(
        nome="Estake", papel="aposta do problema",
        instrucao="Mostre o que está em jogo para a vida de quem assiste.",
        alvo_palavras=(130, 220), abre_loop=True,
    ),
    NarrativeSection(
        nome="Tensao", papel="complicação",
        instrucao="Aumente o conflito com um caso ou contradição verificável.",
        alvo_palavras=(180, 280), abre_loop=True,
    ),
    NarrativeSection(
        nome="Virada", papel="mudança de lente",
        instrucao="Faça a virada que reorganiza o problema e a pergunta central.",
        alvo_palavras=(180, 280), abre_loop=True,
    ),
    NarrativeSection(
        nome="Filosofo", papel="ideia encarnada",
        instrucao=(
            "Apresente o filósofo por meio de uma ideia ancorada no acervo e "
            "levante a objeção mais forte contra ela."
        ),
        alvo_palavras=(260, 380), abre_loop=True,
    ),
    NarrativeSection(
        nome="Prova", papel="concretização",
        instrucao=(
            "Teste a tese com um exemplo, evidência ou situação observável e "
            "responda à objeção pelo seu melhor lado."
        ),
        alvo_palavras=(280, 400), abre_loop=True,
    ),
    NarrativeSection(
        nome="Espelho", papel="implicação pessoal",
        instrucao="Devolva o argumento ao público com uma pergunta final aberta.",
        alvo_palavras=(180, 280), abre_loop=True, pergunta_publico=True,
    ),
    NarrativeSection(
        nome="Aplicacao", papel="próximo gesto",
        instrucao="Converta a tese em uma prática pequena que dê para fazer hoje.",
        alvo_palavras=(220, 320), abre_loop=True,
    ),
    NarrativeSection(
        nome="Fecho", papel="retorno transformado",
        instrucao=(
            "Feche o loop do Gancho transformando a pergunta inicial e termine "
            "com um convite suave a continuar pensando."
        ),
        alvo_palavras=(110, 180), fecha_loop=True,
    ),
)


SECOES_NOMES: list[str] = [section.nome for section in ARQUITETURA]


def _chave_de_nome(nome: str) -> str:
    """Chave de comparação: sem acento, sem caixa, sem espaço nas pontas."""
    decomposto = unicodedata.normalize("NFKD", nome.strip().casefold())
    return "".join(caractere for caractere in decomposto if not unicodedata.combining(caractere))


_POR_CHAVE: dict[str, str] = {_chave_de_nome(nome): nome for nome in SECOES_NOMES}


def canonizar_nome(nome: str) -> str:
    """Nome canônico da seção, tolerando acento e caixa que o modelo escreve.

    O contrato é um conjunto fechado sem acento (`Tensao`, `Filosofo`,
    `Aplicacao`), mas o modelo escreve o português correto — `Tensão`. Sem esta
    canonização na fronteira, o gate lia "seção ausente nas nove", pulava a
    checagem de todas as outras e a run morria em `script_gate_failed` por causa
    de um acento. Nome fora do contrato volta como veio: descartar ou inventar
    esconderia o desvio.
    """
    return _POR_CHAVE.get(_chave_de_nome(nome), nome.strip())


__all__ = ["ARQUITETURA", "SECOES_NOMES", "NarrativeSection", "canonizar_nome"]
