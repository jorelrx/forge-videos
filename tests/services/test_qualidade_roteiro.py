import pytest

from forge.domain.models import Roteiro, Secao
from forge.services.qualidade_roteiro import avaliar_roteiro, conferir_roteiro, conferir_secao


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


def test_espelho_requires_question_as_final_sentence():
    report = conferir_secao(
        "Espelho",
        {
            "nome": "Espelho",
            "conteudo": (
                "Ada Lovelace devolve a decisão para sua rotina e pede um gesto concreto. "
                "Qual escolha está escondida? A resposta começa no próximo passo."
            ),
        },
        [{"title": "Notas", "authors": ["Ada Lovelace"]}],
    )
    assert not report.approved
    assert "espelho_sem_pergunta" in report.codes


def test_citacao_reconhece_nome_em_ordem_natural_e_sobrenome_com_path():
    source = {"title": "Principles", "authors": ["James, William"], "path": "2.2.60.f3"}
    for text in ("William James descreve o eu social.", "James descreve o eu social. [2.2.60.f3]"):
        assert "sem_citacao" not in conferir_secao("Estake", text, [source]).codes
    for text in ("James descreve o eu social.", "James descreve o eu social. [9.f1]", "Outro autor descreve o eu social. [2.2.60.f3]"):
        assert "sem_citacao" in conferir_secao("Estake", text, [source]).codes


def _texto_com_palavras(nome: str, quantidade: int) -> str:
    aberturas = {
        "Gancho": "ab", "Estake": "cd", "Tensao": "ef",
        "Virada": "gh", "Filosofo": "ij", "Prova": "kl",
        "Espelho": "mn", "Aplicacao": "op", "Fecho": "qr",
    }
    palavras = [aberturas[nome] if indice < 18 else f"palavra{indice}" for indice in range(quantidade)]
    if nome != "Gancho":
        palavras[20:22] = ["Ada", "Lovelace"]
    if nome == "Fecho":
        palavras[22] = "agora"
    frases = [palavras[inicio:inicio + 20] for inicio in range(0, quantidade, 20)]
    pontuacao_final = "?" if nome == "Espelho" else "."
    return " ".join(
        " ".join(frase) + (pontuacao_final if indice == len(frases) - 1 else ".")
        for indice, frase in enumerate(frases)
    )


def test_gancho_66_palavras_passam_com_desenvolvimento_mais_longo():
    from forge.domain.roteiro import ARQUITETURA

    nomes = ["Gancho", "Estake", "Tensao", "Virada", "Filosofo", "Prova", "Espelho", "Aplicacao", "Fecho"]
    minimos = {secao.nome: secao.alvo_palavras[0] for secao in ARQUITETURA}
    payload = {
        "tema": "Tema",
        "tese": "Tese",
        "secoes": [
            {"nome": nome, "conteudo": _texto_com_palavras(nome, 66 if nome == "Gancho" else minimos[nome])}
            for nome in nomes
        ],
        "passages_by_section": {
            nome: [{"title": "Notas da máquina", "authors": ["Ada Lovelace"]}]
            for nome in nomes if nome != "Gancho"
        },
    }

    report = conferir_roteiro(payload)

    assert report.approved, [(finding.code, finding.section, finding.details) for finding in report.findings if finding.serious]
    assert "tamanho_desviante" not in report.codes


def test_secao_muito_abaixo_do_minimo_individual_continua_reprovada():
    report = conferir_secao("Gancho", " ".join(f"palavra{indice}" for indice in range(11)), None)

    assert not report.approved
    assert "secao_curta" in report.codes


# --- roteiro de canal: duração e técnicas de retenção ---

def test_roteiro_dentro_dos_alvos_passa(roteiro_longo):
    report = avaliar_roteiro(roteiro_longo())

    assert report.approved, [(f.code, f.section, f.details) for f in report.findings if f.serious]
    assert report.metrics["palavras_total"] == 1600


def test_total_abaixo_de_1500_reprova(roteiro_longo):
    """Cada seção ainda passa sozinha (>= 60% do mínimo); o total é que não fecha."""
    report = avaliar_roteiro(roteiro_longo(Prova=170, Filosofo=160))

    assert "secao_curta" not in report.codes
    assert "roteiro_curto" in report.codes


def test_total_acima_de_2800_e_aviso(roteiro_longo):
    report = avaliar_roteiro(roteiro_longo(Prova=630, Filosofo=600, Aplicacao=500, Tensao=440))

    assert "roteiro_longo" not in report.codes
    assert any(f.code == "roteiro_longo" and not f.serious for f in report.findings)


@pytest.mark.parametrize("abertura", [
    "Olá, bem-vindo ao canal.",
    "Neste vídeo vamos falar de escolhas.",
    "Hoje vamos entender o vazio.",
    "Antes de começar, um aviso.",
    "Fala, pessoal, tudo bem?",
])
def test_gancho_com_preambulo_reprova(roteiro_longo, texto_de, abertura):
    report = avaliar_roteiro(roteiro_longo(Gancho=abertura + " " + texto_de(70, "ba")))

    assert "gancho_com_preambulo" in report.codes


def test_gancho_que_entra_na_cena_nao_e_preambulo(roteiro_longo, texto_de):
    report = avaliar_roteiro(
        roteiro_longo(Gancho="Você acorda às três da manhã. " + texto_de(70, "ba"))
    )

    assert "gancho_com_preambulo" not in report.codes


def test_cta_agressivo_fora_do_fecho_e_aviso(roteiro_longo, texto_de):
    report = avaliar_roteiro(
        roteiro_longo(Tensao=texto_de(200, "di") + " Inscreva-se no canal.")
    )

    assert report.approved
    assert any(f.code == "cta_agressivo" and f.section == "Tensao" for f in report.findings)


def test_convite_no_fecho_nao_e_cta_agressivo(roteiro_longo, texto_de):
    report = avaliar_roteiro(
        roteiro_longo(Fecho=texto_de(120, "nq") + " Se fizer sentido, inscreva-se no canal.")
    )

    assert not any(f.code == "cta_agressivo" for f in report.findings)
