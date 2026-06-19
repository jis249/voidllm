"""YAML config loader with env interpolation and .env.local support."""

from __future__ import annotations

import os
import re
from datetime import timedelta
from pathlib import Path
from typing import Any
from urllib.parse import quote_plus

import yaml

from wai.config.models import (
    AdminConfig,
    BootstrapConfig,
    CacheConfig,
    Config,
    DatabaseConfig,
    DeploymentConfig,
    LoggingConfig,
    MCPServerConfig,
    ModelConfig,
    PricingConfig,
    ProxyConfig,
    RedisConfig,
    ServerConfig,
    SettingsConfig,
    TLSConfig,
    UsageConfig,
)

_ENV_VAR_RE = re.compile(rb"\$\{([^}:]+)(?::-(.*?))?\}")

_DURATION_RE = re.compile(
    r"^(\d+(?:\.\d+)?)(ns|us|µs|ms|s|m|h)$", re.IGNORECASE
)


def find_config_file() -> str:
    if v := os.environ.get("WAI_CONFIG"):
        return v
    for candidate in ("./wai.yaml", "/etc/wai/wai.yaml"):
        if Path(candidate).is_file():
            return candidate
    raise FileNotFoundError(
        "no config file found; set WAI_CONFIG or place wai.yaml in the current directory"
    )


def load_local_env_file(config_path: str) -> None:
    if not config_path:
        return
    env_path = Path(config_path).parent / ".env.local"
    if not env_path.is_file():
        return
    for line in env_path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if "=" not in line:
            continue
        name, value = line.split("=", 1)
        name = name.strip()
        value = value.strip()
        if name and not os.environ.get(name):
            os.environ[name] = value


def interpolate_env(data: bytes) -> bytes:
    def repl(match: re.Match[bytes]) -> bytes:
        name = match.group(1).decode()
        fallback = match.group(2) or b""
        val = os.environ.get(name, "")
        if val:
            if name in ("POSTGRES_PASSWORD",):
                val = quote_plus(val)
            return val.encode()
        return fallback

    return _ENV_VAR_RE.sub(repl, data)


def parse_duration(value: str | None) -> timedelta | None:
    if not value:
        return None
    if isinstance(value, (int, float)):
        return timedelta(seconds=float(value))
    m = _DURATION_RE.match(str(value).strip())
    if not m:
        return None
    amount = float(m.group(1))
    unit = m.group(2).lower()
    if unit == "ns":
        return timedelta(microseconds=amount / 1000)
    if unit in ("us", "µs"):
        return timedelta(microseconds=amount)
    if unit == "ms":
        return timedelta(milliseconds=amount)
    if unit == "s":
        return timedelta(seconds=amount)
    if unit == "m":
        return timedelta(minutes=amount)
    if unit == "h":
        return timedelta(hours=amount)
    return None


def _derive_slug(name: str) -> str:
    s = name.lower().replace(" ", "-")
    slug = "".join(c for c in s if c.isalnum() or c == "-").strip("-")
    return slug or "default"


def _coerce_timedelta(raw: Any, default: timedelta) -> timedelta:
    if raw is None:
        return default
    if isinstance(raw, timedelta):
        return raw
    parsed = parse_duration(str(raw))
    return parsed if parsed is not None else default


def _pricing(raw: dict[str, Any] | None) -> PricingConfig:
    raw = raw or {}
    return PricingConfig(
        input_per_1m=float(raw.get("input_per_1m") or 0),
        output_per_1m=float(raw.get("output_per_1m") or 0),
    )


def _deployment(raw: dict[str, Any]) -> DeploymentConfig:
    return DeploymentConfig(
        name=str(raw.get("name") or ""),
        provider=str(raw.get("provider") or ""),
        base_url=str(raw.get("base_url") or ""),
        api_key=str(raw.get("api_key") or ""),
        azure_deployment=str(raw.get("azure_deployment") or ""),
        azure_api_version=str(raw.get("azure_api_version") or ""),
        gcp_project=str(raw.get("gcp_project") or ""),
        gcp_location=str(raw.get("gcp_location") or ""),
        weight=int(raw.get("weight") or 0),
        priority=int(raw.get("priority") or 0),
    )


def _model(raw: dict[str, Any]) -> ModelConfig:
    return ModelConfig(
        name=str(raw.get("name") or ""),
        provider=str(raw.get("provider") or ""),
        type=str(raw.get("type") or ""),
        base_url=str(raw.get("base_url") or ""),
        api_key=str(raw.get("api_key") or ""),
        aliases=list(raw.get("aliases") or []),
        max_context_tokens=int(raw.get("max_context_tokens") or 0),
        pricing=_pricing(raw.get("pricing")),
        azure_deployment=str(raw.get("azure_deployment") or ""),
        azure_api_version=str(raw.get("azure_api_version") or ""),
        gcp_project=str(raw.get("gcp_project") or ""),
        gcp_location=str(raw.get("gcp_location") or ""),
        timeout=str(raw.get("timeout") or ""),
        strategy=str(raw.get("strategy") or ""),
        max_retries=int(raw.get("max_retries") or 0),
        fallback=str(raw.get("fallback") or ""),
        deployments=[_deployment(d) for d in raw.get("deployments") or []],
    )


def _mcp_server(raw: dict[str, Any]) -> MCPServerConfig:
    return MCPServerConfig(
        name=str(raw.get("name") or ""),
        alias=str(raw.get("alias") or ""),
        url=str(raw.get("url") or ""),
        auth_type=str(raw.get("auth_type") or ""),
        auth_header=str(raw.get("auth_header") or ""),
        auth_token=str(raw.get("auth_token") or ""),
        oauth_token_url=str(raw.get("oauth_token_url") or ""),
        oauth_client_id=str(raw.get("oauth_client_id") or ""),
        oauth_client_secret=str(raw.get("oauth_client_secret") or ""),
        oauth_scopes=str(raw.get("oauth_scopes") or ""),
    )


def _from_dict(data: dict[str, Any]) -> Config:
    server_raw = data.get("server") or {}
    proxy_raw = server_raw.get("proxy") or {}
    admin_raw = server_raw.get("admin") or {}
    tls_raw = admin_raw.get("tls") or {}
    db_raw = data.get("database") or {}
    cache_raw = data.get("cache") or {}
    redis_raw = data.get("redis") or {}
    settings_raw = data.get("settings") or {}
    bootstrap_raw = settings_raw.get("bootstrap") or {}
    usage_raw = settings_raw.get("usage") or {}
    logging_raw = data.get("logging") or {}

    drop_on_full = usage_raw.get("drop_on_full")
    if drop_on_full is None:
        drop_full: bool | None = None
    else:
        drop_full = bool(drop_on_full)

    cfg = Config(
        server=ServerConfig(
            proxy=ProxyConfig(
                port=int(proxy_raw.get("port") or 0),
                read_timeout=_coerce_timedelta(proxy_raw.get("read_timeout"), timedelta(seconds=30)),
                write_timeout=_coerce_timedelta(proxy_raw.get("write_timeout"), timedelta(seconds=120)),
                idle_timeout=_coerce_timedelta(proxy_raw.get("idle_timeout"), timedelta(seconds=60)),
                max_request_body=int(proxy_raw.get("max_request_body") or 0),
                max_response_body=int(proxy_raw.get("max_response_body") or 0),
                max_stream_duration=_coerce_timedelta(
                    proxy_raw.get("max_stream_duration"), timedelta(minutes=5)
                ),
                drain_timeout=_coerce_timedelta(proxy_raw.get("drain_timeout"), timedelta(seconds=25)),
            ),
            admin=AdminConfig(
                port=int(admin_raw.get("port") or 0),
                tls=TLSConfig(
                    enabled=bool(tls_raw.get("enabled")),
                    cert=str(tls_raw.get("cert") or ""),
                    key=str(tls_raw.get("key") or ""),
                ),
            ),
        ),
        database=DatabaseConfig(
            driver=str(db_raw.get("driver") or ""),
            dsn=str(db_raw.get("dsn") or ""),
            max_open_conns=int(db_raw.get("max_open_conns") or 0),
            max_idle_conns=int(db_raw.get("max_idle_conns") or 0),
            conn_max_lifetime=_coerce_timedelta(db_raw.get("conn_max_lifetime"), timedelta(minutes=5)),
        ),
        cache=CacheConfig(
            key_ttl=_coerce_timedelta(cache_raw.get("key_ttl"), timedelta(seconds=30)),
            model_ttl=_coerce_timedelta(cache_raw.get("model_ttl"), timedelta(seconds=60)),
            alias_ttl=_coerce_timedelta(cache_raw.get("alias_ttl"), timedelta(seconds=60)),
        ),
        redis=RedisConfig(
            enabled=bool(redis_raw.get("enabled")),
            url=str(redis_raw.get("url") or ""),
            key_prefix=str(redis_raw.get("key_prefix") or ""),
        ),
        models=[_model(m) for m in data.get("models") or []],
        mcp_servers=[_mcp_server(s) for s in data.get("mcp_servers") or []],
        settings=SettingsConfig(
            admin_key=str(settings_raw.get("admin_key") or ""),
            encryption_key=str(settings_raw.get("encryption_key") or ""),
            license=str(settings_raw.get("license") or ""),
            license_file=str(settings_raw.get("license_file") or ""),
            bootstrap=BootstrapConfig(
                org_name=str(bootstrap_raw.get("org_name") or ""),
                org_slug=str(bootstrap_raw.get("org_slug") or ""),
                admin_email=str(bootstrap_raw.get("admin_email") or ""),
            ),
            usage=UsageConfig(
                buffer_size=int(usage_raw.get("buffer_size") or 0),
                flush_interval=_coerce_timedelta(usage_raw.get("flush_interval"), timedelta(seconds=5)),
                drop_on_full=drop_full,
            ),
            fallback_max_depth=int(settings_raw.get("fallback_max_depth") or 0),
        ),
        logging=LoggingConfig(
            level=str(logging_raw.get("level") or ""),
            format=str(logging_raw.get("format") or ""),
        ),
    )
    _set_defaults(cfg)
    return cfg


def _set_defaults(cfg: Config) -> None:
    if cfg.server.proxy.port == 0:
        cfg.server.proxy.port = 8080
    if cfg.server.proxy.max_request_body <= 0:
        cfg.server.proxy.max_request_body = 20 * 1024 * 1024
    if cfg.server.proxy.max_response_body <= 0:
        cfg.server.proxy.max_response_body = 50 * 1024 * 1024

    cfg.database.driver = "postgres"
    if not cfg.database.dsn:
        pw = quote_plus(os.environ.get("POSTGRES_PASSWORD", "postgres"))
        cfg.database.dsn = f"postgres://postgres:{pw}@localhost:5432/wai?sslmode=disable"

    if cfg.cache.key_ttl.total_seconds() == 0:
        cfg.cache.key_ttl = timedelta(seconds=30)
    if cfg.cache.model_ttl.total_seconds() == 0:
        cfg.cache.model_ttl = timedelta(seconds=60)
    if cfg.cache.alias_ttl.total_seconds() == 0:
        cfg.cache.alias_ttl = timedelta(seconds=60)

    if not cfg.redis.key_prefix:
        cfg.redis.key_prefix = "wai:"

    if cfg.settings.usage.buffer_size == 0:
        cfg.settings.usage.buffer_size = 1000

    if not cfg.settings.bootstrap.org_name:
        cfg.settings.bootstrap.org_name = "Default"
    if not cfg.settings.bootstrap.org_slug:
        cfg.settings.bootstrap.org_slug = _derive_slug(cfg.settings.bootstrap.org_name)
    if not cfg.settings.bootstrap.admin_email:
        cfg.settings.bootstrap.admin_email = "admin@wai.local"

    if not cfg.logging.level:
        cfg.logging.level = "info"
    if not cfg.logging.format:
        cfg.logging.format = "json"


def _load_defaults() -> Config:
    cfg = Config(
        settings=SettingsConfig(
            admin_key=os.environ.get("WAI_ADMIN_KEY", ""),
            encryption_key=os.environ.get("WAI_ENCRYPTION_KEY", ""),
            license=os.environ.get("WAI_LICENSE", ""),
        ),
        database=DatabaseConfig(
            driver="postgres",
            dsn=os.environ.get("WAI_DATABASE_DSN", ""),
        ),
    )
    _set_defaults(cfg)
    return cfg


def load(path: str = "") -> tuple[Config, bool]:
    """Load config from path. Returns (config, used_defaults)."""
    if not path:
        try:
            path = find_config_file()
        except FileNotFoundError:
            return _load_defaults(), True

    load_local_env_file(path)
    raw = interpolate_env(Path(path).read_bytes())
    data = yaml.safe_load(raw) or {}
    if not isinstance(data, dict):
        raise ValueError("config root must be a mapping")

    cfg = _from_dict(data)

    if cfg.settings.license_file and not cfg.settings.license:
        cfg.settings.license = Path(cfg.settings.license_file).read_text(encoding="utf-8").strip()

    if not cfg.settings.admin_key:
        cfg.settings.admin_key = os.environ.get("WAI_ADMIN_KEY", "")
    if not cfg.settings.encryption_key:
        cfg.settings.encryption_key = os.environ.get("WAI_ENCRYPTION_KEY", "")
    if not cfg.settings.license:
        cfg.settings.license = os.environ.get("WAI_LICENSE", "")

    return cfg, False
