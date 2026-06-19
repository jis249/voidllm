"""Model CRUD and health handlers."""

from __future__ import annotations

from typing import Any

import httpx
from fastapi import APIRouter, Depends, Query, Response, status
from pydantic import BaseModel, Field

from wai.api.admin.common import (
    KeyInfo,
    ROLE_MEMBER,
    ROLE_SYSTEM_ADMIN,
    bad_request,
    internal_error,
    new_uuid,
    not_found,
    parse_pagination,
)
from wai.api.admin.handler import get_handler, require_role
from wai.api.admin import repository as repo

router = APIRouter()

VALID_PROVIDERS = {"vllm", "openai", "anthropic", "azure", "custom", "vertex"}
VALID_TYPES = {
    "chat", "embedding", "reranking", "completion", "image", "audio_transcription", "tts"
}


class CreateModelRequest(BaseModel):
    name: str
    provider: str
    type: str = "chat"
    base_url: str
    api_key: str = ""
    max_context_tokens: int = 0
    input_price_per_1m: float = 0
    output_price_per_1m: float = 0
    azure_deployment: str = ""
    azure_api_version: str = ""
    gcp_project: str = ""
    gcp_location: str = ""
    aliases: list[str] = Field(default_factory=list)
    timeout: str = ""
    strategy: str = ""
    max_retries: int = 0
    fallback_model_name: str = ""


class UpdateModelRequest(BaseModel):
    name: str | None = None
    provider: str | None = None
    type: str | None = None
    base_url: str | None = None
    api_key: str | None = None
    max_context_tokens: int | None = None
    input_price_per_1m: float | None = None
    output_price_per_1m: float | None = None
    azure_deployment: str | None = None
    azure_api_version: str | None = None
    gcp_project: str | None = None
    gcp_location: str | None = None
    aliases: list[str] | None = None
    timeout: str | None = None
    strategy: str | None = None
    max_retries: int | None = None
    fallback_model_name: str | None = None


class ModelResponse(BaseModel):
    id: str
    name: str
    provider: str
    type: str
    base_url: str
    max_context_tokens: int
    input_price_per_1m: float
    output_price_per_1m: float
    azure_deployment: str = ""
    azure_api_version: str = ""
    gcp_project: str = ""
    gcp_location: str = ""
    is_active: bool
    source: str
    aliases: list[str] = Field(default_factory=list)
    timeout: str = ""
    strategy: str = ""
    max_retries: int = 0
    fallback_model_name: str = ""
    created_at: str
    updated_at: str


class PaginatedModelsResponse(BaseModel):
    data: list[ModelResponse]
    has_more: bool
    next_cursor: str | None = None


class TestConnectionRequest(BaseModel):
    provider: str
    base_url: str
    api_key: str = ""
    azure_deployment: str = ""
    azure_api_version: str = ""


class TestConnectionResponse(BaseModel):
    status: str
    message: str = ""


class ModelHealthResponse(BaseModel):
    models: list[dict[str, Any]]


def _model_resp(row: dict[str, Any]) -> ModelResponse:
    aliases = row.get("aliases", "") or ""
    alias_list = [a.strip() for a in aliases.split(",") if a.strip()] if aliases else []
    return ModelResponse(
        id=row["id"],
        name=row["name"],
        provider=row["provider"],
        type=row.get("model_type") or row.get("type") or "chat",
        base_url=row["base_url"],
        max_context_tokens=int(row.get("max_context_tokens") or 0),
        input_price_per_1m=float(row.get("input_price_per_1m") or 0),
        output_price_per_1m=float(row.get("output_price_per_1m") or 0),
        azure_deployment=row.get("azure_deployment") or "",
        azure_api_version=row.get("azure_api_version") or "",
        gcp_project=row.get("gcp_project") or "",
        gcp_location=row.get("gcp_location") or "",
        is_active=bool(row.get("is_active", 1)),
        source=row.get("source") or "api",
        aliases=alias_list,
        timeout=row.get("timeout") or "",
        strategy=row.get("strategy") or "",
        max_retries=int(row.get("max_retries") or 0),
        fallback_model_name=row.get("fallback_model_name") or "",
        created_at=row["created_at"],
        updated_at=row["updated_at"],
    )


async def _fetch_model(h, model_id: str) -> dict[str, Any]:
    row = await h.db.fetchone(
        "SELECT * FROM models WHERE id = ? AND deleted_at IS NULL", (model_id,)
    )
    if not row:
        raise not_found("model not found")
    return dict(row)


@router.get("/models/health", response_model=ModelHealthResponse)
async def get_model_health(_: KeyInfo = Depends(require_role(ROLE_MEMBER))) -> ModelHealthResponse:
    h = get_handler()
    if h.health_checker is None:
        return ModelHealthResponse(models=[])
    return ModelHealthResponse(models=h.health_checker.get_all_health())


@router.post("/models/test-connection", response_model=TestConnectionResponse)
async def test_model_connection(
    body: TestConnectionRequest,
    _: KeyInfo = Depends(require_role(ROLE_SYSTEM_ADMIN)),
) -> TestConnectionResponse:
    if body.provider not in VALID_PROVIDERS:
        raise bad_request("invalid provider")
    url = body.base_url.rstrip("/") + "/models"
    headers = {}
    if body.api_key:
        headers["Authorization"] = f"Bearer {body.api_key}"
    try:
        async with httpx.AsyncClient(timeout=10.0, follow_redirects=False) as client:
            resp = await client.get(url, headers=headers)
        if resp.status_code < 500:
            return TestConnectionResponse(status="ok")
        return TestConnectionResponse(status="error", message=f"upstream returned {resp.status_code}")
    except Exception as e:
        return TestConnectionResponse(status="error", message=str(e))


@router.post("/models", response_model=ModelResponse, status_code=status.HTTP_201_CREATED)
async def create_model(
    body: CreateModelRequest,
    key_info: KeyInfo = Depends(require_role(ROLE_SYSTEM_ADMIN)),
) -> ModelResponse:
    h = get_handler()
    if not body.name or not body.provider or not body.base_url:
        raise bad_request("name, provider, and base_url are required")
    if body.type not in VALID_TYPES:
        raise bad_request("invalid model type")
    mid = new_uuid()
    aliases = ",".join(body.aliases)
    await h.db.execute(
        """INSERT INTO models (id, name, provider, model_type, base_url, max_context_tokens,
                                input_price_per_1m, output_price_per_1m, azure_deployment,
                                azure_api_version, gcp_project, gcp_location, aliases, timeout,
                                strategy, max_retries, fallback_model_name, is_active, source,
                                created_by, created_at, updated_at)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 1, 'api', ?, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)""",
        (
            mid, body.name, body.provider, body.type, body.base_url, body.max_context_tokens,
            body.input_price_per_1m, body.output_price_per_1m, body.azure_deployment,
            body.azure_api_version, body.gcp_project, body.gcp_location, aliases, body.timeout,
            body.strategy, body.max_retries, body.fallback_model_name, key_info.user_id,
        ),
    )
    await h.db.commit()
    row = await _fetch_model(h, mid)
    h.registry.reload(await _list_all_models(h))
    return _model_resp(row)


@router.get("/models", response_model=PaginatedModelsResponse)
async def list_models(
    limit: int | None = Query(20),
    cursor: str | None = Query(None),
    _: KeyInfo = Depends(require_role(ROLE_SYSTEM_ADMIN)),
) -> PaginatedModelsResponse:
    h = get_handler()
    p = parse_pagination(limit, cursor)
    params: list[Any] = []
    cursor_clause = ""
    if p.cursor:
        cursor_clause = "AND id > ?"
        params.append(p.cursor)
    params.append(p.limit + 1)
    rows = await h.db.fetchall(
        f"""SELECT * FROM models WHERE deleted_at IS NULL {cursor_clause}
            ORDER BY id LIMIT ?""",
        tuple(params),
    )
    models = [dict(r) for r in rows]
    has_more = len(models) > p.limit
    if has_more:
        models = models[: p.limit]
    return PaginatedModelsResponse(
        data=[_model_resp(m) for m in models],
        has_more=has_more,
        next_cursor=models[-1]["id"] if has_more and models else None,
    )


@router.get("/models/{model_id}", response_model=ModelResponse)
async def get_model(
    model_id: str,
    _: KeyInfo = Depends(require_role(ROLE_SYSTEM_ADMIN)),
) -> ModelResponse:
    h = get_handler()
    row = await _fetch_model(h, model_id)
    return _model_resp(row)


@router.patch("/models/{model_id}", response_model=ModelResponse)
async def update_model(
    model_id: str,
    body: UpdateModelRequest,
    _: KeyInfo = Depends(require_role(ROLE_SYSTEM_ADMIN)),
) -> ModelResponse:
    h = get_handler()
    await _fetch_model(h, model_id)
    fields: dict[str, Any] = {}
    data = body.model_dump(exclude_unset=True)
    if "type" in data:
        fields["model_type"] = data.pop("type")
    if "aliases" in data and data["aliases"] is not None:
        fields["aliases"] = ",".join(data.pop("aliases"))
    fields.update(data)
    if fields:
        sets = ", ".join(f"{k} = ?" for k in fields)
        await h.db.execute(
            f"UPDATE models SET {sets}, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
            (*fields.values(), model_id),
        )
        await h.db.commit()
    row = await _fetch_model(h, model_id)
    h.registry.reload(await _list_all_models(h))
    return _model_resp(row)


@router.delete("/models/{model_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_model(
    model_id: str,
    _: KeyInfo = Depends(require_role(ROLE_SYSTEM_ADMIN)),
) -> Response:
    h = get_handler()
    cur = await h.db.execute(
        "UPDATE models SET deleted_at = CURRENT_TIMESTAMP WHERE id = ? AND deleted_at IS NULL",
        (model_id,),
    )
    await h.db.commit()
    if cur.rowcount == 0:
        raise not_found("model not found")
    h.registry.reload(await _list_all_models(h))
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.patch("/models/{model_id}/activate", response_model=ModelResponse)
async def activate_model(
    model_id: str,
    _: KeyInfo = Depends(require_role(ROLE_SYSTEM_ADMIN)),
) -> ModelResponse:
    h = get_handler()
    await h.db.execute(
        "UPDATE models SET is_active = 1, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
        (model_id,),
    )
    await h.db.commit()
    return _model_resp(await _fetch_model(h, model_id))


@router.patch("/models/{model_id}/deactivate", response_model=ModelResponse)
async def deactivate_model(
    model_id: str,
    _: KeyInfo = Depends(require_role(ROLE_SYSTEM_ADMIN)),
) -> ModelResponse:
    h = get_handler()
    await h.db.execute(
        "UPDATE models SET is_active = 0, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
        (model_id,),
    )
    await h.db.commit()
    return _model_resp(await _fetch_model(h, model_id))


async def _list_all_models(h) -> list[dict[str, Any]]:
    rows = await h.db.fetchall(
        "SELECT name, model_type AS type FROM models WHERE deleted_at IS NULL AND is_active = 1"
    )
    return [dict(r) for r in rows]
