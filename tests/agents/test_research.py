from forge.agents.research import colher, formular_queries, pesquisar
from forge.services.acervo import Passagem


def _passagem(path, score, titulo="Beyond Good and Evil"):
    return Passagem(
        path=path, book_id=4363, book_title=titulo,
        authors=["Friedrich Nietzsche"], breadcrumb="Cap 2",
        text=f"texto de {path}", url="http://acervo.test/books/4363", score=score,
    )


def test_formular_queries_limpa_bullets_e_numeracao(scripted):
    model = scripted(invoke_texts=[
        "1. o que é livre-arbítrio\n- determinismo causal\n* vontade em Nietzsche"
    ])

    queries = formular_queries(model, "livre-arbítrio")

    assert queries == [
        "o que é livre-arbítrio",
        "determinismo causal",
        "vontade em Nietzsche",
    ]


def test_formular_queries_corta_no_maximo(scripted):
    model = scripted(invoke_texts=["\n".join(f"query {i}" for i in range(20))])

    assert len(formular_queries(model, "x")) == 5


def test_colher_deduplica_por_path_e_ordena_por_score(acervo_fake):
    acervo = acervo_fake(por_query={
        # p1 chega primeiro com o score MAIOR (0.8) e de novo depois com o
        # MENOR (0.5) — um merge last-wins guardaria 0.5 e a asserção abaixo
        # capturaria a regressão.
        "a": [_passagem("p1", 0.8), _passagem("p2", 0.9)],
        "b": [_passagem("p1", 0.5), _passagem("p3", 0.2)],
    })

    passagens = colher(acervo, ["a", "b"])

    assert [p.path for p in passagens] == ["p2", "p1", "p3"]
    # p1 apareceu nas duas queries; fica com o maior score, não com o último.
    assert passagens[1].score == 0.8


def test_pesquisar_devolve_brief_e_fontes_estruturadas(scripted, acervo_fake):
    acervo = acervo_fake(por_query={"vontade": [_passagem("4363/ch2/p7", 0.81)]})
    model = scripted(invoke_texts=["vontade", "notas densas sobre a vontade"])

    brief, fontes, bruto = pesquisar(model, "vontade de potência", acervo)

    assert brief == "notas densas sobre a vontade"
    assert len(fontes) == 1
    assert fontes[0].titulo == "Beyond Good and Evil"
    assert fontes[0].autor == "Friedrich Nietzsche"
    assert fontes[0].path == "4363/ch2/p7"
    assert fontes[0].book_id == 4363
    assert "4363/ch2/p7" in bruto


def test_pesquisar_sem_passagens_relata_lacuna_e_nao_chama_o_modelo(scripted, acervo_fake):
    from forge.services.acervo import Candidato

    acervo = acervo_fake(candidatos=[
        Candidato(id=37358, title="Determinism or Free-Will?",
                  authors=["Chapman Cohen"]),
    ])
    # Só uma resposta na fila: a das queries. Se o agente tentar sintetizar um
    # brief sem material, o modelo falso estoura — que é o comportamento que
    # este teste tranca.
    model = scripted(invoke_texts=["determinismo"])

    brief, fontes, _ = pesquisar(model, "determinismo", acervo)

    assert fontes == []
    assert "Lacuna no acervo" in brief
    assert "Determinism or Free-Will?" in brief


def test_pesquisar_repassa_top_para_colher(scripted):
    tops_recebidos = []

    class AcervoQueRegistraTop:
        def buscar(self, q, **kwargs):
            tops_recebidos.append(kwargs.get("top"))
            return [_passagem("p1", 0.5)]

        def descobrir(self, q, **kwargs):
            return []

    model = scripted(invoke_texts=["query única", "brief"])

    pesquisar(model, "tema", AcervoQueRegistraTop(), top=3)

    assert tops_recebidos == [3]


def test_pedido_dirigido_entra_na_formulacao_das_queries(scripted, acervo_fake):
    acervo = acervo_fake(por_query={"kant sobre dever": [_passagem("p1", 0.5)]})
    model = scripted(invoke_texts=["kant sobre dever", "verificação"])

    pesquisar(model, "ética", acervo, pedido="Kant disse que o dever é X?")

    assert acervo.chamadas == ["kant sobre dever"]


def test_juiz_mantem_so_as_passagens_aprovadas(scripted):
    from forge.agents.research import julgar_relevancia
    from forge.domain.models import VeredictoRelevancia

    passagens = [_passagem("p1", 0.9), _passagem("p2", 0.8), _passagem("p3", 0.7)]
    model = scripted(structured=[
        VeredictoRelevancia(relevantes=[0, 2], motivo="a segunda fala de outro assunto")
    ])

    aprovadas, motivo = julgar_relevancia(model, "vontade", passagens)

    assert [p.path for p in aprovadas] == ["p1", "p3"]
    assert "outro assunto" in motivo


def test_juiz_ignora_indice_fora_da_lista(scripted):
    """Índice inventado pelo modelo não pode estourar nem trazer passagem errada."""
    from forge.agents.research import julgar_relevancia
    from forge.domain.models import VeredictoRelevancia

    passagens = [_passagem("p1", 0.9)]
    model = scripted(structured=[VeredictoRelevancia(relevantes=[0, 7, -3], motivo="")])

    aprovadas, _ = julgar_relevancia(model, "vontade", passagens)

    assert [p.path for p in aprovadas] == ["p1"]


def test_colher_por_query_preserva_a_origem(acervo_fake):
    from forge.agents.research import colher_por_query

    acervo = acervo_fake(por_query={
        "a": [_passagem("p1", 0.5), _passagem("p2", 0.9)],
        "b": [_passagem("p1", 0.8)],
    })

    por_query = colher_por_query(acervo, ["a", "b"])

    assert [p.path for p in por_query["a"]] == ["p1", "p2"]
    assert [p.path for p in por_query["b"]] == ["p1"]


def test_query_toda_reprovada_vira_lacuna_registrada(scripted, acervo_fake, tmp_path):
    from forge.agents.research import pesquisar
    from forge.domain.models import VeredictoRelevancia
    from forge.infrastructure.config import Settings

    s = Settings(
        _env_file=None,
        gaps_file=tmp_path / "gaps.txt",
        respostas_ruins_file=tmp_path / "ruins.jsonl",
    )
    acervo = acervo_fake(por_query={
        "boa": [_passagem("p1", 0.9)],
        "ruim": [_passagem("p2", 0.8)],
    })
    model = scripted(
        invoke_texts=["boa\nruim", "notas densas"],
        structured=[VeredictoRelevancia(relevantes=[0], motivo="a segunda é de outro assunto")],
    )

    brief, fontes, _ = pesquisar(model, "vontade", acervo, settings=s)

    assert brief == "notas densas"
    assert [f.path for f in fontes] == ["p1"]
    assert s.gaps_file.read_text(encoding="utf-8").splitlines() == ["ruim"]


def test_query_sem_nenhuma_passagem_vira_lacuna_registrada(scripted, acervo_fake, tmp_path):
    """Uma query que não achou NADA é uma lacuna tão real quanto uma rejeitada
    pelo juiz — e o guard antigo (`achadas and ...`) a descartava em silêncio."""
    from forge.agents.research import pesquisar
    from forge.domain.models import VeredictoRelevancia
    from forge.infrastructure.config import Settings

    s = Settings(
        _env_file=None,
        gaps_file=tmp_path / "gaps.txt",
        respostas_ruins_file=tmp_path / "ruins.jsonl",
    )
    acervo = acervo_fake(por_query={
        "boa": [_passagem("p1", 0.9)],
        "vazia": [],
    })
    model = scripted(
        invoke_texts=["boa\nvazia", "notas densas"],
        structured=[VeredictoRelevancia(relevantes=[0], motivo="ok")],
    )

    brief, fontes, _ = pesquisar(model, "vontade", acervo, settings=s)

    assert brief == "notas densas"
    assert [f.path for f in fontes] == ["p1"]
    assert s.gaps_file.read_text(encoding="utf-8").splitlines() == ["vazia"]


def test_tudo_reprovado_vira_brief_de_lacuna_sem_sintetizar(scripted, acervo_fake, tmp_path):
    """Sem passagem aprovada não há o que sintetizar — e a síntese é a chamada
    mais cara do pipeline (15-22 min nesta máquina)."""
    from forge.agents.research import pesquisar
    from forge.domain.models import VeredictoRelevancia
    from forge.infrastructure.config import Settings
    from forge.services.acervo import Candidato

    s = Settings(_env_file=None, gaps_file=tmp_path / "gaps.txt",
                 respostas_ruins_file=tmp_path / "ruins.jsonl")
    acervo = acervo_fake(
        por_query={"ruim": [_passagem("p1", 0.9)]},
        candidatos=[Candidato(id=37358, title="Determinism or Free-Will?", authors=["Cohen"])],
    )
    # Só duas respostas na fila: queries e veredicto. Se o agente tentar
    # sintetizar, o modelo falso estoura — que é o que este teste tranca.
    model = scripted(
        invoke_texts=["ruim"],
        structured=[VeredictoRelevancia(relevantes=[], motivo="nada sobre o tema")],
    )

    brief, fontes, _ = pesquisar(model, "vontade", acervo, settings=s)

    assert fontes == []
    assert "Lacuna no acervo" in brief
    assert "Determinism or Free-Will?" in brief
    assert s.gaps_file.read_text(encoding="utf-8").splitlines() == ["ruim"]


def test_nenhuma_query_acha_nada_registra_lacunas_sem_juiz(scripted, acervo_fake, tmp_path):
    """Falha total (nenhuma query achou passagem nenhuma) nunca chega a chamar
    o juiz — `if passagens` barra antes. Mesmo assim cada query tem que virar
    lacuna, e isso NÃO depende de `juiz_relevancia`: constatar zero linhas não
    exige LLM nenhum."""
    from forge.agents.research import pesquisar
    from forge.infrastructure.config import Settings

    s = Settings(_env_file=None, juiz_relevancia=False,
                 gaps_file=tmp_path / "gaps.txt",
                 respostas_ruins_file=tmp_path / "ruins.jsonl")
    acervo = acervo_fake(por_query={"a": [], "b": []})
    # Só uma resposta na fila: a das queries. Sem passagem nenhuma não há
    # juiz nem síntese — se o agente tentar qualquer um dos dois o modelo
    # falso estoura, o que tranca o comportamento.
    model = scripted(invoke_texts=["a\nb"])

    brief, fontes, _ = pesquisar(model, "vontade", acervo, settings=s)

    assert fontes == []
    assert "Lacuna no acervo" in brief
    assert sorted(s.gaps_file.read_text(encoding="utf-8").splitlines()) == ["a", "b"]


def test_sem_settings_o_juiz_nao_roda(scripted, acervo_fake):
    """Chamada sem settings mantém o comportamento antigo — é o que os testes
    existentes e qualquer chamador antigo esperam."""
    from forge.agents.research import pesquisar

    acervo = acervo_fake(por_query={"q": [_passagem("p1", 0.9)]})
    model = scripted(invoke_texts=["q", "notas"])

    brief, fontes, _ = pesquisar(model, "vontade", acervo)

    assert brief == "notas"
    assert len(fontes) == 1


def test_juiz_desligado_por_config(scripted, acervo_fake, tmp_path):
    from forge.agents.research import pesquisar
    from forge.infrastructure.config import Settings

    s = Settings(_env_file=None, juiz_relevancia=False,
                 gaps_file=tmp_path / "gaps.txt",
                 respostas_ruins_file=tmp_path / "ruins.jsonl")
    acervo = acervo_fake(por_query={"q": [_passagem("p1", 0.9)]})
    model = scripted(invoke_texts=["q", "notas"])

    brief, fontes, _ = pesquisar(model, "vontade", acervo, settings=s)

    assert brief == "notas"
    assert not s.gaps_file.exists()
