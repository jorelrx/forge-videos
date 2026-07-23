"""Estágio LLM: texto -> entidades (filósofo, escola, obra, ideia, conceito)."""
from langchain_core.messages import HumanMessage
from pydantic import BaseModel, Field

from forge.knowledge.domain.models import Entidade

_PROMPT = (
    "Liste as entidades relevantes do texto: filósofos, escolas, obras, ideias, "
    "conceitos. Classifique cada uma. Não invente nomes que não aparecem. "
    "Texto:\n\n{texto}"
)

class EntidadesOut(BaseModel):
    entidades: list[Entidade] = Field(default_factory=list)

def extrair_entidades(model, texto: str) -> list[Entidade]:
    prompt = _PROMPT.format(texto=texto)
    out = model.with_structured_output(EntidadesOut).invoke([HumanMessage(content=prompt)])
    return out.entidades
