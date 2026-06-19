"""Authentication handlers: login, providers, profile."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import bcrypt
from fastapi import APIRouter, Depends, Request
from fastapi.responses import RedirectResponse
from pydantic import BaseModel

from wai.api.admin.common import (
    KEY_TYPE_SESSION,
    KeyInfo,
    bad_request,
    generate_key,
    get_key_info,
    hash_key,
    hint_key,
    internal_error,
    unauthorized,
    user_key_name,
)
from wai.api.admin.handler import Handler, auth_middleware, get_handler
from wai.api.admin import repository as repo

router = APIRouter()


class LoginRequest(BaseModel):
    email: str
    password: str


class MeResponse(BaseModel):
    id: str
    email: str
    display_name: str
    role: str
    org_id: str | None = None
    is_system_admin: bool


class LoginResponse(BaseModel):
    token: str
    expires_at: str
    user: MeResponse


class AvailableModel(BaseModel):
    name: str
    type: str = "chat"


class AvailableModelsResponse(BaseModel):
    models: list[AvailableModel]


_DUMMY_HASH = bcrypt.hashpw(b"wa-dummy-timing-pad", bcrypt.gensalt())


@router.post("/auth/login", response_model=LoginResponse)
async def login(body: LoginRequest) -> LoginResponse:
    h = get_handler()
    if not body.email:
        raise bad_request("email is required")
    if not body.password:
        raise bad_request("password is required")
    try:
        user_id, pw_hash = await repo.get_user_password_hash(h.db, body.email)
    except repo.NotFoundError:
        bcrypt.checkpw(body.password.encode(), _DUMMY_HASH)
        raise unauthorized("invalid email or password")
    except Exception:
        raise internal_error("authentication failed")
    if not bcrypt.checkpw(body.password.encode(), pw_hash.encode()):
        raise unauthorized("invalid email or password")
    try:
        role, org_id = await repo.resolve_user_role(h.db, user_id)
    except repo.NotFoundError:
        raise unauthorized("user has no organization membership")
    user = await repo.get_user(h.db, user_id)
    assert user
    session_key_name = user_key_name(user["display_name"])
    await repo.revoke_user_sessions(h.db, user_id)
    key = generate_key(KEY_TYPE_SESSION)
    key_hash = hash_key(key, h.hmac_secret)
    key_hint = hint_key(key)
    expires_at = datetime.now(timezone.utc) + timedelta(hours=24)
    expires_at_str = expires_at.strftime("%Y-%m-%dT%H:%M:%S+00:00")
    api_key = await repo.create_api_key(
        h.db,
        {
            "key_hash": key_hash,
            "key_hint": key_hint,
            "key_type": KEY_TYPE_SESSION,
            "name": session_key_name,
            "org_id": org_id,
            "user_id": user_id,
            "expires_at": expires_at_str,
            "created_by": user_id,
        },
    )
    h.key_cache.set(
        key_hash,
        KeyInfo(
            id=api_key["id"],
            key_type=KEY_TYPE_SESSION,
            role=role,
            org_id=org_id,
            user_id=user_id,
            name=session_key_name,
            is_system_admin=user["is_system_admin"],
            expires_at=expires_at,
        ),
    )
    return LoginResponse(
        token=key,
        expires_at=expires_at_str,
        user=MeResponse(
            id=user["id"],
            email=user["email"],
            display_name=user["display_name"],
            role=role,
            org_id=org_id or None,
            is_system_admin=user["is_system_admin"],
        ),
    )


@router.get("/me", response_model=MeResponse)
async def me(key_info: KeyInfo = Depends(auth_middleware)) -> MeResponse:
    h = get_handler()
    if not key_info.user_id:
        raise bad_request("this endpoint requires a user-scoped key")
    user = await repo.get_user(h.db, key_info.user_id)
    if not user:
        from wai.api.admin.common import not_found
        raise not_found("user not found")
    return MeResponse(
        id=user["id"],
        email=user["email"],
        display_name=user["display_name"],
        role=key_info.role,
        org_id=key_info.org_id or None,
        is_system_admin=user["is_system_admin"],
    )


@router.get("/me/available-models", response_model=AvailableModelsResponse)
async def available_models(key_info: KeyInfo = Depends(auth_middleware)) -> AvailableModelsResponse:
    h = get_handler()
    models = []
    for m in h.registry.list_info():
        if h.access_cache.check(key_info.org_id, key_info.team_id, key_info.id, m["name"]):
            models.append(AvailableModel(name=m["name"], type=m.get("type") or "chat"))
    return AvailableModelsResponse(models=models)


# --- Auth providers & OIDC ---

@router.get("/auth/providers")
async def auth_providers() -> dict[str, bool]:
    h = get_handler()
    return {"local": True, "oidc": h.sso_provider is not None}


@router.get("/auth/oidc/login")
async def oidc_login(request: Request) -> RedirectResponse:
    import secrets

    h = get_handler()
    if h.sso_provider is None:
        raise internal_error("SSO not configured")
    state = secrets.token_hex(32)
    nonce = secrets.token_hex(32)
    secure = h.sso_config.redirect_url.startswith("https://")
    response = RedirectResponse(url=h.sso_provider.auth_url(state, nonce), status_code=302)
    response.set_cookie(
        "wai_oidc_state", f"{state}|{nonce}", max_age=300, httponly=True, samesite="lax", secure=secure, path="/"
    )
    return response


@router.get("/auth/oidc/callback")
async def oidc_callback(request: Request, code: str = "", state: str = "") -> RedirectResponse:
    h = get_handler()
    if h.sso_provider is None:
        return RedirectResponse("/login?error=sso_disabled")
    secure = h.sso_config.redirect_url.startswith("https://")
    raw_cookie = request.cookies.get("wai_oidc_state", "")
    parts = raw_cookie.split("|", 1)
    cookie_state = parts[0]
    cookie_nonce = parts[1] if len(parts) == 2 else ""
    if not cookie_state or cookie_state != state:
        return RedirectResponse("/login?error=invalid_state")
    response = RedirectResponse("/auth/callback", status_code=302)
    response.delete_cookie("wai_oidc_state", path="/")
    if not code:
        return RedirectResponse("/login?error=missing_code")
    try:
        claims = await h.sso_provider.exchange(code, cookie_nonce)
    except Exception:
        return RedirectResponse("/login?error=exchange_failed")
    user = await repo.get_user_by_external_id(h.db, "oidc", claims.subject)
    if user is None:
        if not h.sso_config.auto_provision:
            return RedirectResponse("/login?error=not_provisioned")
        orgs = await repo.list_orgs_with_counts(h.db, "", 1, False)
        if not orgs:
            return RedirectResponse("/login?error=provision_failed")
        user = await repo.create_user(
            h.db, email=claims.email, display_name=claims.name or claims.email,
            password_hash=None, auth_provider="oidc", external_id=claims.subject,
        )
        await repo.create_org_membership(h.db, orgs[0]["id"], user["id"], h.sso_config.default_role or "member")
    session_role, session_org_id = await repo.resolve_user_role(h.db, user["id"])
    session_key_name = user_key_name(user["display_name"])
    await repo.revoke_user_sessions(h.db, user["id"])
    key = generate_key(KEY_TYPE_SESSION)
    key_hash = hash_key(key, h.hmac_secret)
    expires_at = datetime.now(timezone.utc) + timedelta(hours=24)
    expires_at_str = expires_at.strftime("%Y-%m-%dT%H:%M:%S+00:00")
    api_key = await repo.create_api_key(
        h.db,
        {
            "key_hash": key_hash, "key_hint": hint_key(key), "key_type": KEY_TYPE_SESSION,
            "name": session_key_name, "org_id": session_org_id, "user_id": user["id"],
            "expires_at": expires_at_str, "created_by": user["id"],
        },
    )
    h.key_cache.set(
        key_hash,
        KeyInfo(
            id=api_key["id"], key_type=KEY_TYPE_SESSION, role=session_role,
            org_id=session_org_id, user_id=user["id"], name=session_key_name,
            is_system_admin=user["is_system_admin"],
            expires_at=expires_at,
        ),
    )
    response.set_cookie(
        "wai_oidc_token", key, max_age=10, httponly=False, samesite="strict", secure=secure, path="/auth/callback"
    )
    return response
