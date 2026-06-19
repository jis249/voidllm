"""Health check and Prometheus metrics routes."""

from __future__ import annotations

import os
import time
from typing import Callable

from fastapi import APIRouter, Request, Response
from fastapi.responses import JSONResponse, PlainTextResponse
from prometheus_client import CONTENT_TYPE_LATEST, generate_latest

from wai.db.connection import Database

_start_time = time.time()
_version = "dev"


def register_health_routes(
    app,
    db: Database,
    *,
    draining: Callable[[], bool] | None = None,
) -> APIRouter:
    router = APIRouter()

    @router.get("/healthz")
    @router.get("/health")
    async def liveness() -> JSONResponse:
        return JSONResponse(
            {
                "status": "ok",
                "version": _version,
                "uptime_seconds": int(time.time() - _start_time),
            }
        )

    @router.get("/readyz")
    async def readiness() -> JSONResponse:
        if draining and draining():
            return JSONResponse({"status": "draining"}, status_code=503)
        try:
            await db.fetchone("SELECT 1")
        except Exception:
            return JSONResponse({"status": "not ready", "database": "error"}, status_code=503)
        return JSONResponse({"status": "ok", "database": "ok"})

    @router.get("/metrics")
    async def metrics(request: Request) -> Response:
        metrics_token = os.environ.get("WAI_METRICS_TOKEN", "")
        if metrics_token:
            auth = request.headers.get("Authorization", "")
            if auth != f"Bearer {metrics_token}":
                return Response(status_code=401)
        return PlainTextResponse(generate_latest(), media_type=CONTENT_TYPE_LATEST)

    app.include_router(router)
    return router
