from langchain_core.messages import HumanMessage

from forge.infrastructure.logging import get_logger
from forge.llms.parsing import MARCADOR_LISTA
from forge.prompts.loader import load_prompt
from forge.domain.models import ReviewResult, Roteiro
from forge.skills.loader import load_skills

logger = get_logger(__name__)

SKILLS = ["story", "retention", "fact_check"]
LE = ["roteiro", "rounds"]

# Palavras que o modelo emite como resposta de checklist. Um item que é só isso
# nunca foi uma alegação.
#
# "na" fica de fora de propósito: é a grafia de "n/a" que já está na lista,
# mas colide com a contração portuguesa comum ("na obra", "na carta") — uma
# alegação real começando por ela seria descartada por engano.
_RESPOSTAS = {"sim", "nao", "não", "ok", "n/a", "nenhum", "nenhuma", "-"}

# Pontuação que pode grudar na palavra de abertura de uma resposta de
# checklist ("Sim,", "OK.", "Sim?"). Removida dos dois lados antes de
# comparar com _RESPOSTAS — uma vírgula sozinha bastaria para reintroduzir o
# problema que esta função existe para resolver.
#
# `*` e `_` porque o modelo enfatiza a resposta do checklist em markdown
# (`**Sim** (carro volta)` saiu do run real); as aspas curvas porque ele
# também as usa no lugar das retas (`“Sim, carro volta no fim.”`). Sem elas a
# decoração blindava o item, ele sobrevivia como alegação, e cada falso
# positivo custa ~50 min de GPU e uma linha de lixo no arquivo de lacunas do
# usuário.
_PONTUACAO_BORDA = ".,;:!?\"'*_“”‘’«»"


def alegacoes_reais(itens: list[str]) -> list[str]:
    """Descarta o que não é alegação factual.

    O prompt já pede afirmações, mas o modelo local reincide no checklist, e cada
    item falso manda o roteiro para outra volta de pesquisa (~50 min nesta
    máquina). Três regras, todas conservadoras: o que sobra tem de ser uma frase
    afirmativa com algum conteúdo.

    O checklist chega como pares pergunta/resposta. A regra de "?" já derruba a
    pergunta; sobra a resposta como fragmento órfão — sempre curta, sempre
    aberta pela palavra de resposta, às vezes com um parêntese colado ("Sim
    (carro volta)") ou pontuação colada ("Sim,", "OK."). Por isso a primeira
    regra olha só a palavra de abertura, não o item inteiro, e trava atrás de
    um teto de tamanho de seis palavras.

    Esse teto é deliberado, não um acidente de calibração: um item com menos
    de seis palavras que abre com uma palavra de resposta é descartado mesmo
    quando parece um veredito negativo de verdade — "Não há registro.", "Não
    confere isso." Duas razões. Primeiro, `verificar` existe para alegações
    que o ROTEIRO faz ("Hume disse X"), não para o veredito do revisor sobre
    o roteiro; um veredito como "Não há registro." é da alçada de `notas`,
    que o revisor já preenche. Segundo, o custo é assimétrico nesta máquina:
    manter por engano custa uma rodada inteira de pesquisa (~50 min de GPU) e
    uma busca sem sentido no acervo; descartar por engano custa uma alegação
    não conferida, que a próxima rodada de review ainda pode pegar. Uma
    negativa de verdade só sobrevive à regra 1 se tiver seis palavras ou
    mais, como "Não há registro de que Hume tenha escrito isso." — sem esse
    teto a regra comeria alegação real, que é pior do que deixar passar um
    item de checklist.
    """
    mantidas: list[str] = []
    for bruto in itens:
        item = bruto.strip()
        if not item:
            continue
        # O marcador de lista tem de sair ANTES de olhar a palavra de abertura:
        # em "1. Sim, o carro volta" a palavra 1 é o marcador, não a resposta,
        # e o item escapava inteiro da regra. Mesmo regex que o parser de
        # queries usa (`llms/parsing`), não uma cópia — é o mesmo modelo
        # emitindo a mesma decoração. A contagem de palavras também é feita
        # sobre o item nu, para que o marcador não empurre uma negativa curta
        # por cima do teto de seis.
        palavras = MARCADOR_LISTA.sub("", item).split()
        if not palavras:
            # Só o marcador, nada mais ("-", "*", "1.").
            logger.debug("Item de verificar descartado: só marcador", item=item)
            continue
        abertura = palavras[0].casefold().strip(_PONTUACAO_BORDA)
        if abertura in _RESPOSTAS and len(palavras) < 6:
            logger.debug("Item de verificar descartado: resposta de checklist", item=item)
            continue
        if item.endswith("?"):
            # Uma pergunta é a metade errada de um checklist: alegação é
            # afirmação, e o prompt agora pede exatamente isso.
            logger.debug("Item de verificar descartado: pergunta", item=item)
            continue
        if len(palavras) < 3:
            logger.debug("Item de verificar descartado: curto demais", item=item)
            continue
        mantidas.append(item)
    return mantidas


def revisar(model, roteiro: Roteiro) -> ReviewResult:
    logger.debug("Starting review phase", tema=roteiro.tema[:50] + "..." if len(roteiro.tema) > 50 else roteiro.tema)
    prompt = load_prompt("review").format(
        roteiro=_render(roteiro), skills=load_skills(SKILLS, "review")
    )
    result = model.with_structured_output(ReviewResult).invoke([HumanMessage(content=prompt)])
    filtradas = alegacoes_reais(result.verificar)
    if len(filtradas) != len(result.verificar):
        logger.info(
            "Itens de verificar descartados",
            descartados=len(result.verificar) - len(filtradas),
            mantidos=len(filtradas),
        )
    result.verificar = filtradas
    logger.info("Review completed", aprovado=result.aprovado, num_notas=len(result.notas))
    return result


def _render(roteiro: Roteiro) -> str:
    partes = [f"Tese: {roteiro.tese}", ""]
    for s in roteiro.secoes:
        partes.append(f"## {s.nome}\n{s.conteudo}\n")
    return "\n".join(partes)
