"""Usage query handlers."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

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
    internal_error,
)
from wai.api.admin.handler import auth_middleware, get_handler, require_role
from wai.api.admin import repository as repo

router = APIRouter()

MAX_USAGE_RANGE_DAYS = 90
VALID_GROUP_BY_ORG = {"", "model", "team", "key", "user", "day", "hour"}
VALID_GROUP_BY_SYS = VALID_GROUP_BY_ORG | {"org"}


class UsageDataPoint(BaseModel):
    group_key: str = ""
    group_label: str = ""
    total_requests: int = 0
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0
    cost_estimate: float = 0
    avg_duration_ms: float = 0


class UsageResponse(BaseModel):
    org_id: str = ""
    from_: str = Field(alias="from")
    to: str
    group_by: str = ""
    data: list[UsageDataPoint] = Field(default_factory=list)

    model_config = {"populate_by_name": True}


def _parse_range(from_str: str, to_str: str) -> tuple[datetime, datetime]:
    if not from_str:
        raise bad_request("from is required")
    if not to_str:
        raise bad_request("to is required")
    try:
        from_dt = datetime.fromisoformat(from_str.replace("Z", "+00:00"))
        to_dt = datetime.fromisoformat(to_str.replace("Z", "+00:00"))
    except ValueError:
        raise bad_request("from and to must be valid RFC3339 timestamps")
    if from_dt >= to_dt:
        raise bad_request("from must be before to")
    if to_dt - from_dt > timedelta(days=MAX_USAGE_RANGE_DAYS):
        raise bad_request("time range must not exceed 90 days")
    return from_dt, to_dt


def _points(aggs: list[dict]) -> list[UsageDataPoint]:
    return [
        UsageDataPoint(
            group_key=a.get("group_key") or "",
            total_requests=int(a.get("total_requests") or 0),
            prompt_tokens=int(a.get("prompt_tokens") or 0),
            completion_tokens=int(a.get("completion_tokens") or 0),
            total_tokens=int(a.get("total_tokens") or 0),
            cost_estimate=float(a.get("cost_estimate") or 0),
            avg_duration_ms=float(a.get("avg_duration_ms") or 0),
        )
        for a in aggs
    ]


@router.get("/usage/me", response_model=UsageResponse)
async def my_usage(
    from_: str = Query(alias="from"),
    to: str = Query(),
    group_by: str = Query(""),
    key_info: KeyInfo = Depends(auth_middleware),
) -> UsageResponse:
    h = get_handler()
    from_dt, to_dt = _parse_range(from_, to)
    if group_by not in VALID_GROUP_BY_ORG:
        raise bad_request("group_by must be one of: model, team, key, user, day, hour")
    aggs = await repo.get_scoped_usage_aggregates(
        h.db, key_info.org_id, key_info.team_id, key_info.user_id,
        from_dt.isoformat(), to_dt.isoformat(), group_by,
    )
    return UsageResponse(
        org_id=key_info.org_id,
        **{"from": from_dt.isoformat()},
        to=to_dt.isoformat(),
        group_by=group_by,
        data=_points(aggs),
    )


@router.get("/usage", response_model=UsageResponse)
async def system_admin_usage(
    from_: str = Query(alias="from"),
    to: str = Query(),
    group_by: str = Query(""),
    org_id: str = Query(""),
    _: KeyInfo = Depends(require_role(ROLE_SYSTEM_ADMIN)),
) -> UsageResponse:
    h = get_handler()
    from_dt, to_dt = _parse_range(from_, to)
    if group_by not in VALID_GROUP_BY_SYS:
        raise bad_request("group_by must be one of: org, model, team, key, user, day, hour")
    oid = org_id or ""
    aggs = await repo.get_scoped_usage_aggregates(
        h.db, oid, "", "", from_dt.isoformat(), to_dt.isoformat(), group_by,
    )
    return UsageResponse(
        org_id=oid,
        **{"from": from_dt.isoformat()},
        to=to_dt.isoformat(),
        group_by=group_by,
        data=_points(aggs),
    )


@router.get("/orgs/{org_id}/usage", response_model=UsageResponse)
async def get_org_usage(
    org_id: str,
    from_: str = Query(alias="from"),
    to: str = Query(),
    group_by: str = Query(""),
    key_info: KeyInfo = Depends(require_role(ROLE_ORG_ADMIN)),
) -> UsageResponse:
    h = get_handler()
    if not has_role(key_info.role, ROLE_SYSTEM_ADMIN) and key_info.org_id != org_id:
        raise forbidden()
    from_dt, to_dt = _parse_range(from_, to)
    if group_by not in VALID_GROUP_BY_ORG:
        raise bad_request("group_by must be one of: model, team, key, user, day, hour")
    aggs = await repo.get_scoped_usage_aggregates(
        h.db, org_id, "", "", from_dt.isoformat(), to_dt.isoformat(), group_by,
    )
    return UsageResponse(
        org_id=org_id,
        **{"from": from_dt.isoformat()},
        to=to_dt.isoformat(),
        group_by=group_by,
        data=_points(aggs),
    )
