from forge.knowledge.domain.models import Chunk, Documento, Proveniencia, hash_texto
from forge.knowledge.stores.vector import _payload, pontos_de

DOC = Documento(
    id="doc-1", hash_sha256=hash_texto("corpo"), titulo="Ética", texto="corpo",
    proveniencia=Proveniencia.de_livro(
        fonte="etica.pdf", autor="Espinosa", obra="Ética", idioma="pt"
    ),
)


def chunk(nivel, cid="c-1", embedding=None, texto="trecho"):
    return Chunk(
        id=cid, documento_id="doc-1", pai_id="c-0", nivel=nivel,
        caminho="0001.0002", ordem=2, texto=texto, pagina=7,
        offset_inicio=0, offset_fim=6, embedding=embedding,
    )


def test_payload_carrega_estrutura_e_proveniencia_para_citar_sem_ir_ao_postgres():
    p = _payload(DOC, chunk("paragrafo"))
    assert p["documento_id"] == "doc-1"
    assert p["pai_id"] == "c-0"
    assert p["caminho"] == "0001.0002"
    assert p["pagina"] == 7
    assert p["autor"] == "Espinosa"
    assert p["obra"] == "Ética"
    assert p["autoridade"] == 1.0
    assert p["texto"] == "trecho"


def test_so_paragrafo_com_embedding_vira_ponto():
    chunks = [
        chunk("livro", cid="raiz", embedding=[0.1]),
        chunk("paragrafo", cid="par", embedding=[0.1]),
        chunk("sentenca", cid="sen", embedding=[0.1]),
    ]
    assert [p.id for p in pontos_de(DOC, chunks)] == ["par"]


def test_paragrafo_sem_embedding_e_ignorado():
    assert pontos_de(DOC, [chunk("paragrafo", embedding=None)]) == []
