"""Proxy API key authentication."""

from __future__ import annotations

from fastapi import Request

from wai.api.admin.handler import authenticate_bearer, get_handler


async def proxy_auth_middleware(request: Request) -> None:
    key_info = await authenticate_bearer(request, proxy=True)
    h = get_handler()
    if h.rate_limiter is not None:
        await h.rate_limiter.check_proxy_request(key_info)
