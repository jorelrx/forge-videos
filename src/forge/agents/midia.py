"""Deriva o plano de mídia do roteiro aprovado.

Roda com o LLM ainda residente, no fim do `forge roteiro`, para que a fase de
GPU não precise recarregar o modelo só para pedir prompts de imagem.
"""

from __future__ import annotations

from pathlib import Path

from langchain_core.messages import HumanMessage

from forge.domain.midia import Beat, BeatProposto, BeatsDaSecao, BlocoNarracao, PlanoMidia
from forge.domain.models import Roteiro
from forge.infrastructure.logging import get_logger
from forge.narracao.tags import sanear_texto
from forge.prompts.loader import load_prompt
from forge.services.persistencia import carregar_modelo, gravar_modelo

logger = get_logger(__name__)

LE = ["tema", "roteiro"]


class PlanoJaExiste(FileExistsError):
    """Já há um plano em disco e ninguém pediu para refazê-lo."""


def planejar_midia(model, roteiro: Roteiro, *, alvo_segundos: int = 15) -> PlanoMidia:
    prompt = load_prompt("midia").format(
        tema=roteiro.tema,
        tese=roteiro.tese,
        roteiro=_fmt_roteiro(roteiro),
        alvo_segundos=alvo_segundos,
    )
    cru = model.with_structured_output(PlanoMidia).invoke([HumanMessage(content=prompt)])
    plano = _normalizar(cru)
    logger.info("Plano de mídia pronto", blocos=len(plano.blocos), beats=len(plano.beats))
    return plano


def _fmt_roteiro(roteiro: Roteiro) -> str:
    return "\n\n".join(f"## {s.nome}\n\n{s.conteudo}" for s in roteiro.secoes)


def _normalizar(cru: PlanoMidia) -> PlanoMidia:
    """Renumera os ids e limpa o que o modelo errou.

    Ids vêm de nós, não do modelo: são a chave que o manifesto e os arquivos de
    saída usam, e um id repetido pelo modelo sobrescreveria um item já gerado.
    """
    mapa: dict[str, str] = {}
    blocos: list[BlocoNarracao] = []
    for i, bloco in enumerate(cru.blocos, 1):
        novo = f"b{i:03d}"
        if bloco.id in mapa:
            # O prompt diz ao modelo que o id não importa, o que convida a
            # repeti-lo. Sobrescrever a entrada mandaria um beat destinado ao
            # primeiro bloco silenciosamente para o segundo; first-wins é
            # arbitrário mas determinístico, avisado, e segue a ordem de leitura.
            logger.warning(
                "Id de bloco repetido pelo modelo; mantendo o primeiro",
                id_repetido=bloco.id, bloco_perdido=novo,
            )
        else:
            mapa[bloco.id] = novo
        texto, removidas = sanear_texto(bloco.texto)
        if removidas:
            logger.warning("Tags inválidas removidas", bloco=novo, tags=removidas)
        blocos.append(BlocoNarracao(id=novo, secao=bloco.secao, texto=texto.strip()))

    beats: list[Beat] = []
    for beat in cru.beats:
        alvo = mapa.get(beat.bloco_id)
        if alvo is None:
            # Beat apontando para bloco inexistente não tem quando entrar em
            # tela; descartar é melhor que ancorá-lo em algum bloco arbitrário.
            logger.warning("Beat órfão descartado", bloco_id=beat.bloco_id)
            continue
        beats.append(Beat(id=f"i{len(beats) + 1:03d}", bloco_id=alvo, prompt=beat.prompt))

    return PlanoMidia(blocos=blocos, beats=beats)


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
