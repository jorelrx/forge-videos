"""Embalagem: o que vai para o YouTube Studio junto com o vídeo.

O modelo propõe o que é criativo (títulos, thumbnail, abertura, rótulos, tags);
o código monta o que é fato (capítulos, fontes, comentário fixado) a partir do
roteiro aprovado e das citações.
"""
import json

import pytest

from forge.agents.embalagem import (
    AVISO_IA, EmbalagemReprovada, comentario_fixado, embalar, estimar_capitulos,
    fontes_da_descricao, gravar_embalagem, montar_descricao,
)
from forge.domain.embalagem import (
    Capitulo, EmbalagemProposta, RotuloCapitulo, ThumbnailProposta, TituloProposto,
)
from forge.domain.roteiro import SECOES_NOMES
from forge.services.citacoes import Citacao

ROTULOS = [
    "O prêmio", "O que está em jogo", "O círculo", "A virada", "O teste de Nietzsche",
    "A prova", "Duas pessoas", "Três passos", "O que fazer com o aplauso",
]


def _proposta(**mudancas) -> EmbalagemProposta:
    base = EmbalagemProposta(
        titulos=[
            TituloProposto(texto="Por que o aplauso não prova que você está certo", angulo="pergunta"),
            TituloProposto(texto="O erro de quem sempre segue a regra", angulo="contraintuitivo"),
            TituloProposto(texto="Como saber se uma regra merece obediência", angulo="benefício"),
        ],
        thumbnail=ThumbnailProposta(texto="O aplauso mente", prompt="a lone figure on a stage"),
        abertura="Todos aprovam. E se ainda assim estiver errado?",
        resumo="Um exame do que justifica uma regra.",
        capitulos=[RotuloCapitulo(secao=s, titulo=t) for s, t in zip(SECOES_NOMES, ROTULOS)],
        tags=["filosofia", "ética", "nietzsche"],
        hashtags=["#filosofia", "#ética"],
    )
    return base.model_copy(update=mudancas)


def _citacao(autor, obra, url=None, path="4363/ch2/p7"):
    return Citacao(
        secao="Prova", bloco=0, tipo="parafrase", texto="fala", autor=autor, obra=obra,
        path=path, book_id=4363, url=url,
    )


CITACOES = [
    _citacao("Nietzsche, Friedrich Wilhelm", "Beyond Good and Evil",
             "https://www.gutenberg.org/ebooks/4363"),
    _citacao("Nietzsche, Friedrich Wilhelm", "Beyond Good and Evil",
             "https://www.gutenberg.org/ebooks/4363", path="4363/ch3/p1"),
    _citacao("", "Dhammapada"),
]


# --- montagem determinística ---

def test_capitulos_estimados_pela_contagem_de_palavras(roteiro_longo):
    capitulos = estimar_capitulos(roteiro_longo(), _proposta().capitulos)

    assert [c.secao for c in capitulos] == SECOES_NOMES
    assert [c.titulo for c in capitulos] == ROTULOS
    assert capitulos[0].inicio_segundos == 0
    # Gancho tem 60 palavras; a 2,5 palavras/s o Estake começa aos 24 s.
    assert capitulos[1].inicio_segundos == 24
    # 60 + 130 = 190 palavras antes da Tensao.
    assert capitulos[2].inicio_segundos == 76


def test_rotulo_ausente_usa_o_papel_da_secao(roteiro_longo):
    rotulos = [
        RotuloCapitulo(secao="Gancho", titulo="O prêmio"),
        RotuloCapitulo(secao="Introdução", titulo="Não existe"),
    ]

    capitulos = estimar_capitulos(roteiro_longo(), rotulos)

    assert len(capitulos) == 9
    assert capitulos[0].titulo == "O prêmio"
    assert capitulos[1].titulo == "Aposta do problema"
    assert "Não existe" not in [c.titulo for c in capitulos]


def test_rotulo_aceita_secao_acentuada_e_achata_quebra_de_linha(roteiro_longo):
    rotulos = [RotuloCapitulo(secao="Tensão", titulo="O círculo\n  que não fecha ")]

    capitulos = estimar_capitulos(roteiro_longo(), rotulos)

    assert capitulos[2].titulo == "O círculo que não fecha"


def test_fontes_deduplicadas_por_autor_e_obra():
    assert fontes_da_descricao(CITACOES) == [
        "Nietzsche, Friedrich Wilhelm — Beyond Good and Evil "
        "(https://www.gutenberg.org/ebooks/4363)",
        "Dhammapada",
    ]


def test_comentario_fixado_e_a_pergunta_final_do_espelho(roteiro_longo, texto_de):
    roteiro = roteiro_longo(
        Espelho=texto_de(180, "jk") + " Você elogiaria igualmente os dois?",
    )

    assert comentario_fixado(roteiro) == "Você elogiaria igualmente os dois?"


def test_descricao_tem_abertura_capitulos_fontes_aviso_e_hashtags():
    capitulos = [
        Capitulo(secao="Gancho", titulo="O prêmio", inicio_segundos=0),
        Capitulo(secao="Estake", titulo="O que está em jogo", inicio_segundos=24),
        Capitulo(secao="Fecho", titulo="O aplauso", inicio_segundos=3725),
    ]

    descricao = montar_descricao(_proposta(), capitulos, ["Dhammapada"], aviso_ia=True)

    linhas = descricao.splitlines()
    assert linhas[0] == "Todos aprovam. E se ainda assim estiver errado?"
    assert "Um exame do que justifica uma regra." in linhas
    assert "00:00 O prêmio" in linhas
    assert "00:24 O que está em jogo" in linhas
    assert "1:02:05 O aplauso" in linhas
    assert linhas.index("Fontes") < linhas.index("- Dhammapada")
    assert AVISO_IA in linhas
    assert linhas[-1] == "#filosofia #ética"


def test_aviso_ia_desligado_sai_da_descricao():
    capitulos = [Capitulo(secao="Gancho", titulo="O prêmio", inicio_segundos=0)]

    descricao = montar_descricao(_proposta(), capitulos, ["Dhammapada"], aviso_ia=False)

    assert AVISO_IA not in descricao


# --- chamada de modelo, gate e segunda tentativa ---

def test_embalar_monta_a_embalagem_completa(scripted, roteiro_longo, texto_de):
    roteiro = roteiro_longo(Espelho=texto_de(180, "jk") + " E você, o que faria?")
    model = scripted(structured=[_proposta()])

    embalagem = embalar(model, roteiro, CITACOES)

    assert [t.texto for t in embalagem.titulos][0].startswith("Por que o aplauso")
    assert embalagem.thumbnail.texto == "O aplauso mente"
    assert len(embalagem.capitulos) == 9 and embalagem.capitulos_estimados is True
    assert embalagem.comentario_fixado == "E você, o que faria?"
    assert embalagem.fontes[1] == "Dhammapada"
    assert "00:00 O prêmio" in embalagem.descricao
    assert AVISO_IA in embalagem.descricao
    assert embalagem.tags == ["filosofia", "ética", "nietzsche"]


def test_prompt_recebe_roteiro_tese_e_obras_citadas(monkeypatch, roteiro_longo):
    from forge.agents import embalagem

    prompts = []

    def invoke(model, schema, messages, **kwargs):
        prompts.append(messages[0].content)
        return _proposta()

    monkeypatch.setattr(embalagem, "invoke_structured", invoke)
    roteiro = roteiro_longo()
    embalar(object(), roteiro, CITACOES)

    assert roteiro.tese in prompts[0]
    assert roteiro.secoes[4].conteudo in prompts[0]
    assert "Beyond Good and Evil" in prompts[0]


def test_embalar_reprovado_tenta_de_novo_com_os_achados(monkeypatch, roteiro_longo):
    from forge.agents import embalagem

    longo = _proposta().titulos[:2] + [TituloProposto(texto="x" * 80, angulo="a")]
    respostas = [_proposta(titulos=longo), _proposta()]
    prompts = []

    def invoke(model, schema, messages, **kwargs):
        prompts.append(messages[0].content)
        return respostas.pop(0)

    monkeypatch.setattr(embalagem, "invoke_structured", invoke)

    resultado = embalar(object(), roteiro_longo(), CITACOES)

    assert len(prompts) == 2
    assert "titulo_longo" not in prompts[0]
    assert "titulo_longo" in prompts[1]
    assert all(len(t.texto) <= 70 for t in resultado.titulos)


def test_embalar_reprovado_duas_vezes_levanta(scripted, roteiro_longo):
    longo = _proposta().titulos[:2] + [TituloProposto(texto="x" * 80, angulo="a")]
    model = scripted(structured=[_proposta(titulos=longo), _proposta(titulos=longo)])

    with pytest.raises(EmbalagemReprovada) as erro:
        embalar(model, roteiro_longo(), CITACOES)

    assert "titulo_longo" in erro.value.report.codes
    assert model.structured == []


def test_roteiro_sem_citacoes_reprova_por_falta_de_fontes(scripted, roteiro_longo):
    """Descrição sem fonte é o oposto do que o canal promete."""
    model = scripted(structured=[_proposta(), _proposta()])

    with pytest.raises(EmbalagemReprovada) as erro:
        embalar(model, roteiro_longo(), [])

    assert "descricao_sem_fontes" in erro.value.report.codes


def test_gravar_embalagem_escreve_json_e_markdown(scripted, roteiro_longo, tmp_path):
    embalagem = embalar(scripted(structured=[_proposta()]), roteiro_longo(), CITACOES)

    caminho_json, caminho_md = gravar_embalagem(tmp_path, embalagem)

    assert caminho_json == tmp_path / "video" / "embalagem.json"
    assert caminho_md == tmp_path / "embalagem.md"
    dados = json.loads(caminho_json.read_text(encoding="utf-8"))
    assert dados["thumbnail"]["texto"] == "O aplauso mente"
    assert len(dados["titulos"]) == 3
    markdown = caminho_md.read_text(encoding="utf-8")
    for cabecalho in ("## Títulos", "## Thumbnail", "## Descrição", "## Tags", "## Comentário fixado"):
        assert cabecalho in markdown
    assert "1. Por que o aplauso não prova que você está certo" in markdown
    assert "filosofia, ética, nietzsche" in markdown


def test_comentario_fixado_dispensa_a_frase_de_introducao(roteiro_longo, texto_de):
    """Na run real a última frase do Espelho abria com uma oração de passagem."""
    roteiro = roteiro_longo(Espelho=texto_de(180, "jk") + (
        " Primeiro, há algo mais delicado a reconhecer: qual exigência você "
        "transformou, sem perceber, numa condição para se respeitar?"
    ))

    assert comentario_fixado(roteiro) == (
        "Qual exigência você transformou, sem perceber, numa condição para se respeitar?"
    )


def test_comentario_fixado_mantem_frase_com_dois_pontos_sem_pergunta_depois(roteiro_longo, texto_de):
    roteiro = roteiro_longo(Espelho=texto_de(180, "jk") + " Pense nisto: o resto vem depois.")

    assert comentario_fixado(roteiro) == "Pense nisto: o resto vem depois."


# --- tempos reais, depois do áudio ---

def _tempos(*inicios_por_secao):
    """Um bloco por seção, começando nos segundos dados; o último dura 30 s."""
    from forge.services.linha_tempo import TrechoTempo

    pares = list(inicios_por_secao)
    fins = [inicio for _, inicio in pares[1:]] + [pares[-1][1] + 30.0]
    return [
        TrechoTempo(bloco_id=f"b{i}", secao=secao, inicio=inicio, fim=fim)
        for i, ((secao, inicio), fim) in enumerate(zip(pares, fins))
    ]


def _embalada(scripted, roteiro_longo):
    return embalar(scripted(structured=[_proposta()]), roteiro_longo(), CITACOES)


def test_tempos_reais_substituem_a_estimativa(scripted, roteiro_longo):
    from forge.agents.embalagem import aplicar_tempos_reais

    embalagem = _embalada(scripted, roteiro_longo)
    tempos = _tempos(*[(secao, 40.4 * i) for i, secao in enumerate(SECOES_NOMES)])

    real = aplicar_tempos_reais(embalagem, tempos, musica=None, aviso_ia=True)

    assert not real.capitulos_estimados
    assert [c.inicio_segundos for c in real.capitulos][:3] == [0, 40, 81]
    assert [c.titulo for c in real.capitulos] == ROTULOS
    assert "00:40 O que está em jogo" in real.descricao
    assert real.descricao.startswith("Todos aprovam.")
    assert AVISO_IA in real.descricao
    assert real.descricao.endswith("#filosofia #ética")
    assert embalagem.capitulos_estimados, "a embalagem original não é alterada"


def test_capitulo_real_curto_e_fundido_no_anterior(scripted, roteiro_longo):
    from forge.agents.embalagem import aplicar_tempos_reais
    from forge.services.qualidade_embalagem import conferir_embalagem

    embalagem = _embalada(scripted, roteiro_longo)
    inicios = [0.0, 30.0, 36.0, 90.0, 130.0, 170.0, 210.0, 250.0, 290.0]

    real = aplicar_tempos_reais(
        embalagem, _tempos(*zip(SECOES_NOMES, inicios)), musica=None, aviso_ia=True,
    )

    # Estake duraria 6 s (30 → 36): o YouTube ignoraria TODOS os capítulos.
    # A Tensao, que começa aos 36, é absorvida pelo Estake.
    assert [c.secao for c in real.capitulos][:3] == ["Gancho", "Estake", "Virada"]
    assert "capitulo_curto" not in conferir_embalagem(real).codes


def test_credito_da_musica_entra_depois_das_fontes(scripted, roteiro_longo):
    from forge.agents.embalagem import aplicar_tempos_reais

    embalagem = _embalada(scripted, roteiro_longo)
    tempos = _tempos(*[(secao, 40.0 * i) for i, secao in enumerate(SECOES_NOMES)])

    real = aplicar_tempos_reais(
        embalagem, tempos, musica="Calma — Fulano (CC BY 4.0)", aviso_ia=False,
    )

    assert real.musica == "Calma — Fulano (CC BY 4.0)"
    assert "Música: Calma — Fulano (CC BY 4.0)" in real.descricao
    assert real.descricao.index("Fontes") < real.descricao.index("Música:")
    assert AVISO_IA not in real.descricao


def test_secao_sem_tempo_real_perde_o_capitulo(scripted, roteiro_longo):
    """Seção cujos blocos não entraram na narração não tem onde apontar."""
    from forge.agents.embalagem import aplicar_tempos_reais

    embalagem = _embalada(scripted, roteiro_longo)
    tempos = _tempos(*[(secao, 40.0 * i) for i, secao in enumerate(SECOES_NOMES[:-1])])

    real = aplicar_tempos_reais(embalagem, tempos, musica=None, aviso_ia=True)

    assert [c.secao for c in real.capitulos] == SECOES_NOMES[:-1]


def test_embalagem_antiga_sem_abertura_volta_inalterada(scripted, roteiro_longo):
    """Gravada antes de a abertura ser guardada: não há como remontar a descrição."""
    from forge.agents.embalagem import aplicar_tempos_reais

    antiga = _embalada(scripted, roteiro_longo).model_copy(update={"abertura": ""})
    tempos = _tempos(*[(secao, 40.0 * i) for i, secao in enumerate(SECOES_NOMES)])

    assert aplicar_tempos_reais(antiga, tempos, musica=None, aviso_ia=True) == antiga


def test_sem_linha_do_tempo_volta_inalterada(scripted, roteiro_longo):
    from forge.agents.embalagem import aplicar_tempos_reais

    embalagem = _embalada(scripted, roteiro_longo)

    assert aplicar_tempos_reais(embalagem, [], musica=None, aviso_ia=True) == embalagem
