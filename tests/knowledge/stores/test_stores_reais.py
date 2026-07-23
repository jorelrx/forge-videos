"""Roda contra os stores de verdade (docker compose up -d). Pulado se não houver.

Cobre o que fake nenhum cobre: se a generated column com CASE é aceita pelo
Postgres, se o índice único de chave_externa existe, se o ts_rank casa com o
stemmer do idioma certo, e os três defeitos do review da Task 8 que só a
execução real do DDL prova corrigidos:

1. Reprocessar um documento precisa atualizar toda a proveniência, não só um
   subconjunto de colunas.
2. `(documento_id, caminho)` é UNIQUE — dois nós do mesmo documento não podem
   reivindicar o mesmo endereço na árvore.
3. `pai_id` referencia `chunks(id)`: aponta para linha inexistente é rejeitado,
   e apagar o documento leva a árvore inteira (pai e filhos) junto via CASCADE.
"""
import pytest

from forge.infrastructure.config import Settings
from forge.knowledge.domain.models import Chunk, Documento, Proveniencia, hash_texto

pytestmark = pytest.mark.integration


@pytest.fixture
def catalog():
    psycopg = pytest.importorskip("psycopg")
    from forge.knowledge.stores.catalog import CatalogStore

    dsn = Settings().knowledge.postgres_dsn
    # connect_timeout curto: sem ele, um host inalcançável (porta morta, firewall)
    # deixa o teste pendurado no timeout de TCP do SO em vez de pular rápido.
    separador = "&" if "?" in dsn else "?"
    dsn_com_timeout = f"{dsn}{separador}connect_timeout=3"
    try:
        store = CatalogStore(dsn_com_timeout)
    except psycopg.OperationalError:
        pytest.skip("Postgres indisponível")
    store.resetar()
    yield store
    store.close()


def documento(idioma="pt", texto="corpo", doc_id=None, chave=None, **overrides):
    kwargs = dict(
        fonte="obra.md", autor="Autor Original", obra="Obra Original",
        edicao="1ª", isbn="978-00", licenca="domínio público", idioma=idioma,
        data_publicacao="1900",
    )
    kwargs.update(overrides)
    return Documento(
        id=doc_id or f"doc-{idioma}", hash_sha256=hash_texto(texto), titulo="Obra",
        texto=texto, chave_externa=chave or f"teste::{idioma}",
        proveniencia=Proveniencia.de_livro(**kwargs),
    )


def chunk(doc_id, texto, cid, *, caminho="0001.0001", pai_id=None, nivel="paragrafo", ordem=1):
    return Chunk(
        id=cid, documento_id=doc_id, pai_id=pai_id, nivel=nivel,
        caminho=caminho, ordem=ordem, texto=texto,
        offset_inicio=0, offset_fim=len(texto) if texto else 0,
    )


def paragrafo(doc_id, texto, cid):
    return chunk(doc_id, texto, cid)


def test_schema_com_generated_column_e_aceito_pelo_postgres(catalog):
    assert catalog.contar_chunks() == 0


def test_chave_externa_e_detectada_depois_do_upsert(catalog):
    doc = documento()
    catalog.upsert_documento(doc)
    assert catalog.existe_chave_externa("teste::pt")
    assert not catalog.existe_chave_externa("teste::inexistente")


def test_stemmer_portugues_casa_flexao(catalog):
    """A config `portuguese` do Postgres é sensível a diacrítico: 'existência'
    (com acento) e 'existencia'/'existencias' (sem acento) caem em radicais
    DIFERENTES ('existent' vs 'existenc') — não há unaccent no pipeline. Por
    isso a consulta usa 'existências', a flexão de plural com o mesmo acento
    do texto indexado, para provar o stemming (singular -> plural), sem
    depender de dobra de acento que o Postgres não faz aqui."""
    doc = documento()
    catalog.upsert_documento(doc)
    catalog.upsert_chunks(
        [paragrafo(doc.id, "a existência precede a essência", "c-pt")], idioma="pt"
    )
    with catalog._conn.cursor() as cur:
        cur.execute(
            "SELECT count(*) FROM chunks "
            "WHERE tsv @@ plainto_tsquery('portuguese', %(q)s)",
            {"q": "existências"},
        )
        assert cur.fetchone()[0] == 1


def test_documento_em_ingles_usa_o_stemmer_ingles(catalog):
    doc = documento(idioma="en", texto="english body")
    catalog.upsert_documento(doc)
    catalog.upsert_chunks(
        [paragrafo(doc.id, "existence precedes essence", "c-en")], idioma="en"
    )
    with catalog._conn.cursor() as cur:
        cur.execute(
            "SELECT count(*) FROM chunks "
            "WHERE tsv @@ plainto_tsquery('english', %(q)s)",
            {"q": "precede"},
        )
        assert cur.fetchone()[0] == 1


def test_apagar_documento_leva_os_chunks_junto(catalog):
    doc = documento()
    catalog.upsert_documento(doc)
    catalog.upsert_chunks([paragrafo(doc.id, "trecho qualquer", "c-1")], idioma="pt")
    assert catalog.contar_chunks() == 1
    with catalog._conn.cursor() as cur:
        cur.execute("DELETE FROM documentos WHERE id = %(i)s", {"i": doc.id})
    assert catalog.contar_chunks() == 0


# --- Fixes do review da Task 8, verificados agora por execução real -------


def test_reprocessar_documento_preserva_a_proveniencia_original(catalog):
    """Write-once: um documento já no catálogo é definitivo. `ON CONFLICT (id)
    DO NOTHING` faz o segundo upsert sob o mesmo id ser um no-op — nenhuma
    coluna muda, mesmo que a proveniência enviada seja completamente diferente.

    Isto inverte deliberadamente o antigo `test_reprocessar_documento_atualiza_
    toda_a_proveniencia` do Fix 1 da Task 8: aquele fix (`DO UPDATE SET` com
    todas as colunas) permitia corrigir um documento já ingerido. A decisão do
    usuário supersede aquele fix — nada landa duas vezes, então não há mais
    "corrigir", só "já existe, ignore".
    """
    doc_id = "doc-reprocessa"

    def com_proveniencia(**campos):
        return Documento(
            id=doc_id, hash_sha256=hash_texto("corpo"), titulo="Obra",
            texto="corpo", chave_externa="teste::reprocessa",
            proveniencia=Proveniencia(**campos),
        )

    original = com_proveniencia(
        tipo="livro", fonte="obra.md", url=None,
        autor="Autor Original", obra="Obra Original", edicao="1ª",
        isbn="978-00", licenca="domínio público", idioma="pt",
        data_publicacao="1900", autoridade=1.0,
    )
    catalog.upsert_documento(original)

    corrigido = com_proveniencia(
        tipo="web", fonte="gutenberg", url="https://exemplo.org/obra",
        autor="Autor Corrigido", obra="Obra Corrigida", edicao="2ª revisada",
        isbn="978-99", licenca="CC-BY", idioma="en",
        data_publicacao="2020", autoridade=0.4,
    )
    catalog.upsert_documento(corrigido)

    with catalog._conn.cursor() as cur:
        cur.execute(
            "SELECT autor, obra, edicao, isbn, licenca, idioma, data_publicacao, "
            "tipo, fonte, url FROM documentos WHERE id = %(i)s",
            {"i": doc_id},
        )
        row = cur.fetchone()

    (autor, obra, edicao, isbn, licenca, idioma, data_publicacao, tipo,
     fonte, url) = row
    assert autor == "Autor Original"
    assert obra == "Obra Original"
    assert edicao == "1ª"
    assert isbn == "978-00"
    assert licenca == "domínio público"
    assert idioma == "pt"
    assert data_publicacao == "1900"
    assert tipo == "livro"
    assert fonte == "obra.md"
    assert url is None


def test_caminho_duplicado_no_mesmo_documento_e_rejeitado(catalog):
    """Fix 2: `(documento_id, caminho)` é UNIQUE. Sem o índice único, um
    segundo chunk com id diferente mas mesmo endereço na árvore seria aceito
    silenciosamente — dois nós reivindicando o mesmo lugar."""
    doc = documento()
    catalog.upsert_documento(doc)
    catalog.upsert_chunks(
        [chunk(doc.id, "primeiro", "c-a", caminho="0001.0001")], idioma="pt"
    )

    psycopg = pytest.importorskip("psycopg")
    duplicado = chunk(doc.id, "segundo", "c-b", caminho="0001.0001")
    with pytest.raises(psycopg.errors.UniqueViolation):
        catalog.upsert_chunks([duplicado], idioma="pt")


def test_pai_id_inexistente_e_rejeitado(catalog):
    """Fix 3 (metade 1): `pai_id` referencia `chunks(id)`. Sem a FK, um pai_id
    apontando para uma linha que nunca existiu seria inserido normalmente,
    deixando um ramo pendurado no vazio."""
    doc = documento()
    catalog.upsert_documento(doc)

    psycopg = pytest.importorskip("psycopg")
    orfao = chunk(doc.id, "orfao", "c-orfao", caminho="0001.0001", pai_id="pai-inexistente")
    with pytest.raises(psycopg.errors.ForeignKeyViolation):
        catalog.upsert_chunks([orfao], idioma="pt")


def test_apagar_documento_leva_arvore_de_tres_niveis_junto(catalog):
    """Fix 3 (metade 2): apagar o documento tem que levar a árvore inteira.

    O Postgres cascateia via `documento_id` para todas as linhas de `chunks`,
    mas a ordem em que ele remove essas linhas dentro do cascade não é
    garantida. Se ele tentar remover um chunk-pai antes do chunk-filho, e
    `pai_id` NÃO tivesse `ON DELETE CASCADE`, essa remoção do pai violaria a FK
    do filho e o `DELETE FROM documentos` inteiro falharia (a linha nunca some
    de fato). Com árvore de 3 níveis (capítulo → seção → parágrafo) a chance de
    o Postgres bater nessa ordem é real, ao contrário de uma árvore de 1 nível
    onde não há `pai_id` não-nulo para colidir com nada."""
    doc = documento()
    catalog.upsert_documento(doc)

    capitulo = chunk(
        doc.id, None, "cap-1", caminho="0001", nivel="capitulo", pai_id=None
    )
    secao = chunk(
        doc.id, None, "sec-1", caminho="0001.0001", nivel="secao", pai_id="cap-1"
    )
    paragrafo1 = chunk(
        doc.id, "trecho um", "par-1", caminho="0001.0001.0001", pai_id="sec-1"
    )
    paragrafo2 = chunk(
        doc.id, "trecho dois", "par-2", caminho="0001.0001.0002", pai_id="sec-1"
    )
    catalog.upsert_chunks([capitulo, secao, paragrafo1, paragrafo2], idioma="pt")
    assert catalog.contar_chunks() == 4

    with catalog._conn.cursor() as cur:
        cur.execute("DELETE FROM documentos WHERE id = %(i)s", {"i": doc.id})

    assert catalog.contar_chunks() == 0
