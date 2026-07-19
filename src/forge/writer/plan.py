from langchain_core.messages import HumanMessage

from forge.logging import get_logger
from forge.writer._prompts import load_prompt
from forge.writer.models import Plano

logger = get_logger(__name__)

def planejar(model, tema: str, research: str) -> tuple[str, str]:
    logger.debug("Starting planning phase", tema=tema[:50] + "..." if len(tema) > 50 else tema)
    prompt = load_prompt("plan").format(tema=tema, research=research)
    plano = model.with_structured_output(Plano).invoke([HumanMessage(content=prompt)])
    tese_resultado = plano.tese
    esboco_resultado = plano.esboco
    logger.info("Planning completed", tese=tese_resultado[:100] + "..." if len(tese_resultado) > 100 else tese_resultado)
    return tese_resultado, esboco_resultado
