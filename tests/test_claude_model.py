import json
from pathlib import Path

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage
from pydantic import BaseModel

from forge.infrastructure.config import Settings
from forge.llms.claude import ClaudeChatModel
from forge.llms.model import build_chat_model, invoke_structured
from forge.services.claude_cli import ClaudeResponse


class Resposta(BaseModel):
    texto: str


class FakeCLI:
    def __init__(self, *respostas):
        self.respostas = list(respostas)
        self.chamadas = []

    def run(self, prompt, *, system, model, timeout, schema=None):
        self.chamadas.append({'prompt': prompt, 'system': system, 'model': model,
                              'timeout': timeout, 'schema': schema})
        return self.respostas.pop(0)


def resposta(text='', structured=None, stop_reason='end_turn'):
    return ClaudeResponse(
        text=text, structured=structured, work_dir=Path('call-1'),
        stop_reason=stop_reason, usage={'input_tokens': 10, 'output_tokens': 4},
    )


def settings(**kw):
    return Settings(_env_file=None, provider='claude', **kw)


def test_provider_claude_usa_opus_e_dispensa_chave():
    s = settings()
    assert s.resolved_model == 'claude-opus-5-5'
    assert s.resolved_api_key is None
    assert isinstance(build_chat_model(s), ClaudeChatModel)


def test_mensagem_unica_vai_crua_e_system_vazio_vira_neutro():
    """Os agentes mandam um HumanMessage só, com quebras de linha e markdown.
    Em JSON o modelo leria `\\n` escapado; e um system vazio poderia cair na
    persona padrão do Claude Code."""
    cli = FakeCLI(resposta(text='Olá.'))
    ClaudeChatModel(settings=settings(), cli=cli).invoke([HumanMessage(content='## Seção\nEscreva.')])
    chamada = cli.chamadas[0]
    assert chamada['prompt'] == '## Seção\nEscreva.'
    assert chamada['system'].strip()
    assert 'código' not in chamada['system'].lower()


def test_conversa_vira_transcricao_em_texto():
    cli = FakeCLI(resposta(text='ok'))
    ClaudeChatModel(settings=settings(), cli=cli).invoke([
        HumanMessage(content='Pergunta 1'), AIMessage(content='Resposta 1'),
        HumanMessage(content='Pergunta 2'),
    ])
    prompt = cli.chamadas[0]['prompt']
    assert '[user]\nPergunta 1' in prompt and '[assistant]\nResposta 1' in prompt
    assert prompt.rstrip().endswith('Pergunta 2')


def test_invoke_separa_system_e_serializa_o_resto():
    cli = FakeCLI(resposta(text='Olá.'))
    model = ClaudeChatModel(settings=settings(), cli=cli)
    msg = model.invoke([
        SystemMessage(content='Regra A.'), SystemMessage(content='Regra B.'),
        HumanMessage(content='Escreva.'),
    ])
    chamada = cli.chamadas[0]
    assert chamada['system'] == 'Regra A.\n\nRegra B.'
    assert chamada['prompt'] == 'Escreva.'
    assert chamada['model'] == 'claude-opus-5-5'
    assert msg.content == 'Olá.'
    assert msg.response_metadata['provider'] == 'claude'
    assert msg.response_metadata['finish_reason'] == 'stop'
    assert msg.usage_metadata == {'input_tokens': 10, 'output_tokens': 4, 'total_tokens': 14}


def test_max_tokens_vira_length():
    cli = FakeCLI(resposta(text='corta', stop_reason='max_tokens'))
    msg = ClaudeChatModel(settings=settings(), cli=cli).invoke('oi')
    assert msg.response_metadata['finish_reason'] == 'length'


def test_structured_le_structured_output():
    cli = FakeCLI(resposta(structured={'texto': 'ok'}))
    model = ClaudeChatModel(settings=settings(), cli=cli)
    out = model.with_structured_output(Resposta, include_raw=True).invoke('oi')
    assert out['parsed'] == Resposta(texto='ok')
    assert out['parsing_error'] is None
    assert cli.chamadas[0]['schema'] == Resposta.model_json_schema()


def test_structured_ausente_vira_parsing_error():
    cli = FakeCLI(resposta(text='não sei', structured=None))
    model = ClaudeChatModel(settings=settings(), cli=cli)
    out = model.with_structured_output(Resposta, include_raw=True).invoke('oi')
    assert out['parsed'] is None
    assert out['parsing_error'] is not None


def test_truncado_sem_estruturado_falha_sem_repetir_a_chamada():
    """O CLI ignora max_tokens: dobrar o orçamento repetiria a mesma chamada
    de Opus duas vezes, contra a cota, para o mesmo corte."""
    import pytest

    cli = FakeCLI(resposta(text='{"tex', stop_reason='max_tokens'))
    model = ClaudeChatModel(settings=settings(), cli=cli)
    with pytest.raises(RuntimeError, match='llm_output_truncated'):
        invoke_structured(model, Resposta, [HumanMessage(content='oi')])
    assert len(cli.chamadas) == 1


def test_invoke_structured_atravessa_o_bind():
    cli = FakeCLI(resposta(structured={'texto': 'ok'}))
    model = ClaudeChatModel(settings=settings(), cli=cli)
    assert invoke_structured(model, Resposta, [HumanMessage(content='oi')]) == Resposta(texto='ok')
