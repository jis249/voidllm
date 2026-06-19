"""Audit log handlers."""

from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, Field

from wai.api.admin.common import (
    KeyInfo,
    ROLE_ORG_ADMIN,
    ROLE_SYSTEM_ADMIN,
    bad_request,
    forbidden,
    has_role,
    internal_error,
    parse_pagination,
    unauthorized,
)
from wai.api.admin.handler import auth_middleware, get_handler
from wai.api.admin import repository as repo

router = APIRouter()


class AuditEventResponse(BaseModel):
    id: str
    timestamp: str
    org_id: str
    actor_id: str
    actor_type: str
    actor_key_id: str
    action: str
    resource_type: str
    resource_id: str
    description: str
    ip_address: str
    status_code: int
    request_id: str = ""


class AuditListResponse(BaseModel):
    data: list[AuditEventResponse]
    has_more: bool
    cursor: str | None = None


@router.get("/audit-logs", response_model=AuditListResponse)
async def list_audit_logs(
    org_id: str = Query(""),
    actor_id: str = Query(""),
    resource_type: str = Query(""),
    action: str = Query(""),
    from_: str = Query("", alias="from"),
    to: str = Query(""),
    limit: int = Query(50),
    cursor: str = Query(""),
    key_info: KeyInfo = Depends(auth_middleware),
) -> AuditListResponse:
    h = get_handler()
    if key_info is None:
        raise unauthorized()
    filter_org = org_id
    if has_role(key_info.role, ROLE_SYSTEM_ADMIN):
        pass
    elif has_role(key_info.role, ROLE_ORG_ADMIN):
        if not key_info.org_id:
            raise forbidden("org context required")
        filter_org = key_info.org_id
    else:
        raise forbidden()
    if from_:
        try:
            datetime.fromisoformat(from_.replace("Z", "+00:00"))
        except ValueError:
            raise bad_request("invalid 'from' timestamp; expected RFC3339 format")
    if to:
        try:
            datetime.fromisoformat(to.replace("Z", "+00:00"))
        except ValueError:
            raise bad_request("invalid 'to' timestamp; expected RFC3339 format")
    if limit < 1 or limit > 200:
        limit = 50
    if cursor:
        parse_pagination(limit, cursor)
    events, has_more = await repo.list_audit_logs(
        h.db,
        {
            "org_id": filter_org,
            "actor_id": actor_id,
            "resource_type": resource_type,
            "action": action,
            "from": from_,
            "to": to,
            "cursor": cursor,
        },
        limit,
    )
    return AuditListResponse(
        data=[
            AuditEventResponse(
                id=e["id"],
                timestamp=e["timestamp"],
                org_id=e.get("org_id") or "",
                actor_id=e.get("actor_id") or "",
                actor_type=e.get("actor_type") or "",
                actor_key_id=e.get("actor_key_id") or "",
                action=e.get("action") or "",
                resource_type=e.get("resource_type") or "",
                resource_id=e.get("resource_id") or "",
                description=e.get("description") or "",
                ip_address=e.get("ip_address") or "",
                status_code=int(e.get("status_code") or 0),
                request_id=e.get("request_id") or "",
            )
            for e in events
        ],
        has_more=has_more,
        cursor=events[-1]["id"] if has_more and events else None,
    )
