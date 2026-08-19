from typing import Any

from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery

from ...bot.dependencies import get_bot_manager
from ...config import settings
from ...logger import bot_logger
from .base import BaseCallbackHandler, CallbackHandler


class UsersCallbackHandler(BaseCallbackHandler):
    """
    Обработчик колбэков для списка пользователей.

    Поддерживает:
    - users_<page>_page - переключение страницы
    - users_<page>_select_<user_id> - выбор пользователя
    - users_close - закрытие списка
    - users_info - информация о странице (заглушка)
    """

    PREFIX_USERS = "users_"
    PREFIX_CLOSE = "users_close"
    PREFIX_INFO = "users_info"

    def __init__(self) -> None:
        super().__init__(self.PREFIX_USERS)

    async def handle(self, callback: CallbackQuery, state: FSMContext, **kwargs: Any) -> Any:
        """
        Обработка колбэка пользователей.
        """
        callback_data = callback.data

        if not callback_data:
            bot_logger.warning("⚠️ Empty callback data in UsersCallbackHandler")
            await CallbackHandler.answer(callback, "Неизвестное действие")
            return None

        # Проверка прав администратора
        if not callback.from_user or callback.from_user.id not in settings.ADMIN_IDS:
            await CallbackHandler.answer(callback, "⛔ У вас нет прав для этой команды.")
            return None

        bot_logger.debug(f"🔍 UsersCallbackHandler: {callback_data}")

        # Обработка закрытия
        if callback_data == self.PREFIX_CLOSE:
            return await self._handle_close(callback, state, **kwargs)

        # Обработка информации о странице (заглушка)
        if callback_data == self.PREFIX_INFO:
            await CallbackHandler.answer(callback, "ℹ️ Информация о странице")
            return None

        # Обработка переключения страницы и выбора пользователя
        if callback_data.startswith(self.PREFIX_USERS):
            return await self._handle_users_action(callback, state, **kwargs)

        bot_logger.warning(f"⚠️ Unknown users callback: {callback_data}")
        await CallbackHandler.answer(callback, "Неизвестное действие")
        return None

    # ОБРАБОТЧИКИ

    @staticmethod
    async def _handle_close(callback: CallbackQuery, state: FSMContext, **_kwargs: Any) -> None:
        """Закрытие списка пользователей"""
        await CallbackHandler.answer(callback)

        from ..handlers.aiogram.users import close_users_list

        await close_users_list(callback, state)

    async def _handle_users_action(self, callback: CallbackQuery, state: FSMContext, **_kwargs: Any) -> None:
        """Обработка действий со списком пользователей"""
        callback_data = callback.data

        if not callback_data:
            return

        parts = callback_data.split("_")
        if len(parts) < 3:
            bot_logger.warning(f"⚠️ Invalid users callback format: {callback_data}")
            return

        try:
            page = int(parts[1])
            action = parts[2]

            if action == "page":
                # Переключение страницы
                await CallbackHandler.answer(callback)

                from ..handlers.aiogram.users import show_users

                await show_users(event=callback, state=state, page=page)

            elif action == "select":
                # Выбор пользователя
                if len(parts) < 4:
                    bot_logger.warning(f"⚠️ No user_id in select callback: {callback_data}")
                    return

                user_id = int(parts[3])
                await self._select_user(callback, state, user_id)

            else:
                bot_logger.warning(f"⚠️ Unknown users action: {action}")
                await CallbackHandler.answer(callback, "Неизвестное действие")

        except ValueError as e:
            bot_logger.warning(f"⚠️ Invalid users callback data: {callback_data}, error: {e}")
            await CallbackHandler.answer(callback, "Неверный формат данных")

    @staticmethod
    async def _select_user(callback: CallbackQuery, state: FSMContext, user_id: int) -> None:
        """
        Обработка выбора пользователя.
        Запускает /actions для выбранного пользователя.
        """
        bot_manager = get_bot_manager()

        try:
            from ..handlers.aiogram.users import select_user

            await select_user(callback, state, user_id)

        except Exception as e:
            bot_logger.error(f"❌ Failed to select user: {e}", exc_info=True)
            await bot_manager.send_toast(
                text=f"❌ Ошибка при выборе пользователя: {str(e)[:100]}",
                event=callback,
                show_alert=True,
            )


users_callback_handler = UsersCallbackHandler()


async def handle_users_callback(callback: CallbackQuery, state: FSMContext) -> None:
    """Удобная обертка для обработки колбэков пользователей"""
    await users_callback_handler.handle(callback, state)


__all__ = [
    "UsersCallbackHandler",
    "users_callback_handler",
    "handle_users_callback",
]
