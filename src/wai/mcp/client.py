"""MCP Streamable HTTP client for tool discovery and health probes."""

from __future__ import annotations

import json
import logging
import time
from typing import Any

import httpx

from wai.crypto.aes import decrypt_string

MCP_PROTOCOL_VERSION = "2024-11-05"
MCP_CLIENT_INFO = {"name": "wai", "version": "1.0"}


def parse_mcp_body(raw: bytes | str) -> dict[str, Any] | None:
    """Parse a JSON-RPC response from plain JSON or SSE ``event: message`` payloads."""
    text = raw.decode() if isinstance(raw, bytes) else raw
    text = text.strip()
    if not text:
        return None

    if text.startswith("event:") or "\ndata:" in text:
        for line in text.splitlines():
            if line.startswith("data:"):
                payload = line[5:].strip()
                if payload:
                    try:
                        doc = json.loads(payload)
                        if isinstance(doc, dict):
                            return doc
                    except json.JSONDecodeError:
                        continue
        return None

    try:
        doc = json.loads(text)
    except json.JSONDecodeError:
        return None
    return doc if isinstance(doc, dict) else None


def build_auth_headers(server: dict[str, Any], encryption_key: bytes | None) -> dict[str, str]:
    auth_type = server.get("auth_type") or "none"
    if auth_type == "none":
        return {}

    token = ""
    encrypted = server.get("auth_token_enc")
    if encrypted and encryption_key:
        try:
            token = decrypt_string(encrypted, encryption_key, f"mcp_server:{server['id']}".encode())
        except Exception:
            logging.getLogger("wai.mcp").warning(
                "failed to decrypt auth token for MCP server %s", server.get("alias")
            )

    if auth_type == "bearer" and token:
        return {"Authorization": f"Bearer {token}"}
    if auth_type == "header" and token:
        header_name = server.get("auth_header") or "Authorization"
        return {header_name: token}
    return {}


async def mcp_request(
    url: str,
    method: str,
    *,
    params: dict[str, Any] | None = None,
    req_id: int | None = 1,
    headers: dict[str, str] | None = None,
    session_id: str | None = None,
    timeout: float = 15.0,
) -> tuple[dict[str, Any] | None, str | None, int]:
    """Send one JSON-RPC request; returns (response doc, session id, latency ms)."""
    body: dict[str, Any] = {
        "jsonrpc": "2.0",
        "method": method,
        "params": params or {},
    }
    if req_id is not None:
        body["id"] = req_id
    req_headers = {"Content-Type": "application/json", "Accept": "application/json, text/event-stream"}
    if headers:
        req_headers.update(headers)
    if session_id:
        req_headers["Mcp-Session-Id"] = session_id

    started = time.perf_counter()
    async with httpx.AsyncClient(timeout=timeout, follow_redirects=False) as client:
        resp = await client.post(url, json=body, headers=req_headers)
    latency_ms = int((time.perf_counter() - started) * 1000)

    new_session = resp.headers.get("mcp-session-id") or session_id
    if resp.status_code >= 400:
        return None, new_session, latency_ms

    doc = parse_mcp_body(resp.content)
    return doc, new_session, latency_ms


async def fetch_mcp_tools(
    server: dict[str, Any],
    *,
    encryption_key: bytes | None = None,
    timeout: float = 15.0,
) -> tuple[list[dict[str, Any]], str | None]:
    """Initialize an MCP session and return upstream tools/list entries."""
    url = server.get("url") or ""
    if not url:
        return [], "missing server URL"

    auth_headers = build_auth_headers(server, encryption_key)
    init_doc, session_id, _ = await mcp_request(
        url,
        "initialize",
        params={
            "protocolVersion": MCP_PROTOCOL_VERSION,
            "capabilities": {},
            "clientInfo": MCP_CLIENT_INFO,
        },
        req_id=1,
        headers=auth_headers,
        timeout=timeout,
    )
    if init_doc is None:
        return [], "no response from initialize"
    if init_doc.get("error"):
        err = init_doc["error"]
        return [], str(err.get("message") or err)

    await mcp_request(
        url,
        "notifications/initialized",
        params={},
        req_id=None,
        headers=auth_headers,
        session_id=session_id,
        timeout=timeout,
    )

    tools_doc, _, _ = await mcp_request(
        url,
        "tools/list",
        params={},
        req_id=2,
        headers=auth_headers,
        session_id=session_id,
        timeout=timeout,
    )
    if tools_doc is None:
        return [], "no response from tools/list"
    if tools_doc.get("error"):
        err = tools_doc["error"]
        return [], str(err.get("message") or err)

    result = tools_doc.get("result") or {}
    tools = result.get("tools") if isinstance(result, dict) else None
    if not isinstance(tools, list):
        return [], "invalid tools/list response"
    return [t for t in tools if isinstance(t, dict)], None


async def probe_mcp_server(
    server: dict[str, Any],
    *,
    encryption_key: bytes | None = None,
    timeout: float = 10.0,
) -> tuple[str, int, str, int]:
    """Probe reachability. Returns (status, latency_ms, last_error, tool_count)."""
    url = server.get("url") or ""
    if not url:
        if server.get("source") == "builtin":
            return "healthy", 0, "", 0
        return "unhealthy", 0, "missing server URL", 0

    if not server.get("is_active", 1):
        return "unknown", 0, "", 0

    auth_headers = build_auth_headers(server, encryption_key)
    doc, _, latency_ms = await mcp_request(
        url,
        "initialize",
        params={
            "protocolVersion": MCP_PROTOCOL_VERSION,
            "capabilities": {},
            "clientInfo": MCP_CLIENT_INFO,
        },
        req_id=1,
        headers=auth_headers,
        timeout=timeout,
    )
    if doc is None:
        return "unhealthy", latency_ms, "no response from server", 0
    if doc.get("error"):
        err = doc["error"]
        return "unhealthy", latency_ms, str(err.get("message") or err), 0
    return "healthy", latency_ms, "", 0
