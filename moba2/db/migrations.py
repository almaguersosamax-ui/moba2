"""Migraciones versionadas a partir de los .sql de moba2/db/schema."""
from __future__ import annotations

from pathlib import Path

from . import connection as db

SCHEMA_DIR = Path(__file__).parent / "schema"


def _applied() -> set[int]:
    rows = db.query("SELECT name FROM sqlite_master WHERE type='table' AND name='schema_migrations'")
    if not rows:
        return set()
    return {r["version"] for r in db.query("SELECT version FROM schema_migrations")}


def _bootstrap() -> None:
    db.execute("""CREATE TABLE IF NOT EXISTS schema_migrations(
                    version INTEGER PRIMARY KEY,
                    applied_at TEXT NOT NULL)""")


def migrate() -> list[int]:
    """Aplica las migraciones pendientes y devuelve las versiones aplicadas ahora."""
    _bootstrap()
    done = _applied()
    applied: list[int] = []
    for path in sorted(SCHEMA_DIR.glob("*.sql")):
        version = int(path.name.split("_", 1)[0])
        if version in done:
            continue
        sql = path.read_text(encoding="utf-8")
        con = db.conn()
        con.executescript(sql)            # applies the DDL (implicit commit)
        con.execute("INSERT INTO schema_migrations(version, applied_at)"
                    " VALUES(?, datetime('now'))", (version,))
        applied.append(version)
    return applied


def current_version() -> int:
    rows = db.query("SELECT MAX(version) AS v FROM schema_migrations")
    return rows[0]["v"] or 0
