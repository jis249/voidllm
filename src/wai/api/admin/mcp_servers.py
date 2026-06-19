"""MCP server CRUD and tool cache handlers."""

from __future__ import annotations

import json
from typing import Any

from fastapi import APIRouter, Depends, Query, Response, status
from pydantic import BaseModel, Field

from wai.api.admin.common import KeyInfo, ROLE_MEMBER, ROLE_ORG_ADMIN, ROLE_SYSTEM_ADMIN, ROLE_TEAM_ADMIN, bad_request, new_uuid, not_found, utc_now_iso
from wai.api.admin.handler import get_handler, require_role
from wai.crypto.aes import encrypt_string
from wai.health.mcp_checker import BUILTIN_WAI_ID, BUILTIN_WAI_TOOLS
from wai.mcp.client import fetch_mcp_tools, probe_mcp_server
from wai.security.url import validate_http_url

router = APIRouter()


class CreateMCPServerRequest(BaseModel):
    alias: str
    name: str
    url: str
    auth_type: str = "none"
    auth_header: str = "Authorization"
    auth_token: str = ""
    description: str = ""


class UpdateMCPServerRequest(BaseModel):
    alias: str | None = None
    name: str | None = None
    url: str | None = None
    auth_type: str | None = None
    auth_header: str | None = None
    auth_token: str | None = None
    description: str | None = None
    code_mode_enabled: bool | None = None


class MCPServerResponse(BaseModel):
    id: str
    alias: str
    name: str
    url: str
    scope: str
    org_id: str | None = None
    team_id: str | None = None
    auth_type: str
    is_active: bool
    source: str = "api"
    code_mode_enabled: bool = True
    description: str = ""
    created_at: str
    updated_at: str


class MCPServerHealthResponse(BaseModel):
    server_id: str
    server_name: str
    alias: str
    status: str = "unknown"
    last_check: str = ""
    last_error: str | None = None
    latency_ms: int = 0
    tool_count: int = 0




def _builtin_wai_server() -> MCPServerResponse:
    now = utc_now_iso()
    return MCPServerResponse(
        id=BUILTIN_WAI_ID,
        alias="wai",
        name="WAI Management",
        url="",
        scope="global",
        auth_type="none",
        is_active=True,
        source="builtin",
        code_mode_enabled=True,
        description="Built-in management MCP server (list models, usage, keys)",
        created_at=now,
        updated_at=now,
    )


def _with_builtin(servers: list[MCPServerResponse]) -> list[MCPServerResponse]:
    if any(s.alias == "wai" and s.source == "builtin" for s in servers):
        return servers
    return [_builtin_wai_server(), *servers]


class BlocklistRequest(BaseModel):
    tool_names: list[str] = Field(default_factory=list)
    tool_name: str = ""

    def resolved_names(self) -> list[str]:
        if self.tool_name.strip():
            return [self.tool_name.strip()]
        return [n.strip() for n in self.tool_names if n.strip()]


def _validate_mcp_url(url: str) -> str:
    h = get_handler()
    try:
        return validate_http_url(url, allow_private=h.mcp_allow_private_urls)
    except ValueError as exc:
        raise bad_request(str(exc)) from exc


def _mcp_resp(row) -> MCPServerResponse:
    d = dict(row)
    scope = "global"
    if d.get("team_id"):
        scope = "team"
    elif d.get("org_id"):
        scope = "org"
    return MCPServerResponse(
        id=d["id"],
        alias=d["alias"],
        name=d["name"],
        url=d["url"],
        scope=scope,
        org_id=d.get("org_id"),
        team_id=d.get("team_id"),
        auth_type=d.get("auth_type") or "none",
        is_active=bool(d.get("is_active", 1)),
        source=d.get("source") or "api",
        code_mode_enabled=bool(d.get("code_mode_enabled", 1)),
        description=d.get("description") or "",
        created_at=d["created_at"],
        updated_at=d["updated_at"],
    )


async def _get_server(h, server_id: str) -> dict[str, Any]:
    row = await h.db.fetchone(
        "SELECT * FROM mcp_servers WHERE id = ? AND deleted_at IS NULL", (server_id,)
    )
    if not row:
        raise not_found("mcp server not found")
    return dict(row)


def _encrypt_auth_token(h, server_id: str, auth_type: str, token: str) -> str | None:
    if auth_type == "none" or not token.strip():
        return None
    return encrypt_string(token.strip(), h.encryption_key, f"mcp_server:{server_id}".encode())


async def _tool_count(h, server_id: str) -> int:
    rows = await h.db.fetchall(
        "SELECT COUNT(*) AS cnt FROM mcp_server_tools WHERE server_id = ?", (server_id,)
    )
    return int(rows[0]["cnt"]) if rows else 0


async def _sync_tools(h, server_id: str, tools: list[dict[str, Any]]) -> int:
    await h.db.execute("DELETE FROM mcp_server_tools WHERE server_id = ?", (server_id,))
    count = 0
    for tool in tools:
        name = str(tool.get("name") or "").strip()
        if not name:
            continue
        description = str(tool.get("description") or "")
        input_schema = tool.get("inputSchema")
        if not isinstance(input_schema, dict):
            input_schema = {}
        await h.db.execute(
            """INSERT INTO mcp_server_tools (id, server_id, name, description, input_schema, fetched_at)
               VALUES (?, ?, ?, ?, ?, CURRENT_TIMESTAMP)""",
            (new_uuid(), server_id, name, description, json.dumps(input_schema)),
        )
        count += 1
    await h.db.execute(
        "UPDATE mcp_servers SET updated_at = CURRENT_TIMESTAMP WHERE id = ?", (server_id,)
    )
    await h.db.commit()
    return count


@router.get("/mcp-servers/health", response_model=list[MCPServerHealthResponse])
async def list_mcp_server_health(_: KeyInfo = Depends(require_role(ROLE_MEMBER))) -> list[MCPServerHealthResponse]:
    h = get_handler()
    if h.mcp_health_checker is not None:
        raw = h.mcp_health_checker.get_all_health()
        return [MCPServerHealthResponse(**item) if isinstance(item, dict) else item for item in raw]
    # No background health probes — derive status from cached tool counts.
    rows = await h.db.fetchall(
        "SELECT id, name, alias FROM mcp_servers WHERE deleted_at IS NULL ORDER BY alias"
    )
    now = utc_now_iso()
    health = []
    for r in rows:
        tool_count = await _tool_count(h, r["id"])
        health.append(
            MCPServerHealthResponse(
                server_id=r["id"],
                server_name=r["name"],
                alias=r["alias"],
                status="unknown",
                last_check=now,
                latency_ms=0,
                tool_count=tool_count,
            )
        )
    builtin = _builtin_wai_server()
    if not any(x.alias == "wai" for x in health):
        health.insert(
            0,
            MCPServerHealthResponse(
                server_id=builtin.id,
                server_name=builtin.name,
                alias=builtin.alias,
                status="healthy",
                last_check=now,
                tool_count=len(BUILTIN_WAI_TOOLS),
            ),
        )
    return health


@router.post("/mcp-servers", response_model=MCPServerResponse, status_code=status.HTTP_201_CREATED)
async def create_mcp_server(
    body: CreateMCPServerRequest,
    _: KeyInfo = Depends(require_role(ROLE_SYSTEM_ADMIN)),
) -> MCPServerResponse:
    h = get_handler()
    sid = new_uuid()
    url = _validate_mcp_url(body.url)
    token_enc = _encrypt_auth_token(h, sid, body.auth_type, body.auth_token)
    await h.db.execute(
        """INSERT INTO mcp_servers (id, alias, name, url, auth_type, auth_header, auth_token_enc,
                                    description, is_active, created_at, updated_at)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, 1, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)""",
        (sid, body.alias, body.name, url, body.auth_type, body.auth_header, token_enc, body.description),
    )
    await h.db.commit()
    return _mcp_resp(await _get_server(h, sid))


@router.get("/mcp-servers", response_model=list[MCPServerResponse])
async def list_mcp_servers(_: KeyInfo = Depends(require_role(ROLE_SYSTEM_ADMIN))) -> list[MCPServerResponse]:
    h = get_handler()
    rows = await h.db.fetchall(
        "SELECT * FROM mcp_servers WHERE org_id IS NULL AND team_id IS NULL AND deleted_at IS NULL"
    )
    return _with_builtin([_mcp_resp(r) for r in rows])


@router.post("/orgs/{org_id}/mcp-servers", response_model=MCPServerResponse, status_code=status.HTTP_201_CREATED)
async def create_org_mcp_server(
    org_id: str,
    body: CreateMCPServerRequest,
    _: KeyInfo = Depends(require_role(ROLE_ORG_ADMIN)),
) -> MCPServerResponse:
    h = get_handler()
    sid = new_uuid()
    url = _validate_mcp_url(body.url)
    token_enc = _encrypt_auth_token(h, sid, body.auth_type, body.auth_token)
    await h.db.execute(
        """INSERT INTO mcp_servers (id, alias, name, url, org_id, auth_type, auth_header, auth_token_enc,
                                    description, is_active, created_at, updated_at)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 1, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)""",
        (sid, body.alias, body.name, url, org_id, body.auth_type, body.auth_header, token_enc, body.description),
    )
    await h.db.commit()
    return _mcp_resp(await _get_server(h, sid))


@router.get("/orgs/{org_id}/mcp-servers", response_model=list[MCPServerResponse])
async def list_org_mcp_servers(
    org_id: str,
    _: KeyInfo = Depends(require_role(ROLE_MEMBER)),
) -> list[MCPServerResponse]:
    h = get_handler()
    rows = await h.db.fetchall(
        """SELECT * FROM mcp_servers WHERE deleted_at IS NULL
           AND (org_id = ? OR (org_id IS NULL AND team_id IS NULL))
           ORDER BY alias""",
        (org_id,),
    )
    return _with_builtin([_mcp_resp(r) for r in rows])


@router.post(
    "/orgs/{org_id}/teams/{team_id}/mcp-servers",
    response_model=MCPServerResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_team_mcp_server(
    org_id: str,
    team_id: str,
    body: CreateMCPServerRequest,
    _: KeyInfo = Depends(require_role(ROLE_TEAM_ADMIN)),
) -> MCPServerResponse:
    h = get_handler()
    sid = new_uuid()
    url = _validate_mcp_url(body.url)
    token_enc = _encrypt_auth_token(h, sid, body.auth_type, body.auth_token)
    await h.db.execute(
        """INSERT INTO mcp_servers (id, alias, name, url, org_id, team_id, auth_type, auth_header,
                                    auth_token_enc, description, is_active, created_at, updated_at)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 1, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)""",
        (
            sid, body.alias, body.name, url, org_id, team_id,
            body.auth_type, body.auth_header, token_enc, body.description,
        ),
    )
    await h.db.commit()
    return _mcp_resp(await _get_server(h, sid))


@router.get("/orgs/{org_id}/teams/{team_id}/mcp-servers", response_model=list[MCPServerResponse])
async def list_team_mcp_servers(
    org_id: str,
    team_id: str,
    _: KeyInfo = Depends(require_role(ROLE_MEMBER)),
) -> list[MCPServerResponse]:
    h = get_handler()
    rows = await h.db.fetchall(
        "SELECT * FROM mcp_servers WHERE team_id = ? AND org_id = ? AND deleted_at IS NULL",
        (team_id, org_id),
    )
    return _with_builtin([_mcp_resp(r) for r in rows])


@router.get("/mcp-servers/{server_id}", response_model=MCPServerResponse)
async def get_mcp_server(
    server_id: str,
    _: KeyInfo = Depends(require_role(ROLE_MEMBER)),
) -> MCPServerResponse:
    h = get_handler()
    return _mcp_resp(await _get_server(h, server_id))


@router.patch("/mcp-servers/{server_id}", response_model=MCPServerResponse)
async def update_mcp_server(
    server_id: str,
    body: UpdateMCPServerRequest,
    _: KeyInfo = Depends(require_role(ROLE_MEMBER)),
) -> MCPServerResponse:
    h = get_handler()
    fields = {k: v for k, v in body.model_dump(exclude_unset=True).items()}
    auth_token = fields.pop("auth_token", None)
    if "url" in fields:
        fields["url"] = _validate_mcp_url(fields["url"])
    if "code_mode_enabled" in fields:
        fields["code_mode_enabled"] = 1 if fields["code_mode_enabled"] else 0
    if auth_token is not None:
        current = await _get_server(h, server_id)
        auth_type = fields.get("auth_type") or current.get("auth_type") or "none"
        fields["auth_token_enc"] = _encrypt_auth_token(h, server_id, auth_type, auth_token)
    if fields:
        sets = ", ".join(f"{k} = ?" for k in fields)
        await h.db.execute(
            f"UPDATE mcp_servers SET {sets}, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
            (*fields.values(), server_id),
        )
        await h.db.commit()
    return _mcp_resp(await _get_server(h, server_id))


@router.delete("/mcp-servers/{server_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_mcp_server(
    server_id: str,
    _: KeyInfo = Depends(require_role(ROLE_MEMBER)),
) -> Response:
    h = get_handler()
    cur = await h.db.execute(
        "UPDATE mcp_servers SET deleted_at = CURRENT_TIMESTAMP WHERE id = ?", (server_id,)
    )
    await h.db.commit()
    if cur.rowcount == 0:
        raise not_found("mcp server not found")
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.patch("/mcp-servers/{server_id}/activate", response_model=MCPServerResponse)
async def activate_mcp_server(
    server_id: str,
    _: KeyInfo = Depends(require_role(ROLE_MEMBER)),
) -> MCPServerResponse:
    h = get_handler()
    await h.db.execute("UPDATE mcp_servers SET is_active = 1 WHERE id = ?", (server_id,))
    await h.db.commit()
    return _mcp_resp(await _get_server(h, server_id))


@router.patch("/mcp-servers/{server_id}/deactivate", response_model=MCPServerResponse)
async def deactivate_mcp_server(
    server_id: str,
    _: KeyInfo = Depends(require_role(ROLE_MEMBER)),
) -> MCPServerResponse:
    h = get_handler()
    await h.db.execute("UPDATE mcp_servers SET is_active = 0 WHERE id = ?", (server_id,))
    await h.db.commit()
    return _mcp_resp(await _get_server(h, server_id))


@router.post("/mcp-servers/{server_id}/test")
async def test_mcp_server_connection(
    server_id: str,
    _: KeyInfo = Depends(require_role(ROLE_MEMBER)),
) -> dict[str, Any]:
    if server_id == BUILTIN_WAI_ID:
        return {"success": True, "tools": len(BUILTIN_WAI_TOOLS)}
    h = get_handler()
    server = await _get_server(h, server_id)
    status, latency_ms, last_error, _ = await probe_mcp_server(
        server,
        encryption_key=h.encryption_key,
        timeout=h.mcp_call_timeout,
    )
    if status != "healthy":
        return {"success": False, "error": last_error or "connection test failed", "latency_ms": latency_ms}
    tool_count = await _tool_count(h, server_id)
    if tool_count == 0:
        tools, fetch_err = await fetch_mcp_tools(
            server,
            encryption_key=h.encryption_key,
            timeout=h.mcp_call_timeout,
        )
        if tools:
            tool_count = await _sync_tools(h, server_id, tools)
        elif fetch_err:
            return {"success": True, "tools": 0, "warning": fetch_err, "latency_ms": latency_ms}
    return {"success": True, "tools": tool_count, "latency_ms": latency_ms}


@router.get("/mcp-servers/{server_id}/blocklist")
async def list_mcp_server_blocklist(
    server_id: str,
    _: KeyInfo = Depends(require_role(ROLE_MEMBER)),
) -> list[dict[str, Any]]:
    if server_id == BUILTIN_WAI_ID:
        return []
    h = get_handler()
    rows = await h.db.fetchall(
        """SELECT id, server_id, tool_name, reason, created_by, created_at
           FROM mcp_tool_blocklist WHERE server_id = ? ORDER BY tool_name""",
        (server_id,),
    )
    return [dict(r) for r in rows]


@router.post("/mcp-servers/{server_id}/blocklist")
async def add_mcp_server_blocklist(
    server_id: str,
    body: BlocklistRequest,
    _: KeyInfo = Depends(require_role(ROLE_MEMBER)),
) -> list[dict[str, Any]]:
    h = get_handler()
    names = body.resolved_names()
    if not names:
        raise bad_request("tool_name is required")
    for name in names:
        await h.db.execute(
            "INSERT OR IGNORE INTO mcp_tool_blocklist (id, server_id, tool_name) VALUES (?, ?, ?)",
            (new_uuid(), server_id, name),
        )
    await h.db.commit()
    return await list_mcp_server_blocklist(server_id, _)


@router.delete("/mcp-servers/{server_id}/blocklist")
async def remove_mcp_server_blocklist(
    server_id: str,
    tool_name: str | None = Query(None),
    body: BlocklistRequest | None = None,
    _: KeyInfo = Depends(require_role(ROLE_MEMBER)),
) -> list[dict[str, Any]]:
    h = get_handler()
    names = [tool_name.strip()] if tool_name and tool_name.strip() else []
    if body is not None:
        names.extend(body.resolved_names())
    names = list(dict.fromkeys(names))
    if not names:
        raise bad_request("tool_name is required")
    for name in names:
        await h.db.execute(
            "DELETE FROM mcp_tool_blocklist WHERE server_id = ? AND tool_name = ?",
            (server_id, name),
        )
    await h.db.commit()
    return await list_mcp_server_blocklist(server_id, _)


@router.post("/mcp-servers/{server_id}/refresh-tools")
async def refresh_mcp_server_tools(
    server_id: str,
    _: KeyInfo = Depends(require_role(ROLE_MEMBER)),
) -> dict[str, int]:
    if server_id == BUILTIN_WAI_ID:
        return {"tool_count": len(BUILTIN_WAI_TOOLS)}
    h = get_handler()
    server = await _get_server(h, server_id)
    tools, err = await fetch_mcp_tools(
        server,
        encryption_key=h.encryption_key,
        timeout=h.mcp_call_timeout,
    )
    if err and not tools:
        raise bad_request(err)
    tool_count = await _sync_tools(h, server_id, tools)
    if h.mcp_health_checker is not None:
        await h.mcp_health_checker.probe_all()
    return {"tool_count": tool_count}


@router.get("/mcp-servers/{server_id}/tools")
async def list_mcp_server_tools(
    server_id: str,
    _: KeyInfo = Depends(require_role(ROLE_MEMBER)),
) -> list[dict[str, Any]]:
    if server_id == BUILTIN_WAI_ID:
        return [
            {"name": t["name"], "description": t["description"], "blocked": False}
            for t in BUILTIN_WAI_TOOLS
        ]
    h = get_handler()
    rows = await h.db.fetchall(
        """SELECT t.name, t.description,
                  CASE WHEN b.tool_name IS NOT NULL THEN 1 ELSE 0 END AS blocked
           FROM mcp_server_tools t
           LEFT JOIN mcp_tool_blocklist b
             ON b.server_id = t.server_id AND b.tool_name = t.name
           WHERE t.server_id = ?
           ORDER BY t.name""",
        (server_id,),
    )
    return [
        {
            "name": r["name"],
            "description": r.get("description") or "",
            "blocked": bool(r.get("blocked")),
        }
        for r in rows
    ]
