import pytest

from forge.agents.pauta import conferir_pauta
from forge.agents.research import PassageEvidence, ResearchBundle
from forge.domain.pauta import ConferenciaPauta, PautaEpisodio

PAUTA = PautaEpisodio(tema="Adiar", promessa="Adiar é preguiça", recorte="A pia cheia",
                      perguntas_pesquisa=["Quem escreveu sobre adiar?"])


def _bundle():
    return ResearchBundle(
        brief="síntese", fontes=[], raw_markdown="", passage_count=1, canonical_paths=["1/c1/p1"],
        passages=[PassageEvidence(path="1/c1/p1", title="Livro", text="Adiar protege de uma avaliação temida.")],
    )


def test_conferir_pauta_devolve_contradicao(scripted):
    resposta = ConferenciaPauta(compativel=False, explicacao="A fonte liga adiar ao medo de avaliação.",
                                evidencias=["1/c1/p1"], promessa_proposta="Adiar como proteção")
    model = scripted(structured=[resposta])
    conferencia = conferir_pauta(model, PAUTA, _bundle())
    assert not conferencia.compativel
    assert conferencia.promessa_proposta == "Adiar como proteção"


def test_conferir_pauta_recusa_caminho_inventado(scripted):
    resposta = ConferenciaPauta(compativel=False, explicacao="x", evidencias=["9/inventado"], recorte_proposto="y")
    with pytest.raises(ValueError):
        conferir_pauta(scripted(structured=[resposta]), PAUTA, _bundle())


def test_briefing_e_diretrizes_carregam_a_pauta():
    pauta = PAUTA.model_copy(update={"abertura": "Abre na pia", "blocos": ["Cena", "Virada"]})
    assert "Quem escreveu sobre adiar?" in pauta.briefing_pesquisa()
    assert "A pia cheia" in pauta.briefing_pesquisa()
    diretrizes = pauta.diretrizes()
    assert "Abertura: Abre na pia" in diretrizes and "2. Virada" in diretrizes
