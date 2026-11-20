"""Identidade do canal Conquistas Cósmicas dentro do pipeline.

A voz do canal e as referências por eixo são markdown carregado pelos agentes;
estes testes guardam o contrato de carga, não o texto.
"""
import pytest

from forge.skills.loader import EIXOS, carregar_eixo, load_skills, resumo_eixos


def test_os_quatro_eixos_do_canal():
    assert EIXOS == (
        "estoicismo", "autoconhecimento", "niilismo-absurdo", "etica-digital-ia",
    )


def test_canal_e_carregada_com_procedimento_so_para_o_dono():
    assert "## Procedimento" in load_skills(["canal"], "write")
    assert "## Procedimento" not in load_skills(["canal"], "review")


def test_canal_define_a_voz_em_segunda_pessoa():
    texto = load_skills(["canal"], "review").casefold()
    assert "você" in texto
    assert "tradução livre" in texto


def test_writing_pede_segunda_pessoa():
    texto = load_skills(["writing"], "write").casefold()
    assert "segunda pessoa" in texto
    assert "primeira pessoa" not in texto


@pytest.mark.parametrize("eixo", EIXOS)
def test_cada_eixo_tem_referencia(eixo):
    assert carregar_eixo(eixo).startswith("#")


def test_eixo_ausente_ou_desconhecido_nao_quebra():
    assert carregar_eixo(None) == "(sem referência de eixo)"
    assert carregar_eixo("xyz") == "(sem referência de eixo)"


def test_resumo_lista_os_quatro_eixos():
    resumo = resumo_eixos()
    assert all(f"- {eixo}:" in resumo for eixo in EIXOS)
    # A linha de foco de cada referência é o que orienta a classificação.
    assert "controle emocional" in resumo


@pytest.mark.parametrize("agente, modulo", [
    ("plan", "forge.agents.plan"),
    ("write", "forge.agents.write"),
    ("review", "forge.agents.review"),
])
def test_agentes_de_roteiro_carregam_a_skill_do_canal(agente, modulo):
    import importlib

    assert "canal" in importlib.import_module(modulo).SKILLS
