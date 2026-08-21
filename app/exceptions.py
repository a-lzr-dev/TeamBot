from typing import TypeVar

R = TypeVar("R")


class AppError(Exception):
    """Базовое исключение приложения"""

    pass


class DatabaseError(AppError):
    """Ошибка базы данных"""

    pass


class TelegramError(AppError):
    """Ошибка Telegram API"""

    pass


class ConfigurationError(AppError):
    """Ошибка конфигурации"""

    pass


class ValidationError(AppError):
    """Ошибка валидации данных"""

    pass


class NotFoundError(AppError):
    """Объект не найден"""

    pass


class AutomationError(AppError):
    """Ошибка автоматизации"""

    pass


class ConversionError(AutomationError):
    """Ошибка конвертации документа"""

    pass


class PyWin32Error(ConversionError):
    """Ошибка pywin32 (Microsoft Word)"""

    pass


__all__ = [
    # Классы исключений
    "AppError",
    "DatabaseError",
    "TelegramError",
    "ConfigurationError",
    "ValidationError",
    "NotFoundError",
    "AutomationError",
    "ConversionError",
    "PyWin32Error",
]
