from langchain_core.messages import HumanMessage

from forge.writer._prompts import load_prompt
from forge.writer.models import ReviewResult, Roteiro


def revisar(model, roteiro: Roteiro) -> ReviewResult:
    prompt = load_prompt("review").format(roteiro=_render(roteiro))
    return model.with_structured_output(ReviewResult).invoke([HumanMessage(content=prompt)])


def _render(roteiro: Roteiro) -> str:
    partes = [f"Tese: {roteiro.tese}", ""]
    for s in roteiro.secoes:
        partes.append(f"## {s.nome}\n{s.conteudo}\n")
    return "\n".join(partes)
