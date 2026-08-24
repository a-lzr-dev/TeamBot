"""
Middleware для определения языка пользователя в Telegram боте.

Назначение:
    Автоматическое определение и установка языка пользователя для всех
    входящих событий (сообщений, callback'ов и т.д.).

Основные функции:
    1. Определение языка пользователя по ID
    2. Внедрение языка и локализатора в контекст обработчика
    3. Поддержка Message и CallbackQuery событий
    4. Использование кеша языковых предпочтений

Технические особенности:
    - Интеграция с Aiogram через BaseMiddleware
    - Автоматическое определение типа события (Message или CallbackQuery)
    - Fallback на DEFAULT_LANGUAGE при отсутствии предпочтений
    - Внедрение locale_manager и функции t() в data

Архитектура:
    - Реализует интерфейс BaseMiddleware от Aiogram
    - Использует get_user_language для получения языка из кеша
    - Интегрируется с locale_manager для локализации
"""

from collections.abc import Awaitable, Callable
from typing import Any

from aiogram import BaseMiddleware
from aiogram.types import CallbackQuery, Message, TelegramObject

from ..locales.manager import DEFAULT_LANGUAGE, locale_manager

# ============================================================
# 1. КЛАСС MIDDLEWARE ДЛЯ ОПРЕДЕЛЕНИЯ ЯЗЫКА
# ============================================================


class LocaleMiddleware(BaseMiddleware):
    """
    Middleware для определения языка пользователя в Telegram боте.

    Автоматически определяет язык пользователя и добавляет в контекст
    обработчика объекты для работы с локализацией.

    Пример использования в Aiogram:
        dp.update.outer_middleware(LocaleMiddleware())

    Attributes:
        default_language (str): Язык по умолчанию
    """

    def __init__(self, default_language: str = DEFAULT_LANGUAGE):
        """
        Инициализация middleware локализации.

        Args:
            default_language: Язык по умолчанию (из конфигурации)
        """
        self.default_language = default_language
        super().__init__()

    # ============================================================
    # 1.1. ОСНОВНОЙ МЕТОД ОБРАБОТКИ СОБЫТИЯ
    # ============================================================

    async def __call__(
        self,
        handler: Callable[[TelegramObject, dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: dict[str, Any],
    ) -> Any:
        """
        Основной метод обработки события с определением языка.

        Args:
            handler: Функция-обработчик события
            event: Объект события (Message, CallbackQuery и т.д.)
            data: Данные контекста для передачи обработчику

        Returns:
            Any: Результат выполнения обработчика

        Flow:
            1. Определение языка пользователя
            2. Добавление языка в контекст
            3. Добавление locale_manager в контекст
            4. Добавление функции t() для удобства
            5. Вызов обработчика
        """
        # 1. Определение языка пользователя
        user_lang = self.default_language

        if isinstance(event, Message) and event.from_user or isinstance(event, CallbackQuery) and event.from_user:
            user_lang = self._get_user_language(event.from_user.id)

        # 2. Добавление данных локализации в контекст
        data["lang"] = user_lang
        data["locale"] = locale_manager
        data["t"] = locale_manager.get  # Для удобства

        # 3. Вызов обработчика
        return await handler(event, data)

    # ============================================================
    # 1.2. ВСПОМОГАТЕЛЬНЫЙ МЕТОД
    # ============================================================

    @staticmethod
    def _get_user_language(user_id: int) -> str:
        """
        Получение языка пользователя из кеша.

        Args:
            user_id: ID пользователя Telegram

        Returns:
            str: Код языка пользователя или DEFAULT_LANGUAGE
        """
        from ..utils.locale import get_user_language

        return get_user_language(user_id)


__all__ = ["LocaleMiddleware"]
