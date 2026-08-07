from typing import TYPE_CHECKING

from .config import settings
from .core.application import ApplicationManager, app_manager, get_app_manager
from .logger import admin_logger, api_logger, app_logger, db_logger, logger_setup, tg_logger
from .services import (
    ErrorService,
    NotificationService,
    ReminderService,
    error_service,
    notification_service,
    reminder_service,
)

if TYPE_CHECKING:
    from .api import APIManager
    from .db import DatabaseManager
    from .tg import TelegramManager


def get_db_manager() -> "DatabaseManager":
    """Ленивая загрузка менеджера БД"""
    from .db.managers import db_manager

    return db_manager


def get_api_manager() -> "APIManager":
    """Ленивая загрузка менеджера API"""
    from .api import api_manager

    return api_manager


def get_tg_manager() -> "TelegramManager":
    """Ленивая загрузка менеджера Telegram"""
    from .tg import tg_manager

    return tg_manager


__all__ = [
    # Логеры
    "app_logger",
    "api_logger",
    "tg_logger",
    "db_logger",
    "admin_logger",
    "logger_setup",
    # Настройки
    "settings",
    # Геттеры менеджеров
    "get_db_manager",
    "get_api_manager",
    "get_tg_manager",
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
