"""Persistência por conta e canal, com revisão otimista e uma análise por vez."""
import json
import time
from collections.abc import Callable
from datetime import UTC, datetime
from uuid import uuid4

from forge.domain.board_criativo import RascunhoBoard


class ConflitoBoard(ValueError):
    """Uma aba já gravou outra revisão."""


def liberar_analises_orfas(db) -> int:
    """Solta as reservas deixadas por um processo da API que parou.

    A análise roda como tarefa de fundo do próprio processo da API (uvicorn sem
    workers), então ao subir nenhuma reserva tem tarefa viva. Sem isso o Board
    ficaria bloqueado até a reserva expirar, mais de meia hora. Uma conclusão
    tardia do processo antigo não encontra mais o dono e é descartada.
    """
    with db.transaction(immediate=True) as conn:
        return conn.execute("""UPDATE boards_criativos SET dono=NULL,operacao=NULL,expira=NULL
            WHERE dono IS NOT NULL""").rowcount


class BoardRepository:
    def __init__(self, db, conta: str, canal: str):
        self.db = db
        self.chave = (conta, canal)

    def _linha(self, conn):
        return conn.execute("SELECT * FROM boards_criativos WHERE conta_id=? AND canal_id=?", self.chave).fetchone()

    @staticmethod
    def _carregar(row) -> RascunhoBoard:
        return RascunhoBoard.model_validate_json(row["dados"]) if row else RascunhoBoard()

    @staticmethod
    def _operacao(row) -> str | None:
        return row["operacao"] if row and row["expira"] and row["expira"] > time.time() else None

    def ler(self) -> tuple[RascunhoBoard, str | None]:
        with self.db.connection() as conn:
            row = self._linha(conn)
        return self._carregar(row), self._operacao(row)

    def _autorizado(self, conn) -> bool:
        return conn.execute("SELECT 1 FROM acesso_canais WHERE conta_id=? AND canal_id=?", self.chave).fetchone() is not None

    def _obter_revisao(self, conn, revisao: int):
        if not self._autorizado(conn):
            raise KeyError("Canal indisponível")
        row = self._linha(conn)
        board = self._carregar(row)
        if board.revisao != revisao:
            raise ConflitoBoard("Outra aba atualizou a pauta. Carregue a revisão atual.")
        return row, board

    def _gravar(self, conn, board: RascunhoBoard):
        conn.execute("""INSERT INTO boards_criativos (conta_id,canal_id,dados) VALUES (?,?,?)
            ON CONFLICT(conta_id,canal_id) DO UPDATE SET dados=excluded.dados""",
                     (*self.chave, board.model_dump_json()))

    def alterar(self, revisao: int, aplicar: Callable[[RascunhoBoard], None]):
        with self.db.transaction(immediate=True) as conn:
            row, board = self._obter_revisao(conn, revisao)
            aplicar(board)
            board.revisao += 1
            self._gravar(conn, board)
            return board, self._operacao(row)

    def reservar(self, revisao: int, tipo: str, validade: float,
                 preparar: Callable[[RascunhoBoard], object | None]):
        with self.db.transaction(immediate=True) as conn:
            row, board = self._obter_revisao(conn, revisao)
            if self._operacao(row):
                return None
            entrada = preparar(board)
            if entrada is None:
                return None
            dono = uuid4().hex
            board.erro = None
            self._gravar(conn, board)
            conn.execute("""UPDATE boards_criativos SET dono=?,operacao=?,expira=?
                WHERE conta_id=? AND canal_id=?""", (dono, tipo, time.time() + validade, *self.chave))
            return dono, entrada

    def concluir(self, dono: str, aplicar: Callable[[RascunhoBoard], None]):
        with self.db.transaction(immediate=True) as conn:
            row = self._linha(conn)
            if not row or row["dono"] != dono:
                return
            if self._autorizado(conn):
                board = self._carregar(row)
                aplicar(board)
                board.revisao += 1
                self._gravar(conn, board)
            conn.execute("""UPDATE boards_criativos SET dono=NULL,operacao=NULL,expira=NULL
                WHERE conta_id=? AND canal_id=?""", self.chave)

    def aprovar(self, revisao: int, validar: Callable[[RascunhoBoard], None],
                criar_run: Callable[[object, RascunhoBoard, str], str]) -> tuple[dict, bool]:
        """Congela a revisão, cria a execução e abre o próximo rascunho numa só transação.

        A chave (conta, canal, revisão) é procurada antes da revisão atual: quem repete
        a aprovação depois que o rascunho já avançou recebe a mesma execução.
        """
        with self.db.transaction(immediate=True) as conn:
            if not self._autorizado(conn):
                raise KeyError("Canal indisponível")
            existente = conn.execute("""SELECT * FROM aprovacoes_pauta
                WHERE conta_id=? AND canal_id=? AND revisao=?""", (*self.chave, revisao)).fetchone()
            if existente:
                return _aprovacao(existente), False
            row, board = self._obter_revisao(conn, revisao)
            if self._operacao(row):
                raise ValueError("Aguarde a IA terminar antes de criar o roteiro.")
            validar(board)
            aprovacao_id = uuid4().hex
            run_id = criar_run(conn, board, aprovacao_id)
            aprovacao = {"id": aprovacao_id, "revisao": revisao, "pauta": board.pauta.model_dump(),
                         "fluxo_id": board.fluxo_id, "run_id": run_id, "criada_em": datetime.now(UTC).isoformat()}
            conn.execute("""INSERT INTO aprovacoes_pauta
                (id,conta_id,canal_id,revisao,pauta,fluxo_id,run_id,criada_em) VALUES (?,?,?,?,?,?,?,?)""",
                         (aprovacao["id"], *self.chave, revisao, json.dumps(aprovacao["pauta"], ensure_ascii=False),
                          aprovacao["fluxo_id"], run_id, aprovacao["criada_em"]))
            self._gravar(conn, RascunhoBoard(
                revisao=board.revisao + 1, posicionamento=board.posicionamento, guardadas=board.guardadas,
                ultima_aprovacao={"id": aprovacao["id"], "run_id": run_id, "revisao": revisao,
                                  "titulo": board.pauta.titulo or board.pauta.tema},
            ))
            return aprovacao, True


def _aprovacao(row) -> dict:
    return {"id": row["id"], "revisao": row["revisao"], "pauta": json.loads(row["pauta"]),
            "fluxo_id": row["fluxo_id"], "run_id": row["run_id"], "criada_em": row["criada_em"]}


def aprovacoes_do_canal(db, conta: str, canal: str, limite: int = 20) -> list[dict]:
    with db.connection() as conn:
        rows = conn.execute("""SELECT * FROM aprovacoes_pauta WHERE conta_id=? AND canal_id=?
            ORDER BY criada_em DESC LIMIT ?""", (conta, canal, limite)).fetchall()
    return [_aprovacao(row) for row in rows]
