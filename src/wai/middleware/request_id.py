"""Request ID middleware."""

from __future__ import annotations

import uuid

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

try:
    from uuid6 import uuid7
except ImportError:
    uuid7 = None  # type: ignore[assignment]


def _new_request_id() -> str:
    if uuid7 is not None:
        return str(uuid7())
    return str(uuid.uuid4())


class RequestIDMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next) -> Response:
        client_id = request.headers.get("X-Request-Id", "")
        try:
            uuid.UUID(client_id)
            request_id = client_id
        except ValueError:
            request_id = _new_request_id()
        request.state.request_id = request_id
        response = await call_next(request)
        response.headers["X-Request-Id"] = request_id
        return response
