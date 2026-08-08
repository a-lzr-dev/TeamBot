from .dependencies import get_api_manager
from .manager import APIManager, api_manager
from .routers import (
    admin_router,
    automation_router,
    avanpost_router,
    errors_router,
    reminders_router,
    tg_msgs_router,
    tg_sync_router,
)

__all__ = [
    # Менеджеры
    "APIManager",
    "api_manager",
    # Роутеры
    "admin_router",
    "automation_router",
    "avanpost_router",
    "errors_router",
    "reminders_router",
    "tg_msgs_router",
    "tg_sync_router",
    # Зависимости
    "get_api_manager",
]
