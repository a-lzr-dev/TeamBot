from .api.dependencies import get_api_manager
from .bot.dependencies import get_bot_manager
from .config import settings
from .core.application import ApplicationManager, app_manager, get_app_manager
from .db.dependencies import get_db_manager
from .logger import admin_logger, api_logger, app_logger, bot_logger, db_logger, logger_setup
from .services import (
    ErrorService,
    NotificationService,
    ReminderService,
    error_service,
    notification_service,
    reminder_service,
)

__all__ = [
    # Логеры
    "app_logger",
    "api_logger",
    "bot_logger",
    "db_logger",
    "admin_logger",
    "logger_setup",
    # Настройки
    "settings",
    # Геттеры менеджеров
    "get_db_manager",
    "get_api_manager",
    "get_bot_manager",
    # Application Manager
    "ApplicationManager",
    "get_app_manager",
    "app_manager",
    # Сервисы
    "ErrorService",
    "error_service",
    "ReminderService",
    "reminder_service",
    "NotificationService",
    "notification_service",
]
