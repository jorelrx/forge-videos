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
        item = self.invoke_texts.pop(0)
        if isinstance(item, AIMessage):
            return item
        return AIMessage(content=item)

    def with_structured_output(self, schema):
        queue = self.structured

        class _Structured:
            def invoke(self, messages):
                return queue.pop(0)

        return _Structured()


@pytest.fixture
def scripted():
    return ScriptedModel


class FakeAcervo:
    """Acervo falso: passagens fixas, sem rede. Registra as queries recebidas.

    `padrao` responde a qualquer query não mapeada — o teste de grafo não sabe
    que texto o modelo roteirizado vai emitir como query.
    """

    def __init__(self, por_query=None, candidatos=None, padrao=None):
        self.por_query = por_query or {}
        self.candidatos = candidatos or []
        self.padrao = padrao or []
        self.chamadas = []

    def buscar(self, q, **kwargs):
        self.chamadas.append(q)
        return self.por_query.get(q, self.padrao)

    def descobrir(self, q, **kwargs):
        return self.candidatos


@pytest.fixture
def acervo_fake():
    return FakeAcervo
