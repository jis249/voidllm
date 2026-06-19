"""Organization CRUD handlers."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, Query, Response, status
from pydantic import BaseModel

from wai.api.admin.common import (
    KeyInfo,
    ROLE_ORG_ADMIN,
    ROLE_SYSTEM_ADMIN,
    SLUG_RE,
    bad_request,
    conflict,
    forbidden,
    has_role,
    internal_error,
    limit_reached,
    not_found,
    parse_pagination,
    unauthorized,
)
from wai.api.admin.handler import auth_middleware, get_handler, require_role
from wai.api.admin import repository as repo

router = APIRouter()


class CreateOrgRequest(BaseModel):
    name: str
    slug: str
    timezone: str | None = None
    daily_token_limit: int = 0
    monthly_token_limit: int = 0
    requests_per_minute: int = 0
    requests_per_day: int = 0


class UpdateOrgRequest(BaseModel):
    name: str | None = None
    slug: str | None = None
    timezone: str | None = None
    daily_token_limit: int | None = None
    monthly_token_limit: int | None = None
    requests_per_minute: int | None = None
    requests_per_day: int | None = None


class OrgResponse(BaseModel):
    id: str
    name: str
    slug: str
    timezone: str | None = None
    daily_token_limit: int
    monthly_token_limit: int
    requests_per_minute: int
    requests_per_day: int
    member_count: int
    team_count: int
    created_at: str
    updated_at: str
    deleted_at: str | None = None


class PaginatedOrgsResponse(BaseModel):
    data: list[OrgResponse]
    has_more: bool
    next_cursor: str | None = None


def _org_resp(o: dict[str, Any]) -> OrgResponse:
    return OrgResponse(
        id=o["id"],
        name=o["name"],
        slug=o["slug"],
        timezone=o.get("timezone"),
        daily_token_limit=int(o.get("daily_token_limit") or 0),
        monthly_token_limit=int(o.get("monthly_token_limit") or 0),
        requests_per_minute=int(o.get("requests_per_minute") or 0),
        requests_per_day=int(o.get("requests_per_day") or 0),
        member_count=int(o.get("member_count") or 0),
        team_count=int(o.get("team_count") or 0),
        created_at=o["created_at"],
        updated_at=o["updated_at"],
        deleted_at=o.get("deleted_at"),
    )


@router.post("/orgs", response_model=OrgResponse, status_code=status.HTTP_201_CREATED)
async def create_org(
    body: CreateOrgRequest,
    _: KeyInfo = Depends(require_role(ROLE_SYSTEM_ADMIN)),
) -> OrgResponse:
    h = get_handler()
    if not body.name:
        raise bad_request("name is required")
    if not body.slug:
        raise bad_request("slug is required")
    if not SLUG_RE.match(body.slug):
        raise bad_request("slug must be lowercase alphanumeric with hyphens, 2-63 characters")
    lic = h.license.load()
    if lic.max_orgs > 0:
        count = await repo.count_orgs(h.db)
        if count >= lic.max_orgs:
            raise limit_reached("organization limit reached for your plan")
    try:
        org = await repo.create_org(
            h.db,
            name=body.name,
            slug=body.slug,
            timezone=body.timezone,
            daily_token_limit=body.daily_token_limit,
            monthly_token_limit=body.monthly_token_limit,
            requests_per_minute=body.requests_per_minute,
            requests_per_day=body.requests_per_day,
        )
    except repo.ConflictError:
        raise conflict("organization slug already exists")
    except Exception:
        raise internal_error("failed to create organization")
    return _org_resp(org)


@router.get("/orgs", response_model=PaginatedOrgsResponse)
async def list_orgs(
    limit: int | None = Query(20),
    cursor: str | None = Query(None),
    include_deleted: bool = Query(False),
    key_info: KeyInfo = Depends(require_role(ROLE_ORG_ADMIN)),
) -> PaginatedOrgsResponse:
    h = get_handler()
    p = parse_pagination(limit, cursor)
    inc_del = include_deleted and has_role(key_info.role, ROLE_SYSTEM_ADMIN)
    if not has_role(key_info.role, ROLE_SYSTEM_ADMIN):
        org = await repo.get_org_with_counts(h.db, key_info.org_id)
        if not org:
            return PaginatedOrgsResponse(data=[], has_more=False)
        return PaginatedOrgsResponse(data=[_org_resp(org)], has_more=False)
    orgs = await repo.list_orgs_with_counts(h.db, p.cursor, p.limit + 1, inc_del)
    has_more = len(orgs) > p.limit
    if has_more:
        orgs = orgs[: p.limit]
    resp = PaginatedOrgsResponse(
        data=[_org_resp(o) for o in orgs],
        has_more=has_more,
        next_cursor=orgs[-1]["id"] if has_more and orgs else None,
    )
    return resp


@router.get("/orgs/{org_id}", response_model=OrgResponse)
async def get_org(
    org_id: str,
    key_info: KeyInfo = Depends(require_role(ROLE_ORG_ADMIN)),
) -> OrgResponse:
    h = get_handler()
    if not has_role(key_info.role, ROLE_SYSTEM_ADMIN) and key_info.org_id != org_id:
        raise forbidden()
    org = await repo.get_org_with_counts(h.db, org_id)
    if not org:
        raise not_found("organization not found")
    return _org_resp(org)


@router.patch("/orgs/{org_id}", response_model=OrgResponse)
async def update_org(
    org_id: str,
    body: UpdateOrgRequest,
    key_info: KeyInfo = Depends(require_role(ROLE_ORG_ADMIN)),
) -> OrgResponse:
    h = get_handler()
    is_sys = has_role(key_info.role, ROLE_SYSTEM_ADMIN)
    is_org_admin = has_role(key_info.role, ROLE_ORG_ADMIN) and key_info.org_id == org_id
    if not is_sys and not is_org_admin:
        raise forbidden()
    if body.slug is not None and not SLUG_RE.match(body.slug):
        raise bad_request("slug must be lowercase alphanumeric with hyphens, 2-63 characters")
    fields = {k: v for k, v in body.model_dump(exclude_unset=True).items() if v is not None or k == "timezone"}
    try:
        await repo.update_org(h.db, org_id, fields)
    except repo.NotFoundError:
        raise not_found("organization not found")
    except repo.ConflictError:
        raise conflict("organization slug already exists")
    except Exception:
        raise internal_error("failed to update organization")
    org = await repo.get_org_with_counts(h.db, org_id)
    assert org
    return _org_resp(org)


@router.delete("/orgs/{org_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_org(
    org_id: str,
    key_info: KeyInfo = Depends(require_role(ROLE_SYSTEM_ADMIN)),
) -> Response:
    h = get_handler()
    try:
        await repo.delete_org(h.db, org_id)
    except repo.NotFoundError:
        raise not_found("organization not found")
    except Exception:
        raise internal_error("failed to delete organization")
    return Response(status_code=status.HTTP_204_NO_CONTENT)
