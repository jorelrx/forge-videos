from pathlib import Path
import sqlite3

from forge.infrastructure.logging import get_logger
from forge.repositories.connection import Database

log = get_logger(__name__)


def migrar(conn: sqlite3.Connection) -> None:
    conn.execute("ALTER TABLE runs ADD COLUMN canal_id TEXT")
    conn.execute("CREATE INDEX idx_runs_canal ON runs(canal_id, created_at DESC, id DESC)")
    conn.execute("ALTER TABLE fluxos_geracao ADD COLUMN canal_id TEXT")


def vincular_publicacoes_legadas(db: Database, raiz: Path) -> None:
    from forge.services.publicacao import ler_estado

    with db.connection() as conn:
        ids = [r[0] for r in conn.execute("SELECT id FROM runs WHERE canal_id IS NULL")]
    for run_id in ids:
        if Path(run_id).name != run_id or run_id in {".", ".."}:
            continue
        try:
            estado = ler_estado(raiz / run_id)
        except (ValueError, OSError):
            log.warning("publicacao_legada_ilegivel", run_id=run_id)
            continue
        if estado and estado.canal_id:
            with db.transaction() as conn:
                conn.execute("UPDATE runs SET canal_id=? WHERE id=? AND canal_id IS NULL",
                             (estado.canal_id, run_id))
