"""Pausa cooperativa do operador local durante o encerramento do Studio."""
import argparse
from time import monotonic, sleep
from uuid import uuid4

from forge.infrastructure.config import get_settings
from forge.repositories.connection import Database
from forge.services.control_plane import ControlPlaneService, TransicaoInvalida


def pausar(db: Database, prazo: int) -> bool:
    controle = ControlPlaneService(db)
    limite = monotonic() + prazo
    while True:
        with db.connection() as conn:
            pendentes = conn.execute(
                "SELECT id, status FROM runs WHERE status IN ('preparing','running','pausing')"
            ).fetchall()
        if not pendentes:
            return True
        for linha in pendentes:
            if linha["status"] != "pausing":
                try:
                    controle.request_pause(linha["id"], idempotency_key=f"stop-{uuid4()}")
                except TransicaoInvalida:
                    pass  # O worker concluiu a etapa entre a consulta e o pedido.
        if monotonic() >= limite:
            return False
        sleep(0.25)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--prazo", type=int, required=True)
    prazo = parser.parse_args().prazo
    raise SystemExit(0 if pausar(Database(get_settings().studio_db_path), prazo) else 1)
