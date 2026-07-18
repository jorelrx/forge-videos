from langchain_anthropic import ChatAnthropic
from langchain_core.language_models import BaseChatModel

from forge.config import Settings


def build_chat_model(settings: Settings) -> BaseChatModel:
    return ChatAnthropic(
        model=settings.model,
        api_key=settings.anthropic_api_key,
        max_tokens=16000,
        thinking={"type": "adaptive"},
        output_config={"effort": settings.effort},
    )
