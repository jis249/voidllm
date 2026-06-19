"""Built-in MCP server JSON-RPC and SSE handlers."""

from __future__ import annotations

import asyncio
import json
import time

from fastapi import APIRouter, Depends, Request
from fastapi.responses import Response, StreamingResponse

from wai.api.admin.common import KeyInfo
from wai.api.admin.handler import auth_middleware, get_handler

router = APIRouter()


def _mcp_error(req_id, code: int, message: str) -> dict:
    return {"jsonrpc": "2.0", "id": req_id, "error": {"code": code, "message": message}}


def _parse_meta(body: bytes) -> dict:
    try:
        msg = json.loads(body)
        return {"method": msg.get("method", ""), "tool_name": (msg.get("params") or {}).get("name", "")}
    except json.JSONDecodeError:
        return {"method": "", "tool_name": ""}


async def _handle_mcp_request(
    request: Request,
    server,
    server_alias: str,
    endpoint: str,
) -> Response:
    h = get_handler()
    body = await request.body()
    if not body:
        return Response(content=json.dumps(_mcp_error(None, -32700, "empty request body")), media_type="application/json")
    key_info: KeyInfo | None = getattr(request.state, "wai_key_info", None)
    if server is None:
        return Response(
            content=json.dumps(_mcp_error(None, -32603, "MCP server not configured")),
            media_type="application/json",
            status_code=503,
        )
    start = time.time()
    if hasattr(server, "handle"):
        result = server.handle(body, identity=key_info)
    else:
        # Simplified stub for management MCP server
        try:
            msg = json.loads(body)
        except json.JSONDecodeError:
            return Response(content=json.dumps(_mcp_error(None, -32700, "parse error")), media_type="application/json")
        method = msg.get("method", "")
        req_id = msg.get("id")
        if method == "tools/list":
            result = {"jsonrpc": "2.0", "id": req_id, "result": {"tools": []}}
        elif method == "initialize":
            result = {"jsonrpc": "2.0", "id": req_id, "result": {"protocolVersion": "2024-11-05", "capabilities": {}}}
        else:
            result = _mcp_error(req_id, -32601, f"method not found: {method}")
    if result is None:
        return Response(status_code=202)
    payload = json.dumps(result) if isinstance(result, dict) else result
    accept = request.headers.get("accept", "")
    if "text/event-stream" in accept:
        sse = f"event: message\ndata: {payload}\n\n"
        return Response(content=sse, media_type="text/event-stream")
    return Response(content=payload, media_type="application/json")


async def _handle_mcp_sse(endpoint: str) -> StreamingResponse:
    async def stream():
        yield f"event: endpoint\ndata: {endpoint}\n\n"
        deadline = time.time() + 600
        while time.time() < deadline:
            yield ": ping\n\n"
            await asyncio.sleep(15)

    return StreamingResponse(stream(), media_type="text/event-stream")


@router.post("/mcp/{alias}")
async def handle_mcp_proxy_alias(
    alias: str,
    request: Request,
    key_info: KeyInfo = Depends(auth_middleware),
):
    from wai.api.admin.mcp_proxy import handle_mcp_proxy

    return await handle_mcp_proxy(alias, request, key_info)


@router.get("/mcp/{alias}")
async def handle_mcp_proxy_sse(
    alias: str,
    key_info: KeyInfo = Depends(auth_middleware),
):
    if alias == "wai":
        return await _handle_mcp_sse("/api/v1/mcp/wai")
    return await _handle_mcp_sse(f"/api/v1/mcp/{alias}")


def register_code_mode_routes(parent: APIRouter) -> None:
    """Register Code Mode routes on parent router when enabled."""

    @parent.post("/mcp")
    async def handle_code_mode_mcp(request: Request, key_info: KeyInfo = Depends(auth_middleware)):
        h = get_handler()
        return await _handle_mcp_request(request, h.code_mode_server, "code-mode", "/api/v1/mcp")

    @parent.get("/mcp")
    async def handle_code_mode_mcp_sse(key_info: KeyInfo = Depends(auth_middleware)):
        return await _handle_mcp_sse("/api/v1/mcp")
