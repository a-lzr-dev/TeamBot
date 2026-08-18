from .dependencies import get_api_manager
from .manager import APIManager, api_manager
from .routers import (
    admin_router,
    automation_router,
    avanpost_router,
    bot_msgs_router,
    bot_sync_router,
    errors_router,
    reminders_router,
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
    "bot_msgs_router",
    "bot_sync_router",
    # Зависимости
    "get_api_manager",
]
