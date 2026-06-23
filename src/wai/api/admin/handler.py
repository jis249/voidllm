"""Admin API Handler with shared dependencies."""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Callable, Awaitable

from fastapi import Depends, Request

from wai.api.admin.common import (
    KEY_INFO_CTX,
    KEY_TYPE_SA,
    KEY_TYPE_SESSION,
    KEY_TYPE_TEAM,
    KEY_TYPE_USER,
    KeyInfo,
    ROLE_MEMBER,
    ROLE_ORG_ADMIN,
    ROLE_SYSTEM_ADMIN,
    ROLE_TEAM_ADMIN,
    derive_hmac_secret,
    get_key_info,
    has_role,
    hash_key,
    load_encryption_key,
    unauthorized,
)
from wai.api.admin import repository as repo
from wai.db.connection import Database
from wai.proxy.access import ModelAccessCache, reload_access_cache


@dataclass
class SSOConfig:
    enabled: bool = False
    issuer: str = ""
    client_id: str = ""
    client_secret: str = ""
    redirect_url: str = ""
    scopes: list[str] = field(default_factory=list)
    allowed_domains: list[str] = field(default_factory=list)
    auto_provision: bool = False
    default_role: str = "member"
    default_org_slug: str = ""
    group_sync: bool = False
    group_claim: str = ""


@dataclass
class ModelRegistry:
    """Minimal model registry for access checks."""

    _models: dict[str, dict[str, Any]] = field(default_factory=dict)

    def list_info(self) -> list[dict[str, str]]:
        return [{"name": n, "type": m.get("type", "chat")} for n, m in self._models.items()]

    def resolve(self, name: str) -> dict[str, Any]:
        if name not in self._models:
            raise KeyError(name)
        return self._models[name]

    def reload(self, models: list[dict[str, Any]]) -> None:
        self._models = {m["name"]: m for m in models}


# Session keys are allowed on /v1/* so the admin Playground can use the login token.
PROXY_KEY_TYPES = frozenset({KEY_TYPE_USER, KEY_TYPE_TEAM, KEY_TYPE_SA, KEY_TYPE_SESSION})


class KeyCache:
    def __init__(self) -> None:
        self._entries: dict[str, KeyInfo] = {}

    def get(self, key_hash: str) -> KeyInfo | None:
        return self._entries.get(key_hash)

    def set(self, key_hash: str, info: KeyInfo) -> None:
        self._entries[key_hash] = info

    def delete(self, key_hash: str) -> None:
        self._entries.pop(key_hash, None)

    def load_all(self, entries: dict[str, KeyInfo]) -> None:
        self._entries = entries


class Handler:
    """Shared dependencies for all admin API route modules."""

    def __init__(
        self,
        db: Database,
        *,
        log: logging.Logger | None = None,
        encryption_key: bytes | None = None,
        sso_config: SSOConfig | None = None,
        sso_provider: Any = None,
        registry: ModelRegistry | None = None,
        access_cache: ModelAccessCache | None = None,
        mcp_server_cache: Any = None,
        health_checker: Any = None,
        mcp_health_checker: Any = None,
        mcp_server: Any = None,
        code_mode_server: Any = None,
        update_checker: Any = None,
        audit_logger: Any = None,
        rate_limiter: Any = None,
        brute_force: Any = None,
        reload_models: Callable[[], Awaitable[None]] | None = None,
        fallback_max_depth: int = 0,
        mcp_call_timeout: float = 30.0,
        mcp_allow_private_urls: bool = False,
    ) -> None:
        self.db = db
        self.log = log or logging.getLogger("wai.admin")
        self.encryption_key = encryption_key or load_encryption_key()
        self.hmac_secret = derive_hmac_secret(self.encryption_key)
        self.key_cache = KeyCache()
        self.registry = registry or ModelRegistry()
        self.access_cache = access_cache or ModelAccessCache()
        self.mcp_server_cache = mcp_server_cache
        self.sso_config = sso_config or SSOConfig()
        self.sso_provider = sso_provider
        self.health_checker = health_checker
        self.mcp_health_checker = mcp_health_checker
        self.mcp_server = mcp_server
        self.code_mode_server = code_mode_server
        self.update_checker = update_checker
        self.audit_logger = audit_logger
        self.rate_limiter = rate_limiter
        self.brute_force = brute_force
        self.reload_models = reload_models
        self.fallback_max_depth = fallback_max_depth
        self.mcp_call_timeout = mcp_call_timeout
        self.mcp_allow_private_urls = mcp_allow_private_urls
        self._fallback_lock = False

    async def seed_key_cache(self) -> None:
        records = await repo.load_all_active_keys(self.db)
        entries: dict[str, KeyInfo] = {}
        for r in records:
            role = self._resolve_role(r)
            expires = None
            if r.get("expires_at"):
                try:
                    expires = datetime.fromisoformat(r["expires_at"].replace("Z", "+00:00"))
                except ValueError:
                    pass
            entries[r["key_hash"]] = KeyInfo(
                id=r["id"],
                key_type=r["key_type"],
                role=role,
                org_id=r["org_id"],
                team_id=r.get("team_id") or "",
                user_id=r.get("user_id") or "",
                service_account_id=r.get("service_account_id") or "",
                name=r.get("name") or "",
                is_system_admin=bool(r.get("is_system_admin")),
                daily_token_limit=int(r.get("daily_token_limit") or 0),
                monthly_token_limit=int(r.get("monthly_token_limit") or 0),
                requests_per_minute=int(r.get("requests_per_minute") or 0),
                requests_per_day=int(r.get("requests_per_day") or 0),
                expires_at=expires,
                org_daily_token_limit=int(r.get("org_daily_token_limit") or 0),
                org_monthly_token_limit=int(r.get("org_monthly_token_limit") or 0),
                org_requests_per_minute=int(r.get("org_requests_per_minute") or 0),
                org_requests_per_day=int(r.get("org_requests_per_day") or 0),
                team_daily_token_limit=int(r.get("team_daily_token_limit") or 0),
                team_monthly_token_limit=int(r.get("team_monthly_token_limit") or 0),
                team_requests_per_minute=int(r.get("team_requests_per_minute") or 0),
                team_requests_per_day=int(r.get("team_requests_per_day") or 0),
            )
        self.key_cache.load_all(entries)

    @staticmethod
    def _resolve_role(r: dict[str, Any]) -> str:
        ktype = r["key_type"]
        if ktype in (KEY_TYPE_USER, KEY_TYPE_SESSION):
            if r.get("is_system_admin"):
                return ROLE_SYSTEM_ADMIN
            if r.get("membership_role"):
                return r["membership_role"]
            return ROLE_MEMBER
        if ktype == KEY_TYPE_TEAM:
            return ROLE_TEAM_ADMIN
        if ktype == KEY_TYPE_SA:
            return ROLE_TEAM_ADMIN if r.get("team_id") else ROLE_ORG_ADMIN
        return ROLE_MEMBER

    async def refresh_access_cache(self) -> None:
        await reload_access_cache(self.db, self.access_cache)


_handler: Handler | None = None


def init_handler(db: Database, **kwargs: Any) -> Handler:
    global _handler
    _handler = Handler(db, **kwargs)
    return _handler


def get_handler() -> Handler:
    if _handler is None:
        raise RuntimeError("handler not initialized")
    return _handler


async def authenticate_bearer(request: Request, *, proxy: bool = False) -> KeyInfo:
    """Validate Bearer token and return KeyInfo. Used by admin and proxy auth."""
    auth_header = request.headers.get("Authorization", "")
    token = auth_header[7:].strip() if auth_header.startswith("Bearer ") else ""
    if not token:
        raise unauthorized("missing authorization header")
    h = get_handler()
    from wai.api.admin.common import validate_prefix

    try:
        validate_prefix(token)
    except ValueError as exc:
        raise unauthorized("invalid API key format") from exc
    kh = hash_key(token, h.hmac_secret)
    info = h.key_cache.get(kh)
    if info is None:
        raise unauthorized("invalid API key")
    if info.expires_at and datetime.now(info.expires_at.tzinfo or None) > info.expires_at:
        h.key_cache.delete(kh)
        raise unauthorized("invalid API key")
    if proxy and info.key_type not in PROXY_KEY_TYPES:
        raise unauthorized("invalid API key")
    request.state.__dict__[KEY_INFO_CTX] = info
    return info


async def auth_middleware(request: Request) -> KeyInfo:
    """Bearer token authentication — stores KeyInfo on request.state."""
    return await authenticate_bearer(request)


def require_role(required: str):
    async def _dep(key_info: KeyInfo = Depends(auth_middleware)) -> KeyInfo:
        if not has_role(key_info.role, required):
            from wai.api.admin.common import forbidden
            raise forbidden()
        return key_info

    return _dep


async def optional_auth(request: Request) -> KeyInfo | None:
    from fastapi import HTTPException

    try:
        return await auth_middleware(request)
    except HTTPException:
        return None
