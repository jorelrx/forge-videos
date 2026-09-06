from langchain_anthropic import ChatAnthropic
from langchain_core.language_models import BaseChatModel
from langchain_openai import ChatOpenAI

from forge.infrastructure.config import Settings
from forge.infrastructure.logging import get_logger

logger = get_logger(__name__)


def build_chat_model(settings: Settings) -> BaseChatModel:
    modelo = settings.resolved_model
    chave = settings.exigir_api_key()
    logger.info("Building LLM model", provider=settings.provider, model=modelo)

    if settings.provider == "lm-studio":
        return ChatOpenAI(
            model=modelo,
            base_url=settings.lm_studio_base_url,
            api_key=chave,
            timeout=settings.llm_timeout,
            max_retries=settings.llm_max_retries,
        )

    if settings.provider == "openai":
        return ChatOpenAI(
            model=modelo,
            api_key=chave,
            timeout=settings.llm_timeout,
            max_retries=settings.llm_max_retries,
        )

    return ChatAnthropic(
        model=modelo,
        api_key=chave,
        max_tokens=16000,
        thinking={"type": "adaptive"},
        output_config={"effort": settings.effort},
        timeout=settings.llm_timeout,
        max_retries=settings.llm_max_retries,
    )
