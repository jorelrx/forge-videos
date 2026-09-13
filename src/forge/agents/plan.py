from langchain_core.messages import HumanMessage

from forge.infrastructure.logging import get_logger
from forge.prompts.loader import load_prompt
from forge.domain.models import Plano
from forge.llms.model import invoke_structured
from forge.skills.loader import load_skills

logger = get_logger(__name__)

SKILLS = ["story"]
LE = ["tema", "research_notes", "run_dir"]

def planejar(model, tema: str, research: str, *, run_dir=None) -> tuple[str, str]:
    logger.debug("Starting planning phase", tema=tema[:50] + "..." if len(tema) > 50 else tema)
    prompt = load_prompt("plan").format(
        tema=tema, research=research, skills=load_skills(SKILLS, "plan")
    )
    plano = invoke_structured(
        model, Plano, [HumanMessage(content=prompt)],
        run_dir=run_dir, etapa="plan", subfase="structured",
    )
    tese_resultado = plano.tese
    esboco_resultado = plano.esboco
    logger.info("Planning completed", tese=tese_resultado[:100] + "..." if len(tese_resultado) > 100 else tese_resultado)
    return tese_resultado, esboco_resultado
