"""Run database migrations (dev helper)."""
from __future__ import annotations

import asyncio
import logging
import sys

from wai.config import load
from wai.db.connection import Database
from wai.db.migrate import run_migrations


async def main() -> None:
    path = sys.argv[1] if len(sys.argv) > 1 else "wai.yaml"
    cfg, _ = load(path)
    db = Database(cfg.database.driver, cfg.database.dsn)
    await db.connect()
    await run_migrations(db, logging.getLogger("wai"))
    print("migrations ok")
    await db.close()


if __name__ == "__main__":
    asyncio.run(main())
