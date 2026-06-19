"""Brute-force protection for login and invite redemption."""

from __future__ import annotations

import logging
from datetime import datetime, timezone

from wai.api.admin.common import rate_limited
from wai.config.models import RateLimitConfig
from wai.db.connection import Database


def _auth_window(minutes: int) -> str:
    now = datetime.now(timezone.utc)
    bucket = int(now.timestamp() // (minutes * 60))
    return f"auth-{minutes}m-{bucket}"


class BruteForceGuard:
    """IP-based attempt tracking stored in PostgreSQL (LB-safe)."""

    def __init__(self, db: Database, cfg: RateLimitConfig, *, log: logging.Logger | None = None) -> None:
        self._db = db
        self._cfg = cfg
        self._log = log or logging.getLogger("wai.bruteforce")

    async def check_allowed(self, ip: str, action: str) -> None:
        if not ip:
            return
        window_minutes, max_attempts = self._limits(action)
        count = await self._get_count(ip, action, window_minutes)
        if count >= max_attempts:
            self._log.warning("brute-force block action=%s ip=%s attempts=%d", action, ip, count)
            raise rate_limited("too many attempts, try again later")

    async def record_failure(self, ip: str, action: str) -> None:
        if not ip:
            return
        window_minutes, _ = self._limits(action)
        await self._increment(ip, action, window_minutes)

    async def clear(self, ip: str, action: str) -> None:
        if not ip:
            return
        window_minutes, _ = self._limits(action)
        window_start = _auth_window(window_minutes)
        await self._db.execute(
            "DELETE FROM rate_limit_counters WHERE scope_type = ? AND scope_id = ? AND window_type = ? AND window_start = ?",
            ("ip", f"{action}:{ip}", "auth", window_start),
        )

    def _limits(self, action: str) -> tuple[int, int]:
        if action == "invite_redeem":
            return self._cfg.invite_window_minutes, self._cfg.invite_max_attempts
        return self._cfg.login_window_minutes, self._cfg.login_max_attempts

    async def _get_count(self, ip: str, action: str, window_minutes: int) -> int:
        row = await self._db.fetchone(
            "SELECT request_count FROM rate_limit_counters WHERE scope_type = ? AND scope_id = ? AND window_type = ? AND window_start = ?",
            ("ip", f"{action}:{ip}", "auth", _auth_window(window_minutes)),
        )
        return int(row["request_count"]) if row else 0

    async def _increment(self, ip: str, action: str, window_minutes: int) -> None:
        window_start = _auth_window(window_minutes)
        await self._db.execute(
            """INSERT INTO rate_limit_counters (scope_type, scope_id, window_type, window_start, request_count)
               VALUES (?, ?, ?, ?, 1)
               ON CONFLICT (scope_type, scope_id, window_type, window_start)
               DO UPDATE SET request_count = rate_limit_counters.request_count + 1""",
            ("ip", f"{action}:{ip}", "auth", window_start),
        )
