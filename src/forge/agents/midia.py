"""Deriva o plano de mídia do roteiro aprovado.

Roda com o LLM ainda residente, no fim do `forge roteiro`, para que a fase de
GPU não precise recarregar o modelo só para pedir prompts de imagem.
"""

from __future__ import annotations

import json
from pathlib import Path

from langchain_core.messages import HumanMessage

from forge.domain.midia import Beat, BlocoNarracao, PlanoMidia
from forge.domain.models import Roteiro
from forge.infrastructure.logging import get_logger
from forge.narracao.tags import sanear_texto
from forge.prompts.loader import load_prompt

logger = get_logger(__name__)

LE = ["tema", "roteiro"]


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


def gravar_plano(run_dir: Path, plano: PlanoMidia) -> Path:
    caminho = caminho_plano(run_dir)
    caminho.parent.mkdir(parents=True, exist_ok=True)
    caminho.write_text(
        json.dumps(plano.model_dump(), ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return caminho


def carregar_plano(run_dir: Path) -> PlanoMidia:
    return PlanoMidia(**json.loads(caminho_plano(run_dir).read_text(encoding="utf-8")))
