import pytest

from forge.agents.midia import propor_beats
from forge.domain.midia import BeatProposto, BeatsDaSecao, BlocoNarracao


def _blocos():
    return [
        BlocoNarracao(id="b001", secao="Hook", texto="Primeira frase do gancho."),
        BlocoNarracao(id="b002", secao="Hook", texto="Segunda frase do gancho."),
    ]


def test_beats_apontam_para_blocos_da_secao(scripted):
    model = scripted(structured=[BeatsDaSecao(beats=[
        BeatProposto(bloco_id="b001", prompt="a hand on a steering wheel"),
        BeatProposto(bloco_id="b002", prompt="a road stretching to the horizon"),
    ])])

    beats = propor_beats(model, "Hook", "Cena: um carro", _blocos(), alvo_segundos=15)

    assert [b.bloco_id for b in beats] == ["b001", "b002"]
    assert beats[0].prompt == "a hand on a steering wheel"
    # O tipo é o contrato: `propor_beats` não devolve `Beat`, devolve
    # `BeatProposto` — sem campo `id`. Ids são do caller, que sabe a contagem
    # corrida no roteiro inteiro; um id atribuído aqui corromperia a
    # renumeração e o modelo não tem como saber qual seria.
    assert all(isinstance(b, BeatProposto) for b in beats)


def test_bloco_id_com_colchetes_do_prompt_e_normalizado(scripted):
    """O modelo ecoa a formatação `[b001] texto` que `beats.md` usa para listar
    os blocos — e devolve o id com colchetes. Sem normalizar, `"[b001]"` nunca
    bate com o `"b001"` nu que está em `validos`, e o beat é descartado como se
    fosse invenção (foi assim que uma seção inteira perdeu todos os beats numa
    corrida real contra o modelo local).
    """
    model = scripted(structured=[BeatsDaSecao(beats=[
        BeatProposto(bloco_id="[b001]", prompt="a hand on a steering wheel"),
        BeatProposto(bloco_id=" b002 ", prompt="a road stretching to the horizon"),
    ])])

    beats = propor_beats(model, "Hook", "", _blocos(), alvo_segundos=15)

    assert [b.bloco_id for b in beats] == ["b001", "b002"]


def test_bloco_id_com_colchetes_mas_ainda_invalido_e_descartado(scripted):
    """Normalizar tira a formatação, não inventa validade: um id de fora da
    seção continua fora mesmo depois de perder os colchetes.
    """
    model = scripted(structured=[BeatsDaSecao(beats=[
        BeatProposto(bloco_id="[b999]", prompt="inventado"),
    ])])

    beats = propor_beats(model, "Hook", "Cena: um carro na estrada", _blocos(),
                         alvo_segundos=15)

    # Sem beat válido, cai no fallback da rubrica — não em b999.
    assert len(beats) == 1
    assert beats[0].bloco_id == "b001"
    assert "carro" in beats[0].prompt


def test_plano_preserva_referencias_em_blocos_autorados(scripted):
    from forge.domain.models import BlocoRoteiro, Roteiro, Secao

    block = BlocoRoteiro(texto="A escolha tem consequências.", referencias=["12/ch1/p2"])
    roteiro = Roteiro(
        tema="tema", tese="tese", fontes=[],
        secoes=[Secao(nome="Gancho", conteudo=block.texto, blocos=[block])],
    )
    model = scripted(structured=[BeatsDaSecao(beats=[
        BeatProposto(bloco_id="b001", prompt="A person at a crossroads"),
    ])])

    plano = __import__("forge.agents.midia", fromlist=["planejar_midia"]).planejar_midia(model, roteiro)

    assert plano.blocos[0].texto == block.texto
    assert plano.blocos[0].referencias == ["12/ch1/p2"]


def test_marcador_de_citacao_legado_nao_vai_para_a_fala():
    from forge.narracao.fatiar import fatiar, texto_narravel, REFERENCIA_LEGADA_RE

    original = "Uma afirmação útil. [4363/ch2/p7] Outra frase segue."
    assert "4363/ch2/p7" not in texto_narravel(original)
    assert fatiar(original) == ["Uma afirmação útil. Outra frase segue."]
    assert REFERENCIA_LEGADA_RE.findall(original) == ["4363/ch2/p7"]
def test_beat_para_bloco_de_fora_da_secao_e_descartado(scripted):
    """O modelo só recebeu os blocos desta seção; citar outro é invenção."""
    model = scripted(structured=[BeatsDaSecao(beats=[
        BeatProposto(bloco_id="b001", prompt="ok"),
        BeatProposto(bloco_id="b999", prompt="inventado"),
    ])])

    beats = propor_beats(model, "Hook", "", _blocos(), alvo_segundos=15)

    assert [b.bloco_id for b in beats] == ["b001"]


def test_secao_sem_beat_proposto_ganha_um_de_fallback(scripted):
    """Uma seção sem imagem deixaria a tela congelada por minutos."""
    model = scripted(structured=[BeatsDaSecao(beats=[])])

    beats = propor_beats(model, "Hook", "Cena: um carro na estrada", _blocos(),
                         alvo_segundos=15)

    assert len(beats) == 1
    assert beats[0].bloco_id == "b001"
    assert "carro" in beats[0].prompt
    assert isinstance(beats[0], BeatProposto)


def test_fallback_dispara_quando_todos_os_beats_propostos_sao_invalidos(scripted):
    """O fallback é decidido pela lista pós-filtro, não pela lista crua do
    modelo: um beat fora da seção e outro sem prompt somem no filtro, e a
    seção fica tão sem imagem quanto se o modelo não tivesse proposto nada.
    """
    model = scripted(structured=[BeatsDaSecao(beats=[
        BeatProposto(bloco_id="b999", prompt="fora da seção"),
        BeatProposto(bloco_id="b001", prompt="   "),
    ])])

    beats = propor_beats(model, "Hook", "Cena: um carro na estrada", _blocos(),
                         alvo_segundos=15)

    assert len(beats) == 1
    assert beats[0].bloco_id == "b001"


def test_beat_duplicado_no_mesmo_bloco_e_descartado(scripted):
    """Dois beats no mesmo bloco não têm como ser distinguidos no tempo — um
    Beat só ancora em um bloco, então dois nele competem pelo mesmo instante
    enquanto outro bloco fica sem imagem nenhuma.
    """
    model = scripted(structured=[BeatsDaSecao(beats=[
        BeatProposto(bloco_id="b001", prompt="primeira proposta"),
        BeatProposto(bloco_id="b001", prompt="segunda proposta, mesmo bloco"),
    ])])

    beats = propor_beats(model, "Hook", "", _blocos(), alvo_segundos=15)

    assert len(beats) == 1
    assert beats[0].prompt == "primeira proposta"


def test_fallback_sem_rubrica_usa_o_nome_da_secao(scripted):
    model = scripted(structured=[BeatsDaSecao(beats=[])])

    beats = propor_beats(model, "Problema", "", _blocos(), alvo_segundos=15)

    assert len(beats) == 1
    assert "Problema" in beats[0].prompt


def test_prompt_vazio_nao_vira_beat(scripted):
    model = scripted(structured=[BeatsDaSecao(beats=[
        BeatProposto(bloco_id="b001", prompt="   "),
        BeatProposto(bloco_id="b002", prompt="uma estrada"),
    ])])

    beats = propor_beats(model, "Hook", "", _blocos(), alvo_segundos=15)

    assert [b.prompt for b in beats] == ["uma estrada"]


def _roteiro_de_duas_secoes():
    from forge.domain.models import Roteiro, Secao

    return Roteiro(
        tema="livre-arbítrio",
        tese="a vontade é sentida, não observada",
        secoes=[
            Secao(nome="Hook", conteudo=(
                "(Cena: um carro na estrada.)\n\n"
                "Primeira frase do gancho. Segunda frase do gancho."
            )),
            Secao(nome="Problema", conteudo="O problema não é físico. É linguístico."),
        ],
    )


def test_plano_cobre_todas_as_secoes(scripted):
    from forge.agents.midia import planejar_midia

    model = scripted(structured=[
        BeatsDaSecao(beats=[BeatProposto(bloco_id="b001", prompt="a car")]),
        BeatsDaSecao(beats=[BeatProposto(bloco_id="b002", prompt="a scale")]),
    ])

    plano = planejar_midia(model, _roteiro_de_duas_secoes())

    assert {b.secao for b in plano.blocos} == {"Hook", "Problema"}
    assert [b.id for b in plano.blocos] == ["b001", "b002"]
    assert [i.id for i in plano.beats] == ["i001", "i002"]


def test_nenhuma_palavra_do_roteiro_se_perde_no_plano(scripted):
    """A trava do plano inteiro: o que a voz diz tem de ser o roteiro inteiro."""
    from forge.agents.midia import planejar_midia
    from forge.narracao.fatiar import texto_narravel

    roteiro = _roteiro_de_duas_secoes()
    model = scripted(structured=[
        BeatsDaSecao(beats=[BeatProposto(bloco_id="b001", prompt="a car")]),
        BeatsDaSecao(beats=[BeatProposto(bloco_id="b002", prompt="a scale")]),
    ])

    plano = planejar_midia(model, roteiro)

    esperado = " ".join(texto_narravel(s.conteudo) for s in roteiro.secoes).split()
    assert " ".join(b.texto for b in plano.blocos).split() == esperado


def test_rubrica_nunca_entra_na_narracao(scripted):
    from forge.agents.midia import planejar_midia

    model = scripted(structured=[
        BeatsDaSecao(beats=[BeatProposto(bloco_id="b001", prompt="a car")]),
        BeatsDaSecao(beats=[BeatProposto(bloco_id="b002", prompt="a scale")]),
    ])

    plano = planejar_midia(model, _roteiro_de_duas_secoes())

    assert all("Cena:" not in b.texto for b in plano.blocos)


def test_cobertura_insuficiente_estoura(scripted, monkeypatch):
    """Se um dia o fatiador regredir, o plano falha alto em vez de narrar 8%.

    É a lição do plano gerado por LLM: 85 palavras de 1079, todos os itens do
    manifesto marcados `ok`, e ninguém percebendo.
    """
    import forge.agents.midia as midia_mod
    from forge.agents.midia import CoberturaInsuficiente, planejar_midia

    monkeypatch.setattr(midia_mod, "fatiar", lambda conteudo, **kw: ["só isto"])
    model = scripted(structured=[
        BeatsDaSecao(beats=[BeatProposto(bloco_id="b001", prompt="a car")]),
        BeatsDaSecao(beats=[BeatProposto(bloco_id="b002", prompt="a scale")]),
    ])

    with pytest.raises(CoberturaInsuficiente):
        planejar_midia(model, _roteiro_de_duas_secoes())


def test_secao_so_com_rubrica_nao_gera_bloco_nem_chamada(scripted):
    from forge.agents.midia import planejar_midia
    from forge.domain.models import Roteiro, Secao

    roteiro = Roteiro(tema="t", tese="t", secoes=[
        Secao(nome="Hook", conteudo="(Cena: nada é dito.)"),
        # Longa de propósito: a trava do ROTEIRO INTEIRO (FIX 2 de FRACAO_
        # NARRAVEL_MINIMA) soma até as palavras da rubrica muda do Hook contra
        # o total; "Uma frase." sozinha (2 palavras) empurrava a fração do
        # roteiro para 33%, abaixo do piso, embora o ponto deste teste seja
        # só a seção sem texto não gastar chamada nenhuma.
        Secao(nome="Problema", conteudo=(
            "Uma frase muito mais longa para garantir que a proporção do "
            "roteiro inteiro continue acima do piso mesmo somando a rubrica "
            "muda."
        )),
    ])
    # Uma única resposta na fila: se o agente chamar o modelo para a seção sem
    # texto, o modelo falso estoura.
    model = scripted(structured=[
        BeatsDaSecao(beats=[BeatProposto(bloco_id="b001", prompt="a scale")]),
    ])

    plano = planejar_midia(model, roteiro)

    assert [b.secao for b in plano.blocos] == ["Problema"]


def test_narracao_apagada_por_texto_narravel_estoura(scripted):
    """O ponto cego da conferência relativa: `texto_narravel` apagando narração.

    `RUBRICA_RE` remove TODA linha inteiramente entre parênteses, não só a
    rubrica de abertura da seção. Uma frase de peso escrita entre parênteses no
    meio da seção some da voz — e a conferência relativa não vê nada, porque
    ela compara os blocos contra a saída do próprio `texto_narravel`. Só a
    conferência contra o texto BRUTO enxerga o buraco.
    """
    from forge.agents.midia import CoberturaInsuficiente, planejar_midia
    from forge.domain.models import Roteiro, Secao

    roteiro = Roteiro(tema="t", tese="t", secoes=[
        Secao(nome="Hook", conteudo=(
            "(Cena: um tribunal.)\n\n"
            "Hume escreveu isso em 1739.\n\n"
            "(E aqui esta o ponto que muda tudo: ninguem escolhe querer o que "
            "quer.)\n\n"
            "Por isso o problema nao e fisico."
        )),
    ])
    # Resposta na fila de sobra: sem a trava nova o plano sairia inteiro e
    # silenciosamente errado, com 12 das 28 palavras narradas.
    model = scripted(structured=[
        BeatsDaSecao(beats=[BeatProposto(bloco_id="b001", prompt="a courtroom")]),
    ])

    with pytest.raises(CoberturaInsuficiente):
        planejar_midia(model, roteiro)


def test_roteiro_so_de_rubricas_nao_vira_plano_vazio(scripted):
    """Plano com zero blocos é o incidente original com o gatilho no escritor.

    `[] == []` satisfaz a conferência relativa, `gravar_plano` grava, o
    manifesto sai com 0 itens e o runner diz "nada pendente". Vídeo mudo,
    nenhum aviso.
    """
    from forge.agents.midia import CoberturaInsuficiente, planejar_midia
    from forge.domain.models import Roteiro, Secao

    roteiro = Roteiro(tema="t", tese="t", secoes=[
        Secao(nome="Hook", conteudo="(Cena: nada é dito.)"),
        Secao(nome="Problema", conteudo="(Cena: o silêncio continua.)"),
    ])
    model = scripted(structured=[])

    with pytest.raises(CoberturaInsuficiente):
        planejar_midia(model, roteiro)


def _secao_no_formato_real(nome: str) -> object:
    """Uma seção com a proporção rubrica/corpo medida no roteiro real.

    Rubrica de 7 palavras sobre um corpo de 46: queda de ~13%, dentro da faixa
    de 10,1%–17,7% das nove seções reais.
    """
    from forge.domain.models import Secao

    return Secao(nome=nome, conteudo=(
        "(Cena: uma sala de tribunal vazia.)\n\n"
        "Hume escreveu isso em mil setecentos e trinta e nove, e a frase "
        "atravessou dois séculos sem perder o corte. O problema não é físico, "
        "é gramatical. Ninguém escolhe querer aquilo que quer, e é justamente "
        "aí que a discussão inteira começa a desmoronar."
    ))


def test_proporcao_do_roteiro_real_passa(scripted):
    """A calibração de FRACAO_NARRAVEL_MINIMA não pode reprovar o corpus real."""
    from forge.agents.midia import planejar_midia
    from forge.domain.models import Roteiro

    roteiro = Roteiro(tema="t", tese="t", secoes=[
        _secao_no_formato_real("Hook"), _secao_no_formato_real("Problema"),
    ])
    model = scripted(structured=[
        BeatsDaSecao(beats=[BeatProposto(bloco_id="b001", prompt="a courtroom")]),
        BeatsDaSecao(beats=[BeatProposto(bloco_id="b003", prompt="a clock")]),
    ])

    plano = planejar_midia(model, roteiro)

    assert len(plano.blocos) > 0


def test_maioria_de_secoes_so_de_rubrica_estoura_no_piso_do_roteiro_inteiro(scripted):
    """Concern 2 do relatório da onda final: o piso por seção isenta seção
    100% rubrica, e uma seção normal isolada passa no próprio piso — então um
    roteiro de 8 seções mudas + 1 seção real passava inteiro carregando só uma
    fração pequena da narração pretendida. É a forma exata do incidente
    original (plano coerente, cobertura ínfima), só que dissolvida entre
    seções em vez de concentrada numa só. Nenhuma seção aqui viola seu próprio
    piso; só a soma do roteiro viola o dela.
    """
    from forge.agents.midia import CoberturaInsuficiente, planejar_midia
    from forge.domain.models import Roteiro, Secao

    rubrica_longa = "(" + " ".join(f"detalhe{n}" for n in range(60)) + ")"
    secoes = [Secao(nome=f"Rubrica{i}", conteudo=rubrica_longa) for i in range(8)]
    secoes.append(_secao_no_formato_real("Real"))
    roteiro = Roteiro(tema="t", tese="t", secoes=secoes)

    # Fila vazia: a trava roda antes do modelo ser chamado (FIX 2); se isto
    # falhar por IndexError em vez de CoberturaInsuficiente, a trava não
    # estourou a tempo.
    model = scripted(structured=[])

    with pytest.raises(CoberturaInsuficiente):
        planejar_midia(model, roteiro)


def test_cobertura_falha_antes_de_qualquer_chamada_ao_modelo(scripted, monkeypatch):
    """`blocos` é função pura de `fatiar`; o modelo não contribui nada.

    Conferir depois do laço de beats gastaria nove chamadas de output
    estruturado — no 9B local, dezenas de minutos com o slot da GPU preso —
    para falhar por um motivo já conhecido antes da primeira. Fila vazia: se o
    modelo for chamado, sai `IndexError` em vez de `CoberturaInsuficiente`.
    """
    import forge.agents.midia as midia_mod
    from forge.agents.midia import CoberturaInsuficiente, planejar_midia

    monkeypatch.setattr(midia_mod, "fatiar", lambda conteudo, **kw: ["só isto"])
    model = scripted(structured=[])

    with pytest.raises(CoberturaInsuficiente):
        planejar_midia(model, _roteiro_de_duas_secoes())


def _roteiro_longo():
    from forge.domain.models import Roteiro, Secao

    frases = " ".join(
        f"Esta é a frase número {n} da seção." for n in range(1, 9)
    )
    return Roteiro(tema="t", tese="t",
                   secoes=[Secao(nome="Hook", conteudo=frases)])


def test_alvo_em_segundos_muda_o_tamanho_dos_blocos(scripted):
    """`FORGE_MIDIA_ALVO_SEGUNDOS` tem de chegar ao fatiador, não só ao prompt.

    Antes, `fatiar` era chamado sem argumentos e ficava no default de 35
    palavras qualquer que fosse o alvo; só a quantidade de beats pedida ao
    modelo mudava. Com alvo baixo o modelo era cobrado por mais beats do que
    havia blocos para ancorar, e o dedup descartava o excedente culpando o
    modelo por uma escolha do operador.
    """
    from forge.agents.midia import planejar_midia

    def _um_beat():
        return scripted(structured=[
            BeatsDaSecao(beats=[BeatProposto(bloco_id="b001", prompt="uma sala")]),
        ])

    padrao = planejar_midia(_um_beat(), _roteiro_longo(), alvo_segundos=15)
    curto = planejar_midia(_um_beat(), _roteiro_longo(), alvo_segundos=4)

    assert len(curto.blocos) > len(padrao.blocos)
    maior_curto = max(len(b.texto.split()) for b in curto.blocos)
    maior_padrao = max(len(b.texto.split()) for b in padrao.blocos)
    assert maior_curto < maior_padrao


def test_midia_nao_declara_le_porque_nao_e_no_do_grafo():
    """`LE` aqui seria decoração — e decoração apodrece.

    `LE` é o contrato que `com_wrapper` usa para estreitar o state antes de
    chamar um nó do grafo. `midia` não é nó: sai do `forge roteiro` depois do
    grafo, chamado direto com o Roteiro, então ninguém lê a lista. Justamente
    por isso ela já mentiu uma vez (declarava `tema`, que `planejar_midia`
    deixou de ler quando `beats.md` largou tema e tese).
    """
    import forge.agents.midia as midia_mod

    assert not hasattr(midia_mod, "LE")


# --- bloco autorado grande demais para o TTS ---

def _roteiro_com_bloco(texto, **campos):
    from forge.domain.models import BlocoRoteiro, Roteiro, Secao

    bloco = BlocoRoteiro(texto=texto, **campos)
    return Roteiro(
        tema="tema", tese="tese", fontes=[],
        secoes=[Secao(nome="Gancho", conteudo=texto, blocos=[bloco])],
    )


def _planejar(scripted, roteiro):
    from forge.agents.midia import planejar_midia

    return planejar_midia(scripted(structured=[BeatsDaSecao(beats=[])]), roteiro)


def test_bloco_autorado_longo_e_fatiado_no_alvo_de_palavras(scripted):
    """Na run real o modelo escreveu blocos de 50 a 83 palavras, e todos acima
    de ~50 estouraram a VRAM do TTS (`tts_vulkan_oom`): 28 de 36 sem áudio."""
    frases = [f"Esta é a frase número {i} e ela tem exatamente doze palavras contadas aqui." for i in range(6)]
    texto = " ".join(frases)

    plano = _planejar(scripted, _roteiro_com_bloco(texto, referencias=["12/ch1/p2"]))

    assert len(plano.blocos) > 1
    assert all(len(b.texto.split()) <= 40 for b in plano.blocos)
    assert " ".join(b.texto for b in plano.blocos) == texto, "nenhuma palavra perdida"
    assert [b.id for b in plano.blocos] == [f"b{i:03d}" for i in range(1, len(plano.blocos) + 1)]
    # A paráfrase atribuída vale para o parágrafo inteiro.
    assert all(b.referencias == ["12/ch1/p2"] for b in plano.blocos)


def test_citacao_literal_fica_so_no_pedaco_que_a_fala(scripted):
    from forge.domain.models import CitacaoLiteral

    antes = " ".join(f"Frase de preparação número {i} com mais algumas palavras de enchimento." for i in range(4))
    citada = "A vida não examinada não vale a pena ser vivida."
    texto = f"{antes} Em tradução livre: {citada} E isso muda a pergunta."
    literal = CitacaoLiteral(path="1656/a/p40", trecho="The unexamined life is not worth living.", traducao=citada)

    plano = _planejar(scripted, _roteiro_com_bloco(texto, citacoes_literais=[literal]))

    com_citacao = [b for b in plano.blocos if b.citacoes_literais]
    assert len(com_citacao) == 1
    assert citada in com_citacao[0].texto


def test_bloco_autorado_curto_passa_intacto(scripted):
    texto = "A escolha tem consequências. E você sabe disso."

    plano = _planejar(scripted, _roteiro_com_bloco(texto, referencias=["12/ch1/p2"]))

    assert [b.texto for b in plano.blocos] == [texto]
