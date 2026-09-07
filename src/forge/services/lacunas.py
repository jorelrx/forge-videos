"""Devolve ao acervo as perguntas que ele não soube responder.

Duas escritas com contratos diferentes, e misturá-las quebraria o acervo:

- `gaps_file` é ARQUIVO DO ACERVO. Segundo o `unanswered_log.py` daquele
  projeto, ele guarda "ONLY the question, no duplicates", uma por linha, e o
  próprio acervo o lê de volta. Escrever o par pergunta/resposta ali destruiria
  o dedupe dele.
- `respostas_ruins_file` é nosso. Guarda a evidência inteira, uma linha JSON por
  caso, e ninguém o lê de volta.

Os dois não recebem os mesmos casos: ver `registrar_lacuna` e `so_evidencia`.
O acervo já registra sozinho a busca que não casou com nada; a única lacuna que
escapa a ele — e portanto a única que escrevemos no arquivo dele — é a passagem
que voltou com score alto e não responde.

Falhar aqui nunca derruba o roteiro: um caminho inexistente ou sem permissão é
um aviso. Perder o registro é ruim; perder o roteiro por causa dele é pior.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from filelock import FileLock, Timeout

from forge.infrastructure.config import Settings
from forge.infrastructure.logging import get_logger
from forge.services.acervo import Passagem

logger = get_logger(__name__)

TRECHO_MAX = 300

# Curto de propósito. O lock só cobre um read-check-append de um arquivo de
# algumas dezenas de linhas; se ele não sai em segundos, quem o segura está
# travado, e esperar mais só atrasa um roteiro de duas horas por um registro
# opcional.
LOCK_TIMEOUT = 5.0


def registrar_lacuna(
    settings: Settings,
    *,
    query: str,
    tema: str,
    motivo: str,
    passagens: list[Passagem],
    so_evidencia: bool = False,
) -> None:
    """Registra uma lacuna nos dois arquivos, ou só no nosso.

    `so_evidencia=True` pula o `gaps_file`. Existe porque as duas condições que
    nos levam a chamar isto não têm o mesmo valor para o acervo:

    - **Busca vazia** (a query não casou com nada): o próprio acervo JÁ anota a
      pergunta nesse caso — ver `routers/search.py` do projeto research, ramo
      `if not passages: container.log_unanswered(q)`, que roda dentro da mesma
      chamada HTTP que acabamos de fazer. Escrever de novo seria duplicar o
      trabalho dele (e o dedupe daqui apaga a nossa cópia de qualquer jeito),
      então gravamos só a evidência do nosso lado.
    - **Rejeição do juiz** (voltaram passagens, e nenhuma responde): esta o
      acervo NÃO detecta — para ele a busca teve sucesso. É exatamente o caso
      que o arquivo dele existe para capturar, e o único que escrevemos lá.
    """
    pergunta = " ".join(query.split())
    if not pergunta:
        return
    if not so_evidencia:
        _anexar_pergunta(settings.gaps_file, pergunta)
    _anexar_evidencia(settings.respostas_ruins_file, pergunta, tema, motivo, passagens)


def _anexar_pergunta(caminho: Path | None, pergunta: str) -> None:
    if caminho is None:
        return
    try:
        caminho.parent.mkdir(parents=True, exist_ok=True)
        # O read-check-append inteiro vai sob lock. No Windows o modo "a" é
        # seek-then-write, e isso NÃO é atômico entre processos: medido nesta
        # máquina, dois processos anexando 3000 linhas cada produziram 5744
        # linhas, 291 delas corrompidas. Mesmo `filelock` do broker de GPU.
        #
        # Isto limita o NOSSO lado apenas: o servidor do acervo escreve no
        # mesmo arquivo durante a nossa própria pesquisa e não toma este lock.
        # Serializar as nossas escritas entre si (o canal desassistido roda em
        # loop, e nada impede dois `forge` simultâneos) é o que está ao nosso
        # alcance sem mudar o outro projeto.
        with FileLock(str(caminho) + ".lock", timeout=LOCK_TIMEOUT):
            _append_deduplicado(caminho, pergunta)
    except Timeout:
        # Mesma postura de tolerância do resto do módulo: não conseguir o lock
        # é perder um registro, e perder o roteiro por causa dele é pior.
        logger.warning("Lock do arquivo de lacunas não veio a tempo; registro pulado",
                       path=str(caminho), timeout=LOCK_TIMEOUT)
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


def _append_deduplicado(caminho: Path, pergunta: str) -> None:
    """Corpo do append. Só é chamado com o lock do arquivo em mãos."""
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
    except (OSError, UnicodeError) as e:
        # Igual ao irmão `_anexar_pergunta`, e pelo mesmo motivo: UnicodeError
        # não é OSError. Aqui o caso é a ponta de ESCRITA — um surrogate solto
        # no texto de uma passagem ou no `motivo` do juiz (um modelo local
        # emite isso) vira UnicodeEncodeError na hora de gravar utf-8. O
        # docstring do módulo promete que esta escrita não derruba o roteiro;
        # sem este ramo a promessa era falsa.
        logger.warning("Não foi possível gravar a evidência da lacuna",
                       path=str(caminho), error=str(e))
