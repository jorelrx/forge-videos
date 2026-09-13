from forge.domain.models import Roteiro, Secao
from forge.services.qualidade_roteiro import conferir_roteiro


def test_named_section_count_is_a_deterministic_gate():
    roteiro = Roteiro(
        tema="Tema", tese="Tese", secoes=[Secao(nome="Gancho", conteudo="texto")]
    )
    report = conferir_roteiro(roteiro, {})
    assert not report.approved
    assert "script_sections_invalid" in report.codes


def test_citation_anchor_accepts_author_or_title():
    payload = {
        "tema": "Tema",
        "tese": "Tese",
        "secoes": [
            {"nome": name, "conteudo": ("Abertura direta. " if name == "Gancho" else "A análise de Ada Lovelace mostra uma consequência concreta para a tese.")}
            for name in ["Gancho", "Estake", "Tensao", "Virada", "Filosofo", "Prova", "Espelho", "Aplicacao", "Fecho"]
        ],
        "passages_by_section": {
            name: [{"title": "Notas da máquina", "authors": ["Ada Lovelace"]}]
            for name in ["Estake", "Tensao", "Virada", "Filosofo", "Prova", "Espelho", "Aplicacao", "Fecho"]
        },
    }
    report = conferir_roteiro(payload)
    assert "sem_citacao" not in report.codes
