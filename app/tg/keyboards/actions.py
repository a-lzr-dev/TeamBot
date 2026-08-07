from typing import Any

from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

from ...config import settings

BUTTONS_PER_ROW_ACTIONS = getattr(settings, "KEYBOARD_BUTTONS_PER_ROW", 3)


class ActionKeyboard:
    """Клавиатуры для меню действий"""

    @staticmethod
    def get_action_menu_keyboard(
        items: list[dict[str, Any]], parent_id: int | None = None, is_admin: bool = False, is_root_menu: bool = False
    ) -> InlineKeyboardMarkup:
        """
        Создание клавиатуры для меню действий.

        Args:
            items: Список пунктов меню с полями 'id', 'name', 'has_subitems'
            parent_id: ID родительского элемента
            is_admin: Является ли пользователь администратором
            is_root_menu: Является ли это главным меню (без кнопки "В главное меню")
        """
        keyboard = []

        # Основные кнопки меню
        row = []
        for item in items:
            name = item.get("name", "Без названия")
            if len(name) > 20:
                name = name[:18] + "…"

            button_text = f"{'▶️ ' if item.get('has_subitems', False) else '• '}{name}"
            button = InlineKeyboardButton(text=button_text, callback_data=f"action_{item.get('id')}")
            row.append(button)

            if len(row) >= BUTTONS_PER_ROW_ACTIONS:
                keyboard.append(row)
                row = []

        if row:
            keyboard.append(row)

        # Навигационная строка
        nav_row = []

        if not is_root_menu:  # не для корневого (ТОЛЬКО для подменю)
            # Кнопка "Назад"
            nav_row.append(InlineKeyboardButton(text="🔙 Назад", callback_data=f"action_back_{parent_id or 0}"))

            # Кнопка "В главное меню"
            nav_row.append(InlineKeyboardButton(text="🏠 В главное меню", callback_data="action_home"))

        # Кнопка "К группам"
        if is_admin:
            nav_row.append(InlineKeyboardButton(text="📋 К группам", callback_data="back_to_groups"))

        if nav_row:
            keyboard.append(nav_row)

        return InlineKeyboardMarkup(inline_keyboard=keyboard)


get_action_menu_keyboard = ActionKeyboard.get_action_menu_keyboard
