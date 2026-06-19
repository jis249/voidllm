"""Configuration dataclasses mirroring internal/config."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import timedelta
from typing import Any


@dataclass
class ProxyConfig:
    port: int = 0
    read_timeout: timedelta = field(default_factory=lambda: timedelta(seconds=30))
    write_timeout: timedelta = field(default_factory=lambda: timedelta(seconds=120))
    idle_timeout: timedelta = field(default_factory=lambda: timedelta(seconds=60))
    max_request_body: int = 0
    max_response_body: int = 0
    max_stream_duration: timedelta = field(default_factory=lambda: timedelta(minutes=5))
    drain_timeout: timedelta = field(default_factory=lambda: timedelta(seconds=25))


@dataclass
class TLSConfig:
    enabled: bool = False
    cert: str = ""
    key: str = ""


@dataclass
class AdminConfig:
    port: int = 0
    tls: TLSConfig = field(default_factory=TLSConfig)


@dataclass
class ServerConfig:
    proxy: ProxyConfig = field(default_factory=ProxyConfig)
    admin: AdminConfig = field(default_factory=AdminConfig)


@dataclass
class DatabaseConfig:
    driver: str = ""
    dsn: str = ""
    max_open_conns: int = 0
    max_idle_conns: int = 0
    conn_max_lifetime: timedelta = field(default_factory=lambda: timedelta(minutes=5))


@dataclass
class CacheConfig:
    key_ttl: timedelta = field(default_factory=lambda: timedelta(seconds=30))
    model_ttl: timedelta = field(default_factory=lambda: timedelta(seconds=60))
    alias_ttl: timedelta = field(default_factory=lambda: timedelta(seconds=60))


@dataclass
class RedisConfig:
    enabled: bool = False
    url: str = ""
    key_prefix: str = ""


@dataclass
class PricingConfig:
    input_per_1m: float = 0.0
    output_per_1m: float = 0.0


@dataclass
class DeploymentConfig:
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
class ModelConfig:
    name: str = ""
    provider: str = ""
    type: str = ""
    base_url: str = ""
    api_key: str = ""
    aliases: list[str] = field(default_factory=list)
    max_context_tokens: int = 0
    pricing: PricingConfig = field(default_factory=PricingConfig)
    azure_deployment: str = ""
    azure_api_version: str = ""
    gcp_project: str = ""
    gcp_location: str = ""
    timeout: str = ""
    strategy: str = ""
    max_retries: int = 0
    fallback: str = ""
    deployments: list[DeploymentConfig] = field(default_factory=list)


@dataclass
class BootstrapConfig:
    org_name: str = ""
    org_slug: str = ""
    admin_email: str = ""


@dataclass
class UsageConfig:
    buffer_size: int = 0
    flush_interval: timedelta = field(default_factory=lambda: timedelta(seconds=5))
    drop_on_full: bool | None = None


@dataclass
class SettingsConfig:
    admin_key: str = ""
    encryption_key: str = ""
    license: str = ""
    license_file: str = ""
    bootstrap: BootstrapConfig = field(default_factory=BootstrapConfig)
    usage: UsageConfig = field(default_factory=UsageConfig)
    fallback_max_depth: int = 0


@dataclass
class MCPServerConfig:
    name: str = ""
    alias: str = ""
    url: str = ""
    auth_type: str = ""
    auth_header: str = ""
    auth_token: str = ""
    oauth_token_url: str = ""
    oauth_client_id: str = ""
    oauth_client_secret: str = ""
    oauth_scopes: str = ""


@dataclass
class LoggingConfig:
    level: str = ""
    format: str = ""


@dataclass
class Config:
    server: ServerConfig = field(default_factory=ServerConfig)
    database: DatabaseConfig = field(default_factory=DatabaseConfig)
    cache: CacheConfig = field(default_factory=CacheConfig)
    redis: RedisConfig = field(default_factory=RedisConfig)
    models: list[ModelConfig] = field(default_factory=list)
    mcp_servers: list[MCPServerConfig] = field(default_factory=list)
    settings: SettingsConfig = field(default_factory=SettingsConfig)
    logging: LoggingConfig = field(default_factory=LoggingConfig)
