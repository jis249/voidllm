"""License management handlers."""

from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from wai.api.admin.common import (
    KeyInfo,
    ROLE_MEMBER,
    ROLE_ORG_ADMIN,
    ROLE_SYSTEM_ADMIN,
    bad_request,
    has_role,
    internal_error,
)
from wai.api.admin.handler import get_handler, require_role
from wai.api.admin import repository as repo

router = APIRouter()


class SetLicenseRequest(BaseModel):
    key: str


class LicenseDetail(BaseModel):
    plan: str
    features: list[str]
    expires_at: datetime | None = None


class SetLicenseResponse(BaseModel):
    status: str
    message: str
    license: LicenseDetail


class LicenseResponse(BaseModel):
    edition: str
    valid: bool
    features: list[str]
    expires_at: datetime | None = None
    max_orgs: int
    max_teams: int
    customer_id: str = ""
    fallback_max_depth: int


def _validate_license_jwt(key: str) -> LicenseDetail:
    """Simplified license validation — accepts JWT-shaped keys for dev."""
    import jwt

    try:
        payload = jwt.decode(key, options={"verify_signature": False})
    except Exception as exc:
        raise bad_request("invalid license key") from exc
    exp = payload.get("exp")
    expires_at = datetime.fromtimestamp(exp) if exp else None
    return LicenseDetail(
        plan=payload.get("plan", "enterprise"),
        features=payload.get("features", []),
        expires_at=expires_at,
    )


@router.put("/settings/license", response_model=SetLicenseResponse)
async def set_license(
    body: SetLicenseRequest,
    _: KeyInfo = Depends(require_role(ROLE_SYSTEM_ADMIN)),
) -> SetLicenseResponse:
    h = get_handler()
    if not body.key:
        raise bad_request("key is required")
    detail = _validate_license_jwt(body.key)
    h.license.edition = detail.plan
    h.license.valid = True
    h.license.features = detail.features
    h.license.expires_at = detail.expires_at
    if h.reload_models:
        try:
            await h.reload_models()
        except Exception:
            h.log.warning("set license: registry reload failed")
    try:
        await repo.set_setting(h.db, "license_jwt", body.key)
    except Exception:
        raise internal_error("failed to persist license")
    return SetLicenseResponse(
        status="saved",
        message="License activated. Restart WAI to enable heartbeat with the new key.",
        license=detail,
    )


@router.get("/license", response_model=LicenseResponse)
async def get_license(key_info: KeyInfo = Depends(require_role(ROLE_MEMBER))) -> LicenseResponse:
    h = get_handler()
    lic = h.license.load()
    resp = LicenseResponse(
        edition=lic.edition,
        valid=lic.valid,
        features=lic.features,
        max_orgs=lic.max_orgs,
        max_teams=lic.max_teams,
        fallback_max_depth=h.fallback_max_depth,
        expires_at=lic.expires_at,
    )
    if has_role(key_info.role, ROLE_ORG_ADMIN):
        resp.customer_id = lic.customer_id
    return resp
