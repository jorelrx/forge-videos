from langchain_core.messages import HumanMessage

from forge.infrastructure.logging import get_logger
from forge.prompts.loader import load_prompt
from forge.domain.models import Plano
from forge.llms.model import invoke_structured
from forge.skills.loader import load_skills, resumo_eixos

logger = get_logger(__name__)

SKILLS = ["story", "canal"]
LE = ["tema", "research_notes", "run_dir"]

def planejar(
    model, tema: str, research: str, *, run_dir=None, diretrizes: str = "",
) -> Plano:
    logger.debug("Starting planning phase", tema=tema[:50] + "..." if len(tema) > 50 else tema)
    prompt = load_prompt("plan").format(
        tema=tema, research=research, skills=load_skills(SKILLS, "plan"),
        eixos=resumo_eixos(),
        fluxo_geracao=(
            "\n\n## Fluxo de geração\n\nIncorpore estas diretrizes no esboço, "
            "respeitando as nove seções e as evidências do acervo.\n\n"
            f"{diretrizes}" if diretrizes else ""
        ),
    )
    plano = invoke_structured(
        model, Plano, [HumanMessage(content=prompt)],
        run_dir=run_dir, etapa="plan", subfase="structured",
    )
    logger.info(
        "Planning completed",
        tese=plano.tese[:100] + "..." if len(plano.tese) > 100 else plano.tese,
        eixo=plano.eixo,
    )
    return plano
