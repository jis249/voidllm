"""Async PostgreSQL database connection (asyncpg)."""

from __future__ import annotations

import os
from contextlib import asynccontextmanager
from typing import Any, AsyncIterator
from urllib.parse import quote_plus

from wai.db.dialect import adapt_sql, split_sql_script

DEFAULT_PG_DSN = os.environ.get(
    "WAI_DATABASE_DSN",
    f"postgres://postgres:{quote_plus(os.environ.get('POSTGRES_PASSWORD', 'postgres'))}"
    "@localhost:5432/wai?sslmode=disable",
)


class Row(dict):
    """Dict row with attribute access."""

    def __getitem__(self, key: str | int) -> Any:
        return super().__getitem__(key)


def _row_from_record(record: Any) -> Row:
    return Row(dict(record))


class ExecuteResult:
    """asyncpg execute status with a SQLite-compatible rowcount."""

    __slots__ = ("status", "rowcount")

    def __init__(self, status: str) -> None:
        self.status = status
        self.rowcount = self._parse_rowcount(status)

    @staticmethod
    def _parse_rowcount(status: str) -> int:
        # asyncpg returns e.g. "UPDATE 1", "DELETE 0", "INSERT 0 1"
        parts = status.split()
        if parts and parts[-1].isdigit():
            return int(parts[-1])
        return 0


class Database:
    """Async PostgreSQL wrapper."""

    def __init__(self, driver: str, dsn: str) -> None:
        if driver and driver.lower().strip() not in ("", "postgres", "postgresql"):
            raise ValueError(f"unsupported database driver {driver!r}; only postgres is supported")
        self.driver = "postgres"
        self.dsn = dsn or DEFAULT_PG_DSN
        self._pg_pool: Any = None

    async def connect(self, *, min_size: int | None = None, max_size: int | None = None) -> None:
        try:
            import asyncpg
        except ImportError as exc:
            raise RuntimeError("PostgreSQL requires asyncpg — run: pip install asyncpg") from exc
        pool_min = 2 if min_size is None else min_size
        pool_max = 25 if max_size is None else max_size
        self._pg_pool = await asyncpg.create_pool(self.dsn, min_size=pool_min, max_size=pool_max)

    async def close(self) -> None:
        if self._pg_pool is not None:
            await self._pg_pool.close()
            self._pg_pool = None

    def _sql(self, sql: str) -> str:
        return adapt_sql(sql, self.driver)

    async def execute(self, sql: str, params: tuple | list = ()) -> ExecuteResult:
        sql = self._sql(sql)
        assert self._pg_pool is not None
        async with self._pg_pool.acquire() as conn:
            status = await conn.execute(sql, *params)
            return ExecuteResult(status)

    async def executemany(self, sql: str, params: list[tuple]) -> Any:
        sql = self._sql(sql)
        assert self._pg_pool is not None
        async with self._pg_pool.acquire() as conn:
            return await conn.executemany(sql, params)

    async def fetchone(self, sql: str, params: tuple | list = ()) -> Row | None:
        sql = self._sql(sql)
        assert self._pg_pool is not None
        async with self._pg_pool.acquire() as conn:
            row = await conn.fetchrow(sql, *params)
            return _row_from_record(row) if row else None

    async def fetchall(self, sql: str, params: tuple | list = ()) -> list[Row]:
        sql = self._sql(sql)
        assert self._pg_pool is not None
        async with self._pg_pool.acquire() as conn:
            rows = await conn.fetch(sql, *params)
            return [_row_from_record(r) for r in rows]

    async def executescript(self, sql: str) -> None:
        assert self._pg_pool is not None
        async with self._pg_pool.acquire() as conn:
            async with conn.transaction():
                for stmt in split_sql_script(sql):
                    await conn.execute(adapt_sql(stmt, "postgres"))

    async def commit(self) -> None:
        """No-op — PostgreSQL autocommits per statement outside explicit transactions."""

    @asynccontextmanager
    async def transaction(self) -> AsyncIterator[Any]:
        assert self._pg_pool is not None
        async with self._pg_pool.acquire() as conn:
            async with conn.transaction():
                yield _PgTransactionConn(conn, self.driver)


class _PgTransactionConn:
    """Transaction-scoped connection wrapper."""

    def __init__(self, conn: Any, driver: str) -> None:
        self._conn = conn
        self._driver = driver

    async def execute(self, sql: str, params: tuple | list = ()) -> ExecuteResult:
        status = await self._conn.execute(adapt_sql(sql, self._driver), *params)
        return ExecuteResult(status)

    async def executemany(self, sql: str, params: list[tuple]) -> None:
        await self._conn.executemany(adapt_sql(sql, self._driver), params)


_db: Database | None = None


def get_database(driver: str = "", dsn: str = "") -> Database:
    global _db
    if _db is None:
        _db = Database(driver or "postgres", dsn or DEFAULT_PG_DSN)
    return _db
