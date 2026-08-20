from typing import Any

from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery

from ...logger import bot_logger
from .base import BaseCallbackHandler, CallbackHandler


class AuthCallbackHandler(BaseCallbackHandler):
    """Обработчик колбэков для авторизации"""

    PREFIX_AUTH_NEEDED = "auth_needed"

    def __init__(self) -> None:
        super().__init__(self.PREFIX_AUTH_NEEDED)

    async def handle(self, callback: CallbackQuery, state: FSMContext, **kwargs: Any) -> None:
        """Обработка колбэка авторизации"""
        callback_data = callback.data

        if callback_data == self.PREFIX_AUTH_NEEDED:
            return await self._handle_auth_needed(callback, state, **kwargs)

        bot_logger.warning(f"⚠️ Unknown auth callback: {callback_data}")
        await CallbackHandler.answer(callback, "Неизвестное действие")
        return None

    @staticmethod
    async def _handle_auth_needed(callback: CallbackQuery, state: FSMContext, **_kwargs: Any) -> None:
        """Обработка кнопки 'Авторизоваться'"""
        await CallbackHandler.answer(callback)

        # Импортируем здесь, чтобы избежать циклических импортов
        from app.bot.handlers.aiogram.auth import cmd_start

        await cmd_start(callback.message, state)


auth_callback_handler = AuthCallbackHandler()
