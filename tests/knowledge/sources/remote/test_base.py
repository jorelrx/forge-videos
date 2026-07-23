from forge.knowledge.domain.models import Documento, Proveniencia, hash_texto
from forge.knowledge.sources.remote.base import Referencia, buscar_e_baixar


def _ref(id_externo, fonte="pag"):
    return Referencia(fonte=fonte, id_externo=id_externo, titulo=id_externo, url="u" + id_externo)


def _doc(ref):
    return Documento(
        id=ref.chave, hash_sha256=hash_texto("t"), titulo=ref.titulo, texto="t",
        proveniencia=Proveniencia.de_fonte_remota(fonte=ref.fonte, autoridade=1.0),
        chave_externa=ref.chave_externa,
    )


class FontePaginada:
    """Devolve páginas fixas; página além do fim retorna [] (esgotou)."""
    nome = "pag"

    def __init__(self, paginas):
        self._paginas = paginas  # list[list[Referencia]]
        self.chamadas = 0

    def buscar(self, query, *, http, pagina):
        self.chamadas += 1
        idx = pagina - 1
        return list(self._paginas[idx]) if 0 <= idx < len(self._paginas) else []

    def baixar(self, ref, *, http):
        return _doc(ref)


def test_limite_por_fonte():
    f = FontePaginada([[_ref("1"), _ref("2"), _ref("3")]])
    docs = buscar_e_baixar([f], "q", limite=2, http=None)
    assert [d.titulo for d in docs] == ["1", "2"]  # capa em limite mesmo com 3 na página


def test_dedupe_por_chave():
    f = FontePaginada([[_ref("1"), _ref("1"), _ref("2")]])
    docs = buscar_e_baixar([f], "q", limite=10, http=None)
    assert [d.titulo for d in docs] == ["1", "2"]  # duplicata removida


def test_pula_ja_ingerido_e_pega_proximo():
    # página tem 1,2,3; 1 e 2 já ingeridos -> pula, pega o 3 (próximo da lista)
    f = FontePaginada([[_ref("1"), _ref("2"), _ref("3")]])
    ingeridos = {_ref("1").chave, _ref("2").chave}
    docs = buscar_e_baixar([f], "q", limite=1, http=None, ja_ingerido=ingeridos.__contains__)
    assert [d.titulo for d in docs] == ["3"]


def test_pagina_ate_completar_limite():
    # limite 2; pág1 tem 1 (já ingerido) + 2; pág2 tem 3 + 4. Espera 2 e 3.
    f = FontePaginada([[_ref("1"), _ref("2")], [_ref("3"), _ref("4")]])
    docs = buscar_e_baixar([f], "q", limite=2, http=None, ja_ingerido={_ref("1").chave}.__contains__)
    assert [d.titulo for d in docs] == ["2", "3"]
    assert f.chamadas == 2  # precisou da 2ª página


def test_para_em_pagina_sem_refs_ineditas():
    # fonte que ignora paginação: devolve sempre a mesma página
    class FonteNaoPagina:
        nome = "np"

        def __init__(self):
            self.chamadas = 0

        def buscar(self, query, *, http, pagina):
            self.chamadas += 1
            return [_ref("1", "np"), _ref("2", "np")]

        def baixar(self, ref, *, http):
            return _doc(ref)

    f = FonteNaoPagina()
    docs = buscar_e_baixar([f], "q", limite=5, http=None, ja_ingerido=lambda _c: True, max_paginas=99)
    assert docs == []
    assert f.chamadas == 2  # pág1 (tudo já ingerido) + pág2 (nada inédito) -> para, não roda 99


def test_max_paginas_cap():
    # cada página traz uma ref inédita, mas todas já ingeridas -> nunca completa
    class FonteInfinita:
        nome = "inf"

        def __init__(self):
            self.chamadas = 0

        def buscar(self, query, *, http, pagina):
            self.chamadas += 1
            return [_ref(str(pagina), "inf")]

        def baixar(self, ref, *, http):
            return _doc(ref)

    f = FonteInfinita()
    docs = buscar_e_baixar([f], "q", limite=5, http=None, ja_ingerido=lambda _c: True, max_paginas=3)
    assert docs == []
    assert f.chamadas == 3  # parou no teto de páginas


def test_fonte_que_quebra_na_busca_nao_derruba_lote():
    class FonteQuebra:
        nome = "quebra"

        def buscar(self, query, *, http, pagina):
            raise RuntimeError("api fora")

        def baixar(self, ref, *, http):
            return _doc(ref)

    boa = FontePaginada([[_ref("1"), _ref("2")]])
    docs = buscar_e_baixar([FonteQuebra(), boa], "q", limite=10, http=None)
    assert [d.titulo for d in docs] == ["1", "2"]  # só a fonte boa


def test_ref_que_quebra_no_download_e_pulada():
    class FonteBaixarRuim:
        nome = "ruim"

        def buscar(self, query, *, http, pagina):
            return [_ref("9", "ruim")] if pagina == 1 else []

        def baixar(self, ref, *, http):
            raise RuntimeError("download 404")

    boa = FontePaginada([[_ref("1"), _ref("2")]])
    docs = buscar_e_baixar([FonteBaixarRuim(), boa], "q", limite=10, http=None)
    assert [d.titulo for d in docs] == ["1", "2"]  # ref ruim pulada, fonte boa mantém 2


def test_documento_vazio_e_descartado():
    class FonteVazia:
        nome = "vazia"

        def buscar(self, query, *, http, pagina):
            return [_ref("1", "vazia")] if pagina == 1 else []

        def baixar(self, ref, *, http):
            return Documento(
                id=ref.chave, hash_sha256=hash_texto("   "), titulo=ref.titulo, texto="   ",
                proveniencia=Proveniencia.de_fonte_remota(fonte=ref.fonte, autoridade=1.0),
                chave_externa=ref.chave_externa,
            )

    boa = FontePaginada([[_ref("1"), _ref("2")]])
    docs = buscar_e_baixar([FonteVazia(), boa], "q", limite=10, http=None)
    assert [d.titulo for d in docs] == ["1", "2"]
    assert all(d.texto.strip() for d in docs)


class FonteEN:
    """Fonte só-inglês: declara idioma_busca; captura a query recebida."""
    nome = "en_only"
    idioma_busca = "en"

    def __init__(self):
        self.recebidas = []

    def buscar(self, query, *, http, pagina):
        self.recebidas.append(query)
        return [_ref("1", "en_only")] if pagina == 1 else []

    def baixar(self, ref, *, http):
        return _doc(ref)


def test_traduz_query_para_fonte_com_idioma_busca():
    f = FonteEN()
    docs = buscar_e_baixar([f], "estoicismo", limite=1, http=None, traduzir=lambda t, i: f"{t}|{i}")
    assert f.recebidas == ["estoicismo|en"]  # query traduzida antes de buscar
    assert len(docs) == 1


def test_nao_traduz_fonte_sem_idioma_busca():
    recebidas = []

    class FontePt:
        nome = "pt"

        def buscar(self, query, *, http, pagina):
            recebidas.append(query)
            return [_ref("1", "pt")] if pagina == 1 else []

        def baixar(self, ref, *, http):
            return _doc(ref)

    buscar_e_baixar([FontePt()], "estoicismo", limite=1, http=None, traduzir=lambda t, i: "NUNCA")
    assert recebidas == ["estoicismo"]  # sem idioma_busca, query intacta


def test_traducao_memoizada_entre_paginas_e_fontes():
    chamadas = []

    def trad(texto, idioma):
        chamadas.append((texto, idioma))
        return "translated"

    a, b = FonteEN(), FonteEN()
    buscar_e_baixar([a, b], "q", limite=1, http=None, traduzir=trad)
    assert len(chamadas) == 1  # mesma idioma -> traduz uma vez só (memoizado)


def test_construir_fontes_expande_all():
    from types import SimpleNamespace

    from forge.knowledge.sources.remote import construir_fontes

    settings = SimpleNamespace(knowledge=SimpleNamespace(wikisource_langs=["pt"]))
    fontes = construir_fontes(["all"], settings=settings)
    nomes = {f.nome for f in fontes}
    assert nomes == {"gutenberg", "internet_archive", "wikisource", "sep"}


def test_construir_fontes_subconjunto():
    from types import SimpleNamespace

    from forge.knowledge.sources.remote import construir_fontes

    settings = SimpleNamespace(knowledge=SimpleNamespace(wikisource_langs=["pt"]))
    fontes = construir_fontes(["gutenberg"], settings=settings)
    assert [f.nome for f in fontes] == ["gutenberg"]


def test_ingerir_busca_remota_sem_docs_retorna_zero(monkeypatch):
    from types import SimpleNamespace

    import forge.knowledge.ingest as ing

    monkeypatch.setattr(ing, "construir_fontes", lambda nomes, *, settings: [], raising=False)

    def _boom(_s):
        raise AssertionError("_montar não devia ser chamado sem docs")

    monkeypatch.setattr(ing, "_montar", _boom)

    settings = SimpleNamespace(
        knowledge=SimpleNamespace(
            wikisource_langs=["pt"], remote_top_n=3, remote_rate_delay=0,
            remote_timeout=5, cache_dir="x", remote_max_pages=10,
            postgres_dsn="postgresql://forge:forge@localhost:5432/forge",
        )
    )
    total = ing.ingerir_busca_remota(["gutenberg"], "tema", settings)
    assert total == 0
