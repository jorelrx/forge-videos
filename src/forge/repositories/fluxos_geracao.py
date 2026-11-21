from uuid import uuid4

from forge.domain.fluxo_geracao import FLUXOS_INICIAIS, FluxoGeracao, NovoFluxoGeracao
from forge.repositories.connection import Database


class FluxosGeracaoRepository:
    def __init__(self, db: Database) -> None:
        self.db = db

    def listar(self) -> list[FluxoGeracao]:
        with self.db.connection() as conn:
            rows = conn.execute(
                "SELECT id, nome, descricao, instrucoes FROM fluxos_geracao ORDER BY nome, id"
            ).fetchall()
        return [*FLUXOS_INICIAIS, *(FluxoGeracao.model_validate(dict(row)) for row in rows)]

    def obter(self, fluxo_id: str) -> FluxoGeracao | None:
        for fluxo in FLUXOS_INICIAIS:
            if fluxo.id == fluxo_id:
                return fluxo
        with self.db.connection() as conn:
            row = conn.execute(
                "SELECT id, nome, descricao, instrucoes FROM fluxos_geracao WHERE id = ?",
                (fluxo_id,),
            ).fetchone()
        return FluxoGeracao.model_validate(dict(row)) if row is not None else None

    def criar(self, entrada: NovoFluxoGeracao) -> FluxoGeracao:
        fluxo = FluxoGeracao(id=f"personalizado-{uuid4().hex}", **entrada.model_dump())
        with self.db.transaction(immediate=True) as conn:
            conn.execute(
                "INSERT INTO fluxos_geracao (id, nome, descricao, instrucoes) "
                "VALUES (:id, :nome, :descricao, :instrucoes)",
                fluxo.model_dump(),
            )
        return fluxo
