import json
from pathlib import Path
from types import SimpleNamespace

import pytest
from langchain_core.messages import HumanMessage
from pydantic import ValidationError

from forge.domain.models import Plano
from forge.infrastructure.config import Settings
from forge.llms.codex import CodexChatModel
from forge.llms.model import build_chat_model, invoke_structured


class FakeCLI:
    def __init__(self, text):
        self.text = text
        self.calls = []
    def run(self, prompt, **kwargs):
        self.calls.append((prompt, kwargs))
        return SimpleNamespace(text=self.text, work_dir=Path('logs'))


def test_factory_does_not_require_api_key():
    model = build_chat_model(Settings(_env_file=None, provider='codex', api_key=None))
    assert isinstance(model, CodexChatModel)
    assert model.model == 'gpt-6.1-sol'


def test_requested_model_is_preserved_without_silent_fallback():
    model = build_chat_model(Settings(_env_file=None, provider='codex', model='gpt-6.1-sol'))
    assert model.model == 'gpt-6.1-sol'


def test_text_returns_langchain_message():
    cli = FakeCLI('Uma reflexão.')
    model = CodexChatModel(settings=Settings(_env_file=None), cli=cli)
    response = model.invoke([HumanMessage(content='Olá')])
    assert response.content == 'Uma reflexão.'
    assert 'Olá' in cli.calls[0][0]
    assert cli.calls[0][1].get('allow_images', False) is False


def test_structured_contract_and_raw_match_existing_agents():
    cli = FakeCLI(json.dumps({'tese':'T', 'esboco':'E'}))
    model = CodexChatModel(settings=Settings(_env_file=None), cli=cli)
    result = invoke_structured(model, Plano, [HumanMessage(content='Planeje')])
    assert result == Plano(tese='T', esboco='E')
    assert cli.calls[0][1]['schema']['type'] == 'object'


def test_native_factory_and_role_mapping(tmp_path):
    from langchain_core.messages import SystemMessage

    from forge.services.codex_native import CodexNative
    settings = Settings(_env_file=None, provider='codex', codex_runs_dir=tmp_path)
    assert isinstance(build_chat_model(settings)._native, CodexNative)
    calls = []
    class Native:
        def chat(self, messages, **kwargs):
            calls.append((messages, kwargs))
            return SimpleNamespace(text='OK', model='gpt-6.1-sol', work_dir=tmp_path, usage={'input_tokens': 10, 'output_tokens': 1}, request_id='response-id')
    response = CodexChatModel(settings=settings, native=Native()).invoke([SystemMessage(content='regra'), HumanMessage(content='pergunta')])
    assert calls[0][0] == [{'role':'system','content':'regra'}, {'role':'user','content':'pergunta'}]
    assert response.response_metadata['model_name'] == 'gpt-6.1-sol'
    assert response.response_metadata['codex_transport'] == 'native'
    assert response.usage_metadata['total_tokens'] == 11


def test_explicit_cli_transport_is_still_available():
    from forge.services.codex import CodexCLI
    settings = Settings(_env_file=None, provider='codex', codex_transport='cli', model='gpt-6-astra')
    model = build_chat_model(settings)
    assert isinstance(model._cli, CodexCLI)


def test_structured_invalid_result_preserves_parse_failure():
    model = CodexChatModel(settings=Settings(_env_file=None), cli=FakeCLI('{}'))
    with pytest.raises(ValidationError):
        invoke_structured(model, Plano, [HumanMessage(content='Planeje')])
