from typing import Any

from aiogram.types import InlineKeyboardMarkup

from ...config import settings
from .generic import ListKeyboardBuilder

BUTTONS_PER_ROW_ACTIONS = getattr(settings, "KEYBOARD_BUTTONS_PER_ROW", 3)


class ActionKeyboard:
    """Клавиатуры для меню действий"""

    @staticmethod
    def get_action_menu_keyboard(
        items: list[dict[str, Any]],
        parent_id: int | None = None,
        is_admin: bool = False,
        is_root_menu: bool = False,
        show_back_to_users: bool = False,
    ) -> InlineKeyboardMarkup:
        """
        Создание клавиатуры для меню действий через ListKeyboardBuilder.

        Args:
            items: Список пунктов меню с полями 'id', 'name', 'has_subitems'
            parent_id: ID родительского элемента
            is_admin: Является ли пользователь администратором
            is_root_menu: Является ли это главным меню (без кнопки "В главное меню")
            show_back_to_users: Показывать кнопку "К списку пользователей"
        """
        builder = ListKeyboardBuilder(
            callback_prefix="action",
            buttons_per_row=BUTTONS_PER_ROW_ACTIONS,
            item_icon="",  # ▶️
            max_name_length=25,
        )

        extra_buttons = []

        # Кнопка "Назад" для подменю
        if not is_root_menu and parent_id is not None:
            extra_buttons.append(("🔙 Назад", f"action_back_{parent_id or 0}"))

        # Кнопка "В главное меню" для подменю
        if not is_root_menu:
            extra_buttons.append(("🏠 В главное меню", "action_home"))

        # Кнопка "К списку пользователей" (если выбран пользователь через /users или сис.админ)
        if is_admin or show_back_to_users:
            extra_buttons.append(("👥 К пользователям", "back_to_users"))

        return builder.build(
            items=items,
            current_page=0,
            total_pages=1,
            search_query=None,
            extra_buttons=extra_buttons if extra_buttons else None,
            item_name_formatter=lambda item: _format_item_name(item),
        )


def _format_item_name(item: dict[str, Any]) -> str:
    """Форматирование названия пункта меню"""
    name = item.get("name", "Без названия")
    has_subitems = item.get("has_subitems", False)
    prefix = "▶️ " if has_subitems else "• "
    return f"{prefix}{name}"


get_action_menu_keyboard = ActionKeyboard.get_action_menu_keyboard
