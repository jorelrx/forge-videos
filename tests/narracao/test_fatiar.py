from forge.narracao.fatiar import (
    dividir_frases,
    extrair_rubrica,
    fatiar,
    texto_narravel,
)

# Trecho literal de output/runs/20260906-183127-*/03-write-r2.md, seção Hook.
HOOK = """(Cena: Um carro acelerando numa estrada reta. O motorista olha para o painel e depois para o volante.)

Eu sei exatamente qual é a posição de cada peça no meu motor agora. Eu sei a velocidade do vento, da temperatura e onde vai dar o próximo obstáculo. Se eu fosse um computador, eu já teríamos calculado o ângulo exato da minha mão antes mesmo de ela mexer. Mas quando eu sinto vontade de virar a esquerda, não é porque uma engrenagem girou. É algo que acontece *dentro* do tempo. A ciência diz que tudo é previsível. O meu corpo diz que eu escolhi. Se a ciência está certa, por que eu me sinto livre?"""


def test_rubrica_de_cena_nao_e_narracao():
    """A rubrica descreve a imagem, não o que a voz diz. Narrá-la seria absurdo."""
    assert "Cena:" not in texto_narravel(HOOK)
    assert texto_narravel(HOOK).startswith("Eu sei exatamente")


def test_rubrica_e_recuperavel_para_semente_visual():
    rubrica = extrair_rubrica(HOOK)

    assert rubrica.startswith("Cena: Um carro acelerando")
    assert not rubrica.endswith(")")


def test_parentese_no_meio_da_frase_nao_e_rubrica():
    """`RUBRICA_RE` usa DOTALL: sem as âncoras de linha ele engoliria daqui até
    o último parêntese do texto, apagando narração."""
    conteudo = (
        "(Cena: um carro.)\n\n"
        "Hume (que era escocês) discordou. Depois calou.\n\n"
        "Outra frase (com aparte) aqui."
    )

    narravel = texto_narravel(conteudo)

    assert "Cena:" not in narravel
    assert "que era escocês" in narravel
    assert "com aparte" in narravel
    assert narravel.startswith("Hume")


def test_secao_sem_rubrica_nao_perde_texto():
    conteudo = "Primeira frase. Segunda frase."

    assert extrair_rubrica(conteudo) == ""
    assert texto_narravel(conteudo) == conteudo


def test_enfase_markdown_sai_mas_a_palavra_fica():
    """O TTS não deve receber asterisco; a palavra em si é narração."""
    assert texto_narravel("É algo que acontece *dentro* do tempo.") == (
        "É algo que acontece dentro do tempo."
    )
    assert texto_narravel("Isso é **muito** claro.") == "Isso é muito claro."
    assert texto_narravel("Isso é _sutil_ demais.") == "Isso é sutil demais."


def test_parentese_multilinha_nao_apaga_narracao_entre_eles():
    """Achado 1 (fix round 1): `.+?` com DOTALL cruzava linhas em busca do
    primeiro `)` que fechasse alguma linha seguinte, apagando tudo no meio —
    inclusive frases inteiras de narração. Uma rubrica é UMA linha só; um
    parêntese que não fecha na mesma linha não é rubrica e não deve consumir
    nada além de si mesmo."""
    conteudo = (
        "(Prologo que abre a secao sem ser rubrica de cena, apenas uma frase\n"
        "entre parenteses que continua) Nao deveria sumir isso.\n\n"
        "Segunda frase normal aqui (com aparte que termina a linha assim)\n\n"
        "Terceira frase ate o fim."
    )

    narravel = texto_narravel(conteudo)

    assert "Nao deveria sumir isso." in narravel
    assert "Segunda frase normal aqui" in narravel
    assert "com aparte que termina a linha assim" in narravel
    assert "Terceira frase ate o fim." in narravel


def test_parentese_que_fecha_a_linha_no_corpo_sobrevive():
    """Uma linha de corpo que termina em `)` não é, por si, uma rubrica de
    cena — só é rubrica se a linha INTEIRA estiver entre parênteses."""
    conteudo = "Segunda frase normal aqui (com aparte que termina a linha assim)"

    assert texto_narravel(conteudo) == conteudo


def test_rubrica_com_crlf_ainda_e_removida():
    """Achado (fix round 2): `[ \\t]*$` sob MULTILINE não considera `\\r\\n`
    como uma unidade — o `\\r` sobra antes do `$`, o `$` não casa ali, e a
    rubrica inteira deixa de ser reconhecida. Não é caso de laboratório: o
    texto de uma seção chega a `planejar_midia` direto do output estruturado
    do modelo, nunca por `Path.read_text()` — nada normaliza CRLF no caminho
    real. Escrito com `\\r\\n` literal na string, não lido de arquivo, porque
    ler em modo texto normalizaria e o teste não provaria nada."""
    conteudo = "(Cena: CRLF teste.)\r\n\r\nTexto normal aqui.\r\n"

    assert texto_narravel(conteudo) == "Texto normal aqui."
    assert extrair_rubrica(conteudo) == "Cena: CRLF teste."


def test_sublinhado_nao_funde_palavras_com_underscore_interno():
    """Achado 2 (fix round 1): `(.+?)\\1` casava o primeiro `_` de
    `livre_arbitrio` com o primeiro `_` de `determinismo_estrito` e apagava
    ambos, colando as palavras. Contagem de palavras por espaço não pega isso
    — é reescrita silenciosa, a mesma classe de bug que rubrica multilinha."""
    assert texto_narravel("Aceita o livre_arbitrio ou o determinismo_estrito?") == (
        "Aceita o livre_arbitrio ou o determinismo_estrito?"
    )


def test_divide_por_pontuacao_final():
    frases = dividir_frases("Uma. Duas! Três? Quatro.")

    assert frases == ["Uma.", "Duas!", "Três?", "Quatro."]


def test_abreviacao_nao_quebra_a_frase():
    """Um ponto depois de Sr. não termina frase; quebrar ali corta a narração no meio."""
    frases = dividir_frases("O Sr. Hume discordou. Depois calou.")

    assert frases == ["O Sr. Hume discordou.", "Depois calou."]


def test_reticencias_nao_viram_tres_frases():
    assert dividir_frases("Ele hesitou... e então falou.") == [
        "Ele hesitou... e então falou."
    ]


def test_nenhuma_palavra_se_perde():
    """A propriedade central: fatiar é cortar, nunca editar."""
    blocos = fatiar(HOOK)
    esperado = texto_narravel(HOOK).split()

    assert " ".join(blocos).split() == esperado


def test_blocos_respeitam_o_teto_de_frases():
    blocos = fatiar(HOOK, max_frases=3)

    for bloco in blocos:
        assert 1 <= len(dividir_frases(bloco)) <= 3


def test_frase_longa_sozinha_vira_um_bloco():
    """Frase que já passa do alvo de palavras não ganha companhia."""
    longa = " ".join(["palavra"] * 60) + "."
    blocos = fatiar(longa + " Curta.", alvo_palavras=35)

    assert blocos[0] == longa
    assert blocos[1] == "Curta."


def test_secao_vazia_nao_gera_bloco():
    assert fatiar("(Cena: nada acontece.)\n\n") == []
    assert fatiar("   ") == []
