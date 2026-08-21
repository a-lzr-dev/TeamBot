"""
Обработчик колбэков для меню действий.

Использует GenericListCallbackHandler для универсальной обработки.
Обеспечивает навигацию по иерархическому меню действий Avanpost:
- Отображение корневого меню и подменю
- Обработка выбора действий
- Навигация назад и в главное меню
- Выполнение действий пользователя
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
    Обработчик колбэков для меню действий Avanpost.

    Расширяет GenericListCallbackHandler для работы с иерархическим меню
    действий. Поддерживает навигацию по дереву действий и выполнение
    конечных действий.

    Префиксы колбэков:
        - action_<id>: Выбор действия или переход в подменю
        - action_back_<parent_id>: Возврат на предыдущий уровень
        - action_home: Возврат в главное меню
        - back_to_groups: Возврат к списку групп
        - action_select_<id>: Выбор из списка (от GenericListCallbackHandler)
    """

    PREFIX_ACTION = "action_"
    PREFIX_BACK = "action_back_"
    PREFIX_HOME = "action_home"
    PREFIX_BACK_TO_GROUPS = "back_to_groups"

    def __init__(self) -> None:
        """Инициализация обработчика действий."""
        super().__init__(prefix=self.PREFIX_ACTION, list_type="action")
        # PAGE_SIZE для совместимости с родительским классом
        self.PAGE_SIZE = 50

    async def handle(self, callback: CallbackQuery, state: FSMContext, **kwargs: Any) -> Any:
        """
        Основной метод обработки колбэка действия.

        Определяет тип колбэка и вызывает соответствующий обработчик.

        Args:
            callback: CallbackQuery от пользователя
            state: Состояние FSM
            **kwargs: Дополнительные параметры (session, group_id, user_display_name)

        Returns:
            Any: Результат обработки
        """
        callback_data = callback.data
        bot_logger.debug(f"🔍 [ActionCallbackHandler] Received callback: {callback_data}")

        if not callback_data:
            bot_logger.warning("⚠️ Empty callback data")
            await CallbackHandler.answer(callback, "Неизвестное действие")
            return None

        # Если колбэк от списка (select_) - передаем родительскому обработчику
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

        # Если не обработано - передаем родительскому обработчику
        bot_logger.debug(f"🔍 [ActionCallbackHandler] Unhandled, passing to parent: {callback_data}")
        return await super().handle(callback, state, **kwargs)

    @staticmethod
    async def _handle_home(
        callback: CallbackQuery,
        state: FSMContext,
        session: Any = None,
        group_id: int | None = None,
    ) -> None:
        """
        Обработка кнопки 'В главное меню'.

        Возвращает пользователя в корневое меню группы действий.

        Args:
            callback: CallbackQuery от пользователя
            state: Состояние FSM
            session: Сессия БД
            group_id: ID группы действий
        """
        await CallbackHandler.answer(callback)

        from ..handlers.aiogram.actions import show_menu
        from ..handlers.aiogram.auth import get_user_group_id

        # Получение ID группы пользователя, если не передан
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

        # Показ главного меню
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
        """
        Обработка кнопки 'Назад'.

        Возвращает пользователя на предыдущий уровень меню.

        Args:
            callback: CallbackQuery от пользователя
            state: Состояние FSM
            session: Сессия БД
            group_id: ID группы действий
            user_display_name: Отображаемое имя пользователя
        """
        bot_manager = get_bot_manager()
        await bot_manager.send_toast(event=callback)

        from ...db import db_manager
        from ..handlers.aiogram.actions import show_menu
        from ..handlers.aiogram.auth import get_user_group_id
        from ..handlers.aiogram.states import ChatDetailsStates, SubMenuStates

        # Получение ID группы пользователя, если не передан
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

        # Извлечение ID родительского элемента из колбэка
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
        current_state = await state.get_state()

        bot_logger.debug(f"📜 Current history: {history}, current parent_id: {parent_id}, state: {current_state}")

        # ============= Исключения =============
        # Возвращение в список чатов, если в деталях чата
        if current_state == ChatDetailsStates.viewing_messages:
            bot_logger.debug("🔄 Returning from chat details to chats list")

            avanpost_user_id = state_data.get("avanpost_user_id")
            if not avanpost_user_id:
                await bot_manager.send_toast(text="❌ Не удалось определить пользователя.", event=callback)
                return

            # Возвращение в состояние просмотра чатов
            await state.set_state(SubMenuStates.viewing_chats)
            await state.update_data(
                chats_page=0,
                chats_search_query=None,
                parent_item_id=parent_id,
                avanpost_user_id=avanpost_user_id,
                selected_chat_id=None,  # Очистка выбранного чата
            )

            from ..handlers.aiogram.lists.chats import show_chats_list

            await show_chats_list(
                event=callback,
                state=state,
                avanpost_user_id=avanpost_user_id,
                page=0,
            )
            return

        # Управление историей навигации
        state_data = await state.get_data()
        history = state_data.get("menu_history", [])

        bot_logger.debug(f"📜 Current history: {history}, current parent_id: {parent_id}")

        if parent_id is not None and parent_id in history:
            # Находждение индекса текущего элемента в истории
            index = history.index(parent_id)
            # Удаление текущего элемент и все, что после него
            history = history[:index]
            bot_logger.debug(f"🗑️ Removed {parent_id} and all after from history")

            # Взятие последнего элемента как нового родителя
            if history:
                parent_id = history[-1]
                bot_logger.debug(f"🔙 Parent from history: {parent_id}")
            else:
                parent_id = None
                bot_logger.debug("🔙 No more history, going to root menu")
        elif parent_id is not None and not history:
            # Если истории нет, но пришел parent_id - идем в корень
            parent_id = None
            bot_logger.debug("🔙 History is empty, going to root menu")
        else:
            # Если parent_id не передан или не найден в истории
            await bot_manager.send_toast(text="Вы уже в главном меню", event=callback)
            return

        # Сохранение обновленной истории
        await state.update_data(menu_history=history)
        bot_logger.debug(f"🔙 Navigate back to parent_id: {parent_id}, history: {history}")

        # Отображение меню на предыдущем уровне
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

        Определяет, является ли действие конечным или имеет подменю.
        Если имеет подменю - показывает его, иначе выполняет действие.

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

            # Взятие последней части, т.к. формат может быть action_select_119
            try:
                action_id = int(parts[-1])
            except ValueError:
                bot_logger.warning(f"⚠️ Invalid action ID in callback: {callback_data}")
                return

        bot_logger.debug(f"🔍 [_handle_action] Extracted action_id: {action_id}")

        # Получение ID группы пользователя, если не передан
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

        # Проверка наличия подменю
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
                    # Выполнение конечного действия
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
        """
        Показать подменю для выбранного действия.

        Args:
            callback: CallbackQuery от пользователя
            state: Состояние FSM
            session: Сессия БД
            group_id: ID группы действий
            action_id: ID выбранного действия (родитель)
            user_display_name: Отображаемое имя пользователя
        """
        from app.bot.handlers.aiogram.actions import show_menu

        bot_manager = get_bot_manager()
        await bot_manager.send_toast(event=callback)

        # Добавление в историю навигации
        state_data = await state.get_data()
        history = state_data.get("menu_history", [])
        history.append(action_id)
        await state.update_data(menu_history=history)

        bot_logger.debug(f"📜 Added {action_id} to history: {history}")

        # Удаление текущего сообщения перед отображением подменю
        if callback.message:
            await bot_manager.delete_message_by_link(callback.message)

        # Отображение подменю
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
    # ============================================================

    async def load_data(self, session: Any, page: int, search_query: str | None, **kwargs: Any) -> dict[str, Any]:
        """
        Загрузка данных для списка.

        Не используется для меню действий, оставлен для совместимости
        с родительским классом.

        Returns:
            dict: Пустой результат
        """
        return {"items": [], "total": 0, "page": 0, "total_pages": 1, "has_prev": False, "has_next": False}

    async def show_list(
        self, event: Any, state: FSMContext, page: int = 0, search_query: str | None = None, **kwargs: Any
    ) -> None:
        """
        Отображение списка.

        Не используется для меню действий, оставлен для совместимости
        с родительским классом.
        """
        pass

    async def on_select(self, callback: CallbackQuery, state: FSMContext, item_id: int, **kwargs: Any) -> None:
        """
        Обработка выбора элемента из списка.

        Перенаправляет на _handle_action для обработки выбора действия.

        Args:
            callback: CallbackQuery от пользователя
            state: Состояние FSM
            item_id: ID выбранного элемента
            **kwargs: Дополнительные параметры
        """
        await self._handle_action(callback, state, action_id=item_id, **kwargs)


action_callback_handler = ActionCallbackHandler()
