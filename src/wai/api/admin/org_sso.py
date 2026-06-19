"""Org SSO configuration handlers."""

from __future__ import annotations

import ipaddress
import json
from urllib.parse import urlparse

import httpx
from fastapi import APIRouter, Depends, Response, status
from pydantic import BaseModel, Field

from wai.api.admin.common import (
    KeyInfo,
    ROLE_ORG_ADMIN,
    ROLE_SYSTEM_ADMIN,
    bad_request,
    forbidden,
    has_role,
    internal_error,
    new_uuid,
    not_found,
)
from wai.api.admin.handler import SSOConfig, get_handler, require_role

router = APIRouter()


class SSOConfigRequest(BaseModel):
    enabled: bool = False
    issuer: str = ""
    client_id: str = ""
    client_secret: str = ""
    redirect_url: str = ""
    scopes: list[str] = Field(default_factory=list)
    allowed_domains: list[str] = Field(default_factory=list)
    auto_provision: bool = False
    default_role: str = "member"
    group_sync: bool = False
    group_claim: str = ""


class SSOConfigResponse(BaseModel):
    id: str = ""
    org_id: str = ""
    enabled: bool = False
    issuer: str = ""
    client_id: str = ""
    has_secret: bool = False
    redirect_url: str = ""
    scopes: list[str] = Field(default_factory=list)
    allowed_domains: list[str] = Field(default_factory=list)
    auto_provision: bool = False
    default_role: str = "member"
    group_sync: bool = False
    group_claim: str = ""
    created_at: str = ""
    updated_at: str = ""


class TestSSORequest(BaseModel):
    issuer: str


class TestSSOResponse(BaseModel):
    status: str
    message: str = ""


def _require_org_admin(key_info: KeyInfo, org_id: str) -> None:
    if not has_role(key_info.role, ROLE_SYSTEM_ADMIN) and not (
        has_role(key_info.role, ROLE_ORG_ADMIN) and key_info.org_id == org_id
    ):
        raise forbidden()


def _is_private_host(host: str) -> bool:
    try:
        ip = ipaddress.ip_address(host)
        return ip.is_private or ip.is_loopback or ip.is_link_local
    except ValueError:
        return host.lower() in ("localhost", "127.0.0.1", "::1")


def _sso_resp(row) -> SSOConfigResponse:
    d = dict(row)
    scopes = json.loads(d.get("scopes") or "[]")
    domains = json.loads(d.get("allowed_domains") or "[]")
    return SSOConfigResponse(
        id=d.get("id") or "",
        org_id=d.get("org_id") or "",
        enabled=bool(d.get("enabled")),
        issuer=d.get("issuer") or "",
        client_id=d.get("client_id") or "",
        has_secret=bool(d.get("client_secret_enc")),
        redirect_url=d.get("redirect_url") or "",
        scopes=scopes,
        allowed_domains=domains,
        auto_provision=bool(d.get("auto_provision")),
        default_role=d.get("default_role") or "member",
        group_sync=bool(d.get("group_sync")),
        group_claim=d.get("group_claim") or "",
        created_at=d.get("created_at") or "",
        updated_at=d.get("updated_at") or "",
    )


@router.get("/orgs/{org_id}/sso", response_model=SSOConfigResponse)
async def get_org_sso_config(
    org_id: str,
    key_info: KeyInfo = Depends(require_role(ROLE_ORG_ADMIN)),
) -> SSOConfigResponse:
    h = get_handler()
    _require_org_admin(key_info, org_id)
    row = await h.db.fetchone(
        "SELECT * FROM org_sso_configs WHERE org_id = ?", (org_id,)
    )
    if not row:
        raise not_found("sso configuration not found")
    return _sso_resp(row)


@router.put("/orgs/{org_id}/sso", response_model=SSOConfigResponse)
async def upsert_org_sso_config(
    org_id: str,
    body: SSOConfigRequest,
    key_info: KeyInfo = Depends(require_role(ROLE_ORG_ADMIN)),
) -> SSOConfigResponse:
    h = get_handler()
    _require_org_admin(key_info, org_id)
    if body.default_role not in ("member", "team_admin"):
        raise bad_request('default_role must be "member" or "team_admin"')
    scopes_json = json.dumps(body.scopes or [])
    domains_json = json.dumps(body.allowed_domains or [])
    existing = await h.db.fetchone("SELECT * FROM org_sso_configs WHERE org_id = ?", (org_id,))
    secret_enc = existing["client_secret_enc"] if existing else ""
    if body.client_secret:
        from cryptography.hazmat.primitives.ciphers.aead import AESGCM

        aes = AESGCM(h.encryption_key[:32])
        nonce = b"\x00" * 12
        ct = aes.encrypt(nonce, body.client_secret.encode(), f"org_sso:{org_id}".encode())
        secret_enc = (nonce + ct).hex()
    if existing:
        await h.db.execute(
            """UPDATE org_sso_configs SET enabled=?, issuer=?, client_id=?, client_secret_enc=?,
               redirect_url=?, scopes=?, allowed_domains=?, auto_provision=?, default_role=?,
               group_sync=?, group_claim=?, updated_at=CURRENT_TIMESTAMP WHERE org_id=?""",
            (
                int(body.enabled), body.issuer, body.client_id, secret_enc, body.redirect_url,
                scopes_json, domains_json, int(body.auto_provision), body.default_role,
                int(body.group_sync), body.group_claim, org_id,
            ),
        )
    else:
        cid = new_uuid()
        await h.db.execute(
            """INSERT INTO org_sso_configs (id, org_id, enabled, issuer, client_id, client_secret_enc,
               redirect_url, scopes, allowed_domains, auto_provision, default_role, group_sync,
               group_claim, created_at, updated_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)""",
            (
                cid, org_id, int(body.enabled), body.issuer, body.client_id, secret_enc,
                body.redirect_url, scopes_json, domains_json, int(body.auto_provision),
                body.default_role, int(body.group_sync), body.group_claim,
            ),
        )
    await h.db.commit()
    row = await h.db.fetchone("SELECT * FROM org_sso_configs WHERE org_id = ?", (org_id,))
    return _sso_resp(row)


@router.delete("/orgs/{org_id}/sso", status_code=status.HTTP_204_NO_CONTENT)
async def delete_org_sso_config(
    org_id: str,
    key_info: KeyInfo = Depends(require_role(ROLE_ORG_ADMIN)),
) -> Response:
    h = get_handler()
    _require_org_admin(key_info, org_id)
    cur = await h.db.execute("DELETE FROM org_sso_configs WHERE org_id = ?", (org_id,))
    await h.db.commit()
    if cur.rowcount == 0:
        raise not_found("sso configuration not found")
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/orgs/{org_id}/sso/test", response_model=TestSSOResponse)
async def test_sso_connection(
    org_id: str,
    body: TestSSORequest,
    key_info: KeyInfo = Depends(require_role(ROLE_ORG_ADMIN)),
) -> TestSSOResponse:
    _require_org_admin(key_info, org_id)
    if not body.issuer:
        raise bad_request("issuer is required")
    u = urlparse(body.issuer)
    if u.scheme not in ("https", "http"):
        raise bad_request("issuer must be a valid https URL")
    if u.scheme == "http" and u.hostname not in ("localhost", "127.0.0.1"):
        raise bad_request("issuer must use https (http is only allowed for localhost)")
    if u.hostname and _is_private_host(u.hostname):
        raise bad_request("issuer URL must not point to a private address")
    discovery = body.issuer.rstrip("/") + "/.well-known/openid-configuration"
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.get(discovery)
        if resp.status_code == 200:
            return TestSSOResponse(status="ok")
        return TestSSOResponse(status="error", message=f"HTTP {resp.status_code}")
    except Exception as e:
        return TestSSOResponse(status="error", message=str(e))
