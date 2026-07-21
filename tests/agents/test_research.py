from langchain_core.messages import AIMessage

from forge.domain.models import Fonte, FonteList
from forge.agents.research import pesquisar, WEB_SEARCH_TOOL


def test_pesquisar_retorna_notas_e_fontes(scripted):
    model = scripted(
        invoke_texts=["notas densas sobre o tema"],
        structured=[FonteList(fontes=[Fonte(titulo="Ética a Nicômaco", autor="Aristóteles")])],
    )
    notes, fontes, raw = pesquisar(model, "virtude")
    assert notes == "notas densas sobre o tema"
    assert fontes[0].autor == "Aristóteles"
    assert model.bound_tools == [WEB_SEARCH_TOOL]


def test_pesquisar_client_side_usa_ferramenta_local(scripted, monkeypatch):
    import forge.agents.research as research_mod

    class FakeTool:
        def invoke(self, args):
            assert args == {"query": "estoicismo"}
            return "resultado da busca local"

    monkeypatch.setattr(research_mod, "buscar_web", FakeTool())

    model = scripted(
        invoke_texts=[
            AIMessage(
                content="",
                tool_calls=[
                    {"name": "buscar_web", "args": {"query": "estoicismo"}, "id": "call_1", "type": "tool_call"}
                ],
            ),
            "notas finais a partir da busca local",
        ],
        structured=[FonteList(fontes=[])],
    )
    notes, fontes, raw = research_mod.pesquisar(model, "estoicismo", provider="lm-studio")
    assert notes == "notas finais a partir da busca local"
    assert fontes == []
