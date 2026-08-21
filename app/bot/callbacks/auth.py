"""
Обработчик колбэков для авторизации пользователей.

Этот модуль предоставляет обработчики для колбэков, связанных
с процессом авторизации пользователей в системе.

Основные функции:
    - Обработка запроса на авторизацию через колбэк
    - Перенаправление пользователя на процесс авторизации

Префиксы колбэков:
    - auth_needed: Запрос на авторизацию пользователя
"""

from typing import Any

from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery

from ...logger import bot_logger
from .base import BaseCallbackHandler, CallbackHandler


class AuthCallbackHandler(BaseCallbackHandler):
    """
    Обработчик колбэков для авторизации пользователей.

    Обрабатывает:
        - Запрос на авторизацию (кнопка "Авторизоваться")
        - Перенаправление на процесс авторизации

    Префиксы колбэков:
        - auth_needed: Требуется авторизация
    """

    PREFIX_AUTH_NEEDED = "auth_needed"

    def __init__(self) -> None:
        """Инициализация обработчика колбэков авторизации."""
        super().__init__(self.PREFIX_AUTH_NEEDED)

    async def handle(self, callback: CallbackQuery, state: FSMContext, **kwargs: Any) -> None:
        """
        Основной метод обработки колбэка авторизации.

        Определяет тип колбэка и вызывает соответствующий обработчик.

        Args:
            callback: CallbackQuery от пользователя
            state: Состояние FSM
            **kwargs: Дополнительные параметры

        Returns:
            None
        """
        callback_data = callback.data

        if callback_data == self.PREFIX_AUTH_NEEDED:
            return await self._handle_auth_needed(callback, state, **kwargs)

        bot_logger.warning(f"⚠️ Unknown auth callback: {callback_data}")
        await CallbackHandler.answer(callback, "Неизвестное действие")
        return None

    @staticmethod
    async def _handle_auth_needed(callback: CallbackQuery, state: FSMContext, **_kwargs: Any) -> None:
        """
        Обработка кнопки 'Авторизоваться'.

        Перенаправляет пользователя на процесс авторизации,
        вызывая команду /start.

        Args:
            callback: CallbackQuery от пользователя
            state: Состояние FSM
            **_kwargs: Дополнительные параметры
        """
        # Подтверждение получения колбэка
        await CallbackHandler.answer(callback)

        from app.bot.handlers.aiogram.auth import cmd_start

        # Запуск процесса авторизации через команду /start
        await cmd_start(callback.message, state)


auth_callback_handler = AuthCallbackHandler()
