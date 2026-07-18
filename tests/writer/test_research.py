from forge.writer.models import Fonte, FonteList
from forge.writer.research import pesquisar, WEB_SEARCH_TOOL


def test_pesquisar_retorna_notas_e_fontes(scripted):
    model = scripted(
        invoke_texts=["notas densas sobre o tema"],
        structured=[FonteList(fontes=[Fonte(titulo="Ética a Nicômaco", autor="Aristóteles")])],
    )
    notes, fontes = pesquisar(model, "virtude")
    assert notes == "notas densas sobre o tema"
    assert fontes[0].autor == "Aristóteles"
    assert model.bound_tools == [WEB_SEARCH_TOOL]
