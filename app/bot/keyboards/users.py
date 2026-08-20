from typing import Any

from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

from ...config import settings

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
        """Создание клавиатуры со списком пользователей"""
        keyboard = []

        # Кнопки пользователей
        row = []
        for user in users:
            user_id = user.get("id")
            name = user.get("name", f"User #{user_id}")
            is_authorized = user.get("is_authorized", False)

            if len(name) > 20:
                name = name[:18] + "…"

            prefix = "✅ " if is_authorized else "⬜ "
            button_text = f"{prefix}{name}"

            button = InlineKeyboardButton(text=button_text, callback_data=f"users_{current_page}_select_{user_id}")
            row.append(button)

            if len(row) >= BUTTONS_PER_ROW_USERS:
                keyboard.append(row)
                row = []

        if row:
            keyboard.append(row)

        # Навигационная строка
        nav_row = []

        if has_prev:
            if search_query:
                nav_row.append(
                    InlineKeyboardButton(
                        text="⬅️ Назад", callback_data=f"users_{current_page - 1}_page_search_{search_query}"
                    )
                )
            else:
                nav_row.append(InlineKeyboardButton(text="⬅️ Назад", callback_data=f"users_{current_page - 1}_page"))

        if search_query:
            nav_row.append(
                InlineKeyboardButton(text=f"🔍 {current_page + 1}/{total_pages} Поиск...", callback_data="users_search")
            )
        else:
            nav_row.append(
                InlineKeyboardButton(
                    text=f"📄 {current_page + 1}/{total_pages} Поиск...",
                    callback_data="users_search",
                )
            )

        if has_next:
            if search_query:
                nav_row.append(
                    InlineKeyboardButton(
                        text="Вперед ➡️", callback_data=f"users_{current_page + 1}_page_search_{search_query}"
                    )
                )
            else:
                nav_row.append(InlineKeyboardButton(text="Вперед ➡️", callback_data=f"users_{current_page + 1}_page"))

        keyboard.append(nav_row)

        # Кнопка закрытия
        keyboard.append([InlineKeyboardButton(text="❌ Закрыть", callback_data="users_close")])

        return InlineKeyboardMarkup(inline_keyboard=keyboard)

    @staticmethod
    def get_close_keyboard() -> InlineKeyboardMarkup:
        """Клавиатура с кнопкой закрытия"""
        return InlineKeyboardMarkup(
            inline_keyboard=[[InlineKeyboardButton(text="❌ Закрыть", callback_data="users_close")]]
        )

    @staticmethod
    def get_search_cancel_keyboard() -> InlineKeyboardMarkup:
        """Клавиатура для отмены поиска (только кнопка отмены)"""
        return InlineKeyboardMarkup(
            inline_keyboard=[[InlineKeyboardButton(text="❌ Отменить поиск", callback_data="users_cancel_search")]]
        )


get_users_keyboard = UserKeyboard.get_users_keyboard
get_close_keyboard = UserKeyboard.get_close_keyboard
get_search_cancel_keyboard = UserKeyboard.get_search_cancel_keyboard
