"""Buffered audit event writer."""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass

from wai.api.admin.common import new_uuid, utc_now_iso
from wai.db.connection import Database


@dataclass
class AuditEvent:
    request_id: str = ""
    org_id: str = ""
    actor_id: str = ""
    actor_type: str = ""
    actor_key_id: str = ""
    action: str = ""
    resource_type: str = ""
    resource_id: str = ""
    description: str = ""
    ip_address: str = ""
    status_code: int = 0


class AuditLogger:
    def __init__(self, db: Database, *, buffer_size: int = 256, log: logging.Logger | None = None) -> None:
        self._db = db
        self._buffer_size = buffer_size
        self._log = log or logging.getLogger("wai.audit")
        self._queue: asyncio.Queue[AuditEvent | None] = asyncio.Queue(maxsize=buffer_size)
        self._task: asyncio.Task[None] | None = None

    async def start(self) -> None:
        self._task = asyncio.create_task(self._run(), name="audit-logger")

    async def stop(self) -> None:
        await self._queue.put(None)
        if self._task is not None:
            await self._task

    def log(self, event: AuditEvent) -> None:
        try:
            self._queue.put_nowait(event)
        except asyncio.QueueFull:
            self._log.warning("audit buffer full, dropping action=%s", event.action)

    async def log_now(self, event: AuditEvent) -> None:
        await self._insert(event)

    async def _run(self) -> None:
        batch: list[AuditEvent] = []
        try:
            while True:
                event = await self._queue.get()
                if event is None:
                    for ev in batch:
                        await self._insert(ev)
                    return
                batch.append(event)
                if len(batch) >= self._buffer_size:
                    for ev in batch:
                        await self._insert(ev)
                    batch = []
        except asyncio.CancelledError:
            for ev in batch:
                await self._insert(ev)
            raise

    async def _insert(self, event: AuditEvent) -> None:
        try:
            await self._db.execute(
                """INSERT INTO audit_logs (
                       id, request_id, timestamp, org_id, actor_id, actor_type, actor_key_id,
                       action, resource_type, resource_id, description, ip_address, status_code
                   ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    new_uuid(),
                    event.request_id,
                    utc_now_iso(),
                    event.org_id,
                    event.actor_id,
                    event.actor_type,
                    event.actor_key_id,
                    event.action,
                    event.resource_type,
                    event.resource_id,
                    event.description,
                    event.ip_address,
                    event.status_code,
                ),
            )
        except Exception as exc:
            self._log.error("audit insert failed action=%s: %s", event.action, exc)
