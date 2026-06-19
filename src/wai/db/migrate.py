"""Database schema migrations."""

from __future__ import annotations

import logging
from pathlib import Path

from wai.db.connection import Database

MIGRATIONS_DIR = Path(__file__).resolve().parent / "migrations"

CREATE_TABLE = """
CREATE TABLE IF NOT EXISTS schema_migrations (
    filename   TEXT PRIMARY KEY,
    applied_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
"""


async def is_migration_applied(db: Database, filename: str) -> bool:
    row = await db.fetchone(
        "SELECT COUNT(*) AS cnt FROM schema_migrations WHERE filename = ?",
        (filename,),
    )
    return bool(row and row["cnt"] > 0)


async def apply_migration(db: Database, filename: str, sql: str) -> None:
    await db.executescript(sql)
    await db.execute(
        "INSERT INTO schema_migrations (filename) VALUES (?)",
        (filename,),
    )
    await db.commit()


async def run_migrations(db: Database, log: logging.Logger | None = None) -> None:
    """Apply all *.up.sql files from migrations/ in sorted order."""
    logger = log or logging.getLogger("wai.migrate")
    await db.execute(CREATE_TABLE)

    filenames = sorted(p.name for p in MIGRATIONS_DIR.glob("*.up.sql"))
    for name in filenames:
        if await is_migration_applied(db, name):
            continue
        sql = (MIGRATIONS_DIR / name).read_text(encoding="utf-8")
        logger.info("applying migration: %s", name)
        await apply_migration(db, name, sql)
        logger.info("migration applied: %s", name)
