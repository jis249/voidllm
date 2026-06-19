"""Model alias handlers."""

from __future__ import annotations

from fastapi import APIRouter, Depends, status
from pydantic import BaseModel

from wai.api.admin.common import (
    KeyInfo,
    ROLE_ORG_ADMIN,
    ROLE_SYSTEM_ADMIN,
    bad_request,
    forbidden,
    has_role,
    new_uuid,
    not_found,
)
from wai.api.admin.handler import get_handler, require_role

router = APIRouter()


class CreateAliasRequest(BaseModel):
    alias: str
    model_name: str


class AliasResponse(BaseModel):
    id: str
    alias: str
    model_name: str
    scope_type: str
    org_id: str | None = None
    team_id: str | None = None
    created_at: str


def _require_org_access(key_info: KeyInfo, org_id: str) -> None:
    if not has_role(key_info.role, ROLE_SYSTEM_ADMIN) and key_info.org_id != org_id:
        raise forbidden()


def _alias_resp(row) -> AliasResponse:
    d = dict(row)
    return AliasResponse(
        id=d["id"],
        alias=d["alias"],
        model_name=d["model_name"],
        scope_type=d["scope_type"],
        org_id=d.get("org_id"),
        team_id=d.get("team_id"),
        created_at=d["created_at"],
    )


@router.post("/orgs/{org_id}/model-aliases", response_model=AliasResponse, status_code=status.HTTP_201_CREATED)
async def create_org_alias(
    org_id: str,
    body: CreateAliasRequest,
    key_info: KeyInfo = Depends(require_role(ROLE_ORG_ADMIN)),
) -> AliasResponse:
    h = get_handler()
    _require_org_access(key_info, org_id)
    if not body.alias or not body.model_name:
        raise bad_request("alias and model_name are required")
    aid = new_uuid()
    await h.db.execute(
        """INSERT INTO model_aliases (id, alias, model_name, scope_type, org_id, team_id, created_by, created_at)
           VALUES (?, ?, ?, 'org', ?, NULL, ?, CURRENT_TIMESTAMP)""",
        (aid, body.alias, body.model_name, org_id, key_info.user_id),
    )
    await h.db.commit()
    row = await h.db.fetchone("SELECT * FROM model_aliases WHERE id = ?", (aid,))
    return _alias_resp(row)


@router.get("/orgs/{org_id}/model-aliases", response_model=list[AliasResponse])
async def list_org_aliases(
    org_id: str,
    key_info: KeyInfo = Depends(require_role(ROLE_ORG_ADMIN)),
) -> list[AliasResponse]:
    h = get_handler()
    _require_org_access(key_info, org_id)
    rows = await h.db.fetchall(
        "SELECT * FROM model_aliases WHERE org_id = ? AND scope_type = 'org' ORDER BY alias",
        (org_id,),
    )
    return [_alias_resp(r) for r in rows]


@router.delete("/orgs/{org_id}/model-aliases/{alias_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_org_alias(
    org_id: str,
    alias_id: str,
    key_info: KeyInfo = Depends(require_role(ROLE_ORG_ADMIN)),
):
    from fastapi import Response

    h = get_handler()
    _require_org_access(key_info, org_id)
    cur = await h.db.execute(
        "DELETE FROM model_aliases WHERE id = ? AND org_id = ? AND scope_type = 'org'",
        (alias_id, org_id),
    )
    await h.db.commit()
    if cur.rowcount == 0:
        raise not_found("alias not found")
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post(
    "/orgs/{org_id}/teams/{team_id}/model-aliases",
    response_model=AliasResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_team_alias(
    org_id: str,
    team_id: str,
    body: CreateAliasRequest,
    key_info: KeyInfo = Depends(require_role(ROLE_ORG_ADMIN)),
) -> AliasResponse:
    h = get_handler()
    _require_org_access(key_info, org_id)
    aid = new_uuid()
    await h.db.execute(
        """INSERT INTO model_aliases (id, alias, model_name, scope_type, org_id, team_id, created_by, created_at)
           VALUES (?, ?, ?, 'team', ?, ?, ?, CURRENT_TIMESTAMP)""",
        (aid, body.alias, body.model_name, org_id, team_id, key_info.user_id),
    )
    await h.db.commit()
    row = await h.db.fetchone("SELECT * FROM model_aliases WHERE id = ?", (aid,))
    return _alias_resp(row)


@router.get("/orgs/{org_id}/teams/{team_id}/model-aliases", response_model=list[AliasResponse])
async def list_team_aliases(
    org_id: str,
    team_id: str,
    key_info: KeyInfo = Depends(require_role(ROLE_ORG_ADMIN)),
) -> list[AliasResponse]:
    h = get_handler()
    _require_org_access(key_info, org_id)
    rows = await h.db.fetchall(
        "SELECT * FROM model_aliases WHERE team_id = ? AND scope_type = 'team' ORDER BY alias",
        (team_id,),
    )
    return [_alias_resp(r) for r in rows]


@router.delete("/orgs/{org_id}/teams/{team_id}/model-aliases/{alias_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_team_alias(
    org_id: str,
    team_id: str,
    alias_id: str,
    key_info: KeyInfo = Depends(require_role(ROLE_ORG_ADMIN)),
):
    from fastapi import Response

    h = get_handler()
    _require_org_access(key_info, org_id)
    cur = await h.db.execute(
        "DELETE FROM model_aliases WHERE id = ? AND team_id = ? AND scope_type = 'team'",
        (alias_id, team_id),
    )
    await h.db.commit()
    if cur.rowcount == 0:
        raise not_found("alias not found")
    return Response(status_code=status.HTTP_204_NO_CONTENT)
