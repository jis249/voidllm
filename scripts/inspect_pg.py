import asyncio
from pathlib import Path

from wai.config import load
from wai.db.connection import Database
from wai.db.dialect import split_sql_script


async def main() -> None:
    cfg, _ = load("wai.yaml")
    db = Database(cfg.database.driver, cfg.database.dsn)
    await db.connect()
    tables = await db.fetchall(
        "SELECT tablename FROM pg_tables WHERE schemaname = 'public'"
    )
    print("tables:", [t["tablename"] for t in tables])
    migs = await db.fetchall("SELECT filename FROM schema_migrations ORDER BY filename")
    print("applied:", [m["filename"] for m in migs])
    sql = Path("src/wai/db/migrations/0001_initial_schema.up.sql").read_text()
    stmts = split_sql_script(sql)
    print("0001 statements:", len(stmts))
    for i, s in enumerate(stmts):
        first = s.strip().split("\n", 1)[0][:100]
        print(f"{i}: {first}")
    await db.close()


if __name__ == "__main__":
    asyncio.run(main())
