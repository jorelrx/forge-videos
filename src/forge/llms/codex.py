"""Adaptador LangChain para texto e JSON pelo Codex autenticado com ChatGPT."""

import json
from typing import Any

from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AIMessage, BaseMessage, convert_to_messages
from langchain_core.outputs import ChatGeneration, ChatResult
from langchain_core.runnables import RunnableLambda
from pydantic import Field, PrivateAttr

from forge.infrastructure.config import Settings
from forge.services.codex import CodexCLI


class CodexChatModel(BaseChatModel):
    settings: Settings = Field(exclude=True)
    model: str = 'gpt-6.1-sol'
    _cli: Any = PrivateAttr(default=None)
    _native: Any = PrivateAttr(default=None)

    def __init__(self, *, settings: Settings, cli=None, native=None, **kwargs):
        super().__init__(settings=settings, model=kwargs.pop('model', settings.resolved_model if settings.provider == 'codex' else settings.codex_model), **kwargs)
        if cli is not None or settings.codex_transport == 'cli':
            self._cli = cli or CodexCLI(settings)
        else:
            from forge.services.codex_native import CodexNative
            self._native = native or CodexNative(settings)

    @property
    def _llm_type(self) -> str:
        return 'codex-native' if self._native is not None else 'codex-cli'

    def _call(self, messages, schema=None) -> AIMessage:
        if hasattr(messages, 'to_messages'):
            messages = messages.to_messages()
        elif isinstance(messages, str):
            messages = [('human', messages)]
        messages = convert_to_messages(messages)
        if self._native is not None:
            roles = {'human': 'user', 'ai': 'assistant', 'system': 'system', 'developer': 'developer'}
            response = self._native.chat(
                [{'role': roles.get(m.type, m.type), 'content': m.content} for m in messages],
                model=self.model, timeout=self.settings.llm_timeout, schema=schema,
            )
            usage = response.usage or {}
            inputs, outputs = int(usage.get('input_tokens', 0)), int(usage.get('output_tokens', 0))
            return AIMessage(content=response.text, response_metadata={
                'finish_reason': 'stop', 'model_name': response.model, 'provider': 'codex',
                'codex_transport': 'native', 'codex_logs': str(response.work_dir),
                'request_id': response.request_id,
            }, usage_metadata={'input_tokens': inputs, 'output_tokens': outputs, 'total_tokens': inputs + outputs})
        prompt = (
            'Execute somente a tarefa de texto abaixo. Não explore arquivos, não use ferramentas, '
            'não altere o projeto e não delegue tarefas. Não acrescente comentários sobre execução. '
            'Responda diretamente ao conteúdo das mensagens, preservando os papéis e instruções.\n\n'
            + json.dumps([{'role': m.type, 'content': m.content} for m in messages], ensure_ascii=False)
        )
        response = self._cli.run(prompt, model=self.model, timeout=self.settings.llm_timeout, schema=schema)
        return AIMessage(content=response.text, response_metadata={
            'finish_reason': 'stop', 'model_name': self.model, 'provider': 'codex',
            'codex_logs': str(response.work_dir),
        })

    def _generate(self, messages: list[BaseMessage], stop=None, run_manager=None, **kwargs) -> ChatResult:
        if stop:
            raise ValueError('Codex CLI não suporta stop sequences')
        return ChatResult(generations=[ChatGeneration(message=self._call(messages))])

    def with_structured_output(self, schema, *, include_raw=False, **kwargs):
        json_schema = schema if isinstance(schema, dict) else schema.model_json_schema()
        def invoke(messages):
            raw = self._call(messages, schema=json_schema)
            try:
                parsed = json.loads(raw.content) if isinstance(schema, dict) else schema.model_validate_json(raw.content)
            except (ValueError, TypeError) as error:
                if include_raw:
                    return {'raw': raw, 'parsed': None, 'parsing_error': error}
                raise
            return {'raw': raw, 'parsed': parsed, 'parsing_error': None} if include_raw else parsed
        return RunnableLambda(invoke)
