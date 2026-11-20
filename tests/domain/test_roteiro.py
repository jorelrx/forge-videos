import json
from pathlib import Path

from forge.domain.roteiro import ARQUITETURA, NarrativeSection


def _fixture(name):
    return json.loads((Path(__file__).parents[1] / "fixtures" / "poc" / name).read_text())


def test_narrative_order_is_the_approved_nine_functions():
    assert [section.nome for section in ARQUITETURA] == [
        "Gancho", "Estake", "Tensao", "Virada", "Filosofo",
        "Prova", "Espelho", "Aplicacao", "Fecho",
    ]


def test_architecture_sections_are_immutable_and_typed():
    assert all(isinstance(section, NarrativeSection) for section in ARQUITETURA)
    assert ARQUITETURA[0].abre_loop is True
    assert ARQUITETURA[-1].fecha_loop is True


def test_characterization_preserves_three_poc_gate_failures():
    from forge.services.qualidade_roteiro import conferir_roteiro

    report = conferir_roteiro(_fixture("roteiro_poc_3_graves.json"))
    assert not report.approved
    # O POC tem ~250 palavras: sob os alvos de vídeo longo ele também é curto.
    # A caracterização que importa é que os três defeitos originais continuam
    # sendo achados, e que nada além de tamanho apareceu.
    originais = {"sem_citacao", "frase_longa", "aberturas_parecidas"}
    assert originais <= report.codes
    assert report.codes - originais == {"secao_curta", "roteiro_curto"}


def test_gate_approves_clean_nine_section_fixture():
    from forge.services.qualidade_roteiro import conferir_roteiro

    report = conferir_roteiro(_fixture("roteiro_sintetico_aprovado.json"))
    # O sintético foi escrito para os alvos antigos: segue limpo em tudo, menos
    # no tamanho, que agora é de vídeo longo.
    assert report.codes == {"secao_curta", "roteiro_curto"}
    assert report.metrics["sections_ok"] == 9
    assert report.metrics["robot_labels"] == 0


def test_gate_approves_long_form_script(roteiro_longo):
    from forge.services.qualidade_roteiro import conferir_roteiro

    report = conferir_roteiro(roteiro_longo())
    assert report.approved
    assert report.metrics["sections_ok"] == 9


def test_hook_is_deliberately_exempt_from_source_citation():
    from forge.services.qualidade_roteiro import conferir_secao

    report = conferir_secao(
        "Gancho",
        {"nome": "Gancho", "conteudo": "Você já sentiu que escolheu sem escolher?"},
        [],
    )
    assert "sem_citacao" not in {finding.code for finding in report.findings}


def test_alvos_somam_duracao_de_video_longo():
    """11 a 16 minutos a 150 palavras/min: o canal é de vídeo longo."""
    assert sum(s.alvo_palavras[0] for s in ARQUITETURA) == 1600
    assert sum(s.alvo_palavras[1] for s in ARQUITETURA) == 2450
    assert {s.nome: s.alvo_palavras for s in ARQUITETURA}["Filosofo"] == (260, 380)
