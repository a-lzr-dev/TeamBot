import asyncio
from collections.abc import Awaitable, Callable
from functools import wraps
from typing import ParamSpec, TypeVar

from .logger import LoggerProtocol, app_logger

P = ParamSpec("P")
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


def log_exceptions(
    logger: LoggerProtocol = app_logger,
) -> Callable[[Callable[P, Awaitable[R]]], Callable[P, Awaitable[R]]]:
    """
    Декоратор для логирования исключений в асинхронных функциях.

    Args:
        logger: Логгер, реализующий LoggerProtocol (ExtendedLogger или logging.Logger)

    Returns:
        Декорированная функция
    """

    def decorator(func: Callable[P, Awaitable[R]]) -> Callable[P, Awaitable[R]]:
        @wraps(func)
        async def wrapper(*args: P.args, **kwargs: P.kwargs) -> R:
            try:
                return await func(*args, **kwargs)
            except asyncio.CancelledError:
                logger.debug(f"Task {func.__name__} was cancelled")
                raise
            except Exception as e:
                logger.error(f"Exception in {func.__name__}: {e}", exc_info=True)
                raise

        return wrapper

    return decorator


def log_exceptions_sync(
    logger: LoggerProtocol = app_logger,
) -> Callable[[Callable[P, R]], Callable[P, R]]:
    """
    Декоратор для логирования исключений в синхронных функциях.

    Args:
        logger: Логгер, реализующий LoggerProtocol (ExtendedLogger или logging.Logger)

    Returns:
        Декорированная функция
    """

    def decorator(func: Callable[P, R]) -> Callable[P, R]:
        @wraps(func)
        def wrapper(*args: P.args, **kwargs: P.kwargs) -> R:
            try:
                return func(*args, **kwargs)
            except Exception as e:
                logger.error(f"Exception in {func.__name__}: {e}", exc_info=True)
                raise

        return wrapper

    return decorator


async def handle_exception(
    exception: Exception,
    logger: LoggerProtocol = app_logger,
) -> None:
    """
    Глобальный обработчик исключений.

    Args:
        exception: Исключение для обработки
        logger: Логгер, реализующий LoggerProtocol
    """
    if isinstance(exception, DatabaseError):
        logger.error(f"Database error: {exception}")
    elif isinstance(exception, TelegramError):
        logger.error(f"Telegram error: {exception}")
    elif isinstance(exception, ValidationError):
        logger.warning(f"Validation error: {exception}")
    else:
        logger.critical(f"Unexpected error: {exception}", exc_info=True)


__all__ = [
    "AppError",
    "DatabaseError",
    "TelegramError",
    "ConfigurationError",
    "ValidationError",
    "NotFoundError",
    "AutomationError",
    "ConversionError",
    "PyWin32Error",
    "log_exceptions",
    "log_exceptions_sync",
    "handle_exception",
]
