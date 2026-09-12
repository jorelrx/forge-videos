import pytest

from forge.repositories.connection import Database
from forge.repositories.schema import TABLES, init_db


def test_init_db_cria_exatamente_todas_as_tabelas_do_app(tmp_path):
    db = Database(tmp_path / "forge.db")
    init_db(db)

    with db.connection() as conn:
        names = {
            row[0]
            for row in conn.execute(
                "SELECT name FROM sqlite_master "
                "WHERE type='table' AND name NOT LIKE 'sqlite_%'"
            )
        }

    assert names == TABLES


def test_init_db_e_idempotente(tmp_path):
    db = Database(tmp_path / "forge.db")
    init_db(db)
    init_db(db)

    with db.connection() as conn:
        assert conn.execute("SELECT version FROM schema_version").fetchone()[0] == 1


def test_init_db_rejeita_schema_mais_novo_que_o_suportado(tmp_path):
    db = Database(tmp_path / "forge.db")
    init_db(db)

    with db.transaction(immediate=True) as conn:
        conn.execute("UPDATE schema_version SET version = 2")

    with pytest.raises(RuntimeError, match="mais nova"):
        init_db(db)
