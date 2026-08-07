from typing import Any

from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

from ...config import settings

BUTTONS_PER_ROW_GROUPS = getattr(settings, "KEYBOARD_BUTTONS_PER_ROW", 3)


class GroupKeyboard:
    """Клавиатуры для групп действий"""

    @staticmethod
    def get_groups_keyboard(groups: list[dict[str, Any]], is_root_menu: bool = False) -> InlineKeyboardMarkup:
        """Создание клавиатуры со списком групп"""
        keyboard = []
        row = []

        for group in groups:
            name = group.get("name", "Без названия")
            if len(name) > 20:
                name = name[:18] + "…"

            button = InlineKeyboardButton(text=f"📂 {name}", callback_data=f"group_{group.get('id')}")
            row.append(button)

            if len(row) >= BUTTONS_PER_ROW_GROUPS:
                keyboard.append(row)
                row = []

        if row:
            keyboard.append(row)

        if not is_root_menu:
            keyboard.append([InlineKeyboardButton(text="🏠 В главное меню", callback_data="action_home")])

        return InlineKeyboardMarkup(inline_keyboard=keyboard)


get_groups_keyboard = GroupKeyboard.get_groups_keyboard
