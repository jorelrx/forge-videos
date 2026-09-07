"""Devolve ao acervo as perguntas que ele não soube responder.

Duas escritas com contratos diferentes, e misturá-las quebraria o acervo:

- `gaps_file` é ARQUIVO DO ACERVO. Segundo o `unanswered_log.py` daquele
  projeto, ele guarda "ONLY the question, no duplicates", uma por linha, e o
  próprio acervo o lê de volta. Escrever o par pergunta/resposta ali destruiria
  o dedupe dele.
- `respostas_ruins_file` é nosso. Guarda a evidência inteira, uma linha JSON por
  caso, e ninguém o lê de volta.

Falhar aqui nunca derruba o roteiro: um caminho inexistente ou sem permissão é
um aviso. Perder o registro é ruim; perder o roteiro por causa dele é pior.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from forge.infrastructure.config import Settings
from forge.infrastructure.logging import get_logger
from forge.services.acervo import Passagem

logger = get_logger(__name__)

TRECHO_MAX = 300


def registrar_lacuna(
    settings: Settings,
    *,
    query: str,
    tema: str,
    motivo: str,
    passagens: list[Passagem],
) -> None:
    pergunta = " ".join(query.split())
    if not pergunta:
        return
    _anexar_pergunta(settings.gaps_file, pergunta)
    _anexar_evidencia(settings.respostas_ruins_file, pergunta, tema, motivo, passagens)


def _anexar_pergunta(caminho: Path | None, pergunta: str) -> None:
    if caminho is None:
        return
    try:
        caminho.parent.mkdir(parents=True, exist_ok=True)
        existentes = set()
        if caminho.exists():
            # Mesma normalização da pergunta de entrada (" ".join(...split())),
            # não só strip() das pontas: o arquivo é escrito por outro
            # projeto e espaçamento interno irregular lá dentro não pode
            # produzir um "quase-duplicado" aqui.
            existentes = {
                " ".join(linha.split())
                for linha in caminho.read_text(encoding="utf-8").splitlines()
                if linha.strip()
            }
        if pergunta in existentes:
            return
        with caminho.open("a", encoding="utf-8") as arquivo:
            arquivo.write(pergunta + "\n")
        logger.info("Lacuna registrada no acervo", pergunta=pergunta)
    except (OSError, UnicodeError) as e:
        # UnicodeDecodeError é ValueError, não OSError — um gaps_file com
        # bytes que não decodificam como utf-8 (arquivo de outro projeto,
        # fora do nosso controle) precisa cair aqui também. Decisão: um
        # arquivo ilegível significa que não dá para checar duplicata, então
        # PULAMOS o append desta chamada em vez de escrever às cegas — o
        # contrato do acervo é "no duplicates", e anexar sem poder comparar
        # quebraria isso silenciosamente. Perder este registro é aceitável;
        # duplicar a linha deles não é.
        logger.warning("Não foi possível registrar a lacuna",
                       path=str(caminho), error=str(e))


def _anexar_evidencia(
    caminho: Path | None,
    pergunta: str,
    tema: str,
    motivo: str,
    passagens: list[Passagem],
) -> None:
    if caminho is None:
        return
    registro = {
        "ts": datetime.now(timezone.utc).isoformat(),
        "tema": tema,
        "query": pergunta,
        "motivo": motivo,
        "passagens": [
            {
                "path": p.path,
                "book_title": p.book_title,
                "score": p.score,
                "trecho": p.text[:TRECHO_MAX],
            }
            for p in passagens
        ],
    }
    try:
        caminho.parent.mkdir(parents=True, exist_ok=True)
        with caminho.open("a", encoding="utf-8") as arquivo:
            arquivo.write(json.dumps(registro, ensure_ascii=False) + "\n")
    except OSError as e:
        logger.warning("Não foi possível gravar a evidência da lacuna",
                       path=str(caminho), error=str(e))
