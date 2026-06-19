"""Team membership handlers."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, Query, Response, status
from pydantic import BaseModel

from wai.api.admin.common import (
    KeyInfo,
    ROLE_MEMBER,
    ROLE_TEAM_ADMIN,
    bad_request,
    conflict,
    internal_error,
    not_found,
    parse_pagination,
)
from wai.api.admin.handler import get_handler, require_role
from wai.api.admin.teams import _require_team_access
from wai.api.admin import repository as repo

router = APIRouter()

VALID_ROLES = {ROLE_TEAM_ADMIN, ROLE_MEMBER}


class CreateTeamMembershipRequest(BaseModel):
    user_id: str
    role: str


class UpdateTeamMembershipRequest(BaseModel):
    role: str | None = None


class TeamMembershipResponse(BaseModel):
    id: str
    team_id: str
    user_id: str
    role: str
    created_at: str


class PaginatedTeamMembershipsResponse(BaseModel):
    data: list[TeamMembershipResponse]
    has_more: bool
    next_cursor: str | None = None


def _mem_resp(m: dict[str, Any]) -> TeamMembershipResponse:
    return TeamMembershipResponse(
        id=m["id"], team_id=m["team_id"], user_id=m["user_id"], role=m["role"], created_at=m["created_at"]
    )


@router.post(
    "/orgs/{org_id}/teams/{team_id}/members",
    response_model=TeamMembershipResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_team_membership(
    org_id: str,
    team_id: str,
    body: CreateTeamMembershipRequest,
    key_info: KeyInfo = Depends(require_role(ROLE_TEAM_ADMIN)),
) -> TeamMembershipResponse:
    h = get_handler()
    team = await _require_team_access(h, key_info, org_id, team_id)
    if not body.user_id:
        raise bad_request("user_id is required")
    if body.role not in VALID_ROLES:
        raise bad_request('role must be "team_admin" or "member"')
    try:
        m = await repo.create_team_membership(h.db, team["id"], body.user_id, body.role)
    except repo.ConflictError:
        raise conflict("user is already a member of this team")
    except Exception:
        raise internal_error("failed to create team membership")
    return _mem_resp(m)


@router.get("/orgs/{org_id}/teams/{team_id}/members", response_model=PaginatedTeamMembershipsResponse)
async def list_team_memberships(
    org_id: str,
    team_id: str,
    limit: int | None = Query(20),
    cursor: str | None = Query(None),
    key_info: KeyInfo = Depends(require_role(ROLE_TEAM_ADMIN)),
) -> PaginatedTeamMembershipsResponse:
    h = get_handler()
    team = await _require_team_access(h, key_info, org_id, team_id)
    p = parse_pagination(limit, cursor)
    memberships = await repo.list_team_memberships(h.db, team["id"], p.cursor, p.limit + 1)
    has_more = len(memberships) > p.limit
    if has_more:
        memberships = memberships[: p.limit]
    return PaginatedTeamMembershipsResponse(
        data=[_mem_resp(m) for m in memberships],
        has_more=has_more,
        next_cursor=memberships[-1]["id"] if has_more and memberships else None,
    )


@router.patch("/orgs/{org_id}/teams/{team_id}/members/{membership_id}", response_model=TeamMembershipResponse)
async def update_team_membership(
    org_id: str,
    team_id: str,
    membership_id: str,
    body: UpdateTeamMembershipRequest,
    key_info: KeyInfo = Depends(require_role(ROLE_TEAM_ADMIN)),
) -> TeamMembershipResponse:
    h = get_handler()
    team = await _require_team_access(h, key_info, org_id, team_id)
    existing = await repo.get_team_membership(h.db, membership_id)
    if not existing or existing["team_id"] != team["id"]:
        raise not_found("team membership not found")
    if body.role is not None and body.role not in VALID_ROLES:
        raise bad_request('role must be "team_admin" or "member"')
    try:
        m = await repo.update_team_membership(h.db, membership_id, body.role)
    except repo.NotFoundError:
        raise not_found("team membership not found")
    except Exception:
        raise internal_error("failed to update team membership")
    return _mem_resp(m)


@router.delete("/orgs/{org_id}/teams/{team_id}/members/{membership_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_team_membership(
    org_id: str,
    team_id: str,
    membership_id: str,
    key_info: KeyInfo = Depends(require_role(ROLE_TEAM_ADMIN)),
) -> Response:
    h = get_handler()
    team = await _require_team_access(h, key_info, org_id, team_id)
    existing = await repo.get_team_membership(h.db, membership_id)
    if not existing or existing["team_id"] != team["id"]:
        raise not_found("team membership not found")
    try:
        await repo.delete_team_membership(h.db, membership_id)
    except repo.NotFoundError:
        raise not_found("team membership not found")
    except Exception:
        raise internal_error("failed to delete team membership")
    return Response(status_code=status.HTTP_204_NO_CONTENT)
