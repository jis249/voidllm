"""Shared admin API utilities: errors, keygen, RBAC, pagination."""

from __future__ import annotations

import hashlib
import hmac
import os
import re
import secrets
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from fastapi import HTTPException, Request
from uuid6 import uuid7

# --- API key prefixes (WAI) ---

KEY_TYPE_USER = "user_key"
KEY_TYPE_TEAM = "team_key"
KEY_TYPE_SA = "sa_key"
KEY_TYPE_SESSION = "session_key"
KEY_TYPE_INVITE = "invite_token"

PREFIX_USER = "wa_uk_"
PREFIX_TEAM = "wa_tk_"
PREFIX_SA = "wa_sa_"
PREFIX_SESSION = "wa_sk_"
PREFIX_INVITE = "wa_iv_"

_PREFIX_MAP = {
    PREFIX_USER: KEY_TYPE_USER,
    PREFIX_TEAM: KEY_TYPE_TEAM,
    PREFIX_SA: KEY_TYPE_SA,
    PREFIX_SESSION: KEY_TYPE_SESSION,
    PREFIX_INVITE: KEY_TYPE_INVITE,
}

_TYPE_PREFIX = {v: k for k, v in _PREFIX_MAP.items()}

# --- RBAC ---

ROLE_SYSTEM_ADMIN = "system_admin"
ROLE_ORG_ADMIN = "org_admin"
ROLE_TEAM_ADMIN = "team_admin"
ROLE_MEMBER = "member"

ROLE_RANK = {
    ROLE_MEMBER: 0,
    ROLE_TEAM_ADMIN: 1,
    ROLE_ORG_ADMIN: 2,
    ROLE_SYSTEM_ADMIN: 3,
}

SLUG_RE = re.compile(r"^[a-z0-9][a-z0-9-]{0,61}[a-z0-9]$")


def has_role(role: str, required: str) -> bool:
    r = ROLE_RANK.get(role)
    req = ROLE_RANK.get(required)
    if r is None or req is None:
        return False
    return r >= req


def derive_hmac_secret(encryption_key: bytes) -> bytes:
    """HKDF-SHA256 with info 'wai-hmac-key' (matches Go app.go derivation)."""
    from cryptography.hazmat.primitives.kdf.hkdf import HKDF
    from cryptography.hazmat.primitives import hashes

    hkdf = HKDF(
        algorithm=hashes.SHA256(),
        length=32,
        salt=None,
        info=b"wai-hmac-key",
    )
    return hkdf.derive(encryption_key)


def load_encryption_key() -> bytes:
    raw = os.environ.get("WAI_ENCRYPTION_KEY", "")
    if not raw:
        raise RuntimeError("WAI_ENCRYPTION_KEY is required")
    from wai.crypto.aes import parse_key

    return parse_key(raw)


def generate_key(key_type: str) -> str:
    prefix = _TYPE_PREFIX.get(key_type)
    if not prefix:
        raise ValueError(f"unknown key type: {key_type}")
    return prefix + secrets.token_hex(24)


def hash_key(plaintext: str, hmac_secret: bytes) -> str:
    return hmac.new(hmac_secret, plaintext.encode(), hashlib.sha256).hexdigest()


def hint_key(plaintext: str) -> str:
    if len(plaintext) <= 10:
        return plaintext
    return plaintext[:6] + "..." + plaintext[-4:]


def validate_prefix(key: str) -> str:
    for prefix, ktype in _PREFIX_MAP.items():
        if key.startswith(prefix):
            return ktype
    raise ValueError("unrecognized key prefix")


def new_uuid() -> str:
    return str(uuid7())


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S+00:00")


# --- API errors (match Go apierror envelope) ---


def api_error(status: int, code: str, message: str, request_id: str = "") -> HTTPException:
    detail: dict[str, Any] = {"error": {"code": code, "message": message}}
    if request_id:
        detail["error"]["request_id"] = request_id
    return HTTPException(status_code=status, detail=detail)


def bad_request(msg: str) -> HTTPException:
    return api_error(400, "bad_request", msg)


def unauthorized(msg: str = "missing authorization header") -> HTTPException:
    return api_error(401, "unauthorized", msg)


def forbidden(msg: str = "insufficient permissions") -> HTTPException:
    return api_error(403, "forbidden", msg)


def not_found(msg: str) -> HTTPException:
    return api_error(404, "not_found", msg)


def conflict(msg: str) -> HTTPException:
    return api_error(409, "conflict", msg)


def internal_error(msg: str) -> HTTPException:
    return api_error(500, "internal_error", msg)


def limit_reached(msg: str) -> HTTPException:
    return api_error(403, "limit_reached", msg)


def gone(msg: str) -> HTTPException:
    return api_error(410, "gone", msg)


@dataclass
class PaginationParams:
    limit: int = 20
    cursor: str = ""


def parse_pagination(limit: int | None, cursor: str | None) -> PaginationParams:
    lim = limit if limit is not None else 20
    if lim <= 0:
        lim = 20
    if lim > 100:
        lim = 100
    cur = (cursor or "").strip()
    if cur:
        import uuid as _uuid

        try:
            _uuid.UUID(cur)
        except ValueError as exc:
            raise bad_request("invalid cursor format") from exc
    return PaginationParams(limit=lim, cursor=cur)


@dataclass
class KeyInfo:
    id: str
    key_type: str
    role: str
    org_id: str
    team_id: str = ""
    user_id: str = ""
    service_account_id: str = ""
    name: str = ""
    daily_token_limit: int = 0
    monthly_token_limit: int = 0
    requests_per_minute: int = 0
    requests_per_day: int = 0
    expires_at: datetime | None = None
    org_daily_token_limit: int = 0
    org_monthly_token_limit: int = 0
    org_requests_per_minute: int = 0
    org_requests_per_day: int = 0
    team_daily_token_limit: int = 0
    team_monthly_token_limit: int = 0
    team_requests_per_minute: int = 0
    team_requests_per_day: int = 0


KEY_INFO_CTX = "wai_key_info"


def get_key_info(request: Request) -> KeyInfo | None:
    return getattr(request.state, KEY_INFO_CTX, None)


def row_get(row: Any, key: str, default: Any = None) -> Any:
    if row is None:
        return default
    try:
        val = row[key]
        return default if val is None else val
    except (KeyError, IndexError, TypeError):
        return default
