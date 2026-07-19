from langchain_core.messages import HumanMessage

from forge.logging import get_logger
from forge.writer._prompts import load_prompt
from forge.writer.models import Fonte, Nota, Roteiro, RoteiroDraft

logger = get_logger(__name__)


def escrever(
    model,
    tema: str,
    tese: str,
    esboco: str,
    research: str,
    fontes: list[Fonte],
    notas: list[Nota] | None = None,
) -> Roteiro:
    logger.debug("Starting write phase", tema=tema[:50] + "..." if len(tema) > 50 else tema)
    prompt = load_prompt("write").format(
        tese=tese, esboco=esboco, research=research, notas=_fmt_notas(notas)
    )
    draft = model.with_structured_output(RoteiroDraft).invoke([HumanMessage(content=prompt)])
    roteiro_resultado = Roteiro(tema=tema, tese=tese, secoes=draft.secoes, fontes=fontes)
    logger.info("Write phase completed", num_secoes=len(roteiro_resultado.secoes))
    return roteiro_resultado


def _fmt_notas(notas: list[Nota] | None) -> str:
    if not notas:
        return "(nenhuma — primeira versão)"
    return "\n".join(f"- [{n.dimensao}] {n.problema} → {n.sugestao}" for n in notas)
