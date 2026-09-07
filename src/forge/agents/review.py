from langchain_core.messages import HumanMessage

from forge.infrastructure.logging import get_logger
from forge.prompts.loader import load_prompt
from forge.domain.models import ReviewResult, Roteiro
from forge.skills.loader import load_skills

logger = get_logger(__name__)

SKILLS = ["story", "retention", "fact_check"]
LE = ["roteiro", "rounds"]

# Palavras que o modelo emite como resposta de checklist. Um item que é só isso
# nunca foi uma alegação.
_RESPOSTAS = {"sim", "nao", "não", "ok", "n/a", "na", "nenhum", "nenhuma", "-"}


def alegacoes_reais(itens: list[str]) -> list[str]:
    """Descarta o que não é alegação factual.

    O prompt já pede afirmações, mas o modelo local reincide no checklist, e cada
    item falso manda o roteiro para outra volta de pesquisa (~50 min nesta
    máquina). Três regras, todas conservadoras: o que sobra tem de ser uma frase
    afirmativa com algum conteúdo.

    O checklist chega como pares pergunta/resposta. A regra de "?" já derruba a
    pergunta; sobra a resposta como fragmento órfão — sempre curta, sempre
    aberta pela palavra de resposta, às vezes com um parêntese colado ("Sim
    (carro volta)"). Por isso a primeira regra olha só a palavra de abertura, não
    o item inteiro, e trava atrás de um teto de tamanho: uma negativa de
    verdade ("Não há registro de que Hume tenha escrito isso") também abre com
    palavra de resposta, mas é longa — sem o teto essa regra comeria alegação
    real, que é pior do que deixar passar um item de checklist.
    """
    mantidas: list[str] = []
    for bruto in itens:
        item = bruto.strip()
        if not item:
            continue
        palavras = item.split()
        abertura = palavras[0].casefold().rstrip(".!")
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
