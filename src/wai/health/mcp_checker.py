"""Periodic health probes for registered MCP servers."""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone
from typing import Any

from wai.db.connection import Database
from wai.mcp.client import fetch_mcp_tools, probe_mcp_server

BUILTIN_WAI_ID = "00000000-0000-7000-8000-000000000001"

BUILTIN_WAI_TOOLS: list[dict[str, str]] = [
    {"name": "list_models", "description": "List models available to the caller"},
    {"name": "list_keys", "description": "List API keys for the organization"},
    {"name": "get_usage", "description": "Summarize token usage for the organization"},
]


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S+00:00")


class MCPHealthChecker:
    INTERVAL_SECONDS = 60.0

    def __init__(
        self,
        db: Database,
        encryption_key: bytes,
        *,
        timeout: float = 10.0,
        log: logging.Logger | None = None,
    ) -> None:
        self.db = db
        self.encryption_key = encryption_key
        self.timeout = timeout
        self.log = log or logging.getLogger("wai.health.mcp")
        self._health: dict[str, dict[str, Any]] = {}
        self._task: asyncio.Task[None] | None = None
        self._stop = asyncio.Event()

    async def start(self) -> None:
        await self.probe_all()
        self._task = asyncio.create_task(self._loop(), name="mcp-health-checker")

    async def stop(self) -> None:
        self._stop.set()
        if self._task is not None:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass

    def get_all_health(self) -> list[dict[str, Any]]:
        return list(self._health.values())

    async def _loop(self) -> None:
        while not self._stop.is_set():
            try:
                await asyncio.wait_for(self._stop.wait(), timeout=self.INTERVAL_SECONDS)
            except TimeoutError:
                await self.probe_all()

    async def _tool_count(self, server_id: str) -> int:
        rows = await self.db.fetchall(
            "SELECT COUNT(*) AS cnt FROM mcp_server_tools WHERE server_id = ?",
            (server_id,),
        )
        return int(rows[0]["cnt"]) if rows else 0

    async def probe_all(self) -> None:
        rows = await self.db.fetchall(
            """SELECT id, name, alias, url, auth_type, auth_header, auth_token_enc,
                      is_active, source
               FROM mcp_servers WHERE deleted_at IS NULL ORDER BY alias"""
        )
        for row in rows:
            item = dict(row)
            try:
                self._health[item["id"]] = await self._probe_server(item)
            except Exception as exc:
                self.log.warning("MCP health probe failed for %s: %s", item.get("alias"), exc)
                self._health[item["id"]] = self._build_result(
                    item,
                    status="unhealthy",
                    latency_ms=0,
                    tool_count=0,
                    last_error=str(exc),
                )

        self._health[BUILTIN_WAI_ID] = self._build_result(
            {
                "id": BUILTIN_WAI_ID,
                "name": "WAI Management",
                "alias": "wai",
                "source": "builtin",
            },
            status="healthy",
            latency_ms=0,
            tool_count=len(BUILTIN_WAI_TOOLS),
            last_error="",
        )

    async def _probe_server(self, server: dict[str, Any]) -> dict[str, Any]:
        tool_count = await self._tool_count(server["id"])
        status, latency_ms, last_error, _ = await probe_mcp_server(
            server,
            encryption_key=self.encryption_key,
            timeout=self.timeout,
        )
        if status == "healthy" and tool_count == 0:
            try:
                tools, fetch_err = await fetch_mcp_tools(
                    server,
                    encryption_key=self.encryption_key,
                    timeout=self.timeout,
                )
                if tools:
                    tool_count = len(tools)
                elif fetch_err and not last_error:
                    last_error = fetch_err
            except Exception as exc:
                self.log.debug("MCP tool prefetch for %s failed: %s", server.get("alias"), exc)

        return self._build_result(
            server,
            status=status,
            latency_ms=latency_ms,
            tool_count=tool_count,
            last_error=last_error,
        )

    @staticmethod
    def _build_result(
        server: dict[str, Any],
        *,
        status: str,
        latency_ms: int,
        tool_count: int,
        last_error: str,
    ) -> dict[str, Any]:
        result: dict[str, Any] = {
            "server_id": server["id"],
            "server_name": server.get("name") or "",
            "alias": server.get("alias") or "",
            "status": status,
            "latency_ms": latency_ms,
            "tool_count": tool_count,
            "last_check": _utc_now_iso(),
        }
        if last_error:
            result["last_error"] = last_error
        return result
