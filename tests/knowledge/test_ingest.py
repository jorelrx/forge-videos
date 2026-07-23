from forge.infrastructure.config import Settings
from forge.knowledge.domain.models import Documento, Proveniencia, hash_texto
from forge.knowledge.ingest import Stores, entrada_de_documento, ingerir_entradas
from forge.knowledge.sources.extract.texto import extrair_texto

LIVRO = """# Capítulo 1

Primeiro parágrafo do capítulo um, longo o suficiente para virar chunk próprio.

Segundo parágrafo do capítulo um, também com tamanho adequado para sobreviver.

# Capítulo 2

Parágrafo do capítulo dois, escrito com folga para passar do mínimo exigido.
"""


class FakeCatalog:
    """Espelha as constraints reais do Postgres (catalog.py): PK em `id` com
    `ON CONFLICT DO NOTHING` (write-once) e UNIQUE em `(documento_id, caminho)`.
    Um fake permissivo aqui é exatamente o que deixou o UniqueViolation real
    passar batido por 195 testes verdes."""

    def __init__(self):
        self._documentos: dict[str, object] = {}
        self._chunks: dict[str, object] = {}
        self._caminhos: dict[tuple[str, str], str] = {}

    @property
    def documentos(self):
        return list(self._documentos.values())

    @property
    def chunks(self):
        return list(self._chunks.values())

    def garantir_schema(self):
        pass

    def resetar(self):
        self._documentos.clear()
        self._chunks.clear()
        self._caminhos.clear()

    def upsert_documento(self, doc):
        if doc.id in self._documentos:
            return  # DO NOTHING: write-once
        self._documentos[doc.id] = doc

    def upsert_chunks(self, chunks, *, idioma=None):
        inseridos = 0
        for c in chunks:
            chave_caminho = (c.documento_id, c.caminho)
            dono_atual = self._caminhos.get(chave_caminho)
            if dono_atual is not None and dono_atual != c.id:
                raise ValueError(
                    f"caminho duplicado no mesmo documento: {chave_caminho} "
                    f"já pertence a {dono_atual}, não a {c.id}"
                )
            if c.id in self._chunks:
                continue  # DO NOTHING: write-once
            self._chunks[c.id] = c
            self._caminhos[chave_caminho] = c.id
            inseridos += 1
        return inseridos

    def existe_chave_externa(self, chave):
        return any(d.chave_externa == chave for d in self._documentos.values())


class FakeVector:
    def __init__(self):
        self.pontos = []

    def garantir_colecao(self):
        pass

    def resetar(self):
        self.pontos.clear()

    def upsert_chunks(self, doc, chunks):
        indexados = [c for c in chunks if c.nivel == "paragrafo" and c.embedding]
        self.pontos.extend(indexados)
        return len(indexados)


class FakeGraph:
    def __init__(self):
        self.escritas = 0

    def garantir_schema(self):
        pass

    def resetar(self):
        self.escritas = 0


def embed_fake(textos):
    return [[float(len(t)), 1.0, 0.0] for t in textos]


def documento(texto=LIVRO):
    return Documento(
        id="doc-1", hash_sha256=hash_texto(texto), titulo="Livro", texto=texto,
        proveniencia=Proveniencia.de_livro(fonte="livro.md", idioma="pt"),
    )


def montar():
    return Stores(vector=FakeVector(), graph=FakeGraph(), catalog=FakeCatalog())


def ingerir(texto=LIVRO, stores=None):
    stores = stores or montar()
    doc = documento(texto)
    total = ingerir_entradas(
        [(doc, extrair_texto(texto))],
        embed_fn=embed_fake, stores=stores, settings=Settings(),
    )
    return stores, doc, total


def test_ingestao_nao_toca_no_modelo_de_linguagem():
    # `ingerir_entradas` não recebe `model`: se algum estágio tentar usar LLM,
    # a assinatura quebra antes de o teste rodar.
    stores, _, total = ingerir()
    assert total > 0
    assert stores.catalog.documentos


def test_documento_e_persistido_com_texto_integro():
    stores, doc, _ = ingerir()
    assert stores.catalog.documentos[0].texto == LIVRO
    assert stores.catalog.documentos[0].hash_sha256 == doc.hash_sha256


def test_arvore_inteira_vai_para_o_catalogo():
    stores, _, _ = ingerir()
    niveis = {c.nivel for c in stores.catalog.chunks}
    assert {"livro", "capitulo", "paragrafo", "sentenca"} <= niveis


def test_so_paragrafo_e_embedado_e_indexado():
    stores, _, _ = ingerir()
    assert all(c.nivel == "paragrafo" for c in stores.vector.pontos)
    embedados = [c for c in stores.catalog.chunks if c.embedding is not None]
    assert all(c.nivel == "paragrafo" for c in embedados)


def test_grafo_nao_recebe_nada_em_k1():
    stores, _, _ = ingerir()
    assert stores.graph.escritas == 0


def test_fidelidade_paragrafos_recompoem_o_original_em_ordem():
    stores, _, _ = ingerir()
    posicao = 0
    for chunk in [c for c in stores.catalog.chunks if c.nivel == "paragrafo"]:
        posicao = LIVRO.index(chunk.texto, posicao)
        posicao += len(chunk.texto)


def test_reingestao_no_mesmo_store_preserva_as_folhas_originais():
    """Write-once (Fix 3): um documento já no catálogo é definitivo. Reingerir
    o MESMO documento no MESMO store — não em stores separados, que nunca
    provaria nada sobre reingestão de verdade — não pode alterar nem duplicar
    as folhas (parágrafo/sentença) já persistidas: `ON CONFLICT (id) DO
    NOTHING` faz o segundo upsert ser um no-op linha a linha."""
    def folhas(stores):
        return {
            c.id: c.texto for c in stores.catalog.chunks
            if c.nivel in {"paragrafo", "sentenca"}
        }

    stores = montar()
    ingerir(stores=stores)
    antes = folhas(stores)

    ingerir(stores=stores)  # mesmo texto, mesmo doc.id -> reingestão real
    depois = folhas(stores)

    assert antes == depois


def test_entrada_de_documento_detecta_marcas_de_texto_sem_arquivo():
    doc = documento()
    _, extraido = entrada_de_documento(doc)
    assert extraido.texto == LIVRO
    assert [m.titulo for m in extraido.marcas] == ["Capítulo 1", "Capítulo 2"]
    assert extraido.paginas == []
