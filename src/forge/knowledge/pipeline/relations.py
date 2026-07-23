"""Estágio LLM: entidades + texto -> relacionamentos (arestas do KG)."""
from langchain_core.messages import HumanMessage
from pydantic import BaseModel, Field

from forge.knowledge.domain.models import Entidade, Relacionamento

_PROMPT = (
    "Dadas as entidades {nomes}, identifique relacionamentos entre elas sustentados "
    "pelo texto (ex.: influenciou, criticou, pertence a, discípulo de). Só relações "
    "que o texto apoia. Texto:\n\n{texto}"
)


class RelacoesOut(BaseModel):
    relacionamentos: list[Relacionamento] = Field(default_factory=list)


def extrair_relacionamentos(
    model, texto: str, entidades: list[Entidade]
) -> list[Relacionamento]:
    # Menos de duas entidades: não há par possível — não gasta chamada.
    if len(entidades) < 2:
        return []
    nomes = ", ".join(e.nome for e in entidades)
    prompt = _PROMPT.format(nomes=nomes, texto=texto)
    out = model.with_structured_output(RelacoesOut).invoke([HumanMessage(content=prompt)])
    return out.relacionamentos
