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
    - users_<page>_page_search_<query> - переключение страницы с поиском
    - users_<page>_select_<user_id> - выбор пользователя
    - users_close - закрытие списка
    - users_search - кнопка поиска
    - users_cancel_search - ОТМЕНА ПОИСКА (НОВЫЙ)
    """

    PREFIX_USERS = "users_"
    PREFIX_CLOSE = "users_close"
    PREFIX_SEARCH = "users_search"
    PREFIX_CANCEL_SEARCH = "users_cancel_search"  # НОВЫЙ ПРЕФИКС

    def __init__(self) -> None:
        super().__init__(self.PREFIX_USERS)

    async def handle(self, callback: CallbackQuery, state: FSMContext, **kwargs: Any) -> Any:
        """Обработка колбэка пользователей"""
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

        # Обработка поиска
        if callback_data == self.PREFIX_SEARCH:
            return await self._handle_search(callback, state, **kwargs)

        # Обработчик: отмена поиска
        if callback_data == self.PREFIX_CANCEL_SEARCH:
            return await self._handle_cancel_search(callback, state, **kwargs)

        # Обработка переключения страницы и выбора пользователя
        if callback_data.startswith(self.PREFIX_USERS):
            return await self._handle_users_action(callback, state, **kwargs)

        bot_logger.warning(f"⚠️ Unknown users callback: {callback_data}")
        await CallbackHandler.answer(callback, "Неизвестное действие")
        return None

    # ============ ОБРАБОТЧИКИ ============

    @staticmethod
    async def _handle_close(callback: CallbackQuery, state: FSMContext, **_kwargs: Any) -> None:
        """Закрытие списка пользователей / отмена поиска"""
        await CallbackHandler.answer(callback)

        # Проверка нахождения в состоянии поиска
        current_state = await state.get_state()

        if current_state == "UserStates:searching_users":
            # Если в поиске - возврат к списку
            from app.bot.handlers.aiogram.users import show_users

            # Сброс состояния поиска
            await state.set_state(None)
            await state.update_data(search_query=None)

            # Получение сохраненной страницы
            data = await state.get_data()
            page = data.get("users_page_before_search", 0)
            await state.update_data(users_page_before_search=0)

            # Отображение списка пользователей
            await show_users(event=callback, state=state, page=page, search_query=None)
        else:
            # Обычное закрытие
            from app.bot.handlers.aiogram.users import close_users_list

            await close_users_list(callback, state)

    @staticmethod
    async def _handle_search(callback: CallbackQuery, state: FSMContext, **_kwargs: Any) -> None:
        """Обработка кнопки поиска"""
        await callback.answer("🔍 Введите поисковый запрос", show_alert=False)

        from app.bot.handlers.aiogram.users import handle_users_search_button

        await handle_users_search_button(callback, state)

    @staticmethod
    async def _handle_cancel_search(callback: CallbackQuery, state: FSMContext, **_kwargs: Any) -> None:
        """Отмена поиска - возврат к списку пользователей"""
        await callback.answer("👥 Возврат к списку пользователей", show_alert=False)

        from app.bot.handlers.aiogram.users import show_users

        # Сброс состояния поиска
        await state.set_state(None)

        # Получение сохраненной страницы
        data = await state.get_data()
        page = data.get("users_page_before_search", 0)

        # Очистка временных переменных
        await state.update_data(
            users_page_before_search=0,
            search_query=None,
        )

        # Удаление сообщения с поиском
        if callback.message:
            try:
                await callback.message.delete()
                bot_logger.debug("🗑️ Deleted search message")
            except Exception as e:
                bot_logger.warning(f"⚠️ Could not delete message: {e}")

        # Отображение списка пользователей
        await show_users(event=callback, state=state, page=page, search_query=None)

        bot_logger.info("✅ Search cancelled, returned to users list")

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

            # Проверка наличия поискового запроса в callback_data
            search_query = None
            if len(parts) >= 5 and parts[3] == "search" and action in ("page", "select"):
                search_query = parts[4]

            if action == "page":
                # Переключение страницы
                await CallbackHandler.answer(callback)

                from app.bot.handlers.aiogram.users import show_users

                await show_users(
                    event=callback,
                    state=state,
                    page=page,
                    search_query=search_query,
                )

            elif action == "select":
                # Выбор пользователя
                if len(parts) < 4:
                    bot_logger.warning(f"⚠️ No user_id in select callback: {callback_data}")
                    return

                # Если есть поисковый запрос, user_id может быть на позиции 3 или 4
                user_id_idx = 3
                if search_query is not None:
                    user_id_idx = 4

                if len(parts) <= user_id_idx:
                    bot_logger.warning(f"⚠️ No user_id in select callback: {callback_data}")
                    return

                user_id = int(parts[user_id_idx])
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
            from app.bot.handlers.aiogram.users import select_user

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
