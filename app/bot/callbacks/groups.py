from typing import Any

from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery

from ...bot.dependencies import get_bot_manager
from ...config import settings
from ...logger import bot_logger
from .base import BaseCallbackHandler, CallbackHandler


class GroupCallbackHandler(BaseCallbackHandler):
    """Обработчик колбэков для групп действий"""

    PREFIX_GROUP = "group_"

    def __init__(self) -> None:
        super().__init__(self.PREFIX_GROUP)

    async def handle(self, callback: CallbackQuery, state: FSMContext, **kwargs: Any) -> Any:
        """Обработка колбэка группы"""
        callback_data = callback.data

        # Исправлено: проверка на None
        if callback_data and callback_data.startswith(self.PREFIX_GROUP):
            return await self._handle_group(callback, state, **kwargs)

        bot_logger.warning(f"⚠️ Unknown group callback: {callback_data}")
        await CallbackHandler.answer(callback, "Неизвестное действие")
        return None

    @staticmethod
    async def _handle_group(callback: CallbackQuery, state: FSMContext, **_kwargs: Any) -> None:
        """Обработка выбора группы"""
        bot_manager = get_bot_manager()

        # Проверка прав администратора
        if not callback.from_user or callback.from_user.id not in settings.ADMIN_IDS:
            await bot_manager.send_toast(text="⛔ У вас нет прав для этого действия.", event=callback)
            return

        # Ответ на CallBack
        await bot_manager.send_toast(event=callback)

        # Извлечение ID группы
        # Исправлено: проверка на None
        callback_data = callback.data
        if not callback_data:
            await bot_manager.send_toast(text="❌ Не удалось определить действие.", event=callback)
            return

        try:
            group_id = int(callback_data.split("_")[1])
        except (ValueError, IndexError):
            bot_logger.warning(f"⚠️ Invalid group callback data: {callback_data}")
            await bot_manager.send_toast(text="❌ Неверный формат данных.", event=callback)
            return

        from ..handlers.aiogram.actions import show_menu

        await show_menu(event=callback, group_id=group_id, state=state, is_callback=True, is_new=True)


group_callback_handler = GroupCallbackHandler()
