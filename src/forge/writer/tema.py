from langchain_core.messages import HumanMessage

from forge.logging import get_logger
from forge.writer._prompts import load_prompt

logger = get_logger(__name__)


def gerar_tema(model, tema: str | None = None) -> str:
    if tema:
        logger.debug("Tema provided", tema=tema)
        return tema
    logger.debug("Generating topic from LLM")
    resp = model.invoke([HumanMessage(content=load_prompt("tema"))])
    result = _texto(resp).strip()
    logger.info("Topic generated", result=result)
    return result


def _texto(resp) -> str:
    content = resp.content
    if isinstance(content, str):
        return content
    return "".join(
        b.get("text", "") for b in content if isinstance(b, dict)
    )
