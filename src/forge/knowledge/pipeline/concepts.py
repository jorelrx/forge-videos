"""Estágio LLM: texto -> conceitos-chave. Mesmo padrão structured dos agents."""
from langchain_core.messages import HumanMessage
from pydantic import BaseModel, Field

from forge.knowledge.domain.models import Conceito

_PROMPT = (
    "Extraia os conceitos-chave do texto abaixo. Só conceitos realmente centrais, "
    "com uma descrição curta quando ajudar. Não invente. Texto:\n\n{texto}"
)

class ConceitosOut(BaseModel):
    conceitos: list[Conceito] = Field(default_factory=list)

def extrair_conceitos(model, texto: str) -> list[Conceito]:
    prompt = _PROMPT.format(texto=texto)
    out = model.with_structured_output(ConceitosOut).invoke([HumanMessage(content=prompt)])
    return out.conceitos
