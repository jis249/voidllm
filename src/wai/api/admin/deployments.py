"""Model deployment sub-resource handlers."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, status
from pydantic import BaseModel

from wai.api.admin.common import (
    KeyInfo,
    ROLE_SYSTEM_ADMIN,
    bad_request,
    new_uuid,
    not_found,
)
from wai.api.admin.handler import get_handler, require_role
from wai.api.admin.models import _fetch_model

router = APIRouter()


class CreateDeploymentRequest(BaseModel):
    name: str
    provider: str
    base_url: str
    api_key: str = ""
    azure_deployment: str = ""
    azure_api_version: str = ""
    gcp_project: str = ""
    gcp_location: str = ""
    weight: int = 1
    priority: int = 0


class UpdateDeploymentRequest(BaseModel):
    name: str | None = None
    provider: str | None = None
    base_url: str | None = None
    api_key: str | None = None
    azure_deployment: str | None = None
    azure_api_version: str | None = None
    gcp_project: str | None = None
    gcp_location: str | None = None
    weight: int | None = None
    priority: int | None = None


class DeploymentResponse(BaseModel):
    id: str
    model_id: str
    name: str
    provider: str
    base_url: str
    azure_deployment: str = ""
    azure_api_version: str = ""
    gcp_project: str = ""
    gcp_location: str = ""
    weight: int
    priority: int
    is_active: bool
    created_at: str
    updated_at: str


def _dep_resp(row: dict[str, Any]) -> DeploymentResponse:
    return DeploymentResponse(
        id=row["id"],
        model_id=row["model_id"],
        name=row["name"],
        provider=row["provider"],
        base_url=row["base_url"],
        azure_deployment=row.get("azure_deployment") or "",
        azure_api_version=row.get("azure_api_version") or "",
        gcp_project=row.get("gcp_project") or "",
        gcp_location=row.get("gcp_location") or "",
        weight=int(row.get("weight") or 1),
        priority=int(row.get("priority") or 0),
        is_active=bool(row.get("is_active", 1)),
        created_at=row["created_at"],
        updated_at=row["updated_at"],
    )


async def _get_deployment(h, model_id: str, deployment_id: str) -> dict[str, Any]:
    row = await h.db.fetchone(
        "SELECT * FROM model_deployments WHERE id = ? AND model_id = ? AND deleted_at IS NULL",
        (deployment_id, model_id),
    )
    if not row:
        raise not_found("deployment not found")
    return dict(row)


@router.post("/models/{model_id}/deployments", response_model=DeploymentResponse, status_code=status.HTTP_201_CREATED)
async def create_deployment(
    model_id: str,
    body: CreateDeploymentRequest,
    _: KeyInfo = Depends(require_role(ROLE_SYSTEM_ADMIN)),
) -> DeploymentResponse:
    h = get_handler()
    await _fetch_model(h, model_id)
    if not body.name or not body.provider or not body.base_url:
        raise bad_request("name, provider, and base_url are required")
    did = new_uuid()
    await h.db.execute(
        """INSERT INTO model_deployments (id, model_id, name, provider, base_url, api_key_encrypted,
                                            azure_deployment, azure_api_version, gcp_project, gcp_location,
                                            weight, priority, is_active, created_at, updated_at)
           VALUES (?, ?, ?, ?, ?, NULL, ?, ?, ?, ?, ?, ?, 1, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)""",
        (
            did, model_id, body.name, body.provider, body.base_url,
            body.azure_deployment, body.azure_api_version, body.gcp_project, body.gcp_location,
            body.weight, body.priority,
        ),
    )
    await h.db.commit()
    row = await _get_deployment(h, model_id, did)
    return _dep_resp(row)


@router.get("/models/{model_id}/deployments", response_model=list[DeploymentResponse])
async def list_deployments(
    model_id: str,
    _: KeyInfo = Depends(require_role(ROLE_SYSTEM_ADMIN)),
) -> list[DeploymentResponse]:
    h = get_handler()
    await _fetch_model(h, model_id)
    rows = await h.db.fetchall(
        "SELECT * FROM model_deployments WHERE model_id = ? AND deleted_at IS NULL ORDER BY priority, id",
        (model_id,),
    )
    return [_dep_resp(dict(r)) for r in rows]


@router.patch("/models/{model_id}/deployments/{deployment_id}", response_model=DeploymentResponse)
async def update_deployment(
    model_id: str,
    deployment_id: str,
    body: UpdateDeploymentRequest,
    _: KeyInfo = Depends(require_role(ROLE_SYSTEM_ADMIN)),
) -> DeploymentResponse:
    h = get_handler()
    await _get_deployment(h, model_id, deployment_id)
    fields = {k: v for k, v in body.model_dump(exclude_unset=True).items()}
    if fields:
        sets = ", ".join(f"{k} = ?" for k in fields)
        await h.db.execute(
            f"UPDATE model_deployments SET {sets}, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
            (*fields.values(), deployment_id),
        )
        await h.db.commit()
    return _dep_resp(await _get_deployment(h, model_id, deployment_id))


@router.delete("/models/{model_id}/deployments/{deployment_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_deployment(
    model_id: str,
    deployment_id: str,
    _: KeyInfo = Depends(require_role(ROLE_SYSTEM_ADMIN)),
):
    from fastapi import Response

    h = get_handler()
    cur = await h.db.execute(
        "UPDATE model_deployments SET deleted_at = CURRENT_TIMESTAMP WHERE id = ? AND model_id = ?",
        (deployment_id, model_id),
    )
    await h.db.commit()
    if cur.rowcount == 0:
        raise not_found("deployment not found")
    return Response(status_code=status.HTTP_204_NO_CONTENT)
