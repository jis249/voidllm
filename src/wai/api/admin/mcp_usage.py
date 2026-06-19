"""MCP usage query handlers."""

from __future__ import annotations

from datetime import datetime, timedelta

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, Field

from wai.api.admin.common import (
    KeyInfo,
    ROLE_MEMBER,
    ROLE_ORG_ADMIN,
    ROLE_SYSTEM_ADMIN,
    bad_request,
    forbidden,
    has_role,
)
from wai.api.admin.handler import auth_middleware, get_handler, require_role

router = APIRouter()

MAX_RANGE_DAYS = 90


class MCPUsageDataPoint(BaseModel):
    group_key: str = ""
    total_calls: int = 0
    total_duration_ms: int = 0
    error_count: int = 0


class MCPUsageResponse(BaseModel):
    org_id: str = ""
    from_: str = Field(alias="from")
    to: str
    group_by: str = ""
    data: list[MCPUsageDataPoint] = Field(default_factory=list)

    model_config = {"populate_by_name": True}


def _parse_range(from_str: str, to_str: str) -> tuple[str, str]:
    if not from_str or not to_str:
        raise bad_request("from and to are required")
    try:
        from_dt = datetime.fromisoformat(from_str.replace("Z", "+00:00"))
        to_dt = datetime.fromisoformat(to_str.replace("Z", "+00:00"))
    except ValueError:
        raise bad_request("invalid timestamp format")
    if from_dt >= to_dt:
        raise bad_request("from must be before to")
    if to_dt - from_dt > timedelta(days=MAX_RANGE_DAYS):
        raise bad_request("time range must not exceed 90 days")
    return from_str, to_str


async def _query_mcp_usage(h, org_id: str, team_id: str, user_id: str, from_s: str, to_s: str, group_by: str):
    group_col = {
        "server": "server_alias", "tool": "tool_name", "team": "team_id",
        "key": "key_id", "user": "user_id", "day": "date(timestamp)",
    }.get(group_by, "server_alias")
    clauses = ["timestamp >= ?", "timestamp < ?"]
    params: list = [from_s, to_s]
    if org_id:
        clauses.append("org_id = ?")
        params.append(org_id)
    if team_id:
        clauses.append("team_id = ?")
        params.append(team_id)
    if user_id:
        clauses.append("user_id = ?")
        params.append(user_id)
    where = " AND ".join(clauses)
    rows = await h.db.fetchall(
        f"""SELECT {group_col} AS group_key,
                   COUNT(*) AS total_calls,
                   COALESCE(SUM(duration_ms), 0) AS total_duration_ms,
                   COALESCE(SUM(CASE WHEN status != 'success' THEN 1 ELSE 0 END), 0) AS error_count
            FROM mcp_usage_events WHERE {where}
            GROUP BY {group_col} ORDER BY group_key""",
        tuple(params),
    )
    return [dict(r) for r in rows]


@router.get("/mcp-usage/me", response_model=MCPUsageResponse)
async def my_mcp_usage(
    from_: str = Query(alias="from"),
    to: str = Query(),
    group_by: str = Query(""),
    key_info: KeyInfo = Depends(auth_middleware),
) -> MCPUsageResponse:
    h = get_handler()
    from_s, to_s = _parse_range(from_, to)
    rows = await _query_mcp_usage(
        h, key_info.org_id, key_info.team_id, key_info.user_id, from_s, to_s, group_by
    )
    return MCPUsageResponse(
        org_id=key_info.org_id,
        **{"from": from_s},
        to=to_s,
        group_by=group_by,
        data=[MCPUsageDataPoint(**r) for r in rows],
    )


@router.get("/mcp-usage", response_model=MCPUsageResponse)
async def get_system_mcp_usage(
    from_: str = Query(alias="from"),
    to: str = Query(),
    group_by: str = Query(""),
    org_id: str = Query(""),
    _: KeyInfo = Depends(require_role(ROLE_SYSTEM_ADMIN)),
) -> MCPUsageResponse:
    h = get_handler()
    from_s, to_s = _parse_range(from_, to)
    rows = await _query_mcp_usage(h, org_id, "", "", from_s, to_s, group_by)
    return MCPUsageResponse(
        org_id=org_id,
        **{"from": from_s},
        to=to_s,
        group_by=group_by,
        data=[MCPUsageDataPoint(**r) for r in rows],
    )


@router.get("/orgs/{org_id}/mcp-usage", response_model=MCPUsageResponse)
async def get_org_mcp_usage(
    org_id: str,
    from_: str = Query(alias="from"),
    to: str = Query(),
    group_by: str = Query(""),
    key_info: KeyInfo = Depends(require_role(ROLE_ORG_ADMIN)),
) -> MCPUsageResponse:
    h = get_handler()
    if not has_role(key_info.role, ROLE_SYSTEM_ADMIN) and key_info.org_id != org_id:
        raise forbidden()
    from_s, to_s = _parse_range(from_, to)
    rows = await _query_mcp_usage(h, org_id, "", "", from_s, to_s, group_by)
    return MCPUsageResponse(
        org_id=org_id,
        **{"from": from_s},
        to=to_s,
        group_by=group_by,
        data=[MCPUsageDataPoint(**r) for r in rows],
    )
