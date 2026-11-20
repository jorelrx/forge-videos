from forge.domain.models import Plano
from forge.agents.plan import planejar


def test_planejar(scripted):
    model = scripted(structured=[Plano(tese="tese X", esboco="esboço Y")])
    plano = planejar(model, "tema", "notas")
    assert plano.tese == "tese X"
    assert plano.esboco == "esboço Y"
    assert plano.eixo is None


def test_planejar_devolve_eixo(scripted):
    model = scripted(structured=[Plano(tese="t", esboco="e", eixo="niilismo-absurdo")])
    assert planejar(model, "tema", "notas").eixo == "niilismo-absurdo"


def test_prompt_do_plano_lista_os_eixos_do_canal(monkeypatch):
    from forge.agents import plan

    prompts = []

    def invoke(model, schema, messages, **kwargs):
        prompts.append(messages[0].content)
        return Plano(tese="t", esboco="e")

    monkeypatch.setattr(plan, "invoke_structured", invoke)
    planejar(object(), "tema", "notas")

    assert "- estoicismo:" in prompts[0]
    assert "- etica-digital-ia:" in prompts[0]
