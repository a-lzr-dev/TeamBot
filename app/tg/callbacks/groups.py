from typing import Any

from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery

from ...config import settings
from ...logger import tg_logger
from ...tg.dependencies import get_tg_manager
from .base import BaseCallbackHandler, CallbackHandler


class GroupCallbackHandler(BaseCallbackHandler):
    """Обработчик колбэков для групп действий"""

    PREFIX_GROUP = "group_"

    def __init__(self) -> None:
        super().__init__(self.PREFIX_GROUP)

    async def handle(self, callback: CallbackQuery, state: FSMContext, **kwargs: Any) -> Any:
        """Обработка колбэка группы"""
        callback_data = callback.data

        if callback_data.startswith(self.PREFIX_GROUP):
            return await self._handle_group(callback, state, **kwargs)

        tg_logger.warning(f"⚠️ Unknown group callback: {callback_data}")
        await CallbackHandler.answer(callback, "Неизвестное действие")
        return None

    @staticmethod
    async def _handle_group(callback: CallbackQuery, state: FSMContext, **kwargs: Any) -> None:
        """Обработка выбора группы"""
        tg_manager = get_tg_manager()

        # Проверка прав администратора
        if not callback.from_user or callback.from_user.id not in settings.ADMIN_IDS:
            await tg_manager.send_toast(text="⛔ У вас нет прав для этого действия.", event=callback)
            return

        # Ответ на CallBack
        await tg_manager.send_toast(event=callback)

        # Извлечение ID группы
        group_id = int(callback.data.split("_")[1])

        from ..handlers.aiogram.actions import show_menu

        await show_menu(event=callback, group_id=group_id, state=state, is_callback=True, is_new=True)


group_callback_handler = GroupCallbackHandler()
