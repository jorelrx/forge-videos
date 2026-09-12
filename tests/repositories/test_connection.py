import sqlite3

import pytest

from forge.repositories.connection import Database


class InterruptTest(BaseException):
    pass


def test_connection_habilita_wal_foreign_keys_e_busy_timeout(tmp_path):
    db = Database(tmp_path / "forge.db", busy_timeout_ms=321)

    with db.connection() as conn:
        assert conn.execute("PRAGMA journal_mode").fetchone()[0] == "wal"
        assert conn.execute("PRAGMA foreign_keys").fetchone()[0] == 1
        assert conn.execute("PRAGMA busy_timeout").fetchone()[0] == 321


def test_connection_passa_busy_timeout_para_sqlite_connect(tmp_path, monkeypatch):
    connect = sqlite3.connect
    received: dict[str, object] = {}

    def connect_with_recorded_timeout(*args, **kwargs):
        received["timeout"] = kwargs["timeout"]
        return connect(*args, **kwargs)

    monkeypatch.setattr(
        "forge.repositories.connection.sqlite3.connect", connect_with_recorded_timeout
    )

    db = Database(tmp_path / "forge.db", busy_timeout_ms=250)
    with db.connection():
        pass

    assert received["timeout"] == 0.25


def test_database_rejeita_busy_timeout_negativo(tmp_path):
    with pytest.raises(ValueError, match="busy_timeout_ms.*maior ou igual a zero"):
        Database(tmp_path / "forge.db", busy_timeout_ms=-1)


def test_transaction_faz_rollback_em_base_exception(tmp_path):
    db = Database(tmp_path / "forge.db")
    with db.connection() as conn:
        conn.execute("CREATE TABLE x (id INTEGER PRIMARY KEY)")

    with pytest.raises(InterruptTest), db.transaction(immediate=True) as conn:
        conn.execute("INSERT INTO x DEFAULT VALUES")
        raise InterruptTest()

    with db.connection() as conn:
        assert conn.execute("SELECT COUNT(*) FROM x").fetchone()[0] == 0
