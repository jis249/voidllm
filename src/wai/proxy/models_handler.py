"""GET /v1/models handler."""

from __future__ import annotations

from fastapi import Request
from fastapi.responses import JSONResponse

from wai.api.admin.common import KEY_INFO_CTX, KeyInfo
from wai.proxy.access import ModelAccessCache
from wai.proxy.registry import Registry


def models_handler(
    registry: Registry,
    access_cache: ModelAccessCache | None,
) -> callable:
    async def handle(request: Request) -> JSONResponse:
        all_models = registry.list_info()
        key_info: KeyInfo | None = getattr(request.state, KEY_INFO_CTX, None)

        if access_cache is None or key_info is None:
            accessible = all_models
        else:
            accessible = [
                m
                for m in all_models
                if access_cache.check(key_info.org_id, key_info.team_id, key_info.id, m.name)
            ]

        data = [
            {
                "id": m.name,
                "object": "model",
                "created": 0,
                "owned_by": "wai",
                "aliases": m.aliases,
            }
            for m in accessible
        ]
        return JSONResponse({"object": "list", "data": data})

    return handle
