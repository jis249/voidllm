"""Invite token handlers."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

import bcrypt
from fastapi import APIRouter, Depends, Query, Request, Response, status
from pydantic import BaseModel

from wai.api.admin.common import (
    KEY_TYPE_INVITE,
    KeyInfo,
    ROLE_ORG_ADMIN,
    ROLE_SYSTEM_ADMIN,
    bad_request,
    conflict,
    forbidden,
    generate_key,
    gone,
    has_role,
    hash_key,
    hint_key,
    internal_error,
    not_found,
    parse_pagination,
)
from wai.api.admin.handler import get_handler, require_role
from wai.api.admin import repository as repo
from wai.net.client_ip import client_ip

router = APIRouter()

INVITE_INVALID_MSG = "invite is no longer valid"


class CreateInviteRequest(BaseModel):
    email: str
    role: str = "member"


class CreateInviteResponse(BaseModel):
    id: str
    token: str
    token_hint: str
    email: str
    role: str
    org_id: str
    expires_at: str
    created_at: str


class InviteResponse(BaseModel):
    id: str
    token_hint: str
    email: str
    role: str
    org_id: str
    status: str
    expires_at: str
    created_by: str
    created_at: str


class PaginatedInvitesResponse(BaseModel):
    data: list[InviteResponse]
    has_more: bool
    next_cursor: str | None = None


class PeekInviteResponse(BaseModel):
    email: str
    org_name: str
    role: str
    expires_at: str


class RedeemInviteRequest(BaseModel):
    token: str
    password: str
    display_name: str


class RedeemInviteResponse(BaseModel):
    id: str
    email: str
    display_name: str
    org_id: str
    role: str


def _require_org_access(key_info: KeyInfo, org_id: str) -> None:
    if not has_role(key_info.role, ROLE_SYSTEM_ADMIN) and key_info.org_id != org_id:
        raise forbidden()


def _invite_status(t: dict[str, Any]) -> str:
    if t.get("redeemed_at"):
        return "redeemed"
    try:
        exp = datetime.fromisoformat(t["expires_at"].replace("Z", "+00:00"))
        if exp < datetime.now(timezone.utc):
            return "expired"
    except ValueError:
        pass
    return "pending"


def _invite_resp(t: dict[str, Any]) -> InviteResponse:
    return InviteResponse(
        id=t["id"],
        token_hint=t["token_hint"],
        email=t["email"],
        role=t["role"],
        org_id=t["org_id"],
        status=_invite_status(t),
        expires_at=t["expires_at"],
        created_by=t["created_by"],
        created_at=t["created_at"],
    )


@router.post("/orgs/{org_id}/invites", response_model=CreateInviteResponse, status_code=status.HTTP_201_CREATED)
async def create_invite(
    org_id: str,
    body: CreateInviteRequest,
    key_info: KeyInfo = Depends(require_role(ROLE_ORG_ADMIN)),
) -> CreateInviteResponse:
    h = get_handler()
    _require_org_access(key_info, org_id)
    if not body.email or "@" not in body.email:
        raise bad_request("email is required and must be a valid email address")
    role = body.role or "member"
    if role not in ("member", "org_admin"):
        raise bad_request("role must be member or org_admin")
    if role == "org_admin" and not has_role(key_info.role, ROLE_SYSTEM_ADMIN):
        raise forbidden("only system admins may invite org admins")
    await repo.revoke_invite_tokens_by_email(h.db, org_id, body.email)
    token = generate_key(KEY_TYPE_INVITE)
    token_hash = hash_key(token, h.hmac_secret)
    expires_at = (datetime.now(timezone.utc) + timedelta(days=7)).strftime("%Y-%m-%dT%H:%M:%S+00:00")
    invite = await repo.create_invite_token(
        h.db,
        {
            "token_hash": token_hash,
            "token_hint": hint_key(token),
            "org_id": org_id,
            "email": body.email,
            "role": role,
            "expires_at": expires_at,
            "created_by": key_info.user_id,
        },
    )
    return CreateInviteResponse(
        id=invite["id"],
        token=token,
        token_hint=invite["token_hint"],
        email=invite["email"],
        role=invite["role"],
        org_id=invite["org_id"],
        expires_at=invite["expires_at"],
        created_at=invite["created_at"],
    )


@router.get("/orgs/{org_id}/invites", response_model=PaginatedInvitesResponse)
async def list_invites(
    org_id: str,
    limit: int | None = Query(20),
    cursor: str | None = Query(None),
    key_info: KeyInfo = Depends(require_role(ROLE_ORG_ADMIN)),
) -> PaginatedInvitesResponse:
    h = get_handler()
    _require_org_access(key_info, org_id)
    p = parse_pagination(limit, cursor)
    tokens = await repo.list_invite_tokens(h.db, org_id, p.cursor, p.limit + 1)
    has_more = len(tokens) > p.limit
    if has_more:
        tokens = tokens[: p.limit]
    return PaginatedInvitesResponse(
        data=[_invite_resp(t) for t in tokens],
        has_more=has_more,
        next_cursor=tokens[-1]["id"] if has_more and tokens else None,
    )


@router.delete("/orgs/{org_id}/invites/{invite_id}", status_code=status.HTTP_204_NO_CONTENT)
async def revoke_invite(
    org_id: str,
    invite_id: str,
    key_info: KeyInfo = Depends(require_role(ROLE_ORG_ADMIN)),
) -> Response:
    h = get_handler()
    _require_org_access(key_info, org_id)
    try:
        await repo.revoke_invite_token(h.db, invite_id, org_id)
    except repo.NotFoundError:
        raise not_found("invite not found")
    except Exception:
        raise internal_error("failed to revoke invite")
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("/invites/peek", response_model=PeekInviteResponse)
async def peek_invite(token: str = Query(...)) -> PeekInviteResponse:
    h = get_handler()
    if not token:
        raise bad_request("token query parameter is required")
    token_hash = hash_key(token, h.hmac_secret)
    invite = await repo.get_invite_token_by_hash(h.db, token_hash)
    if not invite or invite.get("redeemed_at"):
        raise gone(INVITE_INVALID_MSG)
    try:
        exp = datetime.fromisoformat(invite["expires_at"].replace("Z", "+00:00"))
        if exp < datetime.now(timezone.utc):
            raise gone(INVITE_INVALID_MSG)
    except ValueError:
        raise gone(INVITE_INVALID_MSG)
    org = await repo.get_org(h.db, invite["org_id"])
    if not org:
        raise gone(INVITE_INVALID_MSG)
    return PeekInviteResponse(
        email=invite["email"],
        org_name=org["name"],
        role=invite["role"],
        expires_at=invite["expires_at"],
    )


@router.post("/invites/redeem", response_model=RedeemInviteResponse, status_code=status.HTTP_201_CREATED)
async def redeem_invite(body: RedeemInviteRequest, request: Request) -> RedeemInviteResponse:
    h = get_handler()
    ip = client_ip(request)
    if h.brute_force is not None:
        await h.brute_force.check_allowed(ip, "invite_redeem")
    if not body.token:
        raise bad_request("token is required")
    if not body.password or len(body.password) < 8:
        raise bad_request("password must be at least 8 characters")
    if not body.display_name:
        raise bad_request("display_name is required")
    token_hash = hash_key(body.token, h.hmac_secret)
    invite = await repo.get_invite_token_by_hash(h.db, token_hash)
    if not invite or invite.get("redeemed_at"):
        if h.brute_force is not None:
            await h.brute_force.record_failure(ip, "invite_redeem")
        raise bad_request(INVITE_INVALID_MSG)
    try:
        exp = datetime.fromisoformat(invite["expires_at"].replace("Z", "+00:00"))
        if exp < datetime.now(timezone.utc):
            if h.brute_force is not None:
                await h.brute_force.record_failure(ip, "invite_redeem")
            raise bad_request(INVITE_INVALID_MSG)
    except ValueError:
        if h.brute_force is not None:
            await h.brute_force.record_failure(ip, "invite_redeem")
        raise bad_request(INVITE_INVALID_MSG)
    pw_hash = bcrypt.hashpw(body.password.encode(), bcrypt.gensalt()).decode()
    try:
        await repo.redeem_invite_token(h.db, invite["id"])
    except repo.NotFoundError:
        raise bad_request(INVITE_INVALID_MSG)
    try:
        user = await repo.create_user(
            h.db,
            email=invite["email"],
            display_name=body.display_name,
            password_hash=pw_hash,
            auth_provider="local",
        )
    except repo.ConflictError:
        raise conflict("email already registered")
    except Exception:
        raise internal_error("failed to redeem invite")
    await repo.create_org_membership(h.db, invite["org_id"], user["id"], invite["role"])
    if h.brute_force is not None:
        await h.brute_force.clear(ip, "invite_redeem")
    return RedeemInviteResponse(
        id=user["id"],
        email=user["email"],
        display_name=user["display_name"],
        org_id=invite["org_id"],
        role=invite["role"],
    )
