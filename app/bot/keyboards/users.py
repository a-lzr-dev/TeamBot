from typing import Any

from aiogram.types import InlineKeyboardMarkup

from ...config import settings
from ...logger import bot_logger
from .generic import ListKeyboardBuilder

BUTTONS_PER_ROW_USERS = getattr(settings, "KEYBOARD_BUTTONS_PER_ROW", 2)

# Маппинг FK_Group на иконку (эмодзи)
GROUP_ICONS = {
    1: "👤",  # Сотрудник
    2: "🚗",  # Машина
    3: "🏢",  # Объект
    4: "🧑‍️",  # Водитель
    6: "🔄",  # Базы обмена
    7: "👥",  # Группа контактов
    8: "👤",  # Пользователь
    9: "🚚",  # Перевозка привлеченным транспортом
    10: "📇",  # Контакты групп контактов
    11: "❓",  # Неизвестный
}


class UserKeyboard:
    """Клавиатуры для списка пользователей"""

    @staticmethod
    def get_users_keyboard(
        users: list[dict[str, Any]],
        current_page: int = 0,
        total_pages: int = 1,
        has_prev: bool = False,
        has_next: bool = False,
        search_query: str | None = None,
    ) -> InlineKeyboardMarkup:
        """
        Создание клавиатуры со списком пользователей через ListKeyboardBuilder.
        """
        builder = ListKeyboardBuilder(
            callback_prefix="users",
            buttons_per_row=BUTTONS_PER_ROW_USERS,
            item_icon="",
            max_name_length=30,
        )

        return builder.build(
            items=users,
            current_page=current_page,
            total_pages=total_pages,
            search_query=search_query,
            extra_buttons=None,
            item_name_formatter=lambda item: format_user_item(item),
        )

    @staticmethod
    def get_close_keyboard() -> InlineKeyboardMarkup:
        """Клавиатура с кнопкой закрытия"""
        builder = ListKeyboardBuilder(callback_prefix="users")
        return builder.build(
            items=[],
            current_page=0,
            total_pages=1,
            extra_buttons=None,
        )

    @staticmethod
    def get_search_cancel_keyboard() -> InlineKeyboardMarkup:
        """Клавиатура для отмены поиска"""
        from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

        return InlineKeyboardMarkup(
            inline_keyboard=[[InlineKeyboardButton(text="❌ Отменить поиск", callback_data="users_cancel_search")]]
        )


def format_user_item(item: dict[str, Any]) -> str:
    """Форматирование элемента пользователя с иконкой в зависимости от FK_Group"""
    name = item.get("name", f"User #{item.get('id', '?')}")
    is_authorized = item.get("is_authorized", False)
    group_id = item.get("group_id")

    bot_logger.debug(f"🔍 format_user_item: name={name}, group_id={group_id}, is_authorized={is_authorized}")

    # Если group_id None или 0, используем значение по умолчанию (11 - Неизвестный)
    if group_id is None or group_id == 0:
        group_id = 11

    # Получение иконки по group_id
    icon = GROUP_ICONS.get(group_id, "❓")

    # Если пользователь авторизован, добавляем зеленый кружок, иначе белый
    auth_indicator = "🟢" if is_authorized else "⚪"

    result = f"{icon} {name} {auth_indicator}"
    bot_logger.debug(f"🔍 format_user_item result: {result}")

    return result


get_users_keyboard = UserKeyboard.get_users_keyboard
get_close_keyboard = UserKeyboard.get_close_keyboard
get_search_cancel_keyboard = UserKeyboard.get_search_cancel_keyboard
