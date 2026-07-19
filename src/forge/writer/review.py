from langchain_core.messages import HumanMessage

from forge.logging import get_logger
from forge.writer._prompts import load_prompt
from forge.writer.models import ReviewResult, Roteiro

logger = get_logger(__name__)


def revisar(model, roteiro: Roteiro) -> ReviewResult:
    logger.debug("Starting review phase", tema=roteiro.tema[:50] + "..." if len(roteiro.tema) > 50 else roteiro.tema)
    prompt = load_prompt("review").format(roteiro=_render(roteiro))
    result = model.with_structured_output(ReviewResult).invoke([HumanMessage(content=prompt)])
    logger.info("Review completed", aprovado=result.aprovado, num_notas=len(result.notas))
    return result


def _render(roteiro: Roteiro) -> str:
    partes = [f"Tese: {roteiro.tese}", ""]
    for s in roteiro.secoes:
        partes.append(f"## {s.nome}\n{s.conteudo}\n")
    return "\n".join(partes)
