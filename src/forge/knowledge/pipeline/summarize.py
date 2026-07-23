"""Estágio LLM: texto -> resumo. Texto livre, não estruturado."""
from langchain_core.messages import HumanMessage

from forge.llms.parsing import _texto

_PROMPT = (
    "Resuma o texto abaixo em um parágrafo denso, fiel, sem introduzir nada que "
    "não esteja nele. Texto:\n\n{texto}"
)


def resumir(model, texto: str) -> str:
    resp = model.invoke([HumanMessage(content=_PROMPT.format(texto=texto))])
    return _texto(resp).strip()
