from typing import Any

from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery

from ...db import AvanpostRepository, db_manager
from ...logger import tg_logger
from ...tg.dependencies import get_tg_manager
from .base import BaseCallbackHandler, CallbackHandler


class ActionCallbackHandler(BaseCallbackHandler):
    """Обработчик колбэков для меню действий"""

    PREFIX_ACTION = "action_"
    PREFIX_BACK = "action_back_"
    PREFIX_HOME = "action_home"
    PREFIX_BACK_TO_GROUPS = "back_to_groups"

    def __init__(self) -> None:
        super().__init__(self.PREFIX_ACTION)

    async def handle(self, callback: CallbackQuery, state: FSMContext, **kwargs: Any) -> Any:
        """Обработка колбэка действия"""
        callback_data = callback.data

        # Обработка специальных колбэков
        if callback_data == self.PREFIX_HOME:
            return await self._handle_home(callback, state, **kwargs)

        if callback_data == self.PREFIX_BACK_TO_GROUPS:
            return await self._handle_back_to_groups(callback, state, **kwargs)

        if callback_data.startswith(self.PREFIX_BACK):
            return await self._handle_back(callback, state, **kwargs)

        if callback_data.startswith(self.PREFIX_ACTION):
            return await self._handle_action(callback, state, **kwargs)

        tg_logger.warning(f"⚠️ Unknown action callback: {callback_data}")
        await CallbackHandler.answer(callback, "Неизвестное действие")
        return None

    @staticmethod
    async def _handle_home(callback: CallbackQuery, state: FSMContext, **kwargs: Any) -> None:
        """Обработка кнопки 'В главное меню'"""
        await CallbackHandler.answer(callback)

        from ..handlers.aiogram.actions import show_menu
        from ..handlers.aiogram.auth import get_user_group_id

        group_id = await get_user_group_id(callback.from_user.id)
        if not group_id:
            tg_manager = get_tg_manager()
            await tg_manager.send_toast(
                text="❌ **Группа действий не найдена**\n\n"
                "У вас не назначена группа действий в системе.\n"
                "Обратитесь к администратору для настройки прав.",
                event=callback,
            )
            return

        # Очищаем историю при переходе в главное меню
        await state.update_data(menu_history=[])

        await show_menu(event=callback, group_id=group_id, state=state, is_callback=True)

    @staticmethod
    async def _handle_back(callback: CallbackQuery, state: FSMContext, **kwargs: Any) -> None:
        """Обработка кнопки 'Назад'"""
        from ...tg import tg_manager

        await tg_manager.send_toast(event=callback)

        from ..handlers.aiogram.actions import show_menu
        from ..handlers.aiogram.auth import get_user_group_id

        group_id = await get_user_group_id(callback.from_user.id)
        if not group_id:
            await tg_manager.send_toast(
                text="❌ **Группа действий не найдена**\n\n"
                "У вас не назначена группа действий в системе.\n"
                "Обратитесь к администратору для настройки прав.",
                event=callback,
            )
            return

        # Извлекаем parent_id из callback_data
        parts = callback.data.split("_")
        parent_id = None

        if len(parts) >= 3:
            try:
                parent_id = int(parts[2])
                if parent_id == 0:
                    parent_id = None
            except ValueError:
                parent_id = None

        # ============================================================
        # ИСПОЛЬЗУЕМ СОСТОЯНИЕ ДЛЯ ХРАНЕНИЯ ИСТОРИИ ПЕРЕХОДОВ
        # ============================================================

        state_data = await state.get_data()
        history = state_data.get("menu_history", [])

        tg_logger.debug(f"📜 Current history: {history}, current parent_id: {parent_id}")

        if parent_id is not None and history:
            # Удаление текущего элемента из истории (последний элемент)
            if history and history[-1] == parent_id:
                history.pop()
                tg_logger.debug(f"🗑️ Removed {parent_id} from history")

            # Если история не пуста, последний элемент — это родитель
            if history:
                parent_id = history[-1]
                tg_logger.debug(f"🔙 Parent from history: {parent_id}")
            else:
                parent_id = None
                tg_logger.debug("🔙 No more history, going to root menu")
        elif parent_id is not None and not history:
            # Если история пуста, но parent_id есть — переходим в корень
            parent_id = None
            tg_logger.debug("🔙 History is empty, going to root menu")
        else:
            # parent_id is None — уже в корневом меню
            await tg_manager.send_toast(text="Вы уже в главном меню", event=callback)
            return

        # Обновляем состояние
        await state.update_data(menu_history=history)

        tg_logger.debug(f"🔙 Navigate back to parent_id: {parent_id}, history: {history}")

        await show_menu(
            event=callback,
            group_id=group_id,
            parent_item_id=parent_id,
            state=state,
            is_callback=True,
        )

    @staticmethod
    async def _handle_back_to_groups(callback: CallbackQuery, state: FSMContext, **kwargs: Any) -> None:
        """Обработка кнопки 'К группам'"""
        from ...tg import tg_manager

        await CallbackHandler.answer(callback)

        from ..handlers.aiogram.groups import show_groups

        # Очищаем историю при переходе к группам
        await state.update_data(menu_history=[])

        # Удаление текущего сообщения перед показом групп
        await tg_manager.delete_message_by_link(callback.message)

        await show_groups(event=callback.message, state=state)

    @staticmethod
    async def _handle_action(callback: CallbackQuery, state: FSMContext, **kwargs: Any) -> None:
        """Обработка выбора действия"""
        from ...tg import tg_manager

        await CallbackHandler.answer(callback)

        from ..handlers.aiogram.actions import execute_action, show_menu
        from ..handlers.aiogram.auth import get_user_group_id

        # Извлечение ID действия
        parts = callback.data.split("_")
        if len(parts) < 2:
            tg_logger.warning(f"⚠️ Invalid action callback: {callback.data}")
            return

        try:
            action_id = int(parts[1])
        except ValueError:
            tg_logger.warning(f"⚠️ Invalid action ID in callback: {callback.data}")
            return

        group_id = await get_user_group_id(callback.from_user.id)
        if not group_id:
            await tg_manager.send_toast(
                text="❌ **Группа действий не найдена**\n\n"
                "У вас не назначена группа действий в системе.\n"
                "Обратитесь к администратору для настройки прав.",
                event=callback,
            )
            return

        # ============================================================
        # ИСПОЛЬЗУЕМ РЕПОЗИТОРИЙ НАПРЯМУЮ ВМЕСТО check_has_subitems
        # ============================================================
        async with db_manager.get_session("avanpost") as session:
            has_children = await AvanpostRepository.has_subitems(
                session=session,
                group_id=group_id,
                item_id=action_id,
            )

        if has_children:
            # ============================================================
            # СОХРАНЯЕМ ИСТОРИЮ ПЕРЕХОДОВ
            # ============================================================
            state_data = await state.get_data()
            history = state_data.get("menu_history", [])

            # Добавляем текущий action_id в историю
            history.append(action_id)
            await state.update_data(menu_history=history)

            tg_logger.debug(f"📜 Added {action_id} to history: {history}")

            # Удаление текущего сообщения перед показом подменю
            await tg_manager.delete_message_by_link(callback.message)

            await show_menu(
                event=callback.message,
                group_id=group_id,
                parent_item_id=action_id,
                state=state,
                is_callback=True,
                is_new=True,
            )
        else:
            # Выполнение действия
            await execute_action(callback, action_id, state)


action_callback_handler = ActionCallbackHandler()
