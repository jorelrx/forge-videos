import types

from forge.agents.tema import _texto, gerar_tema


def test_tema_fornecido_nao_chama_modelo():
    assert gerar_tema(None, "Sobre o tédio") == "Sobre o tédio"


def test_tema_gerado(scripted):
    model = scripted(invoke_texts=["O tédio é um alarme"])
    assert gerar_tema(model) == "O tédio é um alarme"


def test_texto_lista_de_blocos_de_conteudo():
    resp = types.SimpleNamespace(content=[
        {"type": "text", "text": "abc"},
        {"type": "thinking", "thinking": "x"},
        {"type": "text", "text": "def"},
    ])
    assert _texto(resp) == "abcdef"
