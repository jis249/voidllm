"""Middleware that records mutating admin API calls to the audit log."""

from __future__ import annotations

import re

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

from wai.api.admin.common import KEY_INFO_CTX, KeyInfo
from wai.audit.logger import AuditEvent, AuditLogger
from wai.net.client_ip import client_ip

_UUID_RE = re.compile(
    r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$",
    re.IGNORECASE,
)
_MUTATING = frozenset({"POST", "PUT", "PATCH", "DELETE"})
_SKIP_PREFIXES = (
    "/api/v1/auth/login",
    "/api/v1/auth/oidc/",
    "/api/v1/invites/peek",
    "/api/v1/invites/redeem",
)
_VERB = {"POST": "create", "PUT": "replace", "PATCH": "update", "DELETE": "delete"}


def _parse_audit(method: str, path: str) -> tuple[str, str, str, str]:
    segments = [s for s in path.split("/") if s and s not in ("api", "v1")]
    resource_type = segments[0] if segments else "api"
    resource_id = next((s for s in segments if _UUID_RE.match(s)), "")
    verb = _VERB.get(method, method.lower())
    tail = segments[-1] if segments else ""
    if tail and not _UUID_RE.match(tail):
        action = f"{resource_type}.{tail}.{verb}"
    else:
        action = f"{resource_type}.{verb}"
    description = f"{method} {path}"
    return action, resource_type, resource_id, description


def _actor_from_key(key_info: KeyInfo) -> tuple[str, str, str, str]:
    if key_info.service_account_id:
        return key_info.org_id, key_info.service_account_id, "service_account", key_info.id
    if key_info.user_id:
        return key_info.org_id, key_info.user_id, "user", key_info.id
    return key_info.org_id, "", "system", key_info.id


class AuditMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next) -> Response:
        path = request.url.path
        if request.method not in _MUTATING or not path.startswith("/api/v1/"):
            return await call_next(request)
        if any(path.startswith(prefix) for prefix in _SKIP_PREFIXES):
            return await call_next(request)

        response = await call_next(request)
        audit: AuditLogger | None = getattr(request.app.state, "audit_logger", None)
        if audit is None:
            return response

        key_info: KeyInfo | None = getattr(request.state, KEY_INFO_CTX, None)
        org_id, actor_id, actor_type, actor_key_id = ("", "", "system", "")
        if key_info is not None:
            org_id, actor_id, actor_type, actor_key_id = _actor_from_key(key_info)

        action, resource_type, resource_id, description = _parse_audit(request.method, path)
        audit.log(
            AuditEvent(
                request_id=getattr(request.state, "request_id", "") or "",
                org_id=org_id,
                actor_id=actor_id,
                actor_type=actor_type,
                actor_key_id=actor_key_id,
                action=action,
                resource_type=resource_type,
                resource_id=resource_id,
                description=description,
                ip_address=client_ip(request),
                status_code=response.status_code,
            )
        )
        return response
