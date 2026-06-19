"""Background batched writer for proxy usage events."""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from datetime import datetime, timezone

from wai.api.admin.common import new_uuid
from wai.config.models import UsageConfig
from wai.db.connection import Database
from wai.usage.event import UsageEvent

_MAX_MODEL_NAME_LEN = 256

_USAGE_EVENT_SQL = """INSERT INTO usage_events (
       id, request_id, key_id, key_type, org_id, team_id, user_id,
       service_account_id, model_name, requested_model_name,
       prompt_tokens, completion_tokens, total_tokens, cost_estimate,
       request_duration_ms, ttft_ms, tokens_per_second, status_code
   ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)"""


def _truncate(value: str) -> str:
    if len(value) <= _MAX_MODEL_NAME_LEN:
        return value
    return value[:_MAX_MODEL_NAME_LEN]


def _bucket_hour(iso_ts: str | None = None) -> str:
    dt = datetime.now(timezone.utc)
    if iso_ts:
        try:
            dt = datetime.fromisoformat(iso_ts.replace("Z", "+00:00"))
        except ValueError:
            pass
    dt = dt.astimezone(timezone.utc).replace(minute=0, second=0, microsecond=0)
    return dt.strftime("%Y-%m-%dT%H:00:00+00:00")


@dataclass
class _Rollup:
    org_id: str
    team_id: str
    user_id: str
    key_id: str
    model_name: str
    bucket_hour: str
    request_count: int = 0
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0
    cost_sum: float = 0.0
    duration_sum_ms: float = 0.0
    ttft_sum_ms: float = 0.0
    ttft_count: int = 0


class UsageLogger:
    def __init__(
        self,
        db: Database,
        cfg: UsageConfig,
        *,
        log: logging.Logger | None = None,
    ) -> None:
        self._db = db
        self._buffer_size = cfg.buffer_size or 1000
        self._interval = max(cfg.flush_interval.total_seconds(), 1.0)
        drop = cfg.drop_on_full
        self._drop_on_full = True if drop is None else drop
        self._log = log or logging.getLogger("wai.usage")
        self._queue: asyncio.Queue[UsageEvent | None] = asyncio.Queue(maxsize=self._buffer_size)
        self._task: asyncio.Task[None] | None = None

    async def start(self) -> None:
        self._task = asyncio.create_task(self._run(), name="usage-logger")

    async def stop(self) -> None:
        await self._queue.put(None)
        if self._task is not None:
            await self._task

    def log(self, event: UsageEvent) -> None:
        event.model_name = _truncate(event.model_name)
        event.requested_model_name = _truncate(event.requested_model_name)
        try:
            self._queue.put_nowait(event)
        except asyncio.QueueFull:
            if self._drop_on_full:
                self._log.warning(
                    "usage logger buffer full, dropping event for model=%s key=%s",
                    event.model_name,
                    event.key_id,
                )
            else:
                self._log.warning(
                    "usage logger buffer full, dropping event for model=%s key=%s",
                    event.model_name,
                    event.key_id,
                )

    async def _run(self) -> None:
        batch: list[UsageEvent] = []
        try:
            while True:
                try:
                    event = await asyncio.wait_for(self._queue.get(), timeout=self._interval)
                except TimeoutError:
                    await self._flush(batch)
                    batch = []
                    continue
                if event is None:
                    await self._flush(batch)
                    return
                batch.append(event)
                if len(batch) >= self._buffer_size:
                    await self._flush(batch)
                    batch = []
        except asyncio.CancelledError:
            await self._flush(batch)
            raise

    async def _flush(self, batch: list[UsageEvent]) -> None:
        if not batch:
            return
        rollups: dict[tuple[str, str, str], _Rollup] = {}
        try:
            async with self._db.transaction() as tx:
                event_rows: list[tuple] = []
                for ev in batch:
                    event_rows.append(
                        (
                            new_uuid(),
                            ev.request_id,
                            ev.key_id,
                            ev.key_type,
                            ev.org_id,
                            ev.team_id or None,
                            ev.user_id or None,
                            ev.service_account_id or None,
                            ev.model_name,
                            ev.requested_model_name or None,
                            ev.prompt_tokens,
                            ev.completion_tokens,
                            ev.total_tokens,
                            ev.cost_estimate,
                            ev.request_duration_ms,
                            ev.ttft_ms,
                            ev.tokens_per_second,
                            ev.status_code,
                        )
                    )
                    bucket = _bucket_hour()
                    key = (ev.key_id, ev.model_name, bucket)
                    rollup = rollups.get(key)
                    if rollup is None:
                        rollup = _Rollup(
                            org_id=ev.org_id,
                            team_id=ev.team_id or "",
                            user_id=ev.user_id or "",
                            key_id=ev.key_id,
                            model_name=ev.model_name,
                            bucket_hour=bucket,
                        )
                        rollups[key] = rollup
                    rollup.request_count += 1
                    rollup.prompt_tokens += ev.prompt_tokens
                    rollup.completion_tokens += ev.completion_tokens
                    rollup.total_tokens += ev.total_tokens
                    rollup.cost_sum += ev.cost_estimate or 0.0
                    rollup.duration_sum_ms += ev.request_duration_ms
                    if ev.ttft_ms is not None:
                        rollup.ttft_sum_ms += ev.ttft_ms
                        rollup.ttft_count += 1

                if event_rows:
                    await tx.executemany(_USAGE_EVENT_SQL, event_rows)

                for r in rollups.values():
                    await tx.execute(
                        """INSERT INTO usage_hourly (
                               org_id, team_id, user_id, key_id, model_name, bucket_hour,
                               request_count, prompt_tokens, completion_tokens, total_tokens,
                               cost_sum, duration_sum_ms, ttft_sum_ms, ttft_count
                           ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                           ON CONFLICT (key_id, model_name, bucket_hour) DO UPDATE SET
                               request_count = usage_hourly.request_count + excluded.request_count,
                               prompt_tokens = usage_hourly.prompt_tokens + excluded.prompt_tokens,
                               completion_tokens = usage_hourly.completion_tokens + excluded.completion_tokens,
                               total_tokens = usage_hourly.total_tokens + excluded.total_tokens,
                               cost_sum = usage_hourly.cost_sum + excluded.cost_sum,
                               duration_sum_ms = usage_hourly.duration_sum_ms + excluded.duration_sum_ms,
                               ttft_sum_ms = usage_hourly.ttft_sum_ms + excluded.ttft_sum_ms,
                               ttft_count = usage_hourly.ttft_count + excluded.ttft_count""",
                        (
                            r.org_id,
                            r.team_id,
                            r.user_id,
                            r.key_id,
                            r.model_name,
                            r.bucket_hour,
                            r.request_count,
                            r.prompt_tokens,
                            r.completion_tokens,
                            r.total_tokens,
                            r.cost_sum,
                            r.duration_sum_ms,
                            r.ttft_sum_ms,
                            r.ttft_count,
                        ),
                    )
        except Exception as exc:
            self._log.error("usage flush failed (%d events): %s", len(batch), exc)
