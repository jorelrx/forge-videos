"""Estado por item da fase de vídeo.

40 imagens numa RX 580 são horas. O manifesto existe para que um crash na
imagem 33 custe uma imagem, não a noite inteira: cada item carrega o próprio
estado e o arquivo é regravado depois de cada um.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field

from forge.domain.midia import PlanoMidia
from forge.infrastructure.logging import get_logger

logger = get_logger(__name__)

Tipo = Literal["audio", "imagem"]
Estado = Literal["pendente", "ok", "falhou"]


class Item(BaseModel):
    id: str
    tipo: Tipo
    estado: Estado = "pendente"
    entrada: dict = Field(default_factory=dict)
    saida: str = ""
    duracao_ms: int | None = None
    tentativas: int = 0
    erro: str = ""


class Manifesto(BaseModel):
    itens: list[Item] = Field(default_factory=list)


def caminho(run_dir: Path) -> Path:
    return Path(run_dir) / "video" / "manifesto.json"


def _do_plano(plano: PlanoMidia) -> Manifesto:
    itens = [
        Item(id=b.id, tipo="audio", entrada={"texto": b.texto, "secao": b.secao})
        for b in plano.blocos
    ]
    itens += [
        Item(id=i.id, tipo="imagem", entrada={"prompt": i.prompt, "bloco_id": i.bloco_id})
        for i in plano.beats
    ]
    return Manifesto(itens=itens)


def criar_ou_carregar(run_dir: Path, plano: PlanoMidia) -> Manifesto:
    """Monta o manifesto do plano, preservando o que um run anterior já fez.

    O id vem do plano e é estável, então o estado antigo reata com o item novo
    sem ambiguidade. Porém, se a entrada mudou (ex: texto de um bloco foi editado),
    o item é resetado como pendente, pois a saída anterior não corresponde ao
    novo input. tentativas é preservada para manter histórico de falhas.
    """
    novo = _do_plano(plano)
    if not caminho(run_dir).exists():
        return novo

    antigo = {i.id: i for i in carregar(run_dir).itens}
    itens = []
    for i_novo in novo.itens:
        i_antigo = antigo.get(i_novo.id)
        if i_antigo is None:
            # Item novo, não existe no run anterior
            itens.append(i_novo)
        elif i_antigo.entrada == i_novo.entrada:
            # Entrada inalterada, preserva tudo (resume case)
            itens.append(i_antigo)
        else:
            # Entrada mudou, reset para pendente mas preserva tentativas
            item_resetado = i_novo.model_copy()
            item_resetado.tentativas = i_antigo.tentativas
            itens.append(item_resetado)
            logger.warning(
                "Item entrada mudou, resetando",
                id=i_novo.id,
                estado_anterior=i_antigo.estado,
            )

    logger.info(
        "Manifesto retomado",
        total=len(itens),
        pendentes=sum(1 for i in itens if i.estado == "pendente"),
    )
    return Manifesto(itens=itens)


def carregar(run_dir: Path) -> Manifesto:
    return Manifesto(**json.loads(caminho(run_dir).read_text(encoding="utf-8")))


def gravar(run_dir: Path, manifesto: Manifesto) -> None:
    destino = caminho(run_dir)
    destino.parent.mkdir(parents=True, exist_ok=True)
    # Escrita atômica: um corte de energia no meio da gravação deixaria um JSON
    # truncado no lugar do progresso de horas.
    temporario = destino.with_suffix(".json.tmp")
    temporario.write_text(
        json.dumps(manifesto.model_dump(), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    os.replace(temporario, destino)


def pendentes(manifesto: Manifesto, tipo: str | None = None) -> list[Item]:
    return [
        i for i in manifesto.itens
        if i.estado == "pendente" and (tipo is None or i.tipo == tipo)
    ]
