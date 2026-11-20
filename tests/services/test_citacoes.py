"""`citacoes.json`: a auditoria de fontes do roteiro, derivada por código.

Nenhum modelo participa: tudo sai dos blocos estruturados do roteiro e das
passagens do acervo. É o que alimenta a seção de fontes da descrição do vídeo.
"""
from forge.agents.research import PassageEvidence
from forge.domain.models import BlocoRoteiro, CitacaoLiteral, Roteiro, Secao
from forge.services.citacoes import (
    Citacao, carregar_citacoes, derivar_citacoes, gravar_citacoes,
)

ZARATUSTRA = PassageEvidence(
    path="1998/150.f1", book_id=1998, title="Thus Spake Zarathustra",
    authors=["Nietzsche, Friedrich Wilhelm"],
    text="All delight longs for repetitions.",
    url="https://www.gutenberg.org/ebooks/1998",
)
ALEM = PassageEvidence(
    path="4363/ch2/p7", book_id=4363, title="Beyond Good and Evil",
    authors=["Nietzsche, Friedrich Wilhelm"],
    text="The will to truth tempts us.",
    url="https://www.gutenberg.org/ebooks/4363",
)
PORTUGUES = PassageEvidence(
    path="9/p1", book_id=9, title="Obra em português", authors=[],
    text="A liberdade exige escolha.",
)


def _roteiro(*blocos_da_prova):
    return Roteiro(tema="t", tese="te", secoes=[
        Secao(nome="Gancho", conteudo="Abertura.", blocos=[BlocoRoteiro(texto="Abertura.")]),
        Secao(nome="Prova", conteudo="x", blocos=list(blocos_da_prova)),
    ])


def test_derivar_classifica_traducao_parafrase_e_literal():
    traduzido = BlocoRoteiro(
        texto='Nietzsche escreve, em tradução livre: "todo deleite anseia por repetição".',
        referencias=[ZARATUSTRA.path],
        citacoes_literais=[CitacaoLiteral(
            path=ZARATUSTRA.path, trecho="All delight longs for repetitions.",
            traducao="todo deleite anseia por repetição",
        )],
    )
    parafrase = BlocoRoteiro(
        texto="Para Nietzsche, a vontade de verdade nos seduz.", referencias=[ALEM.path],
    )
    literal = BlocoRoteiro(
        texto="A liberdade exige escolha.", referencias=[PORTUGUES.path],
        citacoes_literais=[CitacaoLiteral(path=PORTUGUES.path, trecho="A liberdade exige escolha.")],
    )

    citacoes = derivar_citacoes(
        _roteiro(traduzido, parafrase, literal), [ZARATUSTRA, ALEM, PORTUGUES],
    )

    assert [c.tipo for c in citacoes] == ["traducao", "parafrase", "literal"]
    assert [c.bloco for c in citacoes] == [0, 1, 2]
    assert all(c.secao == "Prova" for c in citacoes)

    assert citacoes[0].texto == "todo deleite anseia por repetição"
    assert citacoes[0].original == "All delight longs for repetitions."
    assert citacoes[0].obra == "Thus Spake Zarathustra"
    assert citacoes[0].autor == "Nietzsche, Friedrich Wilhelm"
    assert citacoes[0].path == "1998/150.f1" and citacoes[0].book_id == 1998

    assert citacoes[1].texto == parafrase.texto
    assert citacoes[1].original is None
    assert citacoes[1].url == "https://www.gutenberg.org/ebooks/4363"

    assert citacoes[2].texto == "A liberdade exige escolha."
    assert citacoes[2].autor == "" and citacoes[2].url is None


def test_bloco_com_citacao_nao_repete_o_mesmo_caminho_como_parafrase():
    bloco = BlocoRoteiro(
        texto="A liberdade exige escolha. E a vontade de verdade seduz.",
        referencias=[PORTUGUES.path, ALEM.path],
        citacoes_literais=[CitacaoLiteral(path=PORTUGUES.path, trecho="A liberdade exige escolha.")],
    )

    citacoes = derivar_citacoes(_roteiro(bloco), [PORTUGUES, ALEM])

    assert [(c.tipo, c.path) for c in citacoes] == [
        ("literal", PORTUGUES.path), ("parafrase", ALEM.path),
    ]


def test_referencia_sem_passagem_conhecida_e_omitida():
    """Roteiro legado pode citar caminho que não está nas evidências guardadas."""
    bloco = BlocoRoteiro(texto="Fala.", referencias=["sumiu/p1", ALEM.path])

    citacoes = derivar_citacoes(_roteiro(bloco), [ALEM])

    assert [c.path for c in citacoes] == [ALEM.path]


def test_roteiro_sem_blocos_nao_tem_citacoes():
    roteiro = Roteiro(tema="t", tese="te", secoes=[Secao(nome="Prova", conteudo="Texto.")])

    assert derivar_citacoes(roteiro, [ALEM]) == []


def test_gravar_e_carregar_ida_e_volta(tmp_path):
    citacoes = [Citacao(
        secao="Prova", bloco=0, tipo="parafrase", texto="Fala.", original=None,
        autor="Nietzsche", obra="Beyond Good and Evil", path="4363/ch2/p7",
        book_id=4363, url=None,
    )]

    caminho = gravar_citacoes(tmp_path, citacoes)

    assert caminho == tmp_path / "video" / "citacoes.json"
    assert carregar_citacoes(tmp_path) == citacoes


def test_carregar_sem_arquivo_devolve_vazio(tmp_path):
    assert carregar_citacoes(tmp_path) == []


def test_citacao_guarda_a_lista_de_autores():
    """O cartão na tela precisa de cada autor separado; a string juntada por
    vírgula não distingue dois autores de "Sobrenome, Nome"."""
    import inspect

    from forge.services import citacoes

    assert "autores=list(passagem.authors)" in inspect.getsource(citacoes._citacao)
    assert citacoes.Citacao.model_fields["autores"].default_factory is list
