from langchain_core.language_models import BaseChatModel
from langchain_openai import ChatOpenAI

from forge.infrastructure.config import Settings
from forge.llms.model import build_chat_model


def test_builds_chat_model():
    s = Settings(_env_file=None, anthropic_api_key="sk-test")
    m = build_chat_model(s)
    assert isinstance(m, BaseChatModel)
    assert s.model in m.model


def test_builds_lm_studio_chat_model():
    s = Settings(_env_file=None, provider="lm-studio")
    m = build_chat_model(s)
    assert isinstance(m, ChatOpenAI)
    assert m.model_name == s.lm_studio_model
    assert str(m.openai_api_base) == s.lm_studio_base_url
