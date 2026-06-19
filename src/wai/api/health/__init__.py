"""Health, readiness, and metrics endpoints."""

from wai.api.health.routes import register_health_routes

__all__ = ["register_health_routes"]
