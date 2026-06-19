"""Model registry built from YAML config with DB overlay."""

from __future__ import annotations

import logging
import threading
from dataclasses import dataclass, field
from datetime import timedelta
from typing import Any

from wai.config.loader import parse_duration
from wai.config.models import ModelConfig, PricingConfig
from wai.crypto.aes import decrypt_string, encrypt_string
from wai.db.connection import Database

ERR_MODEL_NOT_FOUND = "model not found"


@dataclass
class Deployment:
    name: str = ""
    provider: str = ""
    base_url: str = ""
    api_key: str = ""
    azure_deployment: str = ""
    azure_api_version: str = ""
    gcp_project: str = ""
    gcp_location: str = ""
    weight: int = 0
    priority: int = 0


@dataclass
class Model:
    name: str = ""
    provider: str = ""
    type: str = "chat"
    base_url: str = ""
    api_key: str = ""
    aliases: list[str] = field(default_factory=list)
    max_context_tokens: int = 0
    pricing: PricingConfig = field(default_factory=PricingConfig)
    azure_deployment: str = ""
    azure_api_version: str = ""
    gcp_project: str = ""
    gcp_location: str = ""
    timeout: timedelta = field(default_factory=lambda: timedelta(0))
    strategy: str = ""
    max_retries: int = 0
    fallback_model_name: str = ""
    deployments: list[Deployment] = field(default_factory=list)
    source: str = "yaml"


@dataclass
class ModelInfo:
    name: str
    provider: str
    type: str
    aliases: list[str]
    max_context_tokens: int = 0
    strategy: str = ""
    deployment_count: int = 0


def _model_from_config(mc: ModelConfig) -> Model:
    timeout = parse_duration(mc.timeout) or timedelta(0)
    model_type = mc.type or "chat"
    deployments = [
        Deployment(
            name=d.name,
            provider=d.provider,
            base_url=d.base_url,
            api_key=d.api_key,
            azure_deployment=d.azure_deployment,
            azure_api_version=d.azure_api_version,
            gcp_project=d.gcp_project,
            gcp_location=d.gcp_location,
            weight=d.weight,
            priority=d.priority,
        )
        for d in mc.deployments
    ]
    return Model(
        name=mc.name,
        provider=mc.provider,
        type=model_type,
        base_url=mc.base_url,
        api_key=mc.api_key,
        aliases=list(mc.aliases),
        max_context_tokens=mc.max_context_tokens,
        pricing=mc.pricing,
        azure_deployment=mc.azure_deployment,
        azure_api_version=mc.azure_api_version,
        gcp_project=mc.gcp_project,
        gcp_location=mc.gcp_location,
        timeout=timeout,
        strategy=mc.strategy,
        max_retries=mc.max_retries,
        fallback_model_name=mc.fallback,
        deployments=deployments,
        source="yaml",
    )


class Registry:
    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._models: dict[str, Model] = {}
        self._aliases: dict[str, str] = {}
        self._sorted: list[Model] = []

    @classmethod
    def from_yaml(cls, models: list[ModelConfig]) -> Registry:
        reg = cls()
        for mc in models:
            reg.add_model(_model_from_config(mc))
        return reg

    def add_model(self, model: Model) -> None:
        with self._lock:
            if model.name in self._models:
                old = self._models[model.name]
                for alias in old.aliases:
                    self._aliases.pop(alias, None)
            for alias in model.aliases:
                if alias in self._aliases and self._aliases[alias] != model.name:
                    raise ValueError(f"duplicate alias {alias!r}")
                if alias in self._models and alias != model.name:
                    raise ValueError(f"alias {alias!r} collides with model name")
                self._aliases[alias] = model.name
            self._models[model.name] = model
            self._rebuild_sorted()

    def resolve(self, name_or_alias: str) -> Model:
        with self._lock:
            if name_or_alias in self._models:
                return self._copy(self._models[name_or_alias])
            if name_or_alias in self._aliases:
                return self._copy(self._models[self._aliases[name_or_alias]])
            raise KeyError(ERR_MODEL_NOT_FOUND)

    def list_info(self) -> list[ModelInfo]:
        with self._lock:
            return [
                ModelInfo(
                    name=m.name,
                    provider=m.provider,
                    type=m.type,
                    aliases=list(m.aliases),
                    max_context_tokens=m.max_context_tokens,
                    strategy=m.strategy,
                    deployment_count=len(m.deployments),
                )
                for m in self._sorted
            ]

    def _rebuild_sorted(self) -> None:
        self._sorted = sorted(self._models.values(), key=lambda m: m.name)

    @staticmethod
    def _copy(m: Model) -> Model:
        return Model(
            name=m.name,
            provider=m.provider,
            type=m.type,
            base_url=m.base_url,
            api_key=m.api_key,
            aliases=list(m.aliases),
            max_context_tokens=m.max_context_tokens,
            pricing=m.pricing,
            azure_deployment=m.azure_deployment,
            azure_api_version=m.azure_api_version,
            gcp_project=m.gcp_project,
            gcp_location=m.gcp_location,
            timeout=m.timeout,
            strategy=m.strategy,
            max_retries=m.max_retries,
            fallback_model_name=m.fallback_model_name,
            deployments=list(m.deployments),
            source=m.source,
        )


async def sync_yaml_models(
    db: Database,
    models: list[ModelConfig],
    enc_key: bytes,
    log: logging.Logger | None = None,
) -> None:
    """Upsert YAML-configured models into the database."""
    from wai.api.admin.common import new_uuid

    logger = log or logging.getLogger("wai.registry")
    desired = {m.name for m in models}

    for mc in models:
        row = await db.fetchone(
            "SELECT id, source FROM models WHERE name = ? AND deleted_at IS NULL",
            (mc.name,),
        )
        aliases = ",".join(mc.aliases)
        model_type = mc.type or "chat"
        if row is None:
            mid = new_uuid()
            await db.execute(
                """INSERT INTO models (id, name, provider, model_type, base_url, max_context_tokens,
                                       input_price_per_1m, output_price_per_1m, azure_deployment,
                                       azure_api_version, gcp_project, gcp_location, aliases, timeout,
                                       strategy, max_retries, is_active, source, created_at, updated_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 1, 'yaml',
                           CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)""",
                (
                    mid,
                    mc.name,
                    mc.provider,
                    model_type,
                    mc.base_url,
                    mc.max_context_tokens,
                    mc.pricing.input_per_1m,
                    mc.pricing.output_per_1m,
                    mc.azure_deployment,
                    mc.azure_api_version,
                    mc.gcp_project,
                    mc.gcp_location,
                    aliases,
                    mc.timeout,
                    mc.strategy,
                    mc.max_retries,
                ),
            )
            if mc.api_key:
                enc = encrypt_string(mc.api_key, enc_key, f"model:{mid}".encode())
                await db.execute(
                    "UPDATE models SET api_key_encrypted = ? WHERE id = ?",
                    (enc, mid),
                )
            await db.commit()
            continue

        if row["source"] != "yaml":
            continue

        await db.execute(
            """UPDATE models SET provider = ?, model_type = ?, base_url = ?, max_context_tokens = ?,
                                  input_price_per_1m = ?, output_price_per_1m = ?, azure_deployment = ?,
                                  azure_api_version = ?, gcp_project = ?, gcp_location = ?, aliases = ?,
                                  timeout = ?, strategy = ?, max_retries = ?, updated_at = CURRENT_TIMESTAMP
               WHERE id = ?""",
            (
                mc.provider,
                model_type,
                mc.base_url,
                mc.max_context_tokens,
                mc.pricing.input_per_1m,
                mc.pricing.output_per_1m,
                mc.azure_deployment,
                mc.azure_api_version,
                mc.gcp_project,
                mc.gcp_location,
                aliases,
                mc.timeout,
                mc.strategy,
                mc.max_retries,
                row["id"],
            ),
        )
        if mc.api_key:
            enc = encrypt_string(mc.api_key, enc_key, f"model:{row['id']}".encode())
            await db.execute(
                "UPDATE models SET api_key_encrypted = ? WHERE id = ?",
                (enc, row["id"]),
            )
        await db.commit()

    stale = await db.fetchall(
        "SELECT id, name FROM models WHERE source = 'yaml' AND deleted_at IS NULL"
    )
    for row in stale:
        if row["name"] not in desired:
            await db.execute(
                "UPDATE models SET deleted_at = CURRENT_TIMESTAMP WHERE id = ?",
                (row["id"],),
            )
            logger.info("soft-deleted stale yaml model: %s", row["name"])
    await db.commit()


async def load_db_into_registry(
    db: Database,
    registry: Registry,
    enc_key: bytes,
    log: logging.Logger | None = None,
) -> None:
    """Overlay active DB models onto the registry (DB takes precedence)."""
    logger = log or logging.getLogger("wai.registry")
    rows = await db.fetchall(
        """SELECT * FROM models WHERE deleted_at IS NULL AND is_active = 1"""
    )
    id_to_name = {row["id"]: row["name"] for row in rows}

    for row in rows:
        api_key = ""
        if row["api_key_encrypted"]:
            try:
                api_key = decrypt_string(
                    row["api_key_encrypted"], enc_key, f"model:{row['id']}".encode()
                )
            except Exception as exc:
                logger.error("failed to decrypt model api key for %s: %s", row["name"], exc)

        aliases_raw = row["aliases"] or ""
        aliases = [a.strip() for a in aliases_raw.split(",") if a.strip()]
        timeout = parse_duration(row["timeout"] or "") or timedelta(0)
        fallback_name = ""
        fallback_id = row["fallback_model_id"] if "fallback_model_id" in row.keys() else None
        if fallback_id:
            fallback_name = id_to_name.get(fallback_id, "")

        model = Model(
            name=row["name"],
            provider=row["provider"],
            type=row["model_type"] or "chat",
            base_url=row["base_url"],
            api_key=api_key,
            aliases=aliases,
            max_context_tokens=int(row["max_context_tokens"] or 0),
            pricing=PricingConfig(
                input_per_1m=float(row["input_price_per_1m"] or 0),
                output_per_1m=float(row["output_price_per_1m"] or 0),
            ),
            azure_deployment=row["azure_deployment"] or "",
            azure_api_version=row["azure_api_version"] or "",
            gcp_project=row["gcp_project"] or "",
            gcp_location=row["gcp_location"] or "",
            timeout=timeout,
            strategy=row["strategy"] or "",
            max_retries=int(row["max_retries"] or 0),
            fallback_model_name=fallback_name,
            source=row["source"] or "api",
        )
        try:
            registry.add_model(model)
        except ValueError as exc:
            logger.warning("skipping model %s: %s", row["name"], exc)
