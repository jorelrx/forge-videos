from __future__ import annotations

import sqlite3

from forge.repositories.connection import Database
from forge.repositories.migrations import LATEST_SCHEMA_VERSION as SCHEMA_VERSION, migrate as _migrate

TABLES = {
    "schema_version",
    "videos",
    "runs",
    "stage_runs",
    "work_items",
    "artifacts",
    "events",
    "commands",
    "fluxos_geracao",
    "contas", "sessoes", "tentativas_oidc", "acesso_canais",
    "catalogo_canal", "leituras_canal", "boards_criativos", "aprovacoes_pauta",
}


def init_db(db: Database) -> None:
    _migrate(db)
