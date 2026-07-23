import re

from forge.knowledge.domain.models import Chunk, Documento, Proveniencia, hash_texto
from forge.knowledge.stores.catalog import (
    _SCHEMA,
    _UPSERT_CHUNK,
    _UPSERT_DOC,
    linha_chunk,
    linha_documento,
)


def documento():
    return Documento(
        id="doc-1", hash_sha256=hash_texto("corpo"), titulo="Ética", texto="corpo",
        chave_externa="gutenberg::1234",
        proveniencia=Proveniencia.de_livro(
            fonte="etica.pdf", autor="Espinosa", obra="Ética", edicao="2ª",
            isbn="978-85", licenca="domínio público", idioma="pt",
            data_publicacao="1677",
        ),
    )


def test_linha_documento_leva_o_texto_integro_e_o_hash():
    linha = linha_documento(documento())
    assert linha["texto"] == "corpo"
    assert linha["hash_sha256"] == hash_texto("corpo")


def test_linha_documento_achata_toda_a_proveniencia_de_nivel_1():
    linha = linha_documento(documento())
    for campo in ("autor", "obra", "edicao", "isbn", "licenca", "idioma",
                  "data_publicacao", "url", "fonte", "tipo", "autoridade"):
        assert campo in linha
    assert linha["autor"] == "Espinosa"
    assert linha["chave_externa"] == "gutenberg::1234"


def test_linha_chunk_leva_a_estrutura_e_nao_a_proveniencia():
    chunk = Chunk(
        id="c-1", documento_id="doc-1", pai_id="c-0", nivel="paragrafo",
        caminho="0001.0002", ordem=2, titulo=None, texto="trecho",
        pagina=3, offset_inicio=10, offset_fim=16,
    )
    linha = linha_chunk(chunk)
    assert linha == {
        "id": "c-1", "documento_id": "doc-1", "pai_id": "c-0",
        "nivel": "paragrafo", "caminho": "0001.0002", "ordem": 2,
        "titulo": None, "texto": "trecho", "pagina": 3,
        "offset_inicio": 10, "offset_fim": 16,
    }


def test_schema_indexa_tsvector_por_idioma_e_nao_fixo_em_portugues():
    assert "CASE" in _SCHEMA
    assert "'english'" in _SCHEMA
    assert "'portuguese'" in _SCHEMA


def test_schema_tem_indice_unico_de_chave_externa_para_dedup_pre_download():
    assert "chave_externa" in _SCHEMA
    assert "UNIQUE" in _SCHEMA


def test_schema_liga_chunk_ao_pai_e_indexa_o_caminho():
    assert "pai_id" in _SCHEMA
    assert "chunks_caminho_idx" in _SCHEMA


def test_upsert_doc_e_write_once_nunca_atualiza_um_id_existente():
    """Write-once: um documento já no catálogo é definitivo. `ON CONFLICT (id)
    DO NOTHING` faz o segundo upsert sob o mesmo id ser um no-op — nada é
    reprocessado, nada é corrigido, a linha original nunca muda.

    Isto inverte deliberadamente o antigo teste (Task 8, Fix 1) que exigia
    `DO UPDATE SET` cobrindo todas as colunas: a decisão do usuário supersede
    aquele fix, então a cláusula correta agora é a ausência de qualquer UPDATE.
    """
    assert "ON CONFLICT (id) DO NOTHING" in _UPSERT_DOC
    assert "DO UPDATE" not in _UPSERT_DOC


def test_upsert_chunk_e_write_once_nunca_atualiza_um_id_existente():
    assert "ON CONFLICT (id) DO NOTHING" in _UPSERT_CHUNK
    assert "DO UPDATE" not in _UPSERT_CHUNK


def test_schema_indice_de_caminho_e_unico_por_documento():
    """A árvore estrutural é imutável: reprocessar o mesmo livro reproduz os
    mesmos caminhos. Um índice único em (documento_id, caminho) barra dois nós
    do mesmo documento reivindicando o mesmo endereço — sinal de bug de
    ordenação upstream que hoje passaria silenciosamente."""
    match = re.search(
        r"CREATE (UNIQUE )?INDEX[^;]*chunks_caminho_idx\s+ON\s+chunks\s*\(([^)]*)\)",
        _SCHEMA,
    )
    assert match, "índice chunks_caminho_idx não encontrado no schema"
    assert match.group(1) == "UNIQUE ", "chunks_caminho_idx deve ser UNIQUE"
    colunas = [c.strip() for c in match.group(2).split(",")]
    assert colunas == ["documento_id", "caminho"]


def test_schema_pai_id_referencia_chunks_com_cascade():
    """pai_id precisa de FK para chunks(id): sem ela, um pai_id apontando para
    linha inexistente insere normalmente e deixa um ramo pendurado no vazio. O
    ON DELETE CASCADE é necessário porque a ordem de remoção dentro do cascade
    de documento_id não é garantida — sem ele um pai pode sumir antes do
    filho."""
    match = re.search(
        r"pai_id\s+TEXT(?:\s+REFERENCES\s+chunks\s*\(\s*id\s*\)\s+ON DELETE CASCADE)?",
        _SCHEMA,
    )
    assert match, "coluna pai_id não encontrada"
    assert "REFERENCES" in match.group(0) and "chunks" in match.group(0), (
        "pai_id deve referenciar chunks(id)"
    )
    assert "ON DELETE CASCADE" in match.group(0)
