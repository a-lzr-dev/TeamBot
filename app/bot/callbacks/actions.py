"""
Обработчик колбэков для меню действий.
Использует GenericListCallbackHandler для универсальной обработки.
"""

from typing import Any

from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery

from ...bot.dependencies import get_bot_manager
from ...db import db_manager
from ...db.repositories import AvanpostActionRepository
from ...logger import bot_logger
from .base import CallbackHandler
from .generic import GenericListCallbackHandler


class ActionCallbackHandler(GenericListCallbackHandler):
    """
    Обработчик колбэков для меню действий.
    Использует GenericListCallbackHandler для универсальной обработки.
    """

    PREFIX_ACTION = "action_"
    PREFIX_BACK = "action_back_"
    PREFIX_HOME = "action_home"
    PREFIX_BACK_TO_GROUPS = "back_to_groups"

    def __init__(self) -> None:
        super().__init__(prefix=self.PREFIX_ACTION, list_type="action")
        # PAGE_SIZE для совместимости, но не используется для меню действий
        self.PAGE_SIZE = 50

    async def handle(self, callback: CallbackQuery, state: FSMContext, **kwargs: Any) -> Any:
        """Обработка колбэка действия"""
        callback_data = callback.data
        bot_logger.debug(f"🔍 [ActionCallbackHandler] Received callback: {callback_data}")

        if not callback_data:
            bot_logger.warning("⚠️ Empty callback data")
            await CallbackHandler.answer(callback, "Неизвестное действие")
            return None

        # Если callback от списка (select_) - передаем родителю
        if "_select_" in callback_data:
            bot_logger.debug(f"🔍 [ActionCallbackHandler] List selection detected: {callback_data}")
            return await super().handle(callback, state, **kwargs)

        # Получение дополнительных параметров
        session = kwargs.get("session")
        group_id = kwargs.get("group_id")
        user_display_name = kwargs.get("user_display_name")

        # Обработка специальных колбэков
        if callback_data == self.PREFIX_HOME:
            return await self._handle_home(callback, state, session=session, group_id=group_id)

        if callback_data.startswith(self.PREFIX_BACK):
            return await self._handle_back(
                callback, state, session=session, group_id=group_id, user_display_name=user_display_name
            )

        if callback_data.startswith(self.PREFIX_ACTION):
            return await self._handle_action(
                callback, state, session=session, group_id=group_id, user_display_name=user_display_name
            )

        # Если не обработано - передаем родителю
        bot_logger.debug(f"🔍 [ActionCallbackHandler] Unhandled, passing to parent: {callback_data}")
        return await super().handle(callback, state, **kwargs)

    @staticmethod
    async def _handle_home(
        callback: CallbackQuery,
        state: FSMContext,
        session: Any = None,
        group_id: int | None = None,
    ) -> None:
        """Обработка кнопки 'В главное меню'"""
        await CallbackHandler.answer(callback)

        from ..handlers.aiogram.actions import show_menu
        from ..handlers.aiogram.auth import get_user_group_id

        if not group_id:
            group_id = await get_user_group_id(callback.from_user.id)

        if not group_id:
            bot_manager = get_bot_manager()
            await bot_manager.send_toast(
                text="❌ **Группа действий не найдена**\n\n"
                "У вас не назначена группа действий в системе.\n"
                "Обратитесь к администратору для настройки прав.",
                event=callback,
            )
            return

        # Очистка истории при переходе в главное меню
        await state.update_data(menu_history=[])

        if session is None:
            async with db_manager.get_session("main") as new_session:
                await show_menu(
                    event=callback,
                    group_id=group_id,
                    state=state,
                    session=new_session,
                    is_callback=True,
                )
        else:
            await show_menu(
                event=callback,
                group_id=group_id,
                state=state,
                session=session,
                is_callback=True,
            )

    @staticmethod
    async def _handle_back(
        callback: CallbackQuery,
        state: FSMContext,
        session: Any = None,
        group_id: int | None = None,
        user_display_name: str | None = None,
    ) -> None:
        """Обработка кнопки 'Назад'"""
        bot_manager = get_bot_manager()
        await bot_manager.send_toast(event=callback)

        from ...db import db_manager
        from ..handlers.aiogram.actions import show_menu
        from ..handlers.aiogram.auth import get_user_group_id

        if not group_id:
            group_id = await get_user_group_id(callback.from_user.id)

        if not group_id:
            await bot_manager.send_toast(
                text="❌ **Группа действий не найдена**\n\n"
                "У вас не назначена группа действий в системе.\n"
                "Обратитесь к администратору для настройки прав.",
                event=callback,
            )
            return

        callback_data = callback.data
        if not callback_data:
            await bot_manager.send_toast(text="❌ Не удалось определить действие.", event=callback)
            return

        parts = callback_data.split("_")
        parent_id = None
        if len(parts) >= 3:
            try:
                parent_id = int(parts[2])
                if parent_id == 0:
                    parent_id = None
            except ValueError:
                parent_id = None

        state_data = await state.get_data()
        history = state_data.get("menu_history", [])

        bot_logger.debug(f"📜 Current history: {history}, current parent_id: {parent_id}")

        if parent_id is not None and history:
            if history and history[-1] == parent_id:
                history.pop()
                bot_logger.debug(f"🗑️ Removed {parent_id} from history")
            if history:
                parent_id = history[-1]
                bot_logger.debug(f"🔙 Parent from history: {parent_id}")
            else:
                parent_id = None
                bot_logger.debug("🔙 No more history, going to root menu")
        elif parent_id is not None and not history:
            parent_id = None
            bot_logger.debug("🔙 History is empty, going to root menu")
        else:
            await bot_manager.send_toast(text="Вы уже в главном меню", event=callback)
            return

        await state.update_data(menu_history=history)
        bot_logger.debug(f"🔙 Navigate back to parent_id: {parent_id}, history: {history}")

        if session is None:
            async with db_manager.get_session("main") as new_session:
                await show_menu(
                    event=callback,
                    group_id=group_id,
                    parent_item_id=parent_id,
                    state=state,
                    session=new_session,
                    is_callback=True,
                    user_display_name=user_display_name,
                )
        else:
            await show_menu(
                event=callback,
                group_id=group_id,
                parent_item_id=parent_id,
                state=state,
                session=session,
                is_callback=True,
                user_display_name=user_display_name,
            )

    async def _handle_action(
        self,
        callback: CallbackQuery,
        state: FSMContext,
        action_id: int | None = None,
        session: Any = None,
        group_id: int | None = None,
        user_display_name: str | None = None,
    ) -> None:
        """
        Обработка выбора действия.

        Args:
            callback: CallbackQuery от пользователя
            state: Состояние FSM
            action_id: ID действия (если передан напрямую)
            session: Сессия БД
            group_id: ID группы действий
            user_display_name: Отображаемое имя пользователя
        """
        bot_logger.debug(f"🔍 [_handle_action] START: {callback.data}, action_id={action_id}")
        await CallbackHandler.answer(callback)

        from ...db import db_manager
        from ..handlers.aiogram.actions import execute_action
        from ..handlers.aiogram.auth import get_user_group_id

        callback_data = callback.data
        if not callback_data:
            bot_logger.warning("⚠️ Empty callback data")
            await CallbackHandler.answer(callback, "Неизвестное действие")
            return

        # Если action_id не передан - извлекаем из callback_data
        if action_id is None:
            # Извлечение ID действия из разных форматов:
            # - action_119
            # - action_select_119 (от ListKeyboardBuilder)
            parts = callback_data.split("_")

            if len(parts) < 2:
                bot_logger.warning(f"⚠️ Invalid action callback: {callback_data}")
                return

            # Проверяем, что последняя часть - число
            try:
                # Берем последнюю часть, т.к. формат может быть action_select_119
                action_id = int(parts[-1])
            except ValueError:
                bot_logger.warning(f"⚠️ Invalid action ID in callback: {callback_data}")
                return

        bot_logger.debug(f"🔍 [_handle_action] Extracted action_id: {action_id}")

        if not group_id:
            group_id = await get_user_group_id(callback.from_user.id)

        if not group_id:
            bot_manager = get_bot_manager()
            await bot_manager.send_toast(
                text="❌ **Группа действий не найдена**\n\n"
                "У вас не назначена группа действий в системе.\n"
                "Обратитесь к администратору для настройки прав.",
                event=callback,
            )
            return

        if session is None:
            async with db_manager.get_session("main") as new_session:
                has_children = await AvanpostActionRepository.has_subitems(
                    session=new_session,
                    group_id=group_id,
                    item_id=action_id,
                )

                if has_children:
                    await self._show_submenu(
                        callback=callback,
                        state=state,
                        session=new_session,
                        group_id=group_id,
                        action_id=action_id,
                        user_display_name=user_display_name,
                    )
                else:
                    await execute_action(callback, action_id, state)
        else:
            has_children = await AvanpostActionRepository.has_subitems(
                session=session,
                group_id=group_id,
                item_id=action_id,
            )

            if has_children:
                await self._show_submenu(
                    callback=callback,
                    state=state,
                    session=session,
                    group_id=group_id,
                    action_id=action_id,
                    user_display_name=user_display_name,
                )
            else:
                await execute_action(callback, action_id, state)

    @staticmethod
    async def _show_submenu(
        callback: CallbackQuery,
        state: FSMContext,
        session: Any,
        group_id: int,
        action_id: int,
        user_display_name: str | None = None,
    ) -> None:
        """Показать подменю"""
        from app.bot.handlers.aiogram.actions import show_menu

        bot_manager = get_bot_manager()
        await bot_manager.send_toast(event=callback)

        state_data = await state.get_data()
        history = state_data.get("menu_history", [])
        history.append(action_id)
        await state.update_data(menu_history=history)

        bot_logger.debug(f"📜 Added {action_id} to history: {history}")

        # Удаление текущего сообщения перед показом подменю
        if callback.message:
            await bot_manager.delete_message_by_link(callback.message)

        await show_menu(
            event=callback.message,
            group_id=group_id,
            parent_item_id=action_id,
            state=state,
            session=session,
            is_callback=True,
            _is_new=True,
            user_display_name=user_display_name,
        )

    # ============================================================
    # Методы для совместимости с GenericListCallbackHandler
    # Переопределяем с заглушками, так как для меню действий
    # используются специальные методы _handle_action, _handle_back, _handle_home
    # ============================================================

    async def load_data(self, session: Any, page: int, search_query: str | None, **kwargs: Any) -> dict[str, Any]:
        """Загрузка данных для списка (не используется для меню действий)"""
        return {"items": [], "total": 0, "page": 0, "total_pages": 1, "has_prev": False, "has_next": False}

    async def show_list(
        self, event: Any, state: FSMContext, page: int = 0, search_query: str | None = None, **kwargs: Any
    ) -> None:
        """Отображение списка (не используется для меню действий)"""
        pass

    async def on_select(self, callback: CallbackQuery, state: FSMContext, item_id: int, **kwargs: Any) -> None:
        """Обработка выбора элемента (перенаправляем на _handle_action)"""
        await self._handle_action(callback, state, action_id=item_id, **kwargs)


action_callback_handler = ActionCallbackHandler()
