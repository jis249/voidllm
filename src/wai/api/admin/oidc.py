"""Global SSO configuration (read-only YAML view)."""

from __future__ import annotations

from fastapi import APIRouter, Depends

from wai.api.admin.common import KeyInfo, ROLE_SYSTEM_ADMIN
from wai.api.admin.handler import get_handler, require_role
from wai.api.admin.org_sso import SSOConfigResponse

router = APIRouter()


@router.get("/settings/sso", response_model=SSOConfigResponse)
async def get_global_sso_config(
    _: KeyInfo = Depends(require_role(ROLE_SYSTEM_ADMIN)),
) -> SSOConfigResponse:
    h = get_handler()
    sso = h.sso_config
    return SSOConfigResponse(
        enabled=sso.enabled,
        issuer=sso.issuer,
        client_id=sso.client_id,
        has_secret=bool(sso.client_secret),
        redirect_url=sso.redirect_url,
        scopes=sso.scopes or [],
        allowed_domains=sso.allowed_domains or [],
        auto_provision=sso.auto_provision,
        default_role=sso.default_role,
        group_sync=sso.group_sync,
        group_claim=sso.group_claim,
    )
