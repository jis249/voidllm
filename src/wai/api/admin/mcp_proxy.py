"""External MCP server proxy handlers."""

from __future__ import annotations

import json
import time

import httpx
from fastapi import Request
from fastapi.responses import Response

from wai.api.admin.common import KeyInfo, ROLE_SYSTEM_ADMIN, has_role
from wai.api.admin.handler import get_handler
from wai.security.url import validate_http_url


async def handle_mcp_proxy(alias: str, request: Request, key_info: KeyInfo) -> Response:
    h = get_handler()

    if alias == "wai":
        from wai.api.admin.mcp_handler import _handle_mcp_request

        return await _handle_mcp_request(request, h.mcp_server, "wai", "/api/v1/mcp/wai")

    row = await h.db.fetchone(
        """SELECT * FROM mcp_servers WHERE alias = ? AND is_active = 1 AND deleted_at IS NULL
           AND (org_id IS NULL OR org_id = ?)
           AND (team_id IS NULL OR team_id = ? OR ? = '')
           ORDER BY CASE WHEN team_id IS NOT NULL THEN 0 WHEN org_id IS NOT NULL THEN 1 ELSE 2 END
           LIMIT 1""",
        (alias, key_info.org_id, key_info.team_id, key_info.team_id),
    )
    if not row:
        return Response(
            content=json.dumps({"jsonrpc": "2.0", "id": None, "error": {"code": -32600, "message": "unknown MCP server"}}),
            status_code=404,
            media_type="application/json",
        )
    server = dict(row)
    try:
        validate_http_url(server["url"], allow_private=h.mcp_allow_private_urls)
    except ValueError:
        return Response(
            content=json.dumps({"jsonrpc": "2.0", "id": None, "error": {"code": -32600, "message": "invalid MCP server URL"}}),
            status_code=403,
            media_type="application/json",
        )
    if not server.get("org_id") and not server.get("team_id"):
        if not has_role(key_info.role, ROLE_SYSTEM_ADMIN):
            allowed_ids = await h.db.fetchall(
                "SELECT server_id FROM org_mcp_access WHERE org_id = ?", (key_info.org_id,)
            )
            allowed = {r["server_id"] for r in allowed_ids}
            if allowed and server["id"] not in allowed:
                return Response(
                    content=json.dumps({"jsonrpc": "2.0", "id": None, "error": {"code": -32600, "message": "access denied to MCP server"}}),
                    status_code=403,
                    media_type="application/json",
                )

    body = await request.body()
    start = time.time()
    try:
        async with httpx.AsyncClient(timeout=h.mcp_call_timeout) as client:
            headers = {"Content-Type": "application/json"}
            if request.headers.get("mcp-session-id"):
                headers["Mcp-Session-Id"] = request.headers["mcp-session-id"]
            upstream = await client.post(server["url"], content=body, headers=headers)
        duration_ms = int((time.time() - start) * 1000)
        # Log usage asynchronously (fire-and-forget)
        try:
            from wai.api.admin.common import new_uuid

            await h.db.execute(
                """INSERT INTO mcp_usage_events (id, org_id, team_id, user_id, key_id, server_alias,
                                                   tool_name, duration_ms, status, timestamp)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)""",
                (
                    new_uuid(), key_info.org_id, key_info.team_id or None, key_info.user_id or None,
                    key_info.id, alias, "", duration_ms,
                    "success" if upstream.status_code < 400 else "error",
                ),
            )
            await h.db.commit()
        except Exception:
            pass
        accept = request.headers.get("accept", "")
        if "text/event-stream" in accept:
            return Response(content=upstream.text, media_type="text/event-stream", status_code=upstream.status_code)
        return Response(content=upstream.content, media_type="application/json", status_code=upstream.status_code)
    except Exception:
        return Response(
            content=json.dumps({"jsonrpc": "2.0", "id": None, "error": {"code": -32603, "message": "upstream MCP server error"}}),
            status_code=500,
            media_type="application/json",
        )
