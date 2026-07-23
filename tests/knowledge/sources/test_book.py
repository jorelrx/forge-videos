import pytest

from forge.knowledge.domain.models import hash_texto
from forge.knowledge.sources.book import carregar_livro

CORPO = "# Capítulo 1\n\nParágrafo com tamanho suficiente para virar chunk próprio.\n"


def escrever(tmp_path, nome, corpo=CORPO):
    caminho = tmp_path / nome
    caminho.write_text(corpo, encoding="utf-8")
    return caminho


def test_documento_guarda_o_texto_integro_e_seu_hash(tmp_path):
    doc, _ = carregar_livro(escrever(tmp_path, "etica.md"))
    assert doc.texto == CORPO
    assert doc.hash_sha256 == hash_texto(CORPO)


def test_id_vem_da_chave_externa_e_e_estavel_pelo_caminho(tmp_path):
    caminho = escrever(tmp_path, "etica.md")
    doc_a, _ = carregar_livro(caminho)
    doc_b, _ = carregar_livro(caminho)
    assert doc_a.id == doc_b.id

    outro_caminho = escrever(tmp_path, "outro-nome.md")
    doc_c, _ = carregar_livro(outro_caminho)
    assert doc_a.id != doc_c.id


def test_reprocessar_arquivo_editado_mantem_id_mas_muda_hash(tmp_path):
    caminho = escrever(tmp_path, "a.md")
    doc_a, _ = carregar_livro(caminho)

    escrever(tmp_path, "a.md", CORPO + "\nmais texto aqui.\n")
    doc_b, _ = carregar_livro(caminho)

    assert doc_a.id == doc_b.id
    assert doc_a.hash_sha256 != doc_b.hash_sha256


def test_chave_externa_de_livro_local_e_o_caminho_absoluto(tmp_path):
    caminho = escrever(tmp_path, "etica.md")
    doc, _ = carregar_livro(caminho)
    assert doc.chave_externa == f"arquivo::{caminho.resolve()}"


def test_mesmo_nome_em_diretorios_diferentes_sao_obras_diferentes(tmp_path):
    dir_a = tmp_path / "a"
    dir_b = tmp_path / "b"
    dir_a.mkdir()
    dir_b.mkdir()
    caminho_a = dir_a / "etica.md"
    caminho_b = dir_b / "etica.md"
    caminho_a.write_text(CORPO, encoding="utf-8")
    caminho_b.write_text(CORPO, encoding="utf-8")

    doc_a, _ = carregar_livro(caminho_a)
    doc_b, _ = carregar_livro(caminho_b)

    assert doc_a.chave_externa != doc_b.chave_externa
    assert doc_a.id != doc_b.id


def test_devolve_a_extracao_com_as_marcas_detectadas(tmp_path):
    _, extraido = carregar_livro(escrever(tmp_path, "etica.md"))
    assert extraido.texto == CORPO
    assert [m.titulo for m in extraido.marcas] == ["Capítulo 1"]


def test_proveniencia_e_de_livro_com_autoridade_maxima(tmp_path):
    doc, _ = carregar_livro(escrever(tmp_path, "etica.md"))
    assert doc.proveniencia.tipo == "livro"
    assert doc.proveniencia.autoridade == 1.0
    assert doc.proveniencia.fonte == "etica.md"


def test_formato_nao_suportado_falha_com_mensagem_explicita(tmp_path):
    caminho = tmp_path / "arquivo.docx"
    caminho.write_text("x", encoding="utf-8")
    with pytest.raises(ValueError, match="não suportado"):
        carregar_livro(caminho)
