"""Create the wai PostgreSQL database if it does not exist."""
from __future__ import annotations

import asyncio
import os
import sys
from urllib.parse import quote_plus

import asyncpg


async def main() -> None:
    password = os.environ.get("POSTGRES_PASSWORD", "postgres")
    db_name = os.environ.get("WAI_DATABASE_NAME", "wai")
    pw = quote_plus(password)
    admin_dsn = f"postgres://postgres:{pw}@localhost:5432/postgres?sslmode=disable"
    conn = await asyncpg.connect(admin_dsn)
    try:
        exists = await conn.fetchval(
            "SELECT 1 FROM pg_database WHERE datname = $1", db_name
        )
        if not exists:
            await conn.execute(f'CREATE DATABASE "{db_name}"')
            print(f"Created database {db_name}")
        else:
            print(f"Database {db_name} already exists")
    finally:
        await conn.close()


if __name__ == "__main__":
    asyncio.run(main())
