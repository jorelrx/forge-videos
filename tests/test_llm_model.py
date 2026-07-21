from langchain_core.language_models import BaseChatModel
from langchain_openai import ChatOpenAI

from forge.infrastructure.config import Settings
from forge.llms.model import build_chat_model


def test_builds_chat_model():
    s = Settings(_env_file=None, anthropic_api_key="sk-test")
    m = build_chat_model(s)
    assert isinstance(m, BaseChatModel)
    assert s.resolved_model in m.model


def test_builds_lm_studio_chat_model():
    s = Settings(_env_file=None, provider="lm-studio")
    m = build_chat_model(s)
    assert isinstance(m, ChatOpenAI)
    assert m.model_name == s.resolved_model
    assert str(m.openai_api_base) == s.lm_studio_base_url


def test_openai_usa_a_propria_chave_e_modelo():
    s = Settings(_env_file=None, provider="openai",
                 anthropic_api_key="sk-ant", openai_api_key="sk-oai")
    m = build_chat_model(s)
    assert isinstance(m, ChatOpenAI)
    assert m.model_name == "gpt-5-nano"
    assert m.openai_api_key.get_secret_value() == "sk-oai"


def test_openai_respeita_override_de_modelo():
    s = Settings(_env_file=None, provider="openai", model="gpt-5", openai_api_key="sk-oai")
    assert build_chat_model(s).model_name == "gpt-5"
