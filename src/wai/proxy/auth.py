"""Proxy API key authentication."""

from __future__ import annotations

from datetime import datetime

from fastapi import Request

from wai.api.admin.common import KEY_INFO_CTX, hash_key, unauthorized, validate_prefix
from wai.api.admin.handler import get_handler


async def proxy_auth_middleware(request: Request) -> None:
    auth_header = request.headers.get("Authorization", "")
    token = auth_header[7:].strip() if auth_header.startswith("Bearer ") else ""
    if not token:
        raise unauthorized("missing authorization header")
    try:
        validate_prefix(token)
    except ValueError as exc:
        raise unauthorized("invalid API key format") from exc
    h = get_handler()
    kh = hash_key(token, h.hmac_secret)
    info = h.key_cache.get(kh)
    if info is None:
        raise unauthorized("invalid API key")
    if info.expires_at and datetime.now(info.expires_at.tzinfo or None) > info.expires_at:
        h.key_cache.delete(kh)
        raise unauthorized("invalid API key")
    request.state.__dict__[KEY_INFO_CTX] = info
