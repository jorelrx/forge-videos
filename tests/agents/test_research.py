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
