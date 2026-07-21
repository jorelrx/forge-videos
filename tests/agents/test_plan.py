from forge.domain.models import Plano
from forge.agents.plan import planejar

def test_planejar(scripted):
    model = scripted(structured=[Plano(tese="tese X", esboco="esboço Y")])
    tese, esboco = planejar(model, "tema", "notas")
    assert tese == "tese X"
    assert esboco == "esboço Y"
