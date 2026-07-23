import pytest

from forge.knowledge.domain.models import (
    Chunk,
    Documento,
    Proveniencia,
    caminho_filho,
    hash_texto,
    id_de_chunk,
)


def test_id_de_chunk_vem_do_conteudo_nao_da_posicao():
    a = id_de_chunk("doc-1", "O homem está condenado à liberdade.", 0)
    b = id_de_chunk("doc-1", "O homem está condenado à liberdade.", 0)
    assert a == b


def test_id_de_chunk_separa_ocorrencias_do_mesmo_texto():
    a = id_de_chunk("doc-1", "Ibid.", 0)
    b = id_de_chunk("doc-1", "Ibid.", 1)
    assert a != b


def test_id_de_chunk_separa_documentos():
    a = id_de_chunk("doc-1", "mesmo texto", 0)
    b = id_de_chunk("doc-2", "mesmo texto", 0)
    assert a != b


def test_caminho_filho_usa_padding_de_quatro_digitos():
    assert caminho_filho("", 1) == "0001"
    assert caminho_filho("0001", 3) == "0001.0003"
    assert caminho_filho("0001.0003", 12) == "0001.0003.0012"


def test_caminho_ordena_lexicograficamente_na_ordem_numerica():
    caminhos = [caminho_filho("0001", n) for n in (10, 2, 1)]
    assert sorted(caminhos) == [
        caminho_filho("0001", 1),
        caminho_filho("0001", 2),
        caminho_filho("0001", 10),
    ]


def test_hash_texto_e_estavel_e_hexadecimal():
    h = hash_texto("texto")
    assert h == hash_texto("texto")
    assert len(h) == 64
    assert all(c in "0123456789abcdef" for c in h)


def test_documento_carrega_nivel_1_completo():
    prov = Proveniencia.de_livro(
        fonte="etica.pdf", autor="Espinosa", obra="Ética",
        edicao="2ª", isbn="978-85-000-0000-0", licenca="domínio público",
        idioma="pt", data_publicacao="1677",
    )
    doc = Documento(
        id="doc-1", hash_sha256=hash_texto("corpo"), titulo="Ética",
        texto="corpo", proveniencia=prov,
    )
    assert doc.texto == "corpo"
    assert doc.proveniencia.isbn == "978-85-000-0000-0"
    assert doc.proveniencia.licenca == "domínio público"
    assert doc.proveniencia.autoridade == 1.0
    assert doc.chave_externa is None


def test_chunk_e_no_de_arvore_sem_proveniencia_propria():
    chunk = Chunk(
        id="c-1", documento_id="doc-1", pai_id="c-0", nivel="paragrafo",
        caminho="0001.0002", ordem=2, texto="trecho",
        offset_inicio=10, offset_fim=16,
    )
    assert chunk.pagina is None
    assert chunk.embedding is None
    assert not hasattr(chunk, "proveniencia")


def test_chunk_rejeita_nivel_invalido():
    with pytest.raises(ValueError):
        Chunk(
            id="c-1", documento_id="doc-1", nivel="ideia",
            caminho="0001", ordem=1, offset_inicio=0, offset_fim=1,
        )
