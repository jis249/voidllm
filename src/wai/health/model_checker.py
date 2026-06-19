"""Periodic upstream health probes for configured LLM models."""

from __future__ import annotations

import asyncio
import json
import logging
import time
from datetime import datetime, timezone
from typing import Any

import httpx

from wai.crypto.aes import decrypt_string
from wai.db.connection import Database
from wai.proxy.providers.azure import AzureAdapter
from wai.proxy.registry import Model


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S+00:00")


class ModelHealthChecker:
    """Probes each active model's upstream /models endpoint on a fixed interval."""

    INTERVAL_SECONDS = 60.0
    REQUEST_TIMEOUT = 15.0

    def __init__(
        self,
        db: Database,
        encryption_key: bytes,
        *,
        log: logging.Logger | None = None,
    ) -> None:
        self.db = db
        self.encryption_key = encryption_key
        self.log = log or logging.getLogger("wai.health")
        self._health: dict[str, dict[str, Any]] = {}
        self._task: asyncio.Task[None] | None = None
        self._stop = asyncio.Event()

    async def start(self) -> None:
        await self.probe_all()
        self._task = asyncio.create_task(self._loop(), name="model-health-checker")

    async def stop(self) -> None:
        self._stop.set()
        if self._task is not None:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass

    def get_all_health(self) -> list[dict[str, Any]]:
        return list(self._health.values())

    async def _loop(self) -> None:
        while not self._stop.is_set():
            try:
                await asyncio.wait_for(self._stop.wait(), timeout=self.INTERVAL_SECONDS)
            except TimeoutError:
                await self.probe_all()

    async def probe_all(self) -> None:
        rows = await self.db.fetchall(
            """SELECT id, name, provider, base_url, api_key_encrypted,
                      azure_deployment, azure_api_version
               FROM models WHERE deleted_at IS NULL AND is_active = 1"""
        )
        for row in rows:
            item = dict(row)
            name = item["name"]
            try:
                self._health[name] = await self._probe_model(item)
            except Exception as exc:
                self.log.warning("health probe failed for %s: %s", name, exc)
                self._health[name] = self._build_result(
                    name,
                    status="unhealthy",
                    latency_ms=0,
                    health_ok=False,
                    models_ok=False,
                    functional_ok=False,
                    last_error=str(exc),
                )

    async def _probe_model(self, row: dict[str, Any]) -> dict[str, Any]:
        started = time.perf_counter()
        url = self._models_url(row)
        headers = self._auth_headers(row)
        async with httpx.AsyncClient(timeout=self.REQUEST_TIMEOUT, follow_redirects=False) as client:
            resp = await client.get(url, headers=headers)
        latency_ms = int((time.perf_counter() - started) * 1000)

        health_ok = resp.status_code < 500
        if not health_ok:
            return self._build_result(
                row["name"],
                status="unhealthy",
                latency_ms=latency_ms,
                health_ok=False,
                models_ok=False,
                functional_ok=False,
                last_error=f"upstream returned {resp.status_code}",
            )

        models_ok = False
        functional_ok = False
        last_error = ""

        if resp.status_code < 400:
            models_ok, functional_ok, last_error = self._evaluate_models_response(
                row["name"],
                row.get("provider") or "",
                resp.content,
            )

        if health_ok and models_ok and functional_ok:
            status = "healthy"
        elif health_ok and models_ok:
            status = "degraded"
        elif health_ok:
            status = "degraded"
        else:
            status = "unhealthy"

        return self._build_result(
            row["name"],
            status=status,
            latency_ms=latency_ms,
            health_ok=health_ok,
            models_ok=models_ok,
            functional_ok=functional_ok,
            last_error=last_error,
        )

    def _models_url(self, row: dict[str, Any]) -> str:
        provider = row.get("provider") or ""
        if provider == "azure":
            model = Model(
                name=row["name"],
                provider=provider,
                base_url=row.get("base_url") or "",
                azure_deployment=row.get("azure_deployment") or "",
                azure_api_version=row.get("azure_api_version") or "",
            )
            return AzureAdapter().transform_url(model.base_url, "models", model)
        return (row.get("base_url") or "").rstrip("/") + "/models"

    def _auth_headers(self, row: dict[str, Any]) -> dict[str, str]:
        api_key = ""
        encrypted = row.get("api_key_encrypted")
        if encrypted:
            try:
                api_key = decrypt_string(
                    encrypted,
                    self.encryption_key,
                    f"model:{row['id']}".encode(),
                )
            except Exception as exc:
                self.log.warning("failed to decrypt api key for %s: %s", row["name"], exc)

        provider = row.get("provider") or ""
        if provider == "azure" and api_key:
            return {"api-key": api_key}
        if api_key:
            return {"Authorization": f"Bearer {api_key}"}
        return {}

    @staticmethod
    def _evaluate_models_response(
        model_name: str,
        provider: str,
        body: bytes,
    ) -> tuple[bool, bool, str]:
        try:
            doc = json.loads(body)
        except json.JSONDecodeError:
            return False, False, "invalid JSON from upstream"

        ids: set[str] = set()
        if isinstance(doc.get("data"), list):
            for item in doc["data"]:
                if isinstance(item, dict):
                    for key in ("id", "name", "model"):
                        if item.get(key):
                            ids.add(str(item[key]))
        if isinstance(doc.get("models"), list):
            for item in doc["models"]:
                if isinstance(item, dict):
                    for key in ("name", "model", "id"):
                        if item.get(key):
                            ids.add(str(item[key]))

        if not ids:
            return False, False, "no models in upstream response"

        if provider == "azure":
            return True, True, ""

        if model_name in ids:
            return True, True, ""

        base_name = model_name.split(":")[0]
        if any(mid == base_name or mid.startswith(f"{base_name}:") for mid in ids):
            return True, True, ""

        return True, False, f"model {model_name!r} not found in upstream list"

    @staticmethod
    def _build_result(
        name: str,
        *,
        status: str,
        latency_ms: int,
        health_ok: bool,
        models_ok: bool,
        functional_ok: bool,
        last_error: str = "",
    ) -> dict[str, Any]:
        result: dict[str, Any] = {
            "name": name,
            "status": status,
            "latency_ms": latency_ms,
            "last_check": _utc_now_iso(),
            "health_ok": health_ok,
            "models_ok": models_ok,
            "functional_ok": functional_ok,
        }
        if last_error:
            result["last_error"] = last_error
        return result
