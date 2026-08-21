"""
Модуль общих функций для отображения меню и навигации.

Этот модуль предоставляет основные функции для работы с меню действий:
- Отображение иерархического меню действий
- Формирование заголовков и клавиатур
- Навигация по меню (возврат, переход в главное меню)
- Управление состоянием выбранного пользователя

Основные компоненты:
    - show_menu: Отображение меню действий
    - back_to_users: Возврат к списку пользователей
    - show_users_list: Отображение списка пользователей
"""

from typing import Any

from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, InlineKeyboardMarkup, Message

from ....bot.dependencies import get_bot_manager
from ....config import settings
from ....db.repositories import AvanpostActionRepository
from ....logger import bot_logger
from ....models import ErrorCategory, MessageActionType, MessageType
from ....services.error_service import error_service
from ....utils.decorators import log_exceptions
from ...keyboards import ListKeyboardBuilder

# Количество кнопок в ряду из настроек
BUTTONS_PER_ROW = getattr(settings, "KEYBOARD_BUTTONS_PER_ROW", 3)


@log_exceptions(bot_logger)
async def show_menu(
    *,
    event: Message | CallbackQuery,
    group_id: int,
    state: FSMContext,
    session: Any,
    parent_item_id: int | None = None,
    is_callback: bool = False,
    _is_new: bool = False,
    user_display_name: str | None = None,
) -> None:
    """
    Отображение меню действий с использованием ListKeyboardBuilder.

    Загружает пункты меню для указанной группы действий и родительского элемента,
    формирует заголовок и клавиатуру, отправляет сообщение пользователю.

    Args:
        event: Сообщение или CallbackQuery
        group_id: ID группы действий
        state: Состояние FSM
        session: Сессия БД
        parent_item_id: ID родительского элемента (для подменю)
        is_callback: Является ли событие CallbackQuery
        _is_new: Флаг нового меню (для удаления предыдущего)
        user_display_name: Имя выбранного пользователя
    """
    bot_manager = get_bot_manager()
    _actions_repo = AvanpostActionRepository()

    user_id = None
    try:
        # Получение ID пользователя из состояния или события
        state_data = await state.get_data()
        user_id = state_data.get("user_id")
        selected_user_id = state_data.get("selected_user_id")

        if selected_user_id and not user_id:
            user_id = selected_user_id

        if not user_id and (
            (isinstance(event, CallbackQuery) and event.from_user) or (isinstance(event, Message) and event.from_user)
        ):
            user_id = event.from_user.id

        if not user_id:
            await bot_manager.send_toast(text="❌ Не удалось определить пользователя", event=event)
            return

        # Сохранение прав администратора
        is_admin = user_id in settings.ADMIN_IDS
        await state.update_data(user_id=user_id, is_admin=is_admin)

        # Получение данных меню из репозитория
        lang_code = "RU"
        menu_data = await _actions_repo.get_menu_items_with_parent(
            session=session,
            group_id=group_id,
            parent_item_id=parent_item_id,
            lang_code=lang_code,
        )

        menu_items = menu_data.get("items", [])
        parent_name = menu_data.get("parent_name")
        parent_id = menu_data.get("parent_id")

        # Обработка пустого меню
        if not menu_items:
            empty_text = "📋 Нет доступных действий."
            keyboard = _get_empty_menu_keyboard(
                parent_item_id=parent_item_id,
                show_back_to_users=bool(state_data.get("selected_user_id")),
            )
            await _send_menu_message(event, empty_text, keyboard, bot_manager)
            return

        # Формирование заголовка
        header_text = _build_menu_header(parent_item_id, parent_name, user_display_name)

        # Создание клавиатуры через ListKeyboardBuilder
        builder = ListKeyboardBuilder(
            callback_prefix="action",
            buttons_per_row=BUTTONS_PER_ROW,
            item_icon="",
            max_name_length=25,
        )

        # Формирование дополнительных кнопок
        extra_buttons = []

        # Кнопка "Назад" для подменю
        if parent_item_id is not None:
            extra_buttons.append(("🔙 Назад", f"action_back_{parent_id or 0}"))

        # Кнопка "В главное меню"
        if parent_item_id is not None:
            extra_buttons.append(("🏠 В главное меню", "action_home"))

        # Кнопка "К пользователям" для администраторов
        if is_admin or state_data.get("selected_user_id"):
            extra_buttons.append(("👥 К пользователям", "back_to_users"))

        # Построение клавиатуры
        keyboard = builder.build(
            items=menu_items,
            current_page=0,
            total_pages=1,
            search_query=None,
            extra_buttons=extra_buttons if extra_buttons else None,
            item_name_formatter=lambda item: _format_item_name(item),
        )

        # Отправка сообщения меню
        await _send_menu_message(event, header_text, keyboard, bot_manager, state, is_callback, _is_new)

    except Exception as e:
        bot_logger.error(f"❌ Failed to show menu: {e}", exc_info=True)
        await error_service.log_error(
            error=e,
            component="actions",
            category=ErrorCategory.SYSTEM,
            context={
                "parent_id": parent_item_id,
                "group_id": group_id,
                "user_id": user_id if user_id else None,
            },
        )


def _format_item_name(item: dict[str, Any]) -> str:
    """
    Форматирование названия пункта меню.

    Добавляет иконку в зависимости от наличия подменю.

    Args:
        item: Данные пункта меню

    Returns:
        str: Отформатированное название
    """
    name = item.get("name", "Без названия")
    has_subitems = item.get("has_subitems", False)
    prefix = "▶️ " if has_subitems else "• "
    return f"{prefix}{name}"


def _build_menu_header(
    parent_item_id: int | None,
    parent_name: str | None,
    user_display_name: str | None,
) -> str:
    """
    Формирование заголовка меню.

    Args:
        parent_item_id: ID родительского элемента
        parent_name: Название родительского элемента
        user_display_name: Имя выбранного пользователя

    Returns:
        str: Отформатированный заголовок
    """
    header = "✨ 📋 **МЕНЮ ДЕЙСТВИЙ**"

    # Добавление имени пользователя
    if user_display_name:
        header += f" 👤 {user_display_name}"

    # Добавление названия подменю
    if parent_item_id is not None:
        header += f" • 📂 {parent_name or 'Подменю'} ✨"
    else:
        header += " ✨"

    header += "\n\n"
    return header


def _get_empty_menu_keyboard(
    parent_item_id: int | None,
    show_back_to_users: bool,
) -> InlineKeyboardMarkup | None:
    """
    Получение клавиатуры для пустого меню.

    Args:
        parent_item_id: ID родительского элемента
        show_back_to_users: Показывать кнопку "К пользователям"

    Returns:
        InlineKeyboardMarkup | None: Клавиатура или None
    """
    from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

    buttons = []

    # Кнопка "Назад"
    if parent_item_id is not None:
        buttons.append(InlineKeyboardButton(text="🔙 Назад", callback_data=f"action_back_{parent_item_id}"))

    # Кнопка "К пользователям"
    if show_back_to_users:
        buttons.append(InlineKeyboardButton(text="👥 К пользователям", callback_data="back_to_users"))

    if buttons:
        return InlineKeyboardMarkup(inline_keyboard=[buttons])

    return None


async def _send_menu_message(
    event: Message | CallbackQuery,
    text: str,
    keyboard: InlineKeyboardMarkup | None,
    bot_manager: Any,
    state: FSMContext | None = None,
    is_callback: bool = False,
    _is_new: bool = False,
) -> None:
    """
    Отправка сообщения меню.

    Args:
        event: Сообщение или CallbackQuery
        text: Текст сообщения
        keyboard: Клавиатура
        bot_manager: Экземпляр BotManager
        state: Состояние FSM (опционально)
        is_callback: Является ли событие CallbackQuery
        _is_new: Флаг нового меню
    """

    def _get_chat_id(e: Message | CallbackQuery) -> int:
        """Получение ID чата из события."""
        if isinstance(e, Message):
            chat_id = e.chat.id
            return int(chat_id) if chat_id is not None else 0
        if isinstance(e, CallbackQuery) and e.message:
            chat_id = e.message.chat.id
            return int(chat_id) if chat_id is not None else 0
        return 0

    # Обработка CallbackQuery - удаляем старое сообщение
    if is_callback and isinstance(event, CallbackQuery):
        if event.message:
            await bot_manager.delete_message_by_link(event.message)

        # Отправка нового сообщения
        result = await bot_manager.send_message(
            chat_id=event.message.chat.id if event.message else 0,
            text=text,
            message_type=MessageType.COMMAND_ACTION,
            delete_by_type=MessageActionType.COMMAND_ACTION_CLEANUP,
            parse_mode="Markdown",
            reply_markup=keyboard,
        )
        if result.get("success") and state:
            await state.update_data(last_action_message_id=result.get("message_id"))
    else:
        # Обработка Message
        chat_id = _get_chat_id(event)
        if chat_id:
            await bot_manager.send_message(
                chat_id=chat_id,
                text=text,
                message_type=MessageType.COMMAND_ACTION,
                delete_by_type=MessageActionType.COMMAND_ACTION_CLEANUP,
                parse_mode="Markdown",
                reply_markup=keyboard,
            )


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

    # Отложенный импорт для избежания циклической зависимости
    from .users import users_handler

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
    from .users import users_handler

    await users_handler.show_list(event, state, page, search_query, **kwargs)


__all__ = [
    "show_menu",
    "back_to_users",
    "show_users_list",
]
