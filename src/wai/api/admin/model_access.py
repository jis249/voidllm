"""Model access control handlers."""

from __future__ import annotations

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field

from wai.api.admin.common import (
    KeyInfo,
    ROLE_ORG_ADMIN,
    ROLE_SYSTEM_ADMIN,
    ROLE_TEAM_ADMIN,
    bad_request,
    forbidden,
    has_role,
    internal_error,
    not_found,
)
from wai.api.admin.handler import get_handler, require_role
from wai.api.admin import repository as repo

router = APIRouter()


class ModelAccessRequest(BaseModel):
    models: list[str] = Field(default_factory=list)


class ModelAccessResponse(BaseModel):
    models: list[str] = Field(default_factory=list)


def _require_org_access(key_info: KeyInfo, org_id: str) -> None:
    if not has_role(key_info.role, ROLE_SYSTEM_ADMIN) and key_info.org_id != org_id:
        raise forbidden()


async def _validate_model_names(h, models: list[str]) -> None:
    seen: set[str] = set()
    for name in models:
        if name in seen:
            raise bad_request(f"duplicate model: {name}")
        seen.add(name)
        try:
            h.registry.resolve(name)
        except KeyError:
            raise bad_request(f"unknown model: {name}")


@router.get("/orgs/{org_id}/model-access", response_model=ModelAccessResponse)
async def get_org_model_access(
    org_id: str,
    key_info: KeyInfo = Depends(require_role(ROLE_ORG_ADMIN)),
) -> ModelAccessResponse:
    h = get_handler()
    _require_org_access(key_info, org_id)
    models = await repo.get_org_model_access(h.db, org_id)
    return ModelAccessResponse(models=models)


@router.put("/orgs/{org_id}/model-access", response_model=ModelAccessResponse)
async def set_org_model_access(
    org_id: str,
    body: ModelAccessRequest,
    key_info: KeyInfo = Depends(require_role(ROLE_ORG_ADMIN)),
) -> ModelAccessResponse:
    h = get_handler()
    _require_org_access(key_info, org_id)
    await _validate_model_names(h, body.models)
    await repo.set_org_model_access(h.db, org_id, body.models)
    await h.refresh_access_cache()
    return ModelAccessResponse(models=body.models)


@router.get("/orgs/{org_id}/teams/{team_id}/model-access", response_model=ModelAccessResponse)
async def get_team_model_access(
    org_id: str,
    team_id: str,
    key_info: KeyInfo = Depends(require_role(ROLE_TEAM_ADMIN)),
) -> ModelAccessResponse:
    h = get_handler()
    _require_org_access(key_info, org_id)
    team = await repo.get_team(h.db, team_id)
    if not team or team["org_id"] != org_id:
        raise not_found("team not found")
    if not has_role(key_info.role, ROLE_ORG_ADMIN):
        if not await repo.is_team_member(h.db, key_info.user_id, team_id):
            raise not_found("team not found")
    models = await repo.get_team_model_access(h.db, team_id)
    return ModelAccessResponse(models=models)


@router.put("/orgs/{org_id}/teams/{team_id}/model-access", response_model=ModelAccessResponse)
async def set_team_model_access(
    org_id: str,
    team_id: str,
    body: ModelAccessRequest,
    key_info: KeyInfo = Depends(require_role(ROLE_TEAM_ADMIN)),
) -> ModelAccessResponse:
    h = get_handler()
    _require_org_access(key_info, org_id)
    team = await repo.get_team(h.db, team_id)
    if not team or team["org_id"] != org_id:
        raise not_found("team not found")
    if not has_role(key_info.role, ROLE_ORG_ADMIN):
        if not await repo.is_team_member(h.db, key_info.user_id, team_id):
            raise not_found("team not found")
    await _validate_model_names(h, body.models)
    if body.models:
        org_models = await repo.get_org_model_access(h.db, org_id)
        if org_models:
            for name in body.models:
                if name not in org_models:
                    raise bad_request(f"model not allowed by org: {name}")
    await repo.set_team_model_access(h.db, team_id, body.models)
    await h.refresh_access_cache()
    return ModelAccessResponse(models=body.models)


@router.get("/orgs/{org_id}/keys/{key_id}/model-access", response_model=ModelAccessResponse)
async def get_key_model_access(
    org_id: str,
    key_id: str,
    key_info: KeyInfo = Depends(require_role(ROLE_ORG_ADMIN)),
) -> ModelAccessResponse:
    h = get_handler()
    _require_org_access(key_info, org_id)
    key = await repo.get_api_key(h.db, key_id)
    if not key or key["org_id"] != org_id:
        raise not_found("api key not found")
    models = await repo.get_key_model_access(h.db, key_id)
    return ModelAccessResponse(models=models)


@router.put("/orgs/{org_id}/keys/{key_id}/model-access", response_model=ModelAccessResponse)
async def set_key_model_access(
    org_id: str,
    key_id: str,
    body: ModelAccessRequest,
    key_info: KeyInfo = Depends(require_role(ROLE_ORG_ADMIN)),
) -> ModelAccessResponse:
    h = get_handler()
    _require_org_access(key_info, org_id)
    key = await repo.get_api_key(h.db, key_id)
    if not key or key["org_id"] != org_id:
        raise not_found("api key not found")
    await _validate_model_names(h, body.models)
    if body.models and key.get("team_id"):
        team_models = await repo.get_team_model_access(h.db, key["team_id"])
        if team_models:
            for name in body.models:
                if name not in team_models:
                    raise bad_request(f"model not allowed by team: {name}")
    if body.models:
        org_models = await repo.get_org_model_access(h.db, org_id)
        if org_models:
            for name in body.models:
                if name not in org_models:
                    raise bad_request(f"model not allowed by org: {name}")
    await repo.set_key_model_access(h.db, key_id, body.models)
    await h.refresh_access_cache()
    return ModelAccessResponse(models=body.models)
