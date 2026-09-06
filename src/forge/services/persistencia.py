"""Um só lugar grava modelo pydantic em disco — e grava atômico.

`midia.json` e `manifesto.json` são o mesmo tipo de artefato: JSON derivado de um
modelo, reescrito no meio de um run que dura horas. `midia.json` é o mais caro
dos dois (custa uma chamada de LLM inteira no fim de um run longo, e é a entrada
de tudo o que vem depois), então ele não pode ser o único gravado sem rede de
proteção. Escrita direta deixaria um JSON truncado no lugar do artefato se a
máquina caísse no meio; `os.replace` no mesmo diretório é atômico, então o
destino ou tem o conteúdo antigo inteiro ou o novo inteiro.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import TypeVar

from pydantic import BaseModel

M = TypeVar("M", bound=BaseModel)


def gravar_modelo(destino: Path, modelo: BaseModel) -> Path:
    destino = Path(destino)
    destino.parent.mkdir(parents=True, exist_ok=True)
    # O temporário fica no mesmo diretório de propósito: `os.replace` só é
    # atômico dentro do mesmo filesystem.
    temporario = destino.with_suffix(".json.tmp")
    temporario.write_text(
        json.dumps(modelo.model_dump(), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    os.replace(temporario, destino)
    return destino


def carregar_modelo(origem: Path, tipo: type[M]) -> M:
    return tipo(**json.loads(Path(origem).read_text(encoding="utf-8")))
