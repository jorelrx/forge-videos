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
    assert report.serious_count == 3
    assert report.codes == {"sem_citacao", "frase_longa", "aberturas_parecidas"}


def test_gate_approves_clean_nine_section_fixture():
    from forge.services.qualidade_roteiro import conferir_roteiro

    report = conferir_roteiro(_fixture("roteiro_sintetico_aprovado.json"))
    assert report.approved
    assert report.metrics["sections_ok"] == 9
    assert report.metrics["robot_labels"] == 0


def test_hook_is_deliberately_exempt_from_source_citation():
    from forge.services.qualidade_roteiro import conferir_secao

    report = conferir_secao(
        "Gancho",
        {"nome": "Gancho", "conteudo": "Você já sentiu que escolheu sem escolher?"},
        [],
    )
    assert "sem_citacao" not in {finding.code for finding in report.findings}
