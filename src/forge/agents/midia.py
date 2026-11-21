"""Deriva o plano de mídia do roteiro aprovado.

Roda com o LLM ainda residente, no fim do `forge roteiro`, para que a fase de
GPU não precise recarregar o modelo só para pedir prompts de imagem.

Os blocos de narração vêm do fatiador determinístico (`forge.narracao.fatiar`),
não do modelo, então o texto nunca passa pelo LLM e não há tag de controle
inventada para `sanear_texto` limpar aqui.
"""

from __future__ import annotations

from pathlib import Path

from langchain_core.messages import HumanMessage

from forge.domain.midia import Beat, BeatProposto, BeatsDaSecao, BlocoNarracao, PlanoMidia
from forge.domain.models import BlocoRoteiro, Roteiro
from forge.infrastructure.logging import get_logger
from forge.llms.model import invoke_structured
from forge.narracao.fatiar import (
    PALAVRAS_POR_SEGUNDO,
    REFERENCIA_LEGADA_RE,
    extrair_rubrica,
    fatiar,
    texto_narravel,
)
from forge.prompts.loader import load_prompt
from forge.services.persistencia import carregar_modelo, gravar_modelo

logger = get_logger(__name__)

# Sem `LE` de propósito. `LE` é o contrato que `com_wrapper` usa para estreitar
# o state antes de chamar um nó do grafo; `midia` não é nó — sai do `forge
# roteiro` depois do grafo, chamado direto com o Roteiro. Uma lista aqui não é
# lida por ninguém e por isso já apodreceu uma vez (declarava `tema`, que
# `planejar_midia` deixou de ler quando `beats.md` largou tema e tese).


class PlanoJaExiste(FileExistsError):
    """Já há um plano em disco e ninguém pediu para refazê-lo."""


class CoberturaInsuficiente(RuntimeError):
    """Os blocos não reproduzem o roteiro palavra por palavra.

    Existe por causa de um caso real: a versão anterior pedia o fatiamento ao
    LLM e recebeu 85 palavras de um roteiro de 1079, todas da primeira seção. O
    plano era coerente, o manifesto marcaria tudo `ok`, e o vídeo teria 36
    segundos de narração. Falhar alto aqui é a única defesa.
    """


# Piso da fração do texto BRUTO de uma seção que tem de sobreviver a
# `texto_narravel`. Calibrado nas nove seções do roteiro real: a queda fica
# entre 10,1% e 17,7% e é inteiramente a rubrica de cena, então 0,6 — tolerar
# perder 40% — guarda mais de 2x de margem sobre o pior caso medido. Pega o
# incidente das 85 palavras de 1079 (queda de 92%) e uma rubrica multi-linha ou
# gulosa que apague narração no meio da seção.
FRACAO_NARRAVEL_MINIMA = 0.6


def planejar_midia(
    model,
    roteiro: Roteiro,
    *,
    alvo_segundos: int = 15,
    run_dir: Path | None = None,
    direcao_editorial: str = "",
) -> PlanoMidia:
    # O alvo do operador está em segundos; o fatiador só entende palavras. Sem
    # esta conversão `fatiar` ficava no default de 35 palavras qualquer que
    # fosse `alvo_segundos`, e o knob só era coerente por coincidência no
    # default (2,5 * 15 = 37,5 ≈ 35): baixá-lo pedia mais beats ao modelo do
    # que havia blocos para ancorá-los, e o dedup jogava fora o excedente
    # culpando o modelo por uma escolha do operador.
    alvo_palavras = round(PALAVRAS_POR_SEGUNDO * alvo_segundos)

    blocos: list[BlocoNarracao] = []
    fatiado: list[tuple[str, str, list[BlocoNarracao]]] = []

    # Primeira passada: só corte, sem modelo nenhum.
    for secao in roteiro.secoes:
        if secao.blocos:
            textos, metadados = _fatiar_autorados(secao.blocos, alvo_palavras)
        else:
            textos = fatiar(secao.conteudo, alvo_palavras=alvo_palavras)
            metadados = [None] * len(textos)
        if not textos:
            # Seção só com rubrica não tem narração; não gasta chamada.
            logger.info("Seção sem texto narrável", secao=secao.nome)
            continue

        da_secao = []
        for i, (texto, origem) in enumerate(zip(textos, metadados)):
            da_secao.append(BlocoNarracao(
                id=f"b{len(blocos) + i + 1:03d}", secao=secao.nome, texto=texto,
                referencias=origem.referencias if origem else [],
                citacoes_literais=origem.citacoes_literais if origem else [],
                referencias_legadas=origem.referencias_legadas if origem else [],
            ))
        if not secao.blocos and da_secao:
            da_secao[0].referencias_legadas = list(dict.fromkeys(
                REFERENCIA_LEGADA_RE.findall(secao.conteudo)
            ))
        blocos.extend(da_secao)
        fatiado.append((secao.nome, extrair_rubrica(secao.conteudo), da_secao))

    # As travas rodam ANTES da primeira chamada ao modelo: `blocos` é função
    # pura de `fatiar` e o modelo não contribui nada para elas. Conferir depois
    # do laço de beats jogava fora nove chamadas de output estruturado — no 9B
    # local, dezenas de minutos com o slot da GPU preso — para então falhar por
    # um motivo que já era conhecido antes da primeira.
    _conferir_narracao_absoluta(roteiro, blocos)
    _conferir_cobertura_relativa(roteiro, blocos)

    # Segunda passada: aqui, e só aqui, o modelo entra.
    beats: list[Beat] = []
    for nome, rubrica, da_secao in fatiado:
        if direcao_editorial:
            rubrica = (
                f"{rubrica}\n\n{direcao_editorial}\n"
                "Dê a cada beat uma função na narração: cena, exemplo, virada ou retorno. "
                "No Fecho, retome o elemento visual da abertura com o novo sentido."
            )
        propostos = propor_beats(
            model, nome, rubrica, da_secao, alvo_segundos=alvo_segundos,
            run_dir=run_dir,
        )
        if direcao_editorial and propostos:
            # A montagem começa a narrar no primeiro beat de cada seção.
            # A prévia e o vídeo final precisam começar no mesmo bloco.
            ordem = {bloco.id: indice for indice, bloco in enumerate(da_secao)}
            primeiro = min(propostos, key=lambda item: ordem[item.bloco_id])
            primeiro.bloco_id = da_secao[0].id
        for p in propostos:
            beats.append(
                Beat(id=f"i{len(beats) + 1:03d}", bloco_id=p.bloco_id, prompt=p.prompt)
            )

    logger.info("Plano de mídia pronto", blocos=len(blocos), beats=len(beats),
                palavras=sum(len(b.texto.split()) for b in blocos))
    return PlanoMidia(blocos=blocos, beats=beats)


def _fatiar_autorados(
    autorados: list[BlocoRoteiro], alvo_palavras: int,
) -> tuple[list[str], list[BlocoRoteiro]]:
    """Corta cada bloco escrito pelo modelo no mesmo alvo de palavras do fatiador.

    O bloco autorado é a unidade de CITAÇÃO (um parágrafo e suas fontes), não
    de narração: o modelo escreve parágrafos de 50 a 80 palavras, e o TTS desta
    máquina estoura a VRAM acima de ~50 — numa run real, 28 de 36 blocos
    ficaram sem áudio. Além disso, um bloco por parágrafo dava uma imagem a
    cada ~25 s.

    As referências de paráfrase valem para o parágrafo inteiro e vão para todos
    os pedaços. A citação literal vai só para o pedaço que a fala: é nele que o
    cartão com o trecho precisa aparecer.
    """
    textos: list[str] = []
    metadados: list[BlocoRoteiro] = []
    for bloco in autorados:
        pedacos = fatiar(bloco.texto, alvo_palavras=alvo_palavras) or [bloco.texto]
        literais: list[list] = [[] for _ in pedacos]
        for literal in bloco.citacoes_literais:
            literais[_pedaco_da_citacao(pedacos, literal.traducao or literal.trecho)].append(literal)
        for i, pedaco in enumerate(pedacos):
            textos.append(pedaco)
            metadados.append(BlocoRoteiro(
                texto=pedaco,
                referencias=list(bloco.referencias),
                citacoes_literais=literais[i],
                referencias_legadas=list(bloco.referencias_legadas) if i == 0 else [],
            ))
    return textos, metadados


def _pedaco_da_citacao(pedacos: list[str], falado: str) -> int:
    """Índice do pedaço que contém a citação — ou onde ela começa.

    O fatiador nunca corta no meio de uma frase, mas uma citação de várias
    frases pode atravessar dois pedaços; aí vale o pedaço em que ela começa.
    Sem casar em nenhum, fica no primeiro: perder a citação tiraria da tela
    uma fonte que o roteiro declarou.
    """
    alvo = " ".join(falado.split())
    inicio = alvo[:24]
    normalizados = [" ".join(pedaco.split()) for pedaco in pedacos]
    for i, pedaco in enumerate(normalizados):
        if alvo and alvo in pedaco:
            return i
    for i, pedaco in enumerate(normalizados):
        if inicio and inicio in pedaco:
            return i
    return 0


def _conferir_cobertura_relativa(roteiro: Roteiro, blocos: list[BlocoNarracao]) -> None:
    """Prova que o FATIADOR não perdeu nada do que `texto_narravel` produziu.

    Só isso: os dois lados passam por `texto_narravel`, então um defeito lá
    produz a mesma resposta errada nos dois e esta conferência passa feliz.
    Quem cobre esse ponto cego é `_conferir_narracao_absoluta`.
    """
    esperado = " ".join(texto_narravel(s.conteudo) for s in roteiro.secoes).split()
    obtido = " ".join(b.texto for b in blocos).split()
    if obtido != esperado:
        raise CoberturaInsuficiente(
            f"blocos cobrem {len(obtido)} palavras de {len(esperado)} do roteiro"
        )


def _conferir_narracao_absoluta(roteiro: Roteiro, blocos: list[BlocoNarracao]) -> None:
    """Prova que a NARRAÇÃO ainda é o roteiro, olhando o texto bruto da seção.

    É o único lado da conferência que não passa por `texto_narravel`, e por isso
    o único que enxerga narração apagada pelo próprio `texto_narravel` — hoje
    `RUBRICA_RE`, que remove toda linha inteiramente entre parênteses, não só a
    rubrica de abertura. Uma frase forte entre parênteses no meio da seção some
    da voz sem sinal nenhum, e a conferência relativa concorda com o sumiço.
    """
    if not blocos:
        # Plano vazio é o desfecho exato do incidente original, só que com o
        # gatilho movido para o escritor: manifesto com 0 itens, runner dizendo
        # "nada pendente", vídeo mudo. Nunca é resultado legítimo.
        raise CoberturaInsuficiente(
            "o plano não tem nenhum bloco de narração: o roteiro inteiro sumiu "
            "antes do fatiamento"
        )

    total_bruto = 0
    total_nar = 0
    for secao in roteiro.secoes:
        bruto = len(secao.conteudo.split())
        if not bruto:
            continue
        nar = len(texto_narravel(secao.conteudo).split())
        total_bruto += bruto
        total_nar += nar
        if nar == 0:
            # Seção 100% rubrica é legítima (uma cena muda, sem voz) e já foi
            # anunciada no log da primeira passada. Isenta de propósito: a
            # razão nar/bruto aqui é sempre 0 e reprovaria o roteiro inteiro.
            # O caso perigoso — TODAS as seções assim — cai no `not blocos`
            # acima, que é onde ele de fato importa.
            continue
        if nar / bruto < FRACAO_NARRAVEL_MINIMA:
            raise CoberturaInsuficiente(
                f"seção {secao.nome!r}: só {nar} das {bruto} palavras do texto "
                f"bruto sobraram como narração "
                f"({nar / bruto:.0%} < {FRACAO_NARRAVEL_MINIMA:.0%})"
            )

    # A isenção acima é por seção; esta trava é do ROTEIRO INTEIRO, e não tem
    # isenção nenhuma. Sem ela, um roteiro de várias seções mudas mais uma
    # seção normal isolada passa: cada seção muda é isenta e a seção normal
    # cobre o próprio piso sozinha — mas o roteiro inteiro pode estar
    # carregando só uma fração pequena da narração pretendida. É o incidente
    # original (plano coerente, cobertura ínfima) com o defeito dissolvido
    # entre seções em vez de concentrado numa só.
    if total_bruto and total_nar / total_bruto < FRACAO_NARRAVEL_MINIMA:
        raise CoberturaInsuficiente(
            f"o roteiro inteiro: só {total_nar} das {total_bruto} palavras "
            f"brutas de TODAS as seções sobraram como narração "
            f"({total_nar / total_bruto:.0%} < {FRACAO_NARRAVEL_MINIMA:.0%})"
        )


def caminho_plano(run_dir: Path) -> Path:
    return Path(run_dir) / "video" / "midia.json"


def gravar_plano(run_dir: Path, plano: PlanoMidia, *, forcar: bool = False) -> Path:
    """Grava o plano, recusando sobrescrever um que já existe.

    Os ids dos blocos são posicionais (`b001..`), então um plano refeito com um
    fatiamento diferente renumera tudo. A regra de entrada-mudou do manifesto
    então reseta quase todo item para `pendente` e uma noite inteira de áudio e
    imagem já gerados vira lixo. Refazer o plano tem que ser um ato explícito.
    """
    caminho = caminho_plano(run_dir)
    if caminho.exists() and not forcar:
        raise PlanoJaExiste(
            f"plano de mídia já existe em {caminho}; sobrescrevê-lo renumeraria "
            f"os blocos e descartaria o áudio e as imagens já gerados. "
            f"Use gravar_plano(..., forcar=True) para refazê-lo de propósito."
        )
    return gravar_modelo(caminho, plano)


def carregar_plano(run_dir: Path) -> PlanoMidia:
    return carregar_modelo(caminho_plano(run_dir), PlanoMidia)


def _normalizar_bloco_id(bruto: str) -> str:
    """Tira a formatação que o modelo aprende ecoando a listagem do prompt.

    `beats.md` listava os blocos como `[b001] texto`, e o modelo local
    respondia com o id ainda entre colchetes — `"[b005]"` nunca bate com o
    `"b005"` nu em `validos`, e o beat inteiro é descartado como invenção.
    Estreito de propósito: só um `[` inicial e um `]` final, mais espaço em
    volta — não pontuação arbitrária. `beats.md` foi corrigido para não
    ensinar mais o formato errado; isto é a rede de segurança para respostas
    já viciadas ou de outros modelos.
    """
    normalizado = bruto.strip()
    if normalizado.startswith("[") and normalizado.endswith("]"):
        normalizado = normalizado[1:-1].strip()
    return normalizado


def propor_beats(
    model,
    secao: str,
    rubrica: str,
    blocos: list[BlocoNarracao],
    *,
    alvo_segundos: int,
    run_dir: Path | None = None,
) -> list[BeatProposto]:
    """Os beats que o modelo propõe para uma seção, filtrados — sem id.

    Devolve `BeatProposto`, não `Beat`: id é nosso, atribuído por
    `planejar_midia`, que é quem sabe a contagem corrida do roteiro inteiro. O
    tipo é o contrato; antes era um `Beat` com `id=""` e duas asserções de
    teste segurando a convenção.
    """
    if not blocos:
        return []

    palavras = sum(len(b.texto.split()) for b in blocos)
    quantidade = max(1, round(palavras / PALAVRAS_POR_SEGUNDO / alvo_segundos))

    prompt = load_prompt("beats").format(
        secao=secao,
        rubrica=rubrica or "(nenhuma)",
        blocos="\n".join(f"{b.id}: {b.texto}" for b in blocos),
        quantidade=quantidade,
        alvo_segundos=alvo_segundos,
    )
    proposta = invoke_structured(
        model,
        BeatsDaSecao,
        [HumanMessage(content=prompt)],
        run_dir=run_dir,
        etapa="midia",
        subfase="beats_structured",
    )

    validos = {b.id for b in blocos}
    vistos: set[str] = set()
    beats: list[BeatProposto] = []
    for p in proposta.beats:
        bloco_id = _normalizar_bloco_id(p.bloco_id)
        if bloco_id != p.bloco_id:
            logger.debug("Id de bloco normalizado", secao=secao,
                         bruto=p.bloco_id, normalizado=bloco_id)
        if bloco_id not in validos:
            logger.warning("Beat fora da seção descartado", secao=secao,
                           bloco_id=bloco_id)
            continue
        if not p.prompt.strip():
            logger.warning("Beat sem prompt descartado", secao=secao,
                           bloco_id=bloco_id)
            continue
        if bloco_id in vistos:
            # Um Beat só ancora em um bloco: dois no mesmo bloco competiriam
            # pelo mesmo instante enquanto outro bloco fica sem imagem nenhuma.
            # Mantém o primeiro, na ordem em que o modelo propôs.
            logger.warning("Beat duplicado no mesmo bloco descartado", secao=secao,
                           bloco_id=bloco_id)
            continue
        vistos.add(bloco_id)
        beats.append(BeatProposto(bloco_id=bloco_id, prompt=p.prompt.strip()))

    if not beats:
        # Seção sem imagem deixaria a tela congelada por minutos. A rubrica do
        # autor é a melhor descrição visual disponível sem gastar outra chamada.
        semente = rubrica or f"{secao} — cena ilustrativa"
        logger.warning("Seção sem beat; usando a rubrica", secao=secao)
        beats.append(BeatProposto(bloco_id=blocos[0].id, prompt=semente))

    logger.info("Beats da seção", secao=secao, propostos=len(proposta.beats),
                mantidos=len(beats))
    return beats
