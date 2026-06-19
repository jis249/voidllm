"""API key handlers."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from fastapi import APIRouter, Depends, Query, Response, status
from pydantic import BaseModel

from wai.api.admin.common import (
    KEY_TYPE_SA,
    KEY_TYPE_SESSION,
    KEY_TYPE_TEAM,
    KEY_TYPE_USER,
    KeyInfo,
    ROLE_MEMBER,
    ROLE_ORG_ADMIN,
    ROLE_SYSTEM_ADMIN,
    ROLE_TEAM_ADMIN,
    bad_request,
    forbidden,
    generate_key,
    has_role,
    hash_key,
    hint_key,
    internal_error,
    not_found,
    parse_pagination,
)
from wai.api.admin.handler import get_handler, require_role
from wai.api.admin import repository as repo

router = APIRouter()

VALID_KEY_TYPES = {KEY_TYPE_USER, KEY_TYPE_TEAM, KEY_TYPE_SA}


class CreateAPIKeyRequest(BaseModel):
    name: str
    key_type: str
    team_id: str | None = None
    user_id: str | None = None
    service_account_id: str | None = None
    daily_token_limit: int = 0
    monthly_token_limit: int = 0
    requests_per_minute: int = 0
    requests_per_day: int = 0
    expires_at: str | None = None


class UpdateAPIKeyRequest(BaseModel):
    name: str | None = None
    daily_token_limit: int | None = None
    monthly_token_limit: int | None = None
    requests_per_minute: int | None = None
    requests_per_day: int | None = None
    expires_at: str | None = None


class CreateAPIKeyResponse(BaseModel):
    id: str
    key: str
    key_hint: str
    key_type: str
    name: str
    org_id: str
    team_id: str | None = None
    user_id: str | None = None
    service_account_id: str | None = None
    daily_token_limit: int
    monthly_token_limit: int
    requests_per_minute: int
    requests_per_day: int
    expires_at: str | None = None
    created_by: str
    created_at: str
    updated_at: str


class APIKeyResponse(BaseModel):
    id: str
    key_hint: str
    key_type: str
    name: str
    org_id: str
    team_id: str | None = None
    user_id: str | None = None
    service_account_id: str | None = None
    daily_token_limit: int
    monthly_token_limit: int
    requests_per_minute: int
    requests_per_day: int
    expires_at: str | None = None
    last_used_at: str | None = None
    created_by: str
    created_at: str
    updated_at: str


class PaginatedAPIKeysResponse(BaseModel):
    data: list[APIKeyResponse]
    has_more: bool
    next_cursor: str | None = None


class RotateAPIKeyResponse(BaseModel):
    id: str
    key: str
    key_hint: str
    key_type: str
    name: str
    org_id: str
    created_at: str
    updated_at: str


def _require_org_access(key_info: KeyInfo, org_id: str) -> None:
    if key_info.is_system_admin or has_role(key_info.role, ROLE_SYSTEM_ADMIN):
        return
    if key_info.org_id != org_id:
        raise forbidden()


def _can_manage_all_keys(caller: KeyInfo) -> bool:
    return has_role(caller.role, ROLE_ORG_ADMIN) or caller.is_system_admin


def _key_visible(key: dict[str, Any], caller: KeyInfo) -> bool:
    if _can_manage_all_keys(caller):
        return True
    if has_role(caller.role, ROLE_TEAM_ADMIN):
        if caller.team_id and key.get("team_id") == caller.team_id:
            return True
        if key.get("user_id") == caller.user_id:
            return True
        return False
    return key.get("user_id") == caller.user_id


def _can_manage_key(key: dict[str, Any], caller: KeyInfo) -> bool:
    return _can_manage_all_keys(caller) or _key_visible(key, caller)


def _key_resp(k: dict[str, Any]) -> APIKeyResponse:
    return APIKeyResponse(
        id=k["id"],
        key_hint=k["key_hint"],
        key_type=k["key_type"],
        name=k["name"],
        org_id=k["org_id"],
        team_id=k.get("team_id"),
        user_id=k.get("user_id"),
        service_account_id=k.get("service_account_id"),
        daily_token_limit=int(k.get("daily_token_limit") or 0),
        monthly_token_limit=int(k.get("monthly_token_limit") or 0),
        requests_per_minute=int(k.get("requests_per_minute") or 0),
        requests_per_day=int(k.get("requests_per_day") or 0),
        expires_at=k.get("expires_at"),
        last_used_at=k.get("last_used_at"),
        created_by=k["created_by"],
        created_at=k["created_at"],
        updated_at=k["updated_at"],
    )


@router.post("/orgs/{org_id}/keys", response_model=CreateAPIKeyResponse, status_code=status.HTTP_201_CREATED)
async def create_api_key(
    org_id: str,
    body: CreateAPIKeyRequest,
    key_info: KeyInfo = Depends(require_role(ROLE_MEMBER)),
) -> CreateAPIKeyResponse:
    h = get_handler()
    _require_org_access(key_info, org_id)
    if not key_info.user_id:
        raise bad_request("keys can only be created by user keys")
    if not body.name:
        raise bad_request("name is required")
    if body.key_type not in VALID_KEY_TYPES:
        raise bad_request("key_type must be one of: user_key, team_key, sa_key")
    req = body.model_dump()
    if not _can_manage_all_keys(key_info):
        if body.key_type != KEY_TYPE_USER:
            raise forbidden("you can only create user keys")
        req["user_id"] = key_info.user_id
    if body.key_type == KEY_TYPE_USER and not req.get("user_id"):
        raise bad_request("user_id is required for user_key")
    if body.key_type == KEY_TYPE_TEAM:
        if not body.team_id:
            raise bad_request("team_id is required for team_key")
        team = await repo.get_team(h.db, body.team_id)
        if not team or team["org_id"] != org_id:
            raise bad_request("team not found")
    if body.key_type == KEY_TYPE_SA:
        if not body.service_account_id:
            raise bad_request("service_account_id is required for sa_key")
        sa = await repo.get_service_account(h.db, body.service_account_id)
        if not sa or sa["org_id"] != org_id:
            raise bad_request("service account not found")
    plaintext = generate_key(body.key_type)
    key_hash = hash_key(plaintext, h.hmac_secret)
    api_key = await repo.create_api_key(
        h.db,
        {
            "key_hash": key_hash,
            "key_hint": hint_key(plaintext),
            "key_type": body.key_type,
            "name": body.name,
            "org_id": org_id,
            "team_id": req.get("team_id"),
            "user_id": req.get("user_id"),
            "service_account_id": req.get("service_account_id"),
            "daily_token_limit": body.daily_token_limit,
            "monthly_token_limit": body.monthly_token_limit,
            "requests_per_minute": body.requests_per_minute,
            "requests_per_day": body.requests_per_day,
            "expires_at": body.expires_at,
            "created_by": key_info.user_id,
        },
    )
    owner_admin = False
    membership_role: str | None = None
    target_user_id = req.get("user_id")
    if body.key_type in (KEY_TYPE_USER, KEY_TYPE_SESSION) and target_user_id:
        owner = await repo.get_user(h.db, target_user_id)
        if owner:
            owner_admin = owner["is_system_admin"]
        try:
            membership_role = await repo.get_user_org_role(h.db, target_user_id, org_id)
        except repo.NotFoundError:
            pass
    role_ctx = {
        "key_type": body.key_type,
        "team_id": req.get("team_id"),
        "is_system_admin": owner_admin,
        "membership_role": membership_role,
    }
    cache_role = h._resolve_role(role_ctx)
    h.key_cache.set(
        key_hash,
        KeyInfo(
            id=api_key["id"],
            key_type=body.key_type,
            role=cache_role,
            org_id=org_id,
            team_id=req.get("team_id") or "",
            user_id=req.get("user_id") or "",
            service_account_id=req.get("service_account_id") or "",
            name=body.name,
            is_system_admin=owner_admin,
        ),
    )
    return CreateAPIKeyResponse(
        id=api_key["id"],
        key=plaintext,
        key_hint=api_key["key_hint"],
        key_type=api_key["key_type"],
        name=api_key["name"],
        org_id=api_key["org_id"],
        team_id=api_key.get("team_id"),
        user_id=api_key.get("user_id"),
        service_account_id=api_key.get("service_account_id"),
        daily_token_limit=int(api_key.get("daily_token_limit") or 0),
        monthly_token_limit=int(api_key.get("monthly_token_limit") or 0),
        requests_per_minute=int(api_key.get("requests_per_minute") or 0),
        requests_per_day=int(api_key.get("requests_per_day") or 0),
        expires_at=api_key.get("expires_at"),
        created_by=api_key["created_by"],
        created_at=api_key["created_at"],
        updated_at=api_key["updated_at"],
    )


@router.get("/orgs/{org_id}/keys", response_model=PaginatedAPIKeysResponse)
async def list_api_keys(
    org_id: str,
    limit: int | None = Query(20),
    cursor: str | None = Query(None),
    key_info: KeyInfo = Depends(require_role(ROLE_MEMBER)),
) -> PaginatedAPIKeysResponse:
    h = get_handler()
    _require_org_access(key_info, org_id)
    p = parse_pagination(limit, cursor)
    keys = await repo.list_api_keys(h.db, org_id, p.cursor, p.limit + 1, False)
    if not _can_manage_all_keys(key_info):
        keys = [k for k in keys if _key_visible(k, key_info)]
    has_more = len(keys) > p.limit
    if has_more:
        keys = keys[: p.limit]
    return PaginatedAPIKeysResponse(
        data=[_key_resp(k) for k in keys],
        has_more=has_more,
        next_cursor=keys[-1]["id"] if has_more and keys else None,
    )


@router.get("/orgs/{org_id}/keys/{key_id}", response_model=APIKeyResponse)
async def get_api_key(
    org_id: str,
    key_id: str,
    key_info: KeyInfo = Depends(require_role(ROLE_MEMBER)),
) -> APIKeyResponse:
    h = get_handler()
    _require_org_access(key_info, org_id)
    key = await repo.get_api_key(h.db, key_id)
    if not key or key["org_id"] != org_id:
        raise not_found("api key not found")
    if not _can_manage_key(key, key_info):
        raise not_found("api key not found")
    return _key_resp(key)


@router.patch("/orgs/{org_id}/keys/{key_id}", response_model=APIKeyResponse)
async def update_api_key(
    org_id: str,
    key_id: str,
    body: UpdateAPIKeyRequest,
    key_info: KeyInfo = Depends(require_role(ROLE_MEMBER)),
) -> APIKeyResponse:
    h = get_handler()
    _require_org_access(key_info, org_id)
    existing = await repo.get_api_key(h.db, key_id)
    if not existing or existing["org_id"] != org_id:
        raise not_found("api key not found")
    if not _can_manage_key(existing, key_info):
        raise not_found("api key not found")
    fields = {k: v for k, v in body.model_dump(exclude_unset=True).items()}
    try:
        key = await repo.update_api_key(h.db, key_id, fields)
    except repo.NotFoundError:
        raise not_found("api key not found")
    except Exception:
        raise internal_error("failed to update api key")
    return _key_resp(key)


@router.delete("/orgs/{org_id}/keys/{key_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_api_key(
    org_id: str,
    key_id: str,
    key_info: KeyInfo = Depends(require_role(ROLE_MEMBER)),
) -> Response:
    h = get_handler()
    _require_org_access(key_info, org_id)
    existing = await repo.get_api_key(h.db, key_id)
    if not existing or existing["org_id"] != org_id:
        raise not_found("api key not found")
    if not _can_manage_key(existing, key_info):
        raise not_found("api key not found")
    try:
        await repo.delete_api_key(h.db, key_id)
        key_hash = existing.get("key_hash")
        if key_hash:
            h.key_cache.delete(key_hash)
    except repo.NotFoundError:
        raise not_found("api key not found")
    except Exception:
        raise internal_error("failed to delete api key")
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/orgs/{org_id}/keys/{key_id}/rotate", response_model=RotateAPIKeyResponse)
async def rotate_api_key(
    org_id: str,
    key_id: str,
    key_info: KeyInfo = Depends(require_role(ROLE_MEMBER)),
) -> RotateAPIKeyResponse:
    h = get_handler()
    _require_org_access(key_info, org_id)
    existing = await repo.get_api_key(h.db, key_id)
    if not existing or existing["org_id"] != org_id:
        raise not_found("api key not found")
    if not _can_manage_key(existing, key_info):
        raise not_found("api key not found")
    if existing["key_type"] in (KEY_TYPE_SESSION,):
        raise bad_request("session keys cannot be rotated")
    old_hash = existing.get("key_hash")
    plaintext = generate_key(existing["key_type"])
    key_hash = hash_key(plaintext, h.hmac_secret)
    try:
        key = await repo.update_api_key(
            h.db,
            key_id,
            {"key_hash": key_hash, "key_hint": hint_key(plaintext)},
        )
    except repo.NotFoundError:
        raise not_found("api key not found")
    except Exception:
        raise internal_error("failed to rotate api key")
    if old_hash:
        h.key_cache.delete(old_hash)
    owner_admin = False
    membership_role: str | None = None
    if existing.get("user_id"):
        owner = await repo.get_user(h.db, existing["user_id"])
        if owner:
            owner_admin = owner["is_system_admin"]
        try:
            membership_role = await repo.get_user_org_role(h.db, existing["user_id"], org_id)
        except repo.NotFoundError:
            pass
    role_ctx = {
        **existing,
        "is_system_admin": owner_admin,
        "membership_role": membership_role,
    }
    cache_role = h._resolve_role(role_ctx)
    expires_at = None
    if key.get("expires_at"):
        try:
            expires_at = datetime.fromisoformat(key["expires_at"].replace("Z", "+00:00"))
        except ValueError:
            pass
    h.key_cache.set(
        key_hash,
        KeyInfo(
            id=key["id"],
            key_type=existing["key_type"],
            role=cache_role,
            org_id=org_id,
            team_id=existing.get("team_id") or "",
            user_id=existing.get("user_id") or "",
            service_account_id=existing.get("service_account_id") or "",
            name=key["name"],
            is_system_admin=owner_admin,
            expires_at=expires_at,
        ),
    )
    return RotateAPIKeyResponse(
        id=key["id"],
        key=plaintext,
        key_hint=key["key_hint"],
        key_type=key["key_type"],
        name=key["name"],
        org_id=key["org_id"],
        created_at=key["created_at"],
        updated_at=key["updated_at"],
    )
