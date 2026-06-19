"""FastAPI application factory."""

from __future__ import annotations

import logging
import os
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import Depends, FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from wai.api.admin import register_routes
from wai.api.admin.handler import init_handler
from wai.api.health.routes import register_health_routes
from wai.auth.bootstrap import bootstrap, print_bootstrap_credentials
from wai.config import load
from wai.config.models import Config as ConfigModel
from wai.crypto.aes import parse_key
from wai.db.connection import Database
from wai.db.migrate import run_migrations
from wai.middleware.request_id import RequestIDMiddleware
from wai.proxy.auth import proxy_auth_middleware
from wai.proxy.handler import ProxyHandler
from wai.proxy.models_handler import models_handler
from wai.proxy.registry import Registry, load_db_into_registry, sync_yaml_models

logger = logging.getLogger("wai")


def _register_exception_handlers(app: FastAPI) -> None:
    """Return JSON error bodies compatible with the admin UI (expects error.message)."""

    @app.exception_handler(StarletteHTTPException)
    async def http_exception_handler(_request: Request, exc: StarletteHTTPException):
        if isinstance(exc.detail, dict) and "error" in exc.detail:
            return JSONResponse(status_code=exc.status_code, content=exc.detail)
        return JSONResponse(
            status_code=exc.status_code,
            content={"error": {"code": "http_error", "message": str(exc.detail)}},
        )

    @app.exception_handler(RequestValidationError)
    async def validation_exception_handler(_request: Request, exc: RequestValidationError):
        return JSONResponse(
            status_code=422,
            content={"error": {"code": "bad_request", "message": "invalid request body"}},
        )


def create_app(config: ConfigModel | None = None, config_path: str = "") -> FastAPI:
    cfg, used_defaults = load(config_path) if config is None else (config, False)
    if used_defaults:
        logger.warning("no config file found; using environment defaults")

    registry = Registry.from_yaml(cfg.models)
    db = Database(cfg.database.driver, cfg.database.dsn)
    state: dict = {
        "access_cache": None,
        "alias_cache": None,
        "proxy_handler": None,
        "bootstrap_result": None,
        "routes_registered": False,
    }

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        await db.connect()
        await run_migrations(db, logger)

        enc_key = parse_key(cfg.settings.encryption_key)
        await sync_yaml_models(db, cfg.models, enc_key, logger)
        await load_db_into_registry(db, registry, enc_key, logger)

        from wai.api.admin.common import derive_hmac_secret

        hmac_secret = derive_hmac_secret(enc_key)

        async def reload_models() -> None:
            await load_db_into_registry(db, registry, enc_key, logger)

        handler = init_handler(
            db,
            encryption_key=enc_key,
            reload_models=reload_models,
            fallback_max_depth=cfg.settings.fallback_max_depth,
        )
        await handler.seed_key_cache()

        state["bootstrap_result"] = await bootstrap(
            db,
            cfg.settings,
            hmac_secret,
            key_cache=handler.key_cache,
            log=logger,
        )

        from wai.proxy.access import load_access_cache, load_alias_cache

        state["access_cache"] = await load_access_cache(db)
        state["alias_cache"] = await load_alias_cache(db)
        await handler.refresh_access_cache()

        state["proxy_handler"] = ProxyHandler(
            registry,
            access_cache=state["access_cache"],
            alias_cache=state["alias_cache"],
            log=logger,
            max_request_body=cfg.server.proxy.max_request_body,
            max_response_body=cfg.server.proxy.max_response_body,
            max_stream_duration=cfg.server.proxy.max_stream_duration.total_seconds(),
        )

        if not state["routes_registered"]:
            _register_api_routes(app)
            state["routes_registered"] = True

        app.state.config = cfg
        app.state.db = db
        app.state.registry = registry

        yield

        if state["proxy_handler"]:
            await state["proxy_handler"].close()
        await db.close()
        print_bootstrap_credentials(state["bootstrap_result"])

    app = FastAPI(title="WAI", lifespan=lifespan)
    _register_exception_handlers(app)
    app.add_middleware(RequestIDMiddleware)

    dev_mode = os.environ.get("WAI_DEV", "").lower() in ("1", "true", "yes")
    if dev_mode:
        app.add_middleware(
            CORSMiddleware,
            allow_origins=["*"],
            allow_methods=["*"],
            allow_headers=["*"],
        )

    register_health_routes(app, db)

    def _register_api_routes(target_app: FastAPI) -> None:
        register_routes(target_app)

        @target_app.get("/v1/models", dependencies=[Depends(proxy_auth_middleware)])
        async def list_models(request: Request):
            return await models_handler(registry, state["access_cache"])(request)

        @target_app.api_route("/v1/{path:path}", methods=["GET", "POST", "PUT", "PATCH", "DELETE"])
        async def proxy_route(request: Request, path: str):
            await proxy_auth_middleware(request)
            ph: ProxyHandler | None = state["proxy_handler"]
            if ph is None:
                ph = ProxyHandler(
                    registry,
                    access_cache=state["access_cache"],
                    alias_cache=state["alias_cache"],
                )
            return await ph.handle(request, path)

        ui_dist = Path(__file__).resolve().parents[2] / "ui" / "dist"
        _SPA_EXCLUDE = ("api/", "v1/", "healthz", "readyz", "metrics", "health", "docs", "openapi.json")

        if ui_dist.is_dir() and (ui_dist / "index.html").is_file():
            from fastapi.responses import FileResponse
            from fastapi import HTTPException

            @target_app.get("/")
            @target_app.get("/{full_path:path}", include_in_schema=False)
            async def serve_spa(full_path: str = ""):
                if full_path.startswith(_SPA_EXCLUDE):
                    raise HTTPException(status_code=404)
                if full_path:
                    asset = ui_dist / full_path
                    if asset.is_file():
                        return FileResponse(asset)
                return FileResponse(ui_dist / "index.html")
        else:

            @target_app.get("/", include_in_schema=False)
            async def dev_root():
                from fastapi.responses import HTMLResponse

                return HTMLResponse(
                    """<!DOCTYPE html>
<html><head><title>WAI</title></head>
<body style="font-family:sans-serif;max-width:640px;margin:2rem auto;padding:0 1rem">
<h1>WAI API is running</h1>
<p>The admin UI is not built yet. Run:</p>
<pre>cd ui && npm ci && npm run build</pre>
<p>Then restart the server and open <a href="/login">/login</a></p>
<p>Or use Vite dev UI: <a href="http://127.0.0.1:5173/login">http://127.0.0.1:5173/login</a></p>
</body></html>"""
                )

            @target_app.get("/login", include_in_schema=False)
            async def dev_login_redirect():
                from fastapi.responses import RedirectResponse

                return RedirectResponse("http://127.0.0.1:5173/login")

    return app
