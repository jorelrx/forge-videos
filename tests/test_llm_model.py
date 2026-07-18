from langchain_core.language_models import BaseChatModel

from forge.config import Settings
from forge.llm.model import build_chat_model


def test_builds_chat_model():
    s = Settings(_env_file=None, anthropic_api_key="sk-test")
    m = build_chat_model(s)
    assert isinstance(m, BaseChatModel)
    assert s.model in m.model
