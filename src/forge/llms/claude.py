"""Adaptador LangChain para texto e JSON pela assinatura Claude (`claude -p`)."""

import json
from typing import Any

from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AIMessage, BaseMessage, convert_to_messages
from langchain_core.outputs import ChatGeneration, ChatResult
from langchain_core.runnables import RunnableLambda
from pydantic import Field, PrivateAttr

from forge.infrastructure.config import MODELO_PADRAO, Settings
from forge.services.claude_cli import ClaudeCLI

_PAPEIS = {'human': 'user', 'ai': 'assistant', 'tool': 'tool'}

SYSTEM_NEUTRO = (
    'Você executa uma única tarefa de texto. Siga exatamente as instruções da '
    'mensagem do usuário e responda apenas com o que ela pede.'
)


def _texto(content) -> str:
    """Conteúdo de mensagem como texto, aceitando a forma em blocos."""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return ''.join(
            bloco if isinstance(bloco, str) else str(bloco.get('text', ''))
            for bloco in content if isinstance(bloco, (str, dict))
        )
    return str(content)


class ClaudeChatModel(BaseChatModel):
    settings: Settings = Field(exclude=True)
    model: str = MODELO_PADRAO['claude']
    _cli: Any = PrivateAttr(default=None)

    def __init__(self, *, settings: Settings, cli=None, **kwargs):
        modelo = kwargs.pop('model', None) or (
            settings.resolved_model if settings.provider == 'claude' else MODELO_PADRAO['claude']
        )
        super().__init__(settings=settings, model=modelo, **kwargs)
        self._cli = cli or ClaudeCLI(settings)

    @property
    def _llm_type(self) -> str:
        return 'claude-cli'

    def _call(self, messages, schema=None) -> AIMessage:
        if hasattr(messages, 'to_messages'):
            messages = messages.to_messages()
        elif isinstance(messages, str):
            messages = [('human', messages)]
        messages = convert_to_messages(messages)
        # Vazio, o arquivo de sistema poderia cair na persona padrão do Claude
        # Code (agente de programação); os agentes do forge não mandam system.
        system = '\n\n'.join(
            _texto(m.content) for m in messages if m.type == 'system'
        ) or SYSTEM_NEUTRO
        conversa = [m for m in messages if m.type != 'system']
        if len(conversa) == 1:
            # Texto cru: em JSON o modelo leria quebras de linha escapadas.
            prompt = _texto(conversa[0].content)
        else:
            prompt = '\n\n'.join(
                f'[{_PAPEIS.get(m.type, m.type)}]\n{_texto(m.content)}' for m in conversa
            )
        resposta = self._cli.run(
            prompt, system=system, model=self.model,
            timeout=self.settings.llm_timeout, schema=schema,
        )
        texto = (
            json.dumps(resposta.structured, ensure_ascii=False)
            if resposta.structured is not None else resposta.text
        )
        entrada = int(resposta.usage.get('input_tokens', 0) or 0)
        saida = int(resposta.usage.get('output_tokens', 0) or 0)
        return AIMessage(content=texto, response_metadata={
            'finish_reason': 'length' if resposta.stop_reason == 'max_tokens' else 'stop',
            'model_name': self.model, 'provider': 'claude',
            'claude_logs': str(resposta.work_dir),
        }, usage_metadata={
            'input_tokens': entrada, 'output_tokens': saida, 'total_tokens': entrada + saida,
        })

    def _generate(self, messages: list[BaseMessage], stop=None, run_manager=None, **kwargs) -> ChatResult:
        if stop:
            raise ValueError('Claude CLI não suporta stop sequences')
        return ChatResult(generations=[ChatGeneration(message=self._call(messages))])

    def with_structured_output(self, schema, *, include_raw=False, **kwargs):
        json_schema = schema if isinstance(schema, dict) else schema.model_json_schema()

        def invoke(messages):
            raw = self._call(messages, schema=json_schema)
            try:
                parsed = (
                    json.loads(raw.content) if isinstance(schema, dict)
                    else schema.model_validate_json(raw.content)
                )
            except (ValueError, TypeError) as error:
                # O CLI ignora max_tokens: devolver "length" faria o
                # invoke_structured dobrar um orçamento que não existe e repetir
                # a mesma chamada, contra a cota.
                if raw.response_metadata.get('finish_reason') == 'length':
                    raise RuntimeError('llm_output_truncated') from error
                if include_raw:
                    return {'raw': raw, 'parsed': None, 'parsing_error': error}
                raise
            return {'raw': raw, 'parsed': parsed, 'parsing_error': None} if include_raw else parsed

        return RunnableLambda(invoke)
