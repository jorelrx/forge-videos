from langchain_core.messages import HumanMessage

from forge.infrastructure.logging import get_logger
from forge.prompts.loader import load_prompt
from forge.domain.models import Fonte, Nota, Roteiro, RoteiroDraft
from forge.llms.model import invoke_structured
from forge.skills.loader import load_skills

logger = get_logger(__name__)

SKILLS = ["writing", "story", "retention", "fact_check"]
LE = ["tema", "tese", "esboco", "research_notes", "fontes", "review", "run_dir"]


def escrever(
    model,
    tema: str,
    tese: str,
    esboco: str,
    research: str,
    fontes: list[Fonte],
    notas: list[Nota] | None = None,
    *,
    run_dir=None,
) -> tuple[Roteiro, str | None]:
    logger.debug("Starting write phase", tema=tema[:50] + "..." if len(tema) > 50 else tema)
    prompt = load_prompt("write").format(
        tese=tese,
        esboco=esboco,
        research=research,
        notas=_fmt_notas(notas),
        skills=load_skills(SKILLS, "write"),
    )
    draft = invoke_structured(
        model, RoteiroDraft, [HumanMessage(content=prompt)],
        run_dir=run_dir, etapa="write", subfase="structured",
    )
    roteiro_resultado = Roteiro(tema=tema, tese=tese, secoes=draft.secoes, fontes=fontes)
    logger.info(
        "Write phase completed",
        num_secoes=len(roteiro_resultado.secoes),
        falta_pesquisa=bool(draft.falta_pesquisa),
    )
    return roteiro_resultado, draft.falta_pesquisa


def _fmt_notas(notas: list[Nota] | None) -> str:
    if not notas:
        return "(nenhuma — primeira versão)"
    return "\n".join(f"- [{n.dimensao}] {n.problema} → {n.sugestao}" for n in notas)
