"""Service account handlers."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, Query, Response, status
from pydantic import BaseModel

from wai.api.admin.common import (
    KeyInfo,
    ROLE_MEMBER,
    ROLE_ORG_ADMIN,
    ROLE_SYSTEM_ADMIN,
    bad_request,
    forbidden,
    has_role,
    internal_error,
    not_found,
    parse_pagination,
)
from wai.api.admin.handler import get_handler, require_role
from wai.api.admin import repository as repo

router = APIRouter()


class CreateServiceAccountRequest(BaseModel):
    name: str
    team_id: str | None = None


class UpdateServiceAccountRequest(BaseModel):
    name: str | None = None


class ServiceAccountResponse(BaseModel):
    id: str
    name: str
    org_id: str
    team_id: str | None = None
    created_by: str
    key_count: int
    created_at: str
    updated_at: str
    deleted_at: str | None = None


class PaginatedServiceAccountsResponse(BaseModel):
    data: list[ServiceAccountResponse]
    has_more: bool
    next_cursor: str | None = None


def _require_org_access(key_info: KeyInfo, org_id: str) -> None:
    if not has_role(key_info.role, ROLE_SYSTEM_ADMIN) and key_info.org_id != org_id:
        raise forbidden()


def _sa_resp(sa: dict[str, Any]) -> ServiceAccountResponse:
    return ServiceAccountResponse(
        id=sa["id"],
        name=sa["name"],
        org_id=sa["org_id"],
        team_id=sa.get("team_id"),
        created_by=sa["created_by"],
        key_count=int(sa.get("key_count") or 0),
        created_at=sa["created_at"],
        updated_at=sa["updated_at"],
        deleted_at=sa.get("deleted_at"),
    )


@router.post("/orgs/{org_id}/service-accounts", response_model=ServiceAccountResponse, status_code=status.HTTP_201_CREATED)
async def create_service_account(
    org_id: str,
    body: CreateServiceAccountRequest,
    key_info: KeyInfo = Depends(require_role(ROLE_MEMBER)),
) -> ServiceAccountResponse:
    h = get_handler()
    _require_org_access(key_info, org_id)
    if not key_info.user_id:
        raise bad_request("service accounts can only be created by user keys")
    if not body.name:
        raise bad_request("name is required")
    if body.team_id:
        team = await repo.get_team(h.db, body.team_id)
        if not team or team["org_id"] != org_id:
            raise not_found("team not found")
    try:
        sa = await repo.create_service_account(h.db, body.name, org_id, body.team_id, key_info.user_id)
    except Exception:
        raise internal_error("failed to create service account")
    return _sa_resp({**sa, "key_count": 0})


@router.get("/orgs/{org_id}/service-accounts", response_model=PaginatedServiceAccountsResponse)
async def list_service_accounts(
    org_id: str,
    limit: int | None = Query(20),
    cursor: str | None = Query(None),
    include_deleted: bool = Query(False),
    key_info: KeyInfo = Depends(require_role(ROLE_MEMBER)),
) -> PaginatedServiceAccountsResponse:
    h = get_handler()
    _require_org_access(key_info, org_id)
    p = parse_pagination(limit, cursor)
    inc_del = include_deleted and has_role(key_info.role, ROLE_SYSTEM_ADMIN)
    filter_created_by = "" if has_role(key_info.role, ROLE_ORG_ADMIN) else key_info.user_id
    accounts = await repo.list_service_accounts_with_counts(
        h.db, org_id, filter_created_by, p.cursor, p.limit + 1, inc_del
    )
    has_more = len(accounts) > p.limit
    if has_more:
        accounts = accounts[: p.limit]
    return PaginatedServiceAccountsResponse(
        data=[_sa_resp(a) for a in accounts],
        has_more=has_more,
        next_cursor=accounts[-1]["id"] if has_more and accounts else None,
    )


@router.get("/orgs/{org_id}/service-accounts/{sa_id}", response_model=ServiceAccountResponse)
async def get_service_account(
    org_id: str,
    sa_id: str,
    key_info: KeyInfo = Depends(require_role(ROLE_MEMBER)),
) -> ServiceAccountResponse:
    h = get_handler()
    _require_org_access(key_info, org_id)
    sa = await repo.get_service_account_with_counts(h.db, sa_id)
    if not sa or sa["org_id"] != org_id:
        raise not_found("service account not found")
    if not has_role(key_info.role, ROLE_ORG_ADMIN) and sa["created_by"] != key_info.user_id:
        raise not_found("service account not found")
    return _sa_resp(sa)


@router.patch("/orgs/{org_id}/service-accounts/{sa_id}", response_model=ServiceAccountResponse)
async def update_service_account(
    org_id: str,
    sa_id: str,
    body: UpdateServiceAccountRequest,
    key_info: KeyInfo = Depends(require_role(ROLE_MEMBER)),
) -> ServiceAccountResponse:
    h = get_handler()
    _require_org_access(key_info, org_id)
    existing = await repo.get_service_account(h.db, sa_id)
    if not existing or existing["org_id"] != org_id:
        raise not_found("service account not found")
    if not has_role(key_info.role, ROLE_ORG_ADMIN) and existing["created_by"] != key_info.user_id:
        raise not_found("service account not found")
    try:
        sa = await repo.update_service_account(h.db, sa_id, body.name)
    except repo.NotFoundError:
        raise not_found("service account not found")
    except Exception:
        raise internal_error("failed to update service account")
    return _sa_resp(sa)


@router.delete("/orgs/{org_id}/service-accounts/{sa_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_service_account(
    org_id: str,
    sa_id: str,
    key_info: KeyInfo = Depends(require_role(ROLE_MEMBER)),
) -> Response:
    h = get_handler()
    _require_org_access(key_info, org_id)
    sa = await repo.get_service_account(h.db, sa_id)
    if not sa or sa["org_id"] != org_id:
        raise not_found("service account not found")
    if not has_role(key_info.role, ROLE_ORG_ADMIN) and sa["created_by"] != key_info.user_id:
        raise not_found("service account not found")
    try:
        await repo.delete_service_account(h.db, sa_id)
    except repo.NotFoundError:
        raise not_found("service account not found")
    except Exception:
        raise internal_error("failed to delete service account")
    return Response(status_code=status.HTTP_204_NO_CONTENT)
