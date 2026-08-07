from collections.abc import Awaitable, Callable
from typing import Any

from aiogram import BaseMiddleware
from aiogram.types import CallbackQuery, Message, TelegramObject

from ..locales.manager import DEFAULT_LANGUAGE, locale_manager


class LocaleMiddleware(BaseMiddleware):
    """Middleware для определения языка пользователя"""

    def __init__(self, default_language: str = DEFAULT_LANGUAGE):
        self.default_language = default_language
        super().__init__()

    async def __call__(
        self,
        handler: Callable[[TelegramObject, dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: dict[str, Any],
    ) -> Any:
        """Определение языка пользователя"""
        user_lang = self.default_language

        if isinstance(event, Message) and event.from_user or isinstance(event, CallbackQuery) and event.from_user:
            user_lang = self._get_user_language(event.from_user.id)

        data["lang"] = user_lang
        data["locale"] = locale_manager
        data["t"] = locale_manager.get  # Для удобства

        return await handler(event, data)

    @staticmethod
    def _get_user_language(user_id: int) -> str:
        """Получение языка пользователя из кеша"""
        from ..utils.locale import get_user_language

        return get_user_language(user_id)


__all__ = ["LocaleMiddleware"]
