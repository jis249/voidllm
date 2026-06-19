"""Team CRUD handlers."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, Query, Response, status
from pydantic import BaseModel

from wai.api.admin.common import (
    KeyInfo,
    ROLE_MEMBER,
    ROLE_ORG_ADMIN,
    ROLE_SYSTEM_ADMIN,
    ROLE_TEAM_ADMIN,
    SLUG_RE,
    bad_request,
    conflict,
    forbidden,
    has_role,
    internal_error,
    limit_reached,
    not_found,
    parse_pagination,
)
from wai.api.admin.handler import get_handler, require_role
from wai.api.admin import repository as repo

router = APIRouter()


class CreateTeamRequest(BaseModel):
    name: str
    slug: str
    daily_token_limit: int = 0
    monthly_token_limit: int = 0
    requests_per_minute: int = 0
    requests_per_day: int = 0


class UpdateTeamRequest(BaseModel):
    name: str | None = None
    slug: str | None = None
    daily_token_limit: int | None = None
    monthly_token_limit: int | None = None
    requests_per_minute: int | None = None
    requests_per_day: int | None = None


class TeamResponse(BaseModel):
    id: str
    org_id: str
    name: str
    slug: str
    daily_token_limit: int
    monthly_token_limit: int
    requests_per_minute: int
    requests_per_day: int
    member_count: int
    key_count: int
    created_at: str
    updated_at: str
    deleted_at: str | None = None


class PaginatedTeamsResponse(BaseModel):
    data: list[TeamResponse]
    has_more: bool
    next_cursor: str | None = None


def _require_org_admin(key_info: KeyInfo, org_id: str) -> None:
    if not has_role(key_info.role, ROLE_SYSTEM_ADMIN) and not (
        has_role(key_info.role, ROLE_ORG_ADMIN) and key_info.org_id == org_id
    ):
        raise forbidden()


def _require_org_access(key_info: KeyInfo, org_id: str) -> None:
    if not has_role(key_info.role, ROLE_SYSTEM_ADMIN) and key_info.org_id != org_id:
        raise forbidden()


def _team_resp(t: dict[str, Any]) -> TeamResponse:
    return TeamResponse(
        id=t["id"],
        org_id=t["org_id"],
        name=t["name"],
        slug=t["slug"],
        daily_token_limit=int(t.get("daily_token_limit") or 0),
        monthly_token_limit=int(t.get("monthly_token_limit") or 0),
        requests_per_minute=int(t.get("requests_per_minute") or 0),
        requests_per_day=int(t.get("requests_per_day") or 0),
        member_count=int(t.get("member_count") or 0),
        key_count=int(t.get("key_count") or 0),
        created_at=t["created_at"],
        updated_at=t["updated_at"],
        deleted_at=t.get("deleted_at"),
    )


async def _require_team_access(h, key_info: KeyInfo, org_id: str, team_id: str) -> dict[str, Any]:
    _require_org_access(key_info, org_id)
    team = await repo.get_team(h.db, team_id)
    if not team or team["org_id"] != org_id:
        raise not_found("team not found")
    if not has_role(key_info.role, ROLE_ORG_ADMIN):
        if not await repo.is_team_member(h.db, key_info.user_id, team_id):
            raise not_found("team not found")
    return team


@router.post("/orgs/{org_id}/teams", response_model=TeamResponse, status_code=status.HTTP_201_CREATED)
async def create_team(
    org_id: str,
    body: CreateTeamRequest,
    key_info: KeyInfo = Depends(require_role(ROLE_ORG_ADMIN)),
) -> TeamResponse:
    h = get_handler()
    _require_org_admin(key_info, org_id)
    if not body.name:
        raise bad_request("name is required")
    if not body.slug or not SLUG_RE.match(body.slug):
        raise bad_request("slug must be lowercase alphanumeric with hyphens, 2-63 characters")
    lic = h.license.load()
    if lic.max_teams > 0:
        count = await repo.count_teams(h.db, org_id)
        if count >= lic.max_teams:
            raise limit_reached("team limit reached for your plan")
    try:
        team = await repo.create_team(h.db, org_id, body.model_dump())
    except repo.ConflictError:
        raise conflict("team slug already exists in this organization")
    except Exception:
        raise internal_error("failed to create team")
    return _team_resp({**team, "member_count": 0, "key_count": 0})


@router.get("/orgs/{org_id}/teams", response_model=PaginatedTeamsResponse)
async def list_teams(
    org_id: str,
    limit: int | None = Query(20),
    cursor: str | None = Query(None),
    include_deleted: bool = Query(False),
    key_info: KeyInfo = Depends(require_role(ROLE_MEMBER)),
) -> PaginatedTeamsResponse:
    h = get_handler()
    _require_org_access(key_info, org_id)
    if not has_role(key_info.role, ROLE_ORG_ADMIN):
        teams = await repo.list_user_teams(h.db, org_id, key_info.user_id)
        return PaginatedTeamsResponse(data=[_team_resp(t) for t in teams], has_more=False)
    p = parse_pagination(limit, cursor)
    inc_del = include_deleted and has_role(key_info.role, ROLE_SYSTEM_ADMIN)
    teams = await repo.list_teams_with_counts(h.db, org_id, p.cursor, p.limit + 1, inc_del)
    has_more = len(teams) > p.limit
    if has_more:
        teams = teams[: p.limit]
    return PaginatedTeamsResponse(
        data=[_team_resp(t) for t in teams],
        has_more=has_more,
        next_cursor=teams[-1]["id"] if has_more and teams else None,
    )


@router.get("/orgs/{org_id}/teams/{team_id}", response_model=TeamResponse)
async def get_team(
    org_id: str,
    team_id: str,
    key_info: KeyInfo = Depends(require_role(ROLE_MEMBER)),
) -> TeamResponse:
    h = get_handler()
    _require_org_access(key_info, org_id)
    team = await repo.get_team_with_counts(h.db, team_id)
    if not team or team["org_id"] != org_id:
        raise not_found("team not found")
    if not has_role(key_info.role, ROLE_ORG_ADMIN):
        if not await repo.is_team_member(h.db, key_info.user_id, team_id):
            raise not_found("team not found")
    return _team_resp(team)


@router.patch("/orgs/{org_id}/teams/{team_id}", response_model=TeamResponse)
async def update_team(
    org_id: str,
    team_id: str,
    body: UpdateTeamRequest,
    key_info: KeyInfo = Depends(require_role(ROLE_TEAM_ADMIN)),
) -> TeamResponse:
    h = get_handler()
    existing = await _require_team_access(h, key_info, org_id, team_id)
    if body.slug is not None and not SLUG_RE.match(body.slug):
        raise bad_request("slug must be lowercase alphanumeric with hyphens, 2-63 characters")
    fields = {k: v for k, v in body.model_dump(exclude_unset=True).items()}
    try:
        await repo.update_team(h.db, existing["id"], fields)
    except repo.NotFoundError:
        raise not_found("team not found")
    except repo.ConflictError:
        raise conflict("team slug already exists in this organization")
    except Exception:
        raise internal_error("failed to update team")
    team = await repo.get_team_with_counts(h.db, existing["id"])
    assert team
    return _team_resp(team)


@router.delete("/orgs/{org_id}/teams/{team_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_team(
    org_id: str,
    team_id: str,
    key_info: KeyInfo = Depends(require_role(ROLE_ORG_ADMIN)),
) -> Response:
    h = get_handler()
    team = await _require_team_access(h, key_info, org_id, team_id)
    try:
        await repo.delete_team(h.db, team["id"])
    except repo.NotFoundError:
        raise not_found("team not found")
    except Exception:
        raise internal_error("failed to delete team")
    return Response(status_code=status.HTTP_204_NO_CONTENT)
