import pytest
from langchain_core.messages import AIMessage


class ScriptedModel:
    """Model falso: entrega respostas pré-roteirizadas, sem rede."""

    def __init__(self, *, invoke_texts=None, structured=None):
        self.invoke_texts = list(invoke_texts or [])
        self.structured = list(structured or [])
        self.bound_tools = None

    def bind_tools(self, tools):
        self.bound_tools = tools
        return self

    def invoke(self, messages):
        return AIMessage(content=self.invoke_texts.pop(0))

    def with_structured_output(self, schema):
        queue = self.structured

        class _Structured:
            def invoke(self, messages):
                return queue.pop(0)

        return _Structured()


@pytest.fixture
def scripted():
    return ScriptedModel
