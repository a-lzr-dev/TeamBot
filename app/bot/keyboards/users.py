from typing import Any

from aiogram.types import InlineKeyboardMarkup

from ...config import settings
from .generic import ListKeyboardBuilder

BUTTONS_PER_ROW_USERS = getattr(settings, "KEYBOARD_BUTTONS_PER_ROW", 2)


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
            max_name_length=20,
        )

        return builder.build(
            items=users,
            current_page=current_page,
            total_pages=total_pages,
            search_query=search_query,
            extra_buttons=None,  # Кнопка закрытия добавляется автоматически
            item_name_formatter=lambda item: _format_user_item(item),
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


def _format_user_item(item: dict[str, Any]) -> str:
    """Форматирование элемента пользователя"""
    name = item.get("name", f"User #{item.get('id', '?')}")
    is_authorized = item.get("is_authorized", False)
    prefix = "✅ " if is_authorized else "⬜ "
    return f"{prefix}{name}"


get_users_keyboard = UserKeyboard.get_users_keyboard
get_close_keyboard = UserKeyboard.get_close_keyboard
get_search_cancel_keyboard = UserKeyboard.get_search_cancel_keyboard
