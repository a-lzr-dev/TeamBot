"""
Декоратор для логирования ошибок с выводом JSON-данных.

Назначение:
    Оборачивает функции для автоматического логирования ошибок с детальным
    выводом данных, вызвавших ошибку.

Основные функции:
    1. Перехват и логирование исключений
    2. Извлечение проблемных данных из аргументов функции
    3. Вывод первых 3 записей в формате JSON для диагностики
    4. Поддержка синхронных и асинхронных функций

Технические особенности:
    - Автоматическое определение типа функции (синхронная/асинхронная)
    - Поиск данных в аргументах (list или dict)
    - Безопасная сериализация в JSON с обработкой ошибок
    - Проброс исключения после логирования

Архитектура:
    - Декоратор высшего порядка
    - Использует functools.wraps для сохранения метаданных
    - Интегрируется с app_logger
"""

import asyncio
import json
from collections.abc import Callable
from functools import wraps
from typing import Any

from app.logger import app_logger

# ============================================================
# 1. ДЕКОРАТОР ДЛЯ ЛОГИРОВАНИЯ ОШИБОК
# ============================================================


def log_json_errors(func: Callable) -> Callable:
    """
    Декоратор для логирования ошибок с выводом JSON-данных.

    При возникновении исключения логирует:
    - Имя функции, в которой произошла ошибка
    - Текст ошибки
    - Проблемные данные (первые 3 записи в формате JSON)

    Поддерживает как синхронные, так и асинхронные функции.

    Args:
        func: Оборачиваемая функция

    Returns:
        Callable: Обёрнутая функция

    Example:
        @log_json_errors
        async def process_records(records: list[dict]) -> None:
            # Если здесь возникнет ошибка, будут выведены первые 3 записи
            ...
    """
    # ============================================================
    # 1.1. ОБЩАЯ ЛОГИКА ЛОГИРОВАНИЯ
    # ============================================================

    def _log_error(func_name: str, error: Exception, *args: Any) -> None:
        """
        Внутренняя функция для логирования ошибки.

        Args:
            func_name: Имя функции
            error: Исключение
            *args: Аргументы функции для поиска данных
        """
        # Поиск данных в аргументах (list или dict)
        records = None
        for arg in args:
            if isinstance(arg, list | dict):
                records = arg
                break

        # Логирование ошибки
        app_logger.error(f"❌ Error in {func_name}: {error}")

        # Логирование проблемных данных (если есть)
        if records:
            # Извлекаем первые 3 записи
            preview = records[:3] if isinstance(records, list) else [records]

            try:
                json_preview = json.dumps(
                    preview,
                    ensure_ascii=False,
                    default=str,
                    indent=2,
                )
                app_logger.error(f"   Problematic records (first 3): {json_preview}")
            except Exception as json_error:
                app_logger.error(f"   Failed to serialize records: {json_error}")
                app_logger.error(f"   Records preview: {str(preview)[:500]}")

    # ============================================================
    # 1.2. АСИНХРОННАЯ ОБЁРТКА
    # ============================================================

    @wraps(func)
    async def async_wrapper(*args: Any, **kwargs: Any) -> Any:
        """
        Асинхронная обёртка для логирования ошибок.
        """
        try:
            return await func(*args, **kwargs)
        except Exception as e:
            _log_error(func.__name__, e, *args)
            raise

    # ============================================================
    # 1.3. СИНХРОННАЯ ОБЁРТКА
    # ============================================================

    @wraps(func)
    def sync_wrapper(*args: Any, **kwargs: Any) -> Any:
        """
        Синхронная обёртка для логирования ошибок.
        """
        try:
            return func(*args, **kwargs)
        except Exception as e:
            _log_error(func.__name__, e, *args)
            raise

    # ============================================================
    # 1.4. АВТОМАТИЧЕСКИЙ ВЫБОР ОБЁРТКИ
    # ============================================================

    # Возвращаем соответствующую обёртку в зависимости от типа функции
    return async_wrapper if asyncio.iscoroutinefunction(func) else sync_wrapper


__all__ = [
    "log_json_errors",
]
