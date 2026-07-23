from forge.knowledge.pipeline.segmentar import paragrafos, sentencas

TEXTO = (
    "Primeiro parágrafo com tamanho suficiente para não ser mesclado.\n\n"
    "Segundo parágrafo, também suficientemente longo para sobreviver sozinho.\n\n"
    "curto\n\n"
    "Terceiro parágrafo longo o bastante para permanecer separado do resto."
)


def test_paragrafos_devolvem_offsets_absolutos_que_fatiam_o_original():
    for inicio, fim in paragrafos(TEXTO, 0, len(TEXTO)):
        assert TEXTO[inicio:fim].strip() == TEXTO[inicio:fim]
        assert TEXTO[inicio:fim] in TEXTO


def test_paragrafo_curto_e_mesclado_no_seguinte():
    trechos = [TEXTO[i:f] for i, f in paragrafos(TEXTO, 0, len(TEXTO), min_chars=40)]
    assert not any(t == "curto" for t in trechos)
    assert any(t.startswith("curto") and "Terceiro" in t for t in trechos)


def test_segmentacao_respeita_a_janela_pedida():
    inicio = TEXTO.index("Segundo")
    fim = TEXTO.index("curto")
    resultado = paragrafos(TEXTO, inicio, fim)
    assert all(inicio <= i and f <= fim for i, f in resultado)


def test_janela_so_com_espaco_nao_gera_paragrafo():
    branco = "   \n\n   "
    assert paragrafos(branco, 0, len(branco)) == []


def test_sentencas_quebram_em_pontuacao_final():
    texto = "O homem é livre. Ele escolhe. E responde por isso."
    trechos = [texto[i:f] for i, f in sentencas(texto, 0, len(texto))]
    assert trechos == ["O homem é livre.", "Ele escolhe.", "E responde por isso."]


def test_abreviacao_nao_quebra_sentenca():
    texto = "Segundo o Dr. Silva, a virtude é hábito. Aristóteles concorda."
    trechos = [texto[i:f] for i, f in sentencas(texto, 0, len(texto))]
    assert trechos == [
        "Segundo o Dr. Silva, a virtude é hábito.",
        "Aristóteles concorda.",
    ]


def test_sentenca_sem_pontuacao_final_ainda_e_devolvida():
    texto = "uma frase sem ponto"
    assert [texto[i:f] for i, f in sentencas(texto, 0, len(texto))] == ["uma frase sem ponto"]


def test_sentencas_devolvem_offsets_absolutos_na_janela():
    inicio = TEXTO.index("Segundo")
    fim = TEXTO.index("curto")
    for i, f in sentencas(TEXTO, inicio, fim):
        assert inicio <= i < f <= fim
