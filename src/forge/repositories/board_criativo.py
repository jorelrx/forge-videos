"""Persistência por conta e canal, com revisão otimista e uma análise por vez."""
import time
from collections.abc import Callable
from uuid import uuid4

from forge.domain.board_criativo import RascunhoBoard


class ConflitoBoard(ValueError):
    """Uma aba já gravou outra revisão."""


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
