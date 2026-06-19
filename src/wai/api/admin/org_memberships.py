"""Org membership handlers."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, Query, Response, status
from pydantic import BaseModel

from wai.api.admin.common import (
    KeyInfo,
    ROLE_ORG_ADMIN,
    ROLE_MEMBER,
    ROLE_SYSTEM_ADMIN,
    bad_request,
    conflict,
    forbidden,
    has_role,
    internal_error,
    not_found,
    parse_pagination,
    unauthorized,
)
from wai.api.admin.handler import auth_middleware, get_handler, require_role
from wai.api.admin import repository as repo

router = APIRouter()

VALID_ROLES = {ROLE_ORG_ADMIN, ROLE_MEMBER}


class CreateOrgMembershipRequest(BaseModel):
    user_id: str
    role: str


class UpdateOrgMembershipRequest(BaseModel):
    role: str | None = None


class OrgMembershipResponse(BaseModel):
    id: str
    org_id: str
    user_id: str
    role: str
    created_at: str


class PaginatedOrgMembershipsResponse(BaseModel):
    data: list[OrgMembershipResponse]
    has_more: bool
    next_cursor: str | None = None


def _require_org_access(key_info: KeyInfo, org_id: str) -> None:
    if not has_role(key_info.role, ROLE_SYSTEM_ADMIN) and key_info.org_id != org_id:
        raise forbidden()


def _mem_resp(m: dict[str, Any]) -> OrgMembershipResponse:
    return OrgMembershipResponse(
        id=m["id"], org_id=m["org_id"], user_id=m["user_id"], role=m["role"], created_at=m["created_at"]
    )


@router.post("/orgs/{org_id}/members", response_model=OrgMembershipResponse, status_code=status.HTTP_201_CREATED)
async def create_org_membership(
    org_id: str,
    body: CreateOrgMembershipRequest,
    key_info: KeyInfo = Depends(require_role(ROLE_ORG_ADMIN)),
) -> OrgMembershipResponse:
    h = get_handler()
    _require_org_access(key_info, org_id)
    if not body.user_id:
        raise bad_request("user_id is required")
    if body.role not in VALID_ROLES:
        raise bad_request('role must be "org_admin" or "member"')
    if not has_role(key_info.role, ROLE_SYSTEM_ADMIN) and body.role == ROLE_ORG_ADMIN:
        raise forbidden("only system admins may assign the org_admin role")
    try:
        m = await repo.create_org_membership(h.db, org_id, body.user_id, body.role)
    except repo.ConflictError:
        raise conflict("user is already a member of this organization")
    except Exception:
        raise internal_error("failed to create org membership")
    return _mem_resp(m)


@router.get("/orgs/{org_id}/members", response_model=PaginatedOrgMembershipsResponse)
async def list_org_memberships(
    org_id: str,
    limit: int | None = Query(20),
    cursor: str | None = Query(None),
    key_info: KeyInfo = Depends(require_role(ROLE_ORG_ADMIN)),
) -> PaginatedOrgMembershipsResponse:
    h = get_handler()
    _require_org_access(key_info, org_id)
    p = parse_pagination(limit, cursor)
    memberships = await repo.list_org_memberships(h.db, org_id, p.cursor, p.limit + 1)
    has_more = len(memberships) > p.limit
    if has_more:
        memberships = memberships[: p.limit]
    return PaginatedOrgMembershipsResponse(
        data=[_mem_resp(m) for m in memberships],
        has_more=has_more,
        next_cursor=memberships[-1]["id"] if has_more and memberships else None,
    )


@router.patch("/orgs/{org_id}/members/{membership_id}", response_model=OrgMembershipResponse)
async def update_org_membership(
    org_id: str,
    membership_id: str,
    body: UpdateOrgMembershipRequest,
    key_info: KeyInfo = Depends(require_role(ROLE_ORG_ADMIN)),
) -> OrgMembershipResponse:
    h = get_handler()
    _require_org_access(key_info, org_id)
    existing = await repo.get_org_membership(h.db, membership_id)
    if not existing or existing["org_id"] != org_id:
        raise not_found("org membership not found")
    if body.role is not None:
        if body.role not in VALID_ROLES:
            raise bad_request('role must be "org_admin" or "member"')
        if not has_role(key_info.role, ROLE_SYSTEM_ADMIN) and body.role == ROLE_ORG_ADMIN:
            raise forbidden("only system admins may assign the org_admin role")
    try:
        m = await repo.update_org_membership(h.db, membership_id, body.role)
    except repo.NotFoundError:
        raise not_found("org membership not found")
    except Exception:
        raise internal_error("failed to update org membership")
    return _mem_resp(m)


@router.delete("/orgs/{org_id}/members/{membership_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_org_membership(
    org_id: str,
    membership_id: str,
    key_info: KeyInfo = Depends(require_role(ROLE_ORG_ADMIN)),
) -> Response:
    h = get_handler()
    _require_org_access(key_info, org_id)
    existing = await repo.get_org_membership(h.db, membership_id)
    if not existing or existing["org_id"] != org_id:
        raise not_found("org membership not found")
    try:
        await repo.delete_org_membership(h.db, membership_id)
    except repo.NotFoundError:
        raise not_found("org membership not found")
    except Exception:
        raise internal_error("failed to delete org membership")
    return Response(status_code=status.HTTP_204_NO_CONTENT)
