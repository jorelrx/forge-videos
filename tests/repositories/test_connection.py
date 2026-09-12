import pytest

from forge.repositories.connection import Database


class InterruptTest(BaseException):
    pass


def test_connection_habilita_wal_foreign_keys_e_busy_timeout(tmp_path):
    db = Database(tmp_path / "forge.db")
    with db.connection() as conn:
        assert conn.execute("PRAGMA journal_mode").fetchone()[0] == "wal"
        assert conn.execute("PRAGMA foreign_keys").fetchone()[0] == 1
        assert conn.execute("PRAGMA busy_timeout").fetchone()[0] == 5000


def test_transaction_faz_rollback_em_base_exception(tmp_path):
    db = Database(tmp_path / "forge.db")
    with db.connection() as conn:
        conn.execute("CREATE TABLE x (id INTEGER PRIMARY KEY)")

    with pytest.raises(InterruptTest), db.transaction(immediate=True) as conn:
        conn.execute("INSERT INTO x DEFAULT VALUES")
        raise InterruptTest()

    with db.connection() as conn:
        assert conn.execute("SELECT COUNT(*) FROM x").fetchone()[0] == 0
