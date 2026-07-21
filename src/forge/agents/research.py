from langchain_core.messages import HumanMessage, ToolMessage
from langchain_core.tools import tool

from forge.infrastructure.logging import get_logger
from forge.prompts.loader import load_prompt
from forge.domain.models import Fonte, FonteList
from forge.llms.parsing import _texto
from forge.skills.loader import load_skills

logger = get_logger(__name__)

SKILLS = ["fact_check"]
LE = ["tema", "pedido", "research_notes"]

WEB_SEARCH_TOOL: dict = {"type": "web_search_20260209", "name": "web_search"}
MAX_SEARCH_ROUNDS = 5


@tool
def buscar_web(query: str) -> str:
    """Busca na web e retorna um resumo dos resultados mais relevantes para a query."""
    from ddgs import DDGS

    logger.debug("Web search", query=query)
    resultados = DDGS().text(query, max_results=5)
    if not resultados:
        result_text = "Nenhum resultado encontrado."
        logger.warning("No search results", query=query)
        return result_text
    
    formatted_results = "\n\n".join(
        f"{r.get('title', '')}\n{r.get('href', '')}\n{r.get('body', '')}"
        for r in resultados
    )
    logger.info("Search completed", num_results=len(resultados))
    return formatted_results


def _fmt_pedido(pedido: str | None) -> str:
    if not pedido:
        return ""
    return (
        "ATENÇÃO — esta é uma passagem dirigida, não uma pesquisa do zero.\n"
        "Verifique apenas os pontos abaixo e devolva o que confirmou ou não:\n"
        f"{pedido}"
    )


def pesquisar(
    model, tema: str, provider: str = "anthropic", pedido: str | None = None
) -> tuple[str, list[Fonte], str]:
    if provider == "anthropic":
        brief, raw = _pesquisar_server_side(model, tema, pedido)
    else:
        brief, raw = _pesquisar_client_side(model, tema, pedido)
    fontes = _extrair_fontes(model, brief)
    return brief, fontes, raw


def _pesquisar_server_side(model, tema: str, pedido: str | None) -> tuple[str, str]:
    search = model.bind_tools([WEB_SEARCH_TOOL])
    resp = search.invoke([HumanMessage(content=load_prompt("research").format(
        tema=tema, skills=load_skills(SKILLS, "research"), pedido=_fmt_pedido(pedido)
    ))])
    brief = _texto(resp)
    return brief, str(resp.content)


def _pesquisar_client_side(model, tema: str, pedido: str | None) -> tuple[str, str]:
    """Busca alternativa (DuckDuckGo) para providers sem web_search server-side."""
    tool_model = model.bind_tools([buscar_web])
    messages = [HumanMessage(content=load_prompt("research").format(
        tema=tema, skills=load_skills(SKILLS, "research"), pedido=_fmt_pedido(pedido)
    ))]
    bruto: list[str] = []
    for _ in range(MAX_SEARCH_ROUNDS):
        resp = tool_model.invoke(messages)
        if not getattr(resp, "tool_calls", None):
            return _texto(resp), "\n\n".join(bruto)
        messages.append(resp)
        for call in resp.tool_calls:
            resultado = buscar_web.invoke(call["args"])
            bruto.append(f"### query: {call['args']}\n{resultado}")
            messages.append(ToolMessage(content=resultado, tool_call_id=call["id"]))
    resp = tool_model.invoke(messages)
    return _texto(resp), "\n\n".join(bruto)


def _extrair_fontes(model, notes: str) -> list[Fonte]:
    logger.debug("Extracting sources from research notes", notes_length=len(notes))
    prompt = load_prompt("fontes").format(notes=notes)
    try:
        # Tenta usar with_structured_output primeiro
        result = model.with_structured_output(FonteList).invoke([HumanMessage(content=prompt)])
        fontes_resultado = result.fontes
        logger.info("Sources extracted (via structured output)", num_fontes=len(fontes_resultado))
        return fontes_resultado
    except (ValueError, AttributeError) as e:
        logger.debug("Structured output not supported, falling back to JSON parsing", error=str(e))
        # Fallback para parsing manual se o modelo não suportar with_structured_output
        prompt_json = f"""
Extraia as fontes citáveis destas notas de pesquisa. Inclua apenas fontes com
título e autor identificáveis. Não invente. Se as notas não trazem fontes
confirmadas, retorne uma lista vazia.

Retorne **exclusivamente** um JSON válido no formato:
{{
  "fontes": [
    {{
      "titulo": "Título da fonte",
      "autor": "Autor da fonte",
      "url": "Link da fonte (url)"
    }}
  ]
}}

Notas:
{notes}
"""
        resp = model.invoke([HumanMessage(content=prompt_json)])
        import json
        try:
            data = json.loads(resp.content)
            fontes_resultado = [Fonte(**fonte) for fonte in data.get("fontes", [])]
            logger.info("Sources extracted (via JSON parsing)", num_fontes=len(fontes_resultado))
            return fontes_resultado
        except json.JSONDecodeError as e:
            logger.error("Failed to parse sources from model response", error=str(e))
            return []
