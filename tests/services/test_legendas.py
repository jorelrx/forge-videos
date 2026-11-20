"""Legenda: nenhuma palavra perdida, linhas curtas, tempos coerentes, SRT estável."""

from __future__ import annotations

import re

from forge.domain.midia import BlocoNarracao
from forge.services.legendas import (
    LINHA_MAXIMO,
    LINHAS_MAXIMO,
    Deixa,
    conferir_deixas,
    formatar_srt,
    gerar_deixas,
)
from forge.services.linha_tempo import TrechoTempo


def _bloco(texto: str, bid: str = "b1", secao: str = "Gancho") -> BlocoNarracao:
    return BlocoNarracao(id=bid, secao=secao, texto=texto)


def _tempo(bid: str, inicio: float, fim: float, secao: str = "Gancho") -> TrechoTempo:
    return TrechoTempo(bloco_id=bid, secao=secao, inicio=inicio, fim=fim)


def _palavras(deixas: list[Deixa]) -> list[str]:
    return " ".join(d.texto for d in deixas).split()


FRASE_LONGA = (
    "Marco Aurélio escreveu, numa tenda gelada junto ao Danúbio, que o obstáculo "
    "ao caminho torna-se o próprio caminho, e que ninguém é ferido por aquilo "
    "que não consegue nomear."
)


def test_nenhuma_palavra_perdida_e_tags_fora():
    texto = (
        "<|emotion:awe|> Você já olhou para o céu? <|prosody:pause|> "
        "Ele não olha de volta. Mas nós olhamos."
    )
    deixas = gerar_deixas([_bloco(texto)], [_tempo("b1", 0.0, 12.0)])
    esperado = "Você já olhou para o céu? Ele não olha de volta. Mas nós olhamos.".split()
    assert _palavras(deixas) == esperado
    assert all("<|" not in d.texto for d in deixas)


def test_rubrica_e_enfase_nao_sao_legenda():
    deixas = gerar_deixas(
        [_bloco("(cena: céu noturno)\nIsto é **muito** importante.")],
        [_tempo("b1", 0.0, 5.0)],
    )
    assert _palavras(deixas) == "Isto é muito importante.".split()


def test_linhas_respeitam_limites():
    deixas = gerar_deixas([_bloco(FRASE_LONGA)], [_tempo("b1", 0.0, 30.0)])
    assert _palavras(deixas) == FRASE_LONGA.split()
    assert len(deixas) > 1
    for d in deixas:
        linhas = d.texto.split("\n")
        assert 1 <= len(linhas) <= LINHAS_MAXIMO
        assert all(len(linha) <= LINHA_MAXIMO for linha in linhas)


def test_frase_longa_quebra_em_virgula():
    deixas = gerar_deixas([_bloco(FRASE_LONGA)], [_tempo("b1", 0.0, 30.0)])
    # Todas menos a última terminam em vírgula: o corte preferiu a pontuação.
    assert deixas[0].texto.replace("\n", " ").endswith(",")


def test_frase_longa_sem_virgula_quebra_em_espaco():
    texto = " ".join(["palavra"] * 30) + "."
    deixas = gerar_deixas([_bloco(texto)], [_tempo("b1", 0.0, 40.0)])
    assert _palavras(deixas) == texto.split()
    for d in deixas:
        assert all(len(x) <= LINHA_MAXIMO for x in d.texto.split("\n"))


def test_palavra_unica_maior_que_a_linha_e_excecao_aceita():
    gigante = "x" * 60
    deixas = gerar_deixas([_bloco(f"Veja {gigante} agora.")], [_tempo("b1", 0.0, 10.0)])
    assert _palavras(deixas) == ["Veja", gigante, "agora."]
    assert conferir_deixas(deixas) == []


def test_bloco_curto_funde_deixas():
    bloco = _bloco("Sim. Talvez. Nunca.")
    deixas = gerar_deixas([bloco], [_tempo("b1", 0.0, 0.6)])
    assert len(deixas) == 1
    assert (deixas[0].inicio, deixas[0].fim) == (0.0, 0.6)
    assert _palavras(deixas) == ["Sim.", "Talvez.", "Nunca."]


def test_bloco_longo_mantem_deixas_de_pelo_menos_um_segundo():
    texto = "Primeira ideia aqui. Segunda ideia aqui. Terceira ideia aqui."
    deixas = gerar_deixas([_bloco(texto)], [_tempo("b1", 0.0, 9.0)])
    assert len(deixas) == 3
    assert all(round(d.fim - d.inicio, 3) >= 1.0 for d in deixas)


def test_funde_so_o_necessario():
    # Duas frases curtas ao lado de uma longa: as curtas ficam abaixo de 1 s
    # e se fundem; a longa continua sozinha.
    texto = "Oi. Sim. " + FRASE_LONGA
    deixas = gerar_deixas([_bloco(texto)], [_tempo("b1", 0.0, 20.0)])
    assert _palavras(deixas) == texto.split()
    assert all(round(d.fim - d.inicio, 3) >= 1.0 for d in deixas)


def test_tempos_crescentes_sem_sobreposicao_e_fim_do_bloco():
    blocos = [_bloco(FRASE_LONGA, "b1"), _bloco("Curto. Demais.", "b2"),
              _bloco("Mais uma frase comum para fechar.", "b3")]
    tempos = [_tempo("b1", 0.0, 17.3), _tempo("b2", 17.3, 17.9), _tempo("b3", 17.9, 22.0)]
    deixas = gerar_deixas(blocos, tempos)
    assert conferir_deixas(deixas) == []
    assert deixas[0].inicio == 0.0
    assert deixas[-1].fim == 22.0
    for ant, atual in zip(deixas, deixas[1:]):
        assert atual.inicio >= ant.fim
    # Última deixa de cada bloco termina no fim do bloco.
    fins = {d.fim for d in deixas}
    assert {17.3, 17.9, 22.0} <= fins


def test_bloco_sem_tempo_e_pulado():
    blocos = [_bloco("Tem tempo.", "b1"), _bloco("Sem tempo.", "b2")]
    deixas = gerar_deixas(blocos, [_tempo("b1", 0.0, 3.0)])
    assert _palavras(deixas) == ["Tem", "tempo."]


def test_bloco_so_com_tags_nao_gera_deixa():
    deixas = gerar_deixas([_bloco("<|prosody:pause|>")], [_tempo("b1", 0.0, 2.0)])
    assert deixas == []


def test_formato_srt_exato():
    deixas = [
        Deixa(inicio=1.5, fim=4.0, texto="Primeira linha\nsegunda linha"),
        Deixa(inicio=4.0, fim=3661.007, texto="Outra"),
    ]
    assert formatar_srt(deixas) == (
        "1\n00:00:01,500 --> 00:00:04,000\nPrimeira linha\nsegunda linha\n"
        "\n"
        "2\n00:00:04,000 --> 01:01:01,007\nOutra\n"
    )


def test_srt_vazio():
    assert formatar_srt([]) == ""


def test_caracteres_estranhos_nao_quebram_o_srt():
    texto = "Olha {\\an8} isto <b>aqui</b> --> e\n\n\nlá \\N fim."
    deixas = gerar_deixas([_bloco(texto)], [_tempo("b1", 0.0, 8.0)])
    srt = formatar_srt(deixas)
    for d in deixas:
        for c in "{}<>\\":
            assert c not in d.texto
    blocos_srt = srt.strip().split("\n\n")
    assert len(blocos_srt) == len(deixas)
    for i, b in enumerate(blocos_srt, start=1):
        linhas = b.split("\n")
        assert linhas[0] == str(i)
        assert re.fullmatch(r"\d\d:\d\d:\d\d,\d{3} --> \d\d:\d\d:\d\d,\d{3}", linhas[1])
        assert all(linha.strip() for linha in linhas[2:])
        assert "-->" not in "\n".join(linhas[2:])
    # As palavras de verdade sobreviveram.
    assert {"Olha", "isto", "aqui", "e", "lá", "fim."} <= set(_palavras(deixas))


def test_formatar_srt_defende_texto_de_fora():
    # Deixa montada à mão, com linha em branco e marcação: o SRT não rompe.
    d = Deixa(inicio=0.0, fim=2.0, texto="a\n\n<i>b</i> {x}\n --> c")
    srt = formatar_srt([d])
    assert "\n\n" not in srt.rstrip("\n")
    assert "<" not in srt and "{" not in srt
    assert srt.count("-->") == 1


def test_conferir_deixas_ok():
    assert conferir_deixas([Deixa(inicio=0, fim=1, texto="a"),
                            Deixa(inicio=1, fim=2, texto="b")]) == []


def test_conferir_acusa_sobreposicao():
    problemas = conferir_deixas([Deixa(inicio=0, fim=2, texto="a"),
                                 Deixa(inicio=1.5, fim=3, texto="b")])
    assert len(problemas) == 1 and "sobrepõe" in problemas[0]


def test_conferir_acusa_ordem_invertida():
    problemas = conferir_deixas([Deixa(inicio=5, fim=6, texto="a"),
                                 Deixa(inicio=1, fim=2, texto="b")])
    assert any("ordem" in p for p in problemas)


def test_conferir_acusa_deixa_vazia_e_duracao_nao_positiva():
    problemas = conferir_deixas([Deixa(inicio=0, fim=1, texto="  \n "),
                                 Deixa(inicio=2, fim=2, texto="b")])
    assert any("vazia" in p for p in problemas)
    assert any("duração" in p for p in problemas)


def test_conferir_acusa_linhas_demais_ou_longas():
    longa = "palavra " * 8
    problemas = conferir_deixas([
        Deixa(inicio=0, fim=1, texto="a\nb\nc"),
        Deixa(inicio=1, fim=2, texto=longa.strip()),
    ])
    assert any("linhas" in p for p in problemas)
    assert any(str(LINHA_MAXIMO) in p for p in problemas)
