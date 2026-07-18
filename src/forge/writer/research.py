from langchain_core.messages import HumanMessage

from forge.writer._prompts import load_prompt
from forge.writer.models import Fonte, FonteList
from forge.writer.tema import _texto

WEB_SEARCH_TOOL: dict = {"type": "web_search_20260209", "name": "web_search"}


def pesquisar(model, tema: str) -> tuple[str, list[Fonte]]:
    search = model.bind_tools([WEB_SEARCH_TOOL])
    resp = search.invoke([HumanMessage(content=load_prompt("research").format(tema=tema))])
    notes = _texto(resp)
    fontes = _extrair_fontes(model, notes)
    return notes, fontes


def _extrair_fontes(model, notes: str) -> list[Fonte]:
    prompt = load_prompt("fontes").format(notes=notes)
    result = model.with_structured_output(FonteList).invoke([HumanMessage(content=prompt)])
    return result.fontes
