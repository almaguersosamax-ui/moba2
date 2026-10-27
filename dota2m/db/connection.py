"""Conexión SQLite por hilo, con WAL y claves foráneas activas."""
from __future__ import annotations

import sqlite3
import threading
from pathlib import Path

_local = threading.local()
_db_path: Path | None = None
_init_lock = threading.Lock()


def configure(path: Path | str) -> None:
    global _db_path
    _db_path = Path(path)
    _db_path.parent.mkdir(parents=True, exist_ok=True)


def _connect() -> sqlite3.Connection:
    assert _db_path is not None, "db.configure() no fue llamado"
    con = sqlite3.connect(_db_path, timeout=15, isolation_level=None)
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA journal_mode=WAL")
    con.execute("PRAGMA foreign_keys=ON")
    con.execute("PRAGMA busy_timeout=15000")
    con.execute("PRAGMA synchronous=NORMAL")
    return con


def conn() -> sqlite3.Connection:
    """Conexión del hilo actual (se crea bajo demanda)."""
    con = getattr(_local, "con", None)
    if con is None:
        with _init_lock:
            con = _connect()
        _local.con = con
    return con


def close() -> None:
    con = getattr(_local, "con", None)
    if con is not None:
        con.close()
        _local.con = None


def query(sql: str, args: tuple = ()) -> list[sqlite3.Row]:
    return conn().execute(sql, args).fetchall()


def query_one(sql: str, args: tuple = ()) -> sqlite3.Row | None:
    return conn().execute(sql, args).fetchone()


def execute(sql: str, args: tuple = ()) -> int:
    cur = conn().execute(sql, args)
    return cur.lastrowid or cur.rowcount


def transaction():
    """Contexto de transacción (BEGIN IMMEDIATE / COMMIT / ROLLBACK)."""
    class _Tx:
        def __enter__(self):
            conn().execute("BEGIN IMMEDIATE")
            return conn()

        def __exit__(self, exc_type, exc, tb):
            if exc_type is None:
                conn().execute("COMMIT")
            else:
                conn().execute("ROLLBACK")
            return False

    return _Tx()
