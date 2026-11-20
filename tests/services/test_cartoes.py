"""Cartões de fonte: quem está sendo citado aparece na tela, sem poluir."""
import re

from forge.domain.midia import BlocoNarracao
from forge.domain.models import CitacaoLiteral
from forge.services.cartoes import (
    CITACAO_MAXIMO,
    RODAPE_SEGUNDOS,
    Cartao,
    gerar_ass,
    planejar_cartoes,
)
from forge.services.citacoes import Citacao
from forge.services.linha_tempo import TrechoTempo

JAMES = "acervo/james/varieties/p12"
JAMES_2 = "acervo/james/varieties/p40"
SENECA = "acervo/seneca/cartas/p3"
ANONIMO = "acervo/anonimo/p1"


def _citacao(path, autor, obra):
    return Citacao(
        secao="Gancho", bloco=0, tipo="parafrase", texto="x",
        autor=autor, obra=obra, path=path,
    )


CITACOES = [
    _citacao(JAMES, "William James", "The Varieties of Religious Experience"),
    _citacao(JAMES_2, "William James", "The Varieties of Religious Experience"),
    _citacao(SENECA, "Sêneca", "Cartas a Lucílio"),
    _citacao(ANONIMO, "", "Upanishads"),
]


def _bloco(id_, secao, *, referencias=(), literais=()):
    return BlocoNarracao(
        id=id_, secao=secao, texto="Texto falado.",
        referencias=list(referencias), citacoes_literais=list(literais),
    )


def _tempos(blocos, duracao=10.0):
    tempos, cursor = [], 0.0
    for bloco in blocos:
        tempos.append(TrechoTempo(
            bloco_id=bloco.id, secao=bloco.secao, inicio=cursor, fim=cursor + duracao,
        ))
        cursor += duracao
    return tempos


def _planejar(blocos, duracao=10.0, citacoes=CITACOES):
    return planejar_cartoes(blocos, _tempos(blocos, duracao), citacoes)


# --- planejar_cartoes -------------------------------------------------------


def test_literal_curta_vira_citacao_pela_duracao_do_bloco():
    literal = CitacaoLiteral(path=SENECA, trecho="Enquanto adiamos, a vida passa.")
    cartoes = _planejar([_bloco("b1", "Gancho", literais=[literal])])

    assert cartoes == [Cartao(
        tipo="citacao", inicio=0.0, fim=10.0,
        atribuicao="Sêneca — Cartas a Lucílio",
        texto="Enquanto adiamos, a vida passa.", traducao=False,
    )]


def test_traducao_mostra_o_texto_falado_e_marca_traducao():
    literal = CitacaoLiteral(
        path=JAMES, trecho="The greatest discovery", traducao="A maior descoberta",
    )
    [cartao] = _planejar([_bloco("b1", "Gancho", literais=[literal])])

    assert cartao.tipo == "citacao"
    assert cartao.texto == "A maior descoberta"
    assert cartao.traducao is True


def test_literal_longa_demais_cai_para_rodape():
    trecho = "palavra " * 40
    assert len(trecho.strip()) > CITACAO_MAXIMO
    literal = CitacaoLiteral(path=SENECA, trecho=trecho.strip())
    [cartao] = _planejar([_bloco("b1", "Gancho", literais=[literal])], duracao=20.0)

    assert cartao.tipo == "rodape"
    assert cartao.texto == ""
    assert cartao.atribuicao == "Sêneca — Cartas a Lucílio"
    assert cartao.fim - cartao.inicio <= RODAPE_SEGUNDOS


def test_literal_no_limite_ainda_e_citacao():
    literal = CitacaoLiteral(path=SENECA, trecho="a" * CITACAO_MAXIMO)
    [cartao] = _planejar([_bloco("b1", "Gancho", literais=[literal])])

    assert cartao.tipo == "citacao"


def test_parafrase_vira_rodape_de_ate_seis_segundos():
    [cartao] = _planejar([_bloco("b1", "Gancho", referencias=[JAMES])], duracao=15.0)

    assert cartao == Cartao(
        tipo="rodape", inicio=0.0, fim=RODAPE_SEGUNDOS,
        atribuicao="William James — The Varieties of Religious Experience",
    )


def test_rodape_nao_passa_do_fim_do_bloco():
    [cartao] = _planejar([_bloco("b1", "Gancho", referencias=[JAMES])], duracao=2.5)

    assert (cartao.inicio, cartao.fim) == (0.0, 2.5)


def test_obra_sem_autor_atribui_so_a_obra():
    [cartao] = _planejar([_bloco("b1", "Gancho", referencias=[ANONIMO])])

    assert cartao.atribuicao == "Upanishads"


def test_mesma_obra_em_blocos_seguidos_da_mesma_secao_nao_repete():
    blocos = [
        _bloco("b1", "Gancho", referencias=[JAMES]),
        _bloco("b2", "Gancho", referencias=[JAMES_2]),
        _bloco("b3", "Gancho", referencias=[JAMES]),
    ]

    assert [c.inicio for c in _planejar(blocos)] == [0.0]


def test_mesma_obra_reaparece_na_primeira_citacao_de_outra_secao():
    blocos = [
        _bloco("b1", "Gancho", referencias=[JAMES]),
        _bloco("b2", "Estake", referencias=[JAMES]),
        _bloco("b3", "Estake", referencias=[JAMES]),
    ]

    assert [c.inicio for c in _planejar(blocos)] == [0.0, 10.0]


def test_obra_diferente_gera_cartao_novo():
    blocos = [
        _bloco("b1", "Gancho", referencias=[JAMES]),
        _bloco("b2", "Gancho", referencias=[SENECA]),
        _bloco("b3", "Gancho", referencias=[JAMES]),
    ]

    assert [c.atribuicao.split(" — ")[0] for c in _planejar(blocos)] == [
        "William James", "Sêneca", "William James",
    ]


def test_caminho_desconhecido_nao_gera_cartao():
    literal = CitacaoLiteral(path="acervo/nao/existe", trecho="Frase qualquer.")
    blocos = [
        _bloco("b1", "Gancho", referencias=["acervo/nao/existe"]),
        _bloco("b2", "Gancho", literais=[literal]),
    ]

    assert _planejar(blocos) == []


def test_bloco_sem_citacao_nao_ganha_cartao():
    assert _planejar([_bloco("b1", "Gancho")]) == []


def test_um_cartao_por_bloco_e_citacao_vence_rodape():
    literal = CitacaoLiteral(path=SENECA, trecho="Enquanto adiamos, a vida passa.")
    bloco = _bloco("b1", "Gancho", referencias=[JAMES, SENECA], literais=[literal])

    [cartao] = _planejar([bloco])

    assert cartao.tipo == "citacao"
    assert cartao.atribuicao.startswith("Sêneca")


def test_literal_desconhecida_nao_impede_rodape_da_parafrase_conhecida():
    literal = CitacaoLiteral(path="acervo/nao/existe", trecho="Frase.")
    bloco = _bloco("b1", "Gancho", referencias=[JAMES], literais=[literal])

    [cartao] = _planejar([bloco])

    assert cartao.tipo == "rodape"
    assert cartao.atribuicao.startswith("William James")


def test_bloco_sem_tempo_e_pulado():
    blocos = [_bloco("b1", "Gancho", referencias=[JAMES])]

    assert planejar_cartoes(blocos, [], CITACOES) == []


def test_cartoes_nao_se_sobrepoem():
    literal = CitacaoLiteral(path=SENECA, trecho="Enquanto adiamos, a vida passa.")
    blocos = [
        _bloco("b1", "Gancho", referencias=[JAMES]),
        _bloco("b2", "Gancho", literais=[literal]),
        _bloco("b3", "Gancho", referencias=[JAMES]),
        _bloco("b4", "Estake", literais=[literal]),
        _bloco("b5", "Estake", referencias=[SENECA, JAMES]),
    ]
    cartoes = _planejar(blocos, duracao=3.0)

    assert len(cartoes) >= 4
    for anterior, seguinte in zip(cartoes, cartoes[1:]):
        assert anterior.fim <= seguinte.inicio
    assert all(c.inicio < c.fim for c in cartoes)


def test_sem_citacoes_nao_ha_cartoes():
    literal = CitacaoLiteral(path=SENECA, trecho="Frase.")
    blocos = [_bloco("b1", "Gancho", referencias=[JAMES], literais=[literal])]

    assert _planejar(blocos, citacoes=[]) == []


# --- gerar_ass ----------------------------------------------------------------


def _todos_eventos(ass):
    return [linha for linha in ass.splitlines() if linha.startswith("Dialogue:")]


def _eventos(ass):
    """Eventos de texto; o fundo escurecido da citação é desenho, não texto."""
    return [l for l in _todos_eventos(ass) if l.split(",")[3] != "Fundo"]


def _texto_do_evento(linha):
    # Format tem 10 campos; o texto é o último e pode conter vírgulas.
    return linha.split(",", 9)[9]


def test_ass_tem_cabecalho_estilos_e_eventos():
    cartoes = [
        Cartao(tipo="rodape", inicio=1.5, fim=7.5, atribuicao="Sêneca — Cartas"),
        Cartao(
            tipo="citacao", inicio=3725.25, fim=3730.0,
            atribuicao="Sêneca — Cartas", texto="A vida passa.",
        ),
    ]
    ass = gerar_ass(cartoes, fonte="Georgia")

    assert ass.startswith("[Script Info]")
    assert "PlayResX: 1920" in ass
    assert "PlayResY: 1080" in ass
    assert "[V4+ Styles]" in ass
    estilos = {l.split(",")[0]: l for l in ass.splitlines() if l.startswith("Style:")}
    assert {"Style: Rodape", "Style: Citacao"} <= set(estilos)
    assert estilos["Style: Rodape"].split(",")[1] == "Georgia"
    assert estilos["Style: Citacao"].split(",")[1] == "Georgia"
    # Rodapé no canto inferior esquerdo (an1), citação no centro (an5).
    assert estilos["Style: Rodape"].split(",")[18] == "1"
    assert estilos["Style: Citacao"].split(",")[18] == "5"
    assert "[Events]" in ass
    eventos = _eventos(ass)
    assert len(eventos) == 2
    assert ",0:00:01.50,0:00:07.50," in eventos[0]
    assert ",1:02:05.25,1:02:10.00," in eventos[1]
    for linha in eventos:
        assert re.match(r"Dialogue: \d+,\d:\d\d:\d\d\.\d\d,\d:\d\d:\d\d\.\d\d,", linha)


def test_citacao_tem_fundo_escurecido_por_baixo_no_mesmo_intervalo():
    cartoes = [
        Cartao(tipo="citacao", inicio=2.0, fim=9.0, atribuicao="Obra", texto="Frase."),
        Cartao(tipo="rodape", inicio=10.0, fim=12.0, atribuicao="Obra"),
    ]
    todos = _todos_eventos(gerar_ass(cartoes, fonte="Georgia"))
    fundos = [l for l in todos if l.split(",")[3] == "Fundo"]
    [texto] = [l for l in todos if l.split(",")[3] == "Citacao"]

    assert len(fundos) == 1
    assert fundos[0].split(",")[1:3] == texto.split(",")[1:3]
    assert int(fundos[0].split(",")[0].split()[1]) < int(texto.split(",")[0].split()[1])
    assert "\\p1" in fundos[0]


def test_ass_respeita_resolucao_recebida():
    ass = gerar_ass([], fonte="Arial", largura=1280, altura=720)

    assert "PlayResX: 1280" in ass
    assert "PlayResY: 720" in ass


def test_ass_sem_cartoes_e_valido_e_sem_eventos():
    ass = gerar_ass([], fonte="Georgia")

    assert "[Script Info]" in ass and "[V4+ Styles]" in ass and "[Events]" in ass
    assert "Format: Layer, Start, End" in ass
    assert _eventos(ass) == []


def test_texto_e_escapado_e_nao_vira_override_nem_quebra_a_linha():
    cartoes = [
        Cartao(
            tipo="citacao", inicio=0.0, fim=5.0,
            atribuicao="Autor {\\b1} — Obra",
            texto="Um {\\pos(0,0)} truque\\N com\nquebra\r\nreal",
        ),
        Cartao(tipo="rodape", inicio=6.0, fim=8.0, atribuicao="Obra\n{x}\\h"),
    ]
    ass = gerar_ass(cartoes, fonte="Georgia")
    eventos = _eventos(ass)

    assert len(eventos) == 2
    # Nenhuma linha solta: tudo que não é cabeçalho conhecido é evento.
    corpo = ass.split("[Events]", 1)[1].strip().splitlines()
    assert all(l.startswith(("Format:", "Dialogue:")) for l in corpo)
    citacao, rodape = (_texto_do_evento(l) for l in eventos)
    for texto in (citacao, rodape):
        # Só as tags nossas abrem bloco de override; nada vindo do texto.
        for bloco in _blocos_override(texto):
            assert "pos" not in bloco and "b1" not in bloco and "x" not in bloco
    # O que se vê é o texto original, com chaves e barras literais.
    assert "Um {\\pos(0,0)} truque\\N com quebra real" in _visivel(citacao)
    assert "Autor {\\b1} — Obra" in _visivel(citacao)
    assert "Obra {x}\\h" in _visivel(rodape)


def _blocos_override(texto):
    """Blocos `{...}` que o libass leria como comando: chave sem `\\` antes."""
    return re.findall(r"(?<!\\)\{([^}]*)\}", texto)


def _visivel(texto):
    """Aproxima o que o libass desenha: tira overrides e desfaz os escapes."""
    texto = re.sub(r"(?<!\\)\{[^}]*\}", "", texto)
    texto = texto.replace("\\N", "\n").replace("\\{", "{").replace("\\}", "}")
    return texto.replace("​", "")


def test_citacao_longa_e_quebrada_em_linhas():
    texto = ("A vida não é breve; nós é que a desperdiçamos com coisas pequenas, "
             "e quando enfim percebemos que ela passou, já não há tempo de vivê-la "
             "como gostaríamos de ter vivido.")
    ass = gerar_ass(
        [Cartao(tipo="citacao", inicio=0, fim=5, atribuicao="Sêneca — Obra", texto=texto)],
        fonte="Georgia",
    )
    [evento] = _eventos(ass)
    texto_evento = _texto_do_evento(evento)
    # O corpo vai até a linha em branco que separa a atribuição.
    partes = re.sub(r"\{[^}]*\}", "", texto_evento).split("\\N")
    linhas = partes[:[p.strip() for p in partes].index("")]

    assert len(linhas) >= 3
    assert all(len(l) <= 50 for l in linhas)
    # Nenhuma palavra se perde na quebra.
    assert " ".join(linhas).split() == texto.split()


def test_atribuicao_da_citacao_fica_em_linha_propria():
    ass = gerar_ass(
        [Cartao(tipo="citacao", inicio=0, fim=5, atribuicao="Sêneca — Obra", texto="Curta.")],
        fonte="Georgia",
    )
    texto = _texto_do_evento(_eventos(ass)[0])
    assert re.search(r"Curta\.\\N.*Sêneca — Obra", texto)


def test_traducao_livre_so_aparece_quando_ha_traducao():
    traduzida = Cartao(
        tipo="citacao", inicio=0, fim=5, atribuicao="James — Obra",
        texto="A maior descoberta.", traducao=True,
    )
    original = traduzida.model_copy(update={"traducao": False})
    rodape = Cartao(tipo="rodape", inicio=6, fim=8, atribuicao="James — Obra")

    assert "tradução livre" in gerar_ass([traduzida], fonte="Georgia")
    assert "tradução livre" not in gerar_ass([original], fonte="Georgia")
    assert "tradução livre" not in gerar_ass([rodape], fonte="Georgia")


def test_autor_em_forma_de_catalogo_e_mostrado_na_ordem_de_leitura():
    """O acervo traz "James, William"; na tela isso lê como ficha de biblioteca."""
    from forge.services.cartoes import _atribuicao
    from forge.services.citacoes import Citacao

    def fonte(*autores, autor=None):
        return Citacao(
            secao="Gancho", bloco=0, tipo="parafrase", texto="x",
            autor=autor if autor is not None else ", ".join(autores),
            autores=list(autores), obra="Obra", path="1/a",
        )

    assert _atribuicao(fonte("James, William")) == "William James — Obra"
    assert _atribuicao(fonte("Nietzsche, Friedrich Wilhelm")) == "Friedrich Wilhelm Nietzsche — Obra"
    assert _atribuicao(fonte("Plato")) == "Plato — Obra"
    # Data no lugar do prenome fica como veio.
    assert _atribuicao(fonte("Laozi, 6th century BCE")) == "Laozi, 6th century BCE — Obra"
    # Cada autor é invertido sozinho: juntos por vírgula, dois nomes simples
    # pareceriam "Sobrenome, Nome" e virariam uma pessoa que não existe.
    assert _atribuicao(fonte("Epictetus", "Thomas Wentworth Higginson")) == (
        "Epictetus, Thomas Wentworth Higginson — Obra"
    )
    assert _atribuicao(fonte("Marx, Karl", "Engels, Friedrich")) == "Karl Marx, Friedrich Engels — Obra"


def test_citacao_antiga_sem_lista_de_autores_nao_e_invertida():
    """Sem a lista não dá para saber se a vírgula separa nome ou pessoas."""
    from forge.services.cartoes import _atribuicao
    from forge.services.citacoes import Citacao

    antiga = Citacao(
        secao="Gancho", bloco=0, tipo="parafrase", texto="x",
        autor="Epictetus, Thomas Wentworth Higginson", obra="Obra", path="1/a",
    )

    assert _atribuicao(antiga) == "Epictetus, Thomas Wentworth Higginson — Obra"
