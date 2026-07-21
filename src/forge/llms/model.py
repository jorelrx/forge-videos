from langchain_anthropic import ChatAnthropic
from langchain_core.language_models import BaseChatModel
from langchain_openai import ChatOpenAI

from forge.infrastructure.config import Settings
from forge.infrastructure.logging import get_logger

logger = get_logger(__name__)


def build_chat_model(settings: Settings) -> BaseChatModel:
    if settings.provider == "lm-studio":
        logger.info("Building LLM model", provider="lm-studio", model=settings.lm_studio_model)
        return ChatOpenAI(
            model=settings.lm_studio_model,
            base_url=settings.lm_studio_base_url,
            api_key="lm-studio",
        )
    elif settings.provider == "openai":
        logger.info("Building LLM model", provider="openai", model=settings.model)
        return ChatOpenAI(
            model="gpt-5-nano",
            api_key=settings.openai_api_key or settings.anthropic_api_key,
        )
    else:
        logger.info("Building LLM model", provider="anthropic", model=settings.model, effort=settings.effort)
        return ChatAnthropic(
            model=settings.model,
            api_key=settings.anthropic_api_key,
            max_tokens=16000,
            thinking={"type": "adaptive"},
            output_config={"effort": settings.effort},
        )
