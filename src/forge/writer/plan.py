from langchain_core.messages import HumanMessage

from forge.writer._prompts import load_prompt
from forge.writer.models import Plano


def planejar(model, tema: str, research: str) -> tuple[str, str]:
    prompt = load_prompt("plan").format(tema=tema, research=research)
    plano = model.with_structured_output(Plano).invoke([HumanMessage(content=prompt)])
    return plano.tese, plano.esboco
