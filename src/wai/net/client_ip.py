"""Client IP extraction for rate limiting and audit (load-balancer aware)."""

from __future__ import annotations

from starlette.requests import Request


def client_ip(request: Request) -> str:
    """Return the client IP, honoring X-Forwarded-For from a trusted load balancer."""
    forwarded = request.headers.get("X-Forwarded-For", "")
    if forwarded:
        return forwarded.split(",")[0].strip()
    if request.client:
        return request.client.host
    return ""
