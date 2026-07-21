from langchain_core.messages import HumanMessage

from forge.infrastructure.logging import get_logger
from forge.llms.parsing import _texto
from forge.prompts.loader import load_prompt

logger = get_logger(__name__)

LE = ["tema"]


def gerar_tema(model, tema: str | None = None) -> str:
    if tema:
        logger.debug("Tema provided", tema=tema)
        return tema
    logger.debug("Generating topic from LLM")
    resp = model.invoke([HumanMessage(content=load_prompt("tema"))])
    result = _texto(resp).strip()
    logger.info("Topic generated", result=result)
    return result
