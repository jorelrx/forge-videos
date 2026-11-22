from uuid import uuid4

from forge.domain.fluxo_geracao import FLUXOS_INICIAIS, FluxoGeracao, NovoFluxoGeracao
from forge.repositories.connection import Database


class FluxosGeracaoRepository:
    def __init__(self, db: Database) -> None:
        self.db = db

    def listar(self, *, canal_id: str | None = None) -> list[FluxoGeracao]:
        with self.db.connection() as conn:
            rows = conn.execute(
                "SELECT id, nome, descricao, instrucoes FROM fluxos_geracao "
                "WHERE (? IS NULL OR canal_id = ?) ORDER BY nome, id", (canal_id, canal_id)
            ).fetchall()
        return [*FLUXOS_INICIAIS, *(FluxoGeracao.model_validate(dict(row)) for row in rows)]

    def obter(self, fluxo_id: str, *, canal_id: str | None = None) -> FluxoGeracao | None:
        for fluxo in FLUXOS_INICIAIS:
            if fluxo.id == fluxo_id:
                return fluxo
        with self.db.connection() as conn:
            row = conn.execute(
                "SELECT id, nome, descricao, instrucoes FROM fluxos_geracao WHERE id = ? "
                "AND (? IS NULL OR canal_id = ?)", (fluxo_id, canal_id, canal_id),
            ).fetchone()
        return FluxoGeracao.model_validate(dict(row)) if row is not None else None

    def criar(self, entrada: NovoFluxoGeracao, *, canal_id: str | None = None) -> FluxoGeracao:
        fluxo = FluxoGeracao(id=f"personalizado-{uuid4().hex}", **entrada.model_dump())
        with self.db.transaction(immediate=True) as conn:
            conn.execute(
                "INSERT INTO fluxos_geracao (id, nome, descricao, instrucoes, canal_id) "
                "VALUES (:id, :nome, :descricao, :instrucoes, :canal_id)",
                {**fluxo.model_dump(), "canal_id": canal_id},
            )
        return fluxo
