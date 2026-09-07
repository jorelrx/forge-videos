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
from forge.domain.models import Roteiro
from forge.infrastructure.logging import get_logger
from forge.narracao.fatiar import extrair_rubrica, fatiar, texto_narravel
from forge.prompts.loader import load_prompt
from forge.services.persistencia import carregar_modelo, gravar_modelo

logger = get_logger(__name__)

LE = ["tema", "roteiro"]


class PlanoJaExiste(FileExistsError):
    """Já há um plano em disco e ninguém pediu para refazê-lo."""


class CoberturaInsuficiente(RuntimeError):
    """Os blocos não reproduzem o roteiro palavra por palavra.

    Existe por causa de um caso real: a versão anterior pedia o fatiamento ao
    LLM e recebeu 85 palavras de um roteiro de 1079, todas da primeira seção. O
    plano era coerente, o manifesto marcaria tudo `ok`, e o vídeo teria 36
    segundos de narração. Falhar alto aqui é a única defesa.
    """


def planejar_midia(model, roteiro: Roteiro, *, alvo_segundos: int = 15) -> PlanoMidia:
    blocos: list[BlocoNarracao] = []
    beats: list[Beat] = []

    for secao in roteiro.secoes:
        textos = fatiar(secao.conteudo)
        if not textos:
            # Seção só com rubrica não tem narração; não gasta chamada.
            logger.info("Seção sem texto narrável", secao=secao.nome)
            continue

        da_secao = [
            BlocoNarracao(id=f"b{len(blocos) + i + 1:03d}", secao=secao.nome, texto=t)
            for i, t in enumerate(textos)
        ]
        blocos.extend(da_secao)

        propostos = propor_beats(
            model,
            secao.nome,
            extrair_rubrica(secao.conteudo),
            da_secao,
            alvo_segundos=alvo_segundos,
        )
        for beat in propostos:
            beats.append(
                Beat(id=f"i{len(beats) + 1:03d}", bloco_id=beat.bloco_id,
                     prompt=beat.prompt)
            )

    _conferir_cobertura(roteiro, blocos)
    logger.info("Plano de mídia pronto", blocos=len(blocos), beats=len(beats),
                palavras=sum(len(b.texto.split()) for b in blocos))
    return PlanoMidia(blocos=blocos, beats=beats)


def _conferir_cobertura(roteiro: Roteiro, blocos: list[BlocoNarracao]) -> None:
    esperado = " ".join(texto_narravel(s.conteudo) for s in roteiro.secoes).split()
    obtido = " ".join(b.texto for b in blocos).split()
    if obtido != esperado:
        raise CoberturaInsuficiente(
            f"blocos cobrem {len(obtido)} palavras de {len(esperado)} do roteiro"
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


# ~2,5 palavras por segundo é a cadência medida do higgs nesta voz. Serve para
# estimar quantas imagens uma seção comporta, não para cronometrar nada: a
# duração real sai das métricas do TTS, no manifesto.
PALAVRAS_POR_SEGUNDO = 2.5


def propor_beats(
    model,
    secao: str,
    rubrica: str,
    blocos: list[BlocoNarracao],
    *,
    alvo_segundos: int,
) -> list[Beat]:
    if not blocos:
        return []

    palavras = sum(len(b.texto.split()) for b in blocos)
    quantidade = max(1, round(palavras / PALAVRAS_POR_SEGUNDO / alvo_segundos))

    prompt = load_prompt("beats").format(
        secao=secao,
        rubrica=rubrica or "(nenhuma)",
        blocos="\n".join(f"[{b.id}] {b.texto}" for b in blocos),
        quantidade=quantidade,
        alvo_segundos=alvo_segundos,
    )
    proposta = model.with_structured_output(BeatsDaSecao).invoke(
        [HumanMessage(content=prompt)]
    )

    validos = {b.id for b in blocos}
    vistos: set[str] = set()
    beats: list[Beat] = []
    for p in proposta.beats:
        if p.bloco_id not in validos:
            logger.warning("Beat fora da seção descartado", secao=secao,
                           bloco_id=p.bloco_id)
            continue
        if not p.prompt.strip():
            logger.warning("Beat sem prompt descartado", secao=secao,
                           bloco_id=p.bloco_id)
            continue
        if p.bloco_id in vistos:
            # Um Beat só ancora em um bloco: dois no mesmo bloco competiriam
            # pelo mesmo instante enquanto outro bloco fica sem imagem nenhuma.
            # Mantém o primeiro, na ordem em que o modelo propôs.
            logger.warning("Beat duplicado no mesmo bloco descartado", secao=secao,
                           bloco_id=p.bloco_id)
            continue
        vistos.add(p.bloco_id)
        beats.append(Beat(id="", bloco_id=p.bloco_id, prompt=p.prompt.strip()))

    if not beats:
        # Seção sem imagem deixaria a tela congelada por minutos. A rubrica do
        # autor é a melhor descrição visual disponível sem gastar outra chamada.
        semente = rubrica or f"{secao} — cena ilustrativa"
        logger.warning("Seção sem beat; usando a rubrica", secao=secao)
        beats.append(Beat(id="", bloco_id=blocos[0].id, prompt=semente))

    logger.info("Beats da seção", secao=secao, propostos=len(proposta.beats),
                mantidos=len(beats))
    return beats
