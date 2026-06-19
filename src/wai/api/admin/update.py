"""Update check status handler."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends

from wai.api.admin.common import KeyInfo
from wai.api.admin.handler import auth_middleware, get_handler

router = APIRouter()


@router.get("/system/update-check")
async def get_update_status(_: KeyInfo = Depends(auth_middleware)) -> dict[str, Any]:
    h = get_handler()
    if h.update_checker is None:
        return {"current_version": "dev", "needs_update": False}
    if hasattr(h.update_checker, "get_info"):
        return h.update_checker.get_info()
    return {"current_version": "dev", "needs_update": False}
