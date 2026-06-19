"""WAI Admin API — FastAPI port of internal/api/admin."""

from wai.api.admin.handler import Handler, get_handler, init_handler
from wai.api.admin.routes import API_PREFIX, create_admin_router, register_routes

__all__ = [
    "API_PREFIX",
    "Handler",
    "create_admin_router",
    "get_handler",
    "init_handler",
    "register_routes",
]
