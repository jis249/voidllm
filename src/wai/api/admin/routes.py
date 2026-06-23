"""Admin API route registration."""

from __future__ import annotations

from fastapi import APIRouter, Depends

from wai.api.admin import (
    audit,
    auth,
    dashboard,
    deployments,
    invites,
    keys,
    mcp_access,
    mcp_handler,
    mcp_servers,
    mcp_usage,
    model_access,
    model_aliases,
    models,
    oidc,
    org_memberships,
    org_sso,
    orgs,
    service_accounts,
    system,
    team_memberships,
    teams,
    update,
    usage,
    users,
)
from wai.api.admin.handler import auth_middleware, get_handler

API_PREFIX = "/api/v1"


def create_admin_router() -> APIRouter:
    """Build the complete admin API router with all routes from routes.go."""
    root = APIRouter()

    # Public routes — no auth required (matches routes.go public group)
    public = APIRouter()
    public.add_api_route(f"{API_PREFIX}/auth/login", auth.login, methods=["POST"], tags=["auth"])
    public.add_api_route(f"{API_PREFIX}/auth/oidc/exchange", auth.oidc_exchange, methods=["POST"], tags=["auth"])
    public.add_api_route(f"{API_PREFIX}/auth/providers", auth.auth_providers, methods=["GET"], tags=["auth"])
    public.add_api_route(f"{API_PREFIX}/invites/peek", invites.peek_invite, methods=["GET"], tags=["invites"])
    public.add_api_route(f"{API_PREFIX}/invites/redeem", invites.redeem_invite, methods=["POST"], tags=["invites"])

    h = get_handler()
    if h.sso_provider is not None:
        public.add_api_route(f"{API_PREFIX}/auth/oidc/login", auth.oidc_login, methods=["GET"], tags=["auth"])
        public.add_api_route(f"{API_PREFIX}/auth/oidc/callback", auth.oidc_callback, methods=["GET"], tags=["auth"])

    root.include_router(public)

    # Authenticated /api/v1 group
    authed = APIRouter(dependencies=[Depends(auth_middleware)])

    authed.add_api_route(f"{API_PREFIX}/me", auth.me, methods=["GET"], tags=["auth"])
    authed.add_api_route(f"{API_PREFIX}/me/available-models", auth.available_models, methods=["GET"], tags=["auth"])
    authed.include_router(dashboard.router, prefix=API_PREFIX)
    authed.include_router(system.router, prefix=API_PREFIX)
    authed.include_router(usage.router, prefix=API_PREFIX)
    authed.include_router(mcp_usage.router, prefix=API_PREFIX)
    authed.include_router(audit.router, prefix=API_PREFIX)
    authed.include_router(orgs.router, prefix=API_PREFIX)
    authed.include_router(users.router, prefix=API_PREFIX)
    authed.include_router(org_memberships.router, prefix=API_PREFIX)
    authed.include_router(teams.router, prefix=API_PREFIX)
    authed.include_router(team_memberships.router, prefix=API_PREFIX)
    authed.include_router(service_accounts.router, prefix=API_PREFIX)
    authed.add_api_route(f"{API_PREFIX}/orgs/{{org_id}}/invites", invites.create_invite, methods=["POST"], tags=["invites"])
    authed.add_api_route(f"{API_PREFIX}/orgs/{{org_id}}/invites", invites.list_invites, methods=["GET"], tags=["invites"])
    authed.add_api_route(
        f"{API_PREFIX}/orgs/{{org_id}}/invites/{{invite_id}}", invites.revoke_invite, methods=["DELETE"], tags=["invites"]
    )
    authed.include_router(keys.router, prefix=API_PREFIX)
    authed.include_router(models.router, prefix=API_PREFIX)
    authed.include_router(deployments.router, prefix=API_PREFIX)
    authed.include_router(model_access.router, prefix=API_PREFIX)
    authed.include_router(model_aliases.router, prefix=API_PREFIX)
    authed.include_router(mcp_access.router, prefix=API_PREFIX)
    authed.include_router(mcp_servers.router, prefix=API_PREFIX)
    authed.include_router(org_sso.router, prefix=API_PREFIX)
    authed.include_router(oidc.router, prefix=API_PREFIX)
    authed.include_router(update.router, prefix=API_PREFIX)
    authed.include_router(mcp_handler.router, prefix=API_PREFIX)

    if h.code_mode_server is not None:
        mcp_handler.register_code_mode_routes(authed)

    root.include_router(authed)
    return root


def register_routes(app, handler=None) -> APIRouter:
    """Mount admin routes on a FastAPI app."""
    router = create_admin_router()
    app.include_router(router)
    return router
