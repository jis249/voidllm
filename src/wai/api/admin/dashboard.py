"""Dashboard statistics handler."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field

from wai.api.admin.common import (
    KeyInfo,
    ROLE_ORG_ADMIN,
    ROLE_SYSTEM_ADMIN,
    ROLE_TEAM_ADMIN,
    internal_error,
)
from wai.api.admin.handler import auth_middleware, get_handler
from wai.api.admin import repository as repo

router = APIRouter()

WARN_THRESHOLD = 0.80


class BudgetWarning(BaseModel):
    window: str
    scope: str
    limit: int
    usage: int
    percent_used: float


class DashboardStatsResponse(BaseModel):
    scope: str
    active_keys: int = 0
    total_teams: int | None = None
    total_members: int | None = None
    requests_24h: int = 0
    tokens_24h: int = 0
    cost_estimate_24h: float = 0
    budget_warnings: list[BudgetWarning] = Field(default_factory=list)
    models_healthy: int = 0
    models_unhealthy: int = 0
    models_degraded: int = 0


@router.get("/dashboard/stats", response_model=DashboardStatsResponse)
async def dashboard_stats(key_info: KeyInfo = Depends(auth_middleware)) -> DashboardStatsResponse:
    h = get_handler()
    org_id = key_info.org_id
    from_dt = datetime.now(timezone.utc) - timedelta(hours=24)
    from_iso = from_dt.strftime("%Y-%m-%dT%H:%M:%S+00:00")
    resp = DashboardStatsResponse(scope="user")

    if key_info.role in (ROLE_SYSTEM_ADMIN, ROLE_ORG_ADMIN):
        resp.scope = "org"
        resp.active_keys = await repo.count_active_keys(h.db, org_id)
        resp.total_teams = await repo.count_teams(h.db, org_id)
        resp.total_members = await repo.count_org_members(h.db, org_id)
        team_id = ""
        user_id = ""
    elif key_info.role == ROLE_TEAM_ADMIN:
        team_id = key_info.team_id
        if not team_id:
            team_id = await repo.get_user_team_id(h.db, org_id, key_info.user_id)
        user_id = ""
        if team_id:
            resp.scope = "team"
            resp.active_keys = await repo.count_team_keys(h.db, team_id)
            resp.total_members = await repo.count_team_members(h.db, team_id)
        else:
            return resp
    else:
        team_id = ""
        user_id = key_info.user_id
        resp.scope = "user"
        resp.active_keys = await repo.count_user_keys(h.db, org_id, key_info.user_id)

    agg = await repo.get_hourly_usage_totals(h.db, org_id, team_id, user_id, from_iso)
    resp.requests_24h = int(agg.get("total_requests") or 0)
    resp.tokens_24h = int(agg.get("total_tokens") or 0)
    resp.cost_estimate_24h = float(agg.get("cost_estimate") or 0)

    if resp.scope == "org":
        org = await repo.get_org(h.db, org_id)
        if org:
            if org.get("daily_token_limit", 0) > 0:
                pct = resp.tokens_24h / org["daily_token_limit"]
                if pct >= WARN_THRESHOLD:
                    resp.budget_warnings.append(
                        BudgetWarning(
                            window="daily", scope="org",
                            limit=int(org["daily_token_limit"]),
                            usage=resp.tokens_24h, percent_used=pct,
                        )
                    )
            if org.get("monthly_token_limit", 0) > 0:
                monthly = await repo.get_monthly_token_usage(h.db, org_id)
                pct = monthly / org["monthly_token_limit"]
                if pct >= WARN_THRESHOLD:
                    resp.budget_warnings.append(
                        BudgetWarning(
                            window="monthly", scope="org",
                            limit=int(org["monthly_token_limit"]),
                            usage=monthly, percent_used=pct,
                        )
                    )

    if h.health_checker is not None:
        for mh in h.health_checker.get_all_health():
            status = mh.get("status") if isinstance(mh, dict) else getattr(mh, "status", "")
            if status == "healthy":
                resp.models_healthy += 1
            elif status == "unhealthy":
                resp.models_unhealthy += 1
            elif status == "degraded":
                resp.models_degraded += 1

    return resp
