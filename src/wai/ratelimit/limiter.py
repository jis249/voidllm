"""PostgreSQL-backed rate limiting (works across load-balanced instances)."""

from __future__ import annotations

import logging
from datetime import datetime, timezone

from wai.api.admin.common import KeyInfo, limit_reached
from wai.db.connection import Database

_SCOPE_CHECKS = (
    ("key", lambda k: k.id, "requests_per_minute", "requests_per_day", "daily_token_limit", "monthly_token_limit"),
    ("team", lambda k: k.team_id, "team_requests_per_minute", "team_requests_per_day", "team_daily_token_limit", "team_monthly_token_limit"),
    ("org", lambda k: k.org_id, "org_requests_per_minute", "org_requests_per_day", "org_daily_token_limit", "org_monthly_token_limit"),
)


def _minute_window() -> str:
    now = datetime.now(timezone.utc).replace(second=0, microsecond=0)
    return now.strftime("%Y-%m-%dT%H:%M:00+00:00")


def _day_window() -> str:
    now = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)
    return now.strftime("%Y-%m-%dT00:00:00+00:00")


def _month_window() -> str:
    now = datetime.now(timezone.utc).replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    return now.strftime("%Y-%m-%dT00:00:00+00:00")


class RateLimiter:
    """Enforces per-key/team/org request and token limits using shared DB counters."""

    def __init__(self, db: Database, *, log: logging.Logger | None = None) -> None:
        self._db = db
        self._log = log or logging.getLogger("wai.ratelimit")

    async def check_proxy_request(self, key_info: KeyInfo) -> None:
        """Raise limit_reached when any configured scope exceeds its request rate."""
        for scope_type, id_fn, rpm_attr, rpd_attr, _, _ in _SCOPE_CHECKS:
            scope_id = id_fn(key_info)
            if not scope_id:
                continue
            rpm = int(getattr(key_info, rpm_attr) or 0)
            rpd = int(getattr(key_info, rpd_attr) or 0)
            if rpm > 0:
                count = await self._increment(scope_type, scope_id, "minute", _minute_window())
                if count > rpm:
                    raise limit_reached("requests per minute limit exceeded")
            if rpd > 0:
                count = await self._increment(scope_type, scope_id, "day", _day_window())
                if count > rpd:
                    raise limit_reached("requests per day limit exceeded")

        await self._check_token_limits(key_info)

    async def check_token_usage(self, key_info: KeyInfo, tokens: int) -> None:
        """Verify token usage after a completed request would not exceed daily/monthly caps."""
        if tokens <= 0:
            return
        for scope_type, id_fn, _, _, daily_attr, monthly_attr in _SCOPE_CHECKS:
            scope_id = id_fn(key_info)
            if not scope_id:
                continue
            daily_limit = int(getattr(key_info, daily_attr) or 0)
            monthly_limit = int(getattr(key_info, monthly_attr) or 0)
            if daily_limit > 0:
                used = await self._sum_hourly_tokens(scope_type, scope_id, _day_window())
                if used + tokens > daily_limit:
                    raise limit_reached("daily token limit exceeded")
            if monthly_limit > 0:
                used = await self._sum_hourly_tokens(scope_type, scope_id, _month_window())
                if used + tokens > monthly_limit:
                    raise limit_reached("monthly token limit exceeded")

    async def _check_token_limits(self, key_info: KeyInfo) -> None:
        for scope_type, id_fn, _, _, daily_attr, monthly_attr in _SCOPE_CHECKS:
            scope_id = id_fn(key_info)
            if not scope_id:
                continue
            daily_limit = int(getattr(key_info, daily_attr) or 0)
            monthly_limit = int(getattr(key_info, monthly_attr) or 0)
            if daily_limit > 0:
                used = await self._sum_hourly_tokens(scope_type, scope_id, _day_window())
                if used >= daily_limit:
                    raise limit_reached("daily token limit exceeded")
            if monthly_limit > 0:
                used = await self._sum_hourly_tokens(scope_type, scope_id, _month_window())
                if used >= monthly_limit:
                    raise limit_reached("monthly token limit exceeded")

    async def _increment(self, scope_type: str, scope_id: str, window_type: str, window_start: str) -> int:
        row = await self._db.fetchone(
            """INSERT INTO rate_limit_counters (scope_type, scope_id, window_type, window_start, request_count)
               VALUES (?, ?, ?, ?, 1)
               ON CONFLICT (scope_type, scope_id, window_type, window_start)
               DO UPDATE SET request_count = rate_limit_counters.request_count + 1
               RETURNING request_count""",
            (scope_type, scope_id, window_type, window_start),
        )
        return int(row["request_count"]) if row else 1

    async def _sum_hourly_tokens(self, scope_type: str, scope_id: str, since_bucket: str) -> int:
        col = {"key": "key_id", "team": "team_id", "org": "org_id"}.get(scope_type)
        if not col:
            return 0
        row = await self._db.fetchone(
            f"SELECT COALESCE(SUM(total_tokens), 0) AS t FROM usage_hourly WHERE {col} = ? AND bucket_hour >= ?",
            (scope_id, since_bucket),
        )
        return int(row["t"]) if row else 0
