import json

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


def test_pesquisar_expoe_bundle_de_evidencias_sem_quebrar_unpack(scripted, acervo_fake):
    from forge.agents.research import ResearchBundle

    acervo = acervo_fake(por_query={"vontade": [_passagem("p1", 0.81)]})
    model = scripted(invoke_texts=["vontade", "notas densas"])

    bundle = pesquisar(model, "vontade de potência", acervo)
    brief, fontes, bruto = bundle

    assert isinstance(bundle, ResearchBundle)
    assert bundle.passages[0].path == "p1"
    assert bundle.canonical_paths == ["p1"]
    assert bundle.passage_count == 1
    assert (brief, fontes, bruto) == (bundle.brief, bundle.fontes, bundle.raw_markdown)


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


def test_query_sem_nenhuma_passagem_registra_so_a_evidencia(scripted, acervo_fake, tmp_path):
    """Uma query que não achou NADA é uma lacuna real, mas o acervo já a
    registrou sozinho durante a busca que acabamos de fazer
    (`routers/search.py`, `if not passages: container.log_unanswered(q)`).
    Escrever de novo no arquivo dele seria duplicação pura; a evidência do
    nosso lado continua sendo gravada."""
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
    assert not s.gaps_file.exists()
    registros = [
        json.loads(linha)
        for linha in s.respostas_ruins_file.read_text(encoding="utf-8").splitlines()
    ]
    assert [r["query"] for r in registros] == ["vazia"]


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
    exige LLM nenhum.

    A lacuna vai só para a evidência: o acervo já anotou cada uma dessas
    perguntas ele mesmo, na própria chamada de busca."""
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
    assert not s.gaps_file.exists()
    registros = [
        json.loads(linha)
        for linha in s.respostas_ruins_file.read_text(encoding="utf-8").splitlines()
    ]
    assert sorted(r["query"] for r in registros) == ["a", "b"]


def test_query_vazia_em_pool_parcial_sem_juiz_registra_evidencia(
    scripted, acervo_fake, tmp_path
):
    from forge.infrastructure.config import Settings

    settings = Settings(
        _env_file=None,
        juiz_relevancia=False,
        gaps_file=tmp_path / "gaps.txt",
        respostas_ruins_file=tmp_path / "ruins.jsonl",
    )
    acervo = acervo_fake(por_query={"boa": [_passagem("p1", 0.9)], "vazia": []})
    model = scripted(invoke_texts=["boa\nvazia", "notas densas"])

    pesquisar(model, "vontade", acervo, settings=settings)

    registros = [
        json.loads(linha)
        for linha in settings.respostas_ruins_file.read_text(encoding="utf-8").splitlines()
    ]
    assert [registro["query"] for registro in registros] == ["vazia"]


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


class _ModeloQueEspiaOJuiz:
    """Captura o prompt entregue ao juiz e devolve um veredicto fixo."""

    def __init__(self, invoke_texts, veredicto):
        self.invoke_texts = list(invoke_texts)
        self.veredicto = veredicto
        self.prompt_do_juiz = None

    def invoke(self, messages):
        from langchain_core.messages import AIMessage

        return AIMessage(content=self.invoke_texts.pop(0))

    def with_structured_output(self, schema):
        pai = self

        class _Structured:
            def invoke(self, messages):
                pai.prompt_do_juiz = messages[0].content
                return pai.veredicto

        return _Structured()


def test_juiz_recebe_as_queries_e_nao_so_o_tema(acervo_fake, tmp_path):
    """Spec S8: o juiz recebe "a query e as passagens".

    Com o tema nu, uma passagem no tema que não responde à query era aprovada,
    e a inversa ia para o arquivo de lacunas do usuário como irrespondível.
    """
    from forge.domain.models import VeredictoRelevancia
    from forge.infrastructure.config import Settings

    s = Settings(_env_file=None, gaps_file=tmp_path / "gaps.txt",
                 respostas_ruins_file=tmp_path / "ruins.jsonl")
    acervo = acervo_fake(por_query={"leibniz sobre poder oblíquo": [_passagem("p1", 0.9)]})
    model = _ModeloQueEspiaOJuiz(
        ["leibniz sobre poder oblíquo", "notas"],
        VeredictoRelevancia(relevantes=[0], motivo=""),
    )

    pesquisar(model, "vontade", acervo, settings=s)

    assert "leibniz sobre poder oblíquo" in model.prompt_do_juiz


def test_juiz_recebe_o_pedido_dirigido_do_handoff(acervo_fake, tmp_path):
    """No handoff `review → research` o `pedido` carrega a alegação a conferir.

    Sem ela o juiz aprovava qualquer coisa vagamente sobre o assunto enquanto a
    alegação seguia sem checagem — e essa volta custa ~50 min nesta máquina.
    """
    from forge.domain.models import VeredictoRelevancia
    from forge.infrastructure.config import Settings

    s = Settings(_env_file=None, gaps_file=tmp_path / "gaps.txt",
                 respostas_ruins_file=tmp_path / "ruins.jsonl")
    acervo = acervo_fake(por_query={"bergson duração": [_passagem("p1", 0.9)]})
    model = _ModeloQueEspiaOJuiz(
        ["bergson duração", "notas"],
        VeredictoRelevancia(relevantes=[0], motivo=""),
    )

    pesquisar(model, "vontade", acervo,
              pedido="Bergson afirma em Time and Free Will que a duração não é mensurável.",
              settings=s)

    assert "Time and Free Will" in model.prompt_do_juiz


def test_juiz_que_estoura_nao_derruba_a_pesquisa(acervo_fake, tmp_path):
    """O juiz é opcional (`FORGE_JUIZ_RELEVANCIA`); o roteiro não é.

    Timeout de 10 min, `400 Model unloaded by user` (não retentado pelo cliente
    OpenAI) e falha de validação de structured output são os modos de falha
    reais do lm-studio. Qualquer um matava o grafo duas horas run adentro.
    """
    from forge.infrastructure.config import Settings

    s = Settings(_env_file=None, gaps_file=tmp_path / "gaps.txt",
                 respostas_ruins_file=tmp_path / "ruins.jsonl")
    acervo = acervo_fake(por_query={"q": [_passagem("p1", 0.9)]})

    class ModeloComJuizQuebrado:
        def __init__(self):
            self.invoke_texts = ["q", "notas densas"]

        def invoke(self, messages):
            from langchain_core.messages import AIMessage

            return AIMessage(content=self.invoke_texts.pop(0))

        def with_structured_output(self, schema):
            class _Estoura:
                def invoke(self, messages):
                    raise RuntimeError("400 - Model unloaded by user or API request")

            return _Estoura()

    brief, fontes, _ = pesquisar(ModeloComJuizQuebrado(), "vontade", acervo, settings=s)

    assert brief == "notas densas"          # a síntese aconteceu
    assert [f.path for f in fontes] == ["p1"]  # a passagem sobreviveu
    assert not s.gaps_file.exists()          # nenhuma lacuna inventada
    assert not s.respostas_ruins_file.exists()


def _acervo_com_pool(acervo_fake, quantas):
    return acervo_fake(por_query={"q": [_passagem(f"p{i}", 0.9) for i in range(quantas)]})


def test_pool_grande_reprovado_inteiro_e_lido_como_juiz_quebrado(scripted, acervo_fake, tmp_path):
    """Piso de sanidade: uma dúzia de passagens reprovadas item por item é um
    veredicto degenerado, não um acervo sem o livro.

    Sem o piso, `passagens` esvazia, o controle cai no ramo de lacuna, a síntese
    é pulada e `fontes` fica vazia — e `write` não tem guarda para isso, então o
    roteiro sai afirmando coisas sem um único caminho citável.
    """
    from forge.agents.research import POOL_MINIMO_PARA_DESCONFIAR_DO_JUIZ
    from forge.domain.models import VeredictoRelevancia
    from forge.infrastructure.config import Settings

    s = Settings(_env_file=None, gaps_file=tmp_path / "gaps.txt",
                 respostas_ruins_file=tmp_path / "ruins.jsonl")
    acervo = _acervo_com_pool(acervo_fake, POOL_MINIMO_PARA_DESCONFIAR_DO_JUIZ)
    model = scripted(
        invoke_texts=["q", "notas densas"],
        structured=[VeredictoRelevancia(relevantes=[], motivo="nada serve")],
    )

    brief, fontes, _ = pesquisar(model, "vontade", acervo, settings=s)

    assert brief == "notas densas"
    assert len(fontes) == POOL_MINIMO_PARA_DESCONFIAR_DO_JUIZ
    assert not s.gaps_file.exists()
    assert not s.respostas_ruins_file.exists()


def test_pool_pequeno_reprovado_inteiro_continua_sendo_lacuna(scripted, acervo_fake, tmp_path):
    """O outro lado do piso: reprovar um punhado de passagens é plausível, e
    continua valendo como lacuna registrada — que é o que D8 existe para fazer."""
    from forge.agents.research import POOL_MINIMO_PARA_DESCONFIAR_DO_JUIZ
    from forge.domain.models import VeredictoRelevancia
    from forge.infrastructure.config import Settings

    s = Settings(_env_file=None, gaps_file=tmp_path / "gaps.txt",
                 respostas_ruins_file=tmp_path / "ruins.jsonl")
    acervo = _acervo_com_pool(acervo_fake, POOL_MINIMO_PARA_DESCONFIAR_DO_JUIZ - 1)
    # Só duas respostas na fila: queries e veredicto. Uma tentativa de sintetizar
    # estoura o modelo falso — é isso que tranca o comportamento.
    model = scripted(
        invoke_texts=["q"],
        structured=[VeredictoRelevancia(relevantes=[], motivo="nada sobre o tema")],
    )

    brief, fontes, _ = pesquisar(model, "vontade", acervo, settings=s)

    assert fontes == []
    assert "Lacuna no acervo" in brief
    assert s.gaps_file.read_text(encoding="utf-8").splitlines() == ["q"]
