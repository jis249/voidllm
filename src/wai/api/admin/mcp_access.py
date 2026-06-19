"""MCP access control handlers."""

from __future__ import annotations

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field

from wai.api.admin.common import (
    KeyInfo,
    ROLE_ORG_ADMIN,
    ROLE_SYSTEM_ADMIN,
    ROLE_TEAM_ADMIN,
    forbidden,
    has_role,
    not_found,
)
from wai.api.admin.handler import get_handler, require_role
from wai.api.admin import repository as repo

router = APIRouter()


class MCPAccessRequest(BaseModel):
    server_ids: list[str] = Field(default_factory=list)


class MCPAccessResponse(BaseModel):
    server_ids: list[str] = Field(default_factory=list)


def _require_org_access(key_info: KeyInfo, org_id: str) -> None:
    if not has_role(key_info.role, ROLE_SYSTEM_ADMIN) and key_info.org_id != org_id:
        raise forbidden()


async def _get_mcp_access(db, table: str, col: str, entity_id: str) -> list[str]:
    rows = await db.fetchall(
        f"SELECT server_id FROM {table} WHERE {col} = ? ORDER BY server_id", (entity_id,)
    )
    return [r["server_id"] for r in rows]


async def _set_mcp_access(db, table: str, col: str, entity_id: str, server_ids: list[str]) -> None:
    from wai.api.admin.common import new_uuid

    await db.execute(f"DELETE FROM {table} WHERE {col} = ?", (entity_id,))
    for sid in server_ids:
        await db.execute(
            f"INSERT INTO {table} (id, {col}, server_id) VALUES (?, ?, ?)",
            (new_uuid(), entity_id, sid),
        )
    await db.commit()


@router.get("/orgs/{org_id}/mcp-access", response_model=MCPAccessResponse)
async def get_org_mcp_access(
    org_id: str,
    key_info: KeyInfo = Depends(require_role(ROLE_ORG_ADMIN)),
) -> MCPAccessResponse:
    h = get_handler()
    _require_org_access(key_info, org_id)
    ids = await _get_mcp_access(h.db, "org_mcp_access", "org_id", org_id)
    return MCPAccessResponse(server_ids=ids)


@router.put("/orgs/{org_id}/mcp-access", response_model=MCPAccessResponse)
async def set_org_mcp_access(
    org_id: str,
    body: MCPAccessRequest,
    key_info: KeyInfo = Depends(require_role(ROLE_ORG_ADMIN)),
) -> MCPAccessResponse:
    h = get_handler()
    _require_org_access(key_info, org_id)
    await _set_mcp_access(h.db, "org_mcp_access", "org_id", org_id, body.server_ids)
    return MCPAccessResponse(server_ids=body.server_ids)


@router.get("/orgs/{org_id}/teams/{team_id}/mcp-access", response_model=MCPAccessResponse)
async def get_team_mcp_access(
    org_id: str,
    team_id: str,
    key_info: KeyInfo = Depends(require_role(ROLE_TEAM_ADMIN)),
) -> MCPAccessResponse:
    h = get_handler()
    _require_org_access(key_info, org_id)
    team = await repo.get_team(h.db, team_id)
    if not team or team["org_id"] != org_id:
        raise not_found("team not found")
    ids = await _get_mcp_access(h.db, "team_mcp_access", "team_id", team_id)
    return MCPAccessResponse(server_ids=ids)


@router.put("/orgs/{org_id}/teams/{team_id}/mcp-access", response_model=MCPAccessResponse)
async def set_team_mcp_access(
    org_id: str,
    team_id: str,
    body: MCPAccessRequest,
    key_info: KeyInfo = Depends(require_role(ROLE_TEAM_ADMIN)),
) -> MCPAccessResponse:
    h = get_handler()
    _require_org_access(key_info, org_id)
    await _set_mcp_access(h.db, "team_mcp_access", "team_id", team_id, body.server_ids)
    return MCPAccessResponse(server_ids=body.server_ids)


@router.get("/orgs/{org_id}/keys/{key_id}/mcp-access", response_model=MCPAccessResponse)
async def get_key_mcp_access(
    org_id: str,
    key_id: str,
    key_info: KeyInfo = Depends(require_role(ROLE_ORG_ADMIN)),
) -> MCPAccessResponse:
    h = get_handler()
    _require_org_access(key_info, org_id)
    key = await repo.get_api_key(h.db, key_id)
    if not key or key["org_id"] != org_id:
        raise not_found("api key not found")
    ids = await _get_mcp_access(h.db, "key_mcp_access", "key_id", key_id)
    return MCPAccessResponse(server_ids=ids)


@router.put("/orgs/{org_id}/keys/{key_id}/mcp-access", response_model=MCPAccessResponse)
async def set_key_mcp_access(
    org_id: str,
    key_id: str,
    body: MCPAccessRequest,
    key_info: KeyInfo = Depends(require_role(ROLE_ORG_ADMIN)),
) -> MCPAccessResponse:
    h = get_handler()
    _require_org_access(key_info, org_id)
    await _set_mcp_access(h.db, "key_mcp_access", "key_id", key_id, body.server_ids)
    return MCPAccessResponse(server_ids=body.server_ids)


@router.get("/orgs/{org_id}/available-mcp-servers")
async def list_available_global_mcp_servers(
    org_id: str,
    key_info: KeyInfo = Depends(require_role(ROLE_ORG_ADMIN)),
) -> dict:
    h = get_handler()
    _require_org_access(key_info, org_id)
    allowed = await _get_mcp_access(h.db, "org_mcp_access", "org_id", org_id)
    if allowed:
        placeholders = ",".join("?" * len(allowed))
        rows = await h.db.fetchall(
            f"SELECT id, alias, name FROM mcp_servers WHERE id IN ({placeholders}) AND is_active = 1",
            tuple(allowed),
        )
    else:
        rows = await h.db.fetchall(
            "SELECT id, alias, name FROM mcp_servers WHERE org_id IS NULL AND team_id IS NULL AND is_active = 1"
        )
    return {"servers": [dict(r) for r in rows]}
