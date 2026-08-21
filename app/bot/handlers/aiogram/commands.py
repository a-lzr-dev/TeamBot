"""
Модуль обработчика списка пользователей.

Этот модуль предоставляет функциональность для управления пользователями
в системе Avanpost через Telegram бота.

Основные компоненты:
    - UsersListHandler: Обработчик списка пользователей с пагинацией и поиском
    - Команда /users для просмотра списка пользователей
    - Выбор пользователя для запуска меню действий
    - Возврат к списку пользователей из меню действий

Использует GenericListCallbackHandler для универсальной обработки списков.

Функциональность:
    - Отображение списка пользователей с пагинацией
    - Поиск по пользователям
    - Выбор пользователя для выполнения действий
    - Статус авторизации пользователей
    - Только для администраторов
"""

from typing import Any

from aiogram import Router
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, Message

from ....bot.callbacks.generic import GenericListCallbackHandler, GenericSearchHandler
from ....bot.dependencies import get_bot_manager
from ....config import settings
from ....db import db_manager
from ....db.repositories import AvanpostUserRepository, UserRepository
from ....logger import bot_logger
from ....models import ErrorCategory, MessageActionType, MessageType
from ....services import error_service
from ....utils.decorators import log_exceptions
from ...keyboards import ListKeyboardBuilder
from ...keyboards.users import GROUP_ICONS
from .actions import show_menu
from .auth import _auth_cache, is_user_authenticated

# Создание роутера для обработки пользователей
router = Router(name="aiogram_users")

# Репозитории для работы с данными
_user_repo = UserRepository()
_avanpost_user_repo = AvanpostUserRepository()


class UserStates(StatesGroup):
    """Состояния для работы с пользователями."""

    viewing_users = State()  # Просмотр списка пользователей
    searching_users = State()  # Поиск пользователей


class UsersListHandler(GenericListCallbackHandler):
    """
    Обработчик списка пользователей Avanpost.

    Наследуется от GenericListCallbackHandler и реализует:
        - Загрузку данных пользователей из БД
        - Отображение списка с пагинацией
        - Обработку выбора пользователя
        - Поиск по пользователям

    Атрибуты:
        PAGE_SIZE: Количество пользователей на странице
        STATE_VIEWING: Состояние просмотра списка
        STATE_SEARCHING: Состояние поиска
    """

    def __init__(self) -> None:
        """Инициализация обработчика списка пользователей."""
        super().__init__(prefix="users", list_type="users")
        self.PAGE_SIZE = 10
        self.STATE_VIEWING = UserStates.viewing_users
        self.STATE_SEARCHING = UserStates.searching_users

    async def load_data(
        self,
        session: Any,
        page: int,
        search_query: str | None,
        **kwargs: Any,
    ) -> dict[str, Any]:
        """
        Загрузка данных пользователей из базы данных.

        Args:
            session: Сессия БД
            page: Номер страницы
            search_query: Поисковый запрос (опционально)
            **kwargs: Дополнительные параметры

        Returns:
            dict: Данные списка пользователей
        """
        try:
            # Получение пользователей из репозитория
            data = await _avanpost_user_repo.get_avanpost_users_page(
                session=session,
                page=page,
                page_size=self.PAGE_SIZE,
                search_query=search_query,
            )

            # Форматирование элементов списка
            items = []
            for user in data.get("users", []):
                is_authorized = user.get("is_authorized", False)
                group_id = user.get("group_id")

                # Получение иконки по group_id
                icon = GROUP_ICONS.get(group_id, "❓")
                auth_indicator = "🟢" if is_authorized else "⚪"
                name = user.get("name", f"User #{user.get('id')}")
                items.append(
                    {
                        "id": user.get("id"),
                        "name": user.get("name", f"User #{user.get('id')}"),
                        "display_name": f"{icon} {name} {auth_indicator}",
                        "phone": user.get("phone"),
                        "group_id": user.get("group_id"),
                        "telegram_id": user.get("telegram_id"),
                        "is_authorized": is_authorized,
                    }
                )

            return {
                "items": items,
                "total": data.get("total", 0),
                "page": data.get("page", 0),
                "total_pages": data.get("total_pages", 0),
                "has_prev": data.get("has_prev", False),
                "has_next": data.get("has_next", False),
                "search_query": data.get("search_query"),
            }
        except Exception as e:
            bot_logger.error(f"❌ Failed to load users: {e}", exc_info=True)
            return {
                "items": [],
                "total": 0,
                "page": page,
                "total_pages": 0,
                "has_prev": False,
                "has_next": False,
                "search_query": search_query,
                "error": str(e),
            }

    async def show_list(
        self,
        event: Message | CallbackQuery,
        state: FSMContext,
        page: int = 0,
        search_query: str | None = None,
        **kwargs: Any,
    ) -> None:
        """
        Отображение списка пользователей.

        Args:
            event: Сообщение или CallbackQuery
            state: Состояние FSM
            page: Номер страницы
            search_query: Поисковый запрос
            **kwargs: Дополнительные параметры
        """
        bot_manager = get_bot_manager()

        # Подтверждение получения колбэка
        if isinstance(event, CallbackQuery):
            await event.answer()

        chat_id = self._get_chat_id(event)
        if not chat_id:
            bot_logger.error("❌ Cannot determine chat_id for show_users_list")
            return

        try:
            # Загрузка данных пользователей
            async with db_manager.get_session() as session:
                data = await self.load_data(session, page, search_query)

            # Обработка ошибки загрузки
            if data.get("error"):
                await bot_manager.send_message(
                    chat_id=chat_id,
                    text=f"❌ Ошибка загрузки пользователей: {data['error']}",
                    message_type=MessageType.COMMAND_ACTION_INFO,
                    delete_by_type=MessageActionType.COMMAND_ACTION_CLEANUP,
                    parse_mode="Markdown",
                    reply_markup=self.get_close_keyboard(),
                )
                return

            items = data["items"]
            total = data["total"]
            current_page = data["page"]
            total_pages = data["total_pages"]

            # Отображение пустого списка
            if total == 0:
                empty_text = "👥 **СПИСОК ПОЛЬЗОВАТЕЛЕЙ**\n\n"
                if search_query:
                    empty_text += f"🔍 По запросу `{search_query}` пользователи не найдены."
                else:
                    empty_text += "Нет пользователей в системе."

                await bot_manager.send_message(
                    chat_id=chat_id,
                    text=empty_text,
                    message_type=MessageType.COMMAND_ACTION_INFO,
                    delete_by_type=MessageActionType.COMMAND_ACTION_CLEANUP,
                    parse_mode="Markdown",
                    reply_markup=self.get_close_keyboard(),
                )
                return

            # Формирование текста списка
            start_item = current_page * self.PAGE_SIZE + 1
            end_item = min(start_item + self.PAGE_SIZE - 1, total)

            text = "👥 **СПИСОК ПОЛЬЗОВАТЕЛЕЙ**\n\n"
            if search_query:
                text += f"🔍 **Поиск:** `{search_query}`\n"
            text += f"📊 Показаны: {start_item}-{end_item} из {total}\n"
            text += f"📄 Страница {current_page + 1} из {total_pages}\n\n"
            text += "Выберите пользователя для запуска меню действий:\n"

            # Построение клавиатуры
            builder = ListKeyboardBuilder(
                callback_prefix="users",
                buttons_per_row=2,
                item_icon="",
                max_name_length=25,
            )

            keyboard = builder.build(
                items=items,
                current_page=current_page,
                total_pages=total_pages,
                search_query=search_query,
                item_name_formatter=lambda item: item.get("display_name", item.get("name", "Unknown")),
                extra_buttons=None,
            )

            # Сохранение состояния
            state_keys = await self.get_state_keys()
            await state.update_data(
                **{
                    state_keys["page"]: current_page,
                    state_keys["search_query"]: search_query,
                }
            )

            # Отправка сообщения
            await bot_manager.send_message(
                chat_id=chat_id,
                text=text,
                message_type=MessageType.COMMAND_ACTION,
                delete_by_type=MessageActionType.COMMAND_ACTION_CLEANUP,
                parse_mode="Markdown",
                reply_markup=keyboard,
            )

        except Exception as e:
            bot_logger.error(f"❌ Failed to show users: {e}", exc_info=True)
            await error_service.log_error(
                error=e,
                component="users",
                category=ErrorCategory.SYSTEM,
            )
            await bot_manager.send_message(
                chat_id=chat_id,
                text="❌ Произошла ошибка при загрузке пользователей. Попробуйте позже.",
                message_type=MessageType.COMMAND_ACTION_INFO,
                delete_by_type=MessageActionType.COMMAND_ACTION_CLEANUP,
                parse_mode="Markdown",
                reply_markup=self.get_close_keyboard(),
            )

    async def on_select(
        self,
        callback: CallbackQuery,
        state: FSMContext,
        item_id: int,
        **kwargs: Any,
    ) -> None:
        """
        Обработка выбора пользователя.

        При выборе пользователя:
        1. Проверяет права администратора
        2. Загружает данные пользователя
        3. Сохраняет состояние выбранного пользователя
        4. Открывает меню действий для пользователя

        Args:
            callback: CallbackQuery от пользователя
            state: Состояние FSM
            item_id: ID выбранного пользователя
            **kwargs: Дополнительные параметры
        """
        bot_manager = get_bot_manager()

        # Проверка прав администратора
        if not callback.from_user or callback.from_user.id not in settings.ADMIN_IDS:
            await bot_manager.send_toast(text="⛔ У вас нет прав для этой команды.", event=callback)
            return

        try:
            # Получение данных выбранного пользователя
            async with db_manager.get_session() as session:
                user = await _user_repo.get_avanpost_user_data(session, item_id)

            if not user:
                await bot_manager.send_toast(
                    text=f"❌ Пользователь {item_id} не найден.",
                    event=callback,
                )
                return

            user_name = user.get("FName") or f"User #{item_id}"
            group_id = user.get("FK_MenuGroup")

            if not group_id:
                await bot_manager.send_toast(
                    text=f"❌ У пользователя {user_name} не назначена группа действий.",
                    event=callback,
                    show_alert=True,
                )
                return

            telegram_user_id = callback.from_user.id

            # Сохранение в кеш авторизации
            _auth_cache[telegram_user_id] = {
                "avanpost_user_id": item_id,
                "group_id": group_id,
                "phone": user.get("FPhone"),
                "telegram_user_id": telegram_user_id,
            }

            # Сохранение состояния выбранного пользователя
            await state.update_data(
                selected_user_id=item_id,
                selected_user_name=user_name,
                selected_user_group_id=group_id,
                use_group_id=group_id,
                user_id=item_id,
                is_admin=telegram_user_id in settings.ADMIN_IDS,
                menu_history=[],
            )

            await bot_manager.send_toast(
                text=f"✅ Выбран пользователь: {user_name}",
                event=callback,
            )

            # Удаление текущего сообщения
            if callback.message:
                await bot_manager.delete_message_by_link(callback.message)

            # Открытие меню действий для выбранного пользователя
            async with db_manager.get_session() as session:
                await show_menu(
                    event=callback,
                    group_id=group_id,
                    state=state,
                    session=session,
                    is_callback=True,
                    _is_new=True,
                    user_display_name=user_name,
                )

            bot_logger.info(f"✅ User {item_id} selected, showing actions menu with group {group_id}")

        except Exception as e:
            bot_logger.error(f"❌ Failed to select user: {e}", exc_info=True)
            await bot_manager.send_toast(
                text=f"❌ Ошибка при выборе пользователя: {str(e)[:100]}",
                event=callback,
                show_alert=True,
            )

    async def get_state_keys(self) -> dict[str, str]:
        """
        Получение ключей для состояния.

        Returns:
            dict: Словарь с ключами состояния
        """
        return {
            "page": "users_page",
            "search_query": "users_search_query",
            "page_before_search": "users_page_before_search",
            "search_message_id": "users_search_message_id",
            "total": "users_total",
            "total_pages": "users_total_pages",
        }

    @staticmethod
    def _get_chat_id(event: Message | CallbackQuery) -> int | None:
        """
        Получение ID чата из события.

        Args:
            event: Сообщение или CallbackQuery

        Returns:
            int | None: ID чата
        """
        if isinstance(event, Message):
            chat_id = event.chat.id
            return int(chat_id) if chat_id is not None else None
        if isinstance(event, CallbackQuery) and event.message:
            chat_id = event.message.chat.id
            return int(chat_id) if chat_id is not None else None
        return None

    def get_close_keyboard(self) -> Any:
        """
        Клавиатура с кнопкой закрытия.

        Returns:
            InlineKeyboardMarkup: Клавиатура
        """
        from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

        return InlineKeyboardMarkup(
            inline_keyboard=[[InlineKeyboardButton(text="❌ Закрыть", callback_data="users_close")]]
        )


# ============================================================
# ПУБЛИЧНЫЕ ФУНКЦИИ ДЛЯ ВНЕШНЕГО ИСПОЛЬЗОВАНИЯ
# ============================================================

# Создание экземпляра обработчика
users_handler = UsersListHandler()
users_search_handler = GenericSearchHandler(users_handler)


async def show_users_list(
    event: Message | CallbackQuery,
    state: FSMContext,
    page: int = 0,
    search_query: str | None = None,
    **kwargs: Any,
) -> None:
    """
    Публичная функция для отображения списка пользователей.

    Args:
        event: Сообщение или CallbackQuery
        state: Состояние FSM
        page: Номер страницы
        search_query: Поисковый запрос
        **kwargs: Дополнительные параметры
    """
    await users_handler.show_list(event, state, page, search_query, **kwargs)


async def back_to_users(
    event: CallbackQuery,
    state: FSMContext,
) -> None:
    """
    Возврат к списку пользователей из меню действий.

    Очищает состояние выбранного пользователя и показывает список.

    Args:
        event: CallbackQuery от пользователя
        state: Состояние FSM
    """
    bot_manager = get_bot_manager()

    # Очистка состояния от выбранного пользователя
    await state.update_data(
        selected_user_id=None,
        selected_user_name=None,
        selected_user_group_id=None,
        use_group_id=None,
        user_id=None,
        menu_history=[],
        is_admin=False,
    )

    # Сброс страницы и поиска
    state_keys = await users_handler.get_state_keys()
    await state.update_data(
        **{
            state_keys["page"]: 0,
            state_keys["search_query"]: None,
        }
    )

    # Удаление текущего сообщения
    if event.message:
        try:
            await bot_manager.delete_message_by_link(event.message)
        except Exception as e:
            bot_logger.warning(f"⚠️ Could not delete message: {e}")

    # Ответ на callback
    await event.answer()

    # Показ списка пользователей
    await users_handler.show_list(event=event, state=state, page=0)


# ============================================================
# КОМАНДА /users
# ============================================================


@router.message(Command("users"))
@log_exceptions(bot_logger)
async def cmd_users(message: Message, state: FSMContext) -> None:
    """
    Команда для вызова списка пользователей.

    Доступна только для администраторов.

    Args:
        message: Сообщение от пользователя
        state: Состояние FSM
    """
    bot_manager = get_bot_manager()

    # Проверка прав администратора
    if not message.from_user or message.from_user.id not in settings.ADMIN_IDS:
        await bot_manager.send_answer(
            text="⛔ У вас нет прав для этой команды.",
            event=message,
            message_type=MessageType.COMMAND_ACTION_INFO,
            delete_by_type=MessageActionType.COMMAND_ACTION_CLEANUP,
        )
        return

    # Проверка авторизации
    if not await is_user_authenticated(message.from_user.id):
        await bot_manager.send_answer(
            text="🔐 **Требуется авторизация**\n\n"
            "Для доступа к списку пользователей необходимо авторизоваться.\n"
            "Используйте /start для начала авторизации.",
            event=message,
            message_type=MessageType.COMMAND_ACTION_INFO,
            delete_by_type=MessageActionType.COMMAND_ACTION_CLEANUP,
        )
        return

    # Очистка состояния
    await state.update_data(
        selected_user_id=None,
        selected_user_name=None,
        selected_user_group_id=None,
        use_group_id=None,
        user_id=None,
        menu_history=[],
        is_admin=False,
    )

    # Удаление команды из чата
    await bot_manager.delete_message_by_link(message)

    # Отображение списка пользователей
    await users_handler.show_list(event=message, state=state, page=0)


# ============================================================
# РЕГИСТРАЦИЯ ОБРАБОТЧИКОВ
# ============================================================


@router.callback_query(lambda c: c.data.startswith("users_"))
async def handle_users_callback(callback: CallbackQuery, state: FSMContext) -> None:
    """
    Обработка колбэков для пользователей.

    Args:
        callback: CallbackQuery от пользователя
        state: Состояние FSM
    """
    await users_handler.handle(callback, state)


@router.message(UserStates.searching_users)
async def handle_users_search(message: Message, state: FSMContext) -> None:
    """
    Обработка поискового запроса для пользователей.

    Args:
        message: Сообщение с поисковым запросом
        state: Состояние FSM
    """
    await users_search_handler.handle_search_query(message, state)


__all__ = [
    "router",
    "UserStates",
    "cmd_users",
    "show_users_list",
    "back_to_users",
    "users_handler",
]
