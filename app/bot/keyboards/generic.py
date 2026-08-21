"""
Универсальные клавиатуры для типовых операций:
- Списки с пагинацией
- Подтверждение действий
- Навигация
- Поиск
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

# Импорты для type checking
if TYPE_CHECKING:
    from collections.abc import Callable

# Runtime imports
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

from ...config import settings

# ============================================================
# БАЗОВАЯ КОНФИГУРАЦИЯ
# ============================================================

DEFAULT_BUTTONS_PER_ROW = getattr(settings, "KEYBOARD_BUTTONS_PER_ROW", 3)


# ============================================================
# КЛАСС-СТРОИТЕЛЬ КЛАВИАТУР СПИСКОВ
# ============================================================


class ListKeyboardBuilder:
    """Строитель клавиатур для списков"""

    def __init__(
        self,
        callback_prefix: str,
        buttons_per_row: int = DEFAULT_BUTTONS_PER_ROW,
        item_icon: str = "📌",
        max_name_length: int = 20,
    ):
        # Убеждаемся, что префикс заканчивается на "_"
        self.callback_prefix = callback_prefix if callback_prefix.endswith("_") else f"{callback_prefix}_"
        self.buttons_per_row = buttons_per_row
        self.item_icon = item_icon
        self.max_name_length = max_name_length

    def build(
        self,
        items: list[dict[str, Any]],
        current_page: int = 0,
        total_pages: int = 1,
        search_query: str | None = None,
        extra_buttons: list[tuple[str, str]] | None = None,
        item_name_formatter: Callable[[dict[str, Any]], str] | None = None,
    ) -> InlineKeyboardMarkup:
        """Построение клавиатуры"""
        from app.logger import bot_logger

        bot_logger.debug(f"🔍 [ListKeyboardBuilder] Building keyboard with {len(items)} items")
        bot_logger.debug(f"🔍 [ListKeyboardBuilder] extra_buttons: {extra_buttons}")

        keyboard = []

        # Кнопки элементов
        row = []
        for item in items:
            if item_name_formatter:
                name = item_name_formatter(item)
            else:
                name = item.get("name", f"Item #{item.get('id', '?')}")

            # Обрезание длинного имени
            if len(name) > self.max_name_length:
                name = name[: self.max_name_length - 1] + "…"

            button = InlineKeyboardButton(
                text=f"{self.item_icon} {name}",
                callback_data=f"{self.callback_prefix}select_{item.get('id')}",
            )
            row.append(button)

            if len(row) >= self.buttons_per_row:
                keyboard.append(row)
                row = []

        if row:
            keyboard.append(row)

        # Строка навигации - показываем только если есть пагинация или поиск
        if total_pages > 1 or search_query:
            nav_row = []

            if current_page > 0:
                if search_query:
                    nav_row.append(
                        InlineKeyboardButton(
                            text="⬅️ Назад",
                            callback_data=f"{self.callback_prefix}page_{current_page - 1}_search_{search_query}",
                        )
                    )
                else:
                    nav_row.append(
                        InlineKeyboardButton(
                            text="⬅️ Назад", callback_data=f"{self.callback_prefix}page_{current_page - 1}"
                        )
                    )

            page_text = f"🔍 {current_page + 1}/{total_pages}"
            nav_row.append(
                InlineKeyboardButton(text=f"{page_text} Поиск...", callback_data=f"{self.callback_prefix}search")
            )

            if current_page < total_pages - 1:
                if search_query:
                    nav_row.append(
                        InlineKeyboardButton(
                            text="Вперед ➡️",
                            callback_data=f"{self.callback_prefix}page_{current_page + 1}_search_{search_query}",
                        )
                    )
                else:
                    nav_row.append(
                        InlineKeyboardButton(
                            text="Вперед ➡️", callback_data=f"{self.callback_prefix}page_{current_page + 1}"
                        )
                    )

            keyboard.append(nav_row)

        # Дополнительные кнопки + закрытие
        bottom_row = []

        if extra_buttons:
            for text, callback_data in extra_buttons:
                bottom_row.append(InlineKeyboardButton(text=text, callback_data=callback_data))

        bottom_row.append(InlineKeyboardButton(text="❌ Закрыть", callback_data=f"{self.callback_prefix}close"))
        keyboard.append(bottom_row)

        return InlineKeyboardMarkup(inline_keyboard=keyboard)

    def build_with_back(
        self,
        items: list[dict[str, Any]],
        current_page: int = 0,
        total_pages: int = 1,
        search_query: str | None = None,
        back_callback: str | None = None,
        back_text: str = "🔙 Назад к действиям",
    ) -> InlineKeyboardMarkup:
        """Построение клавиатуры с кнопкой 'Назад'"""
        extra_buttons = []
        if back_callback:
            extra_buttons.append((back_text, back_callback))
        return self.build(items, current_page, total_pages, search_query, extra_buttons)


# ============================================================
# КЛАВИАТУРЫ ДЛЯ ПОДТВЕРЖДЕНИЯ
# ============================================================


def get_confirm_keyboard(
    confirm_text: str = "✅ Да",
    confirm_callback: str = "confirm",
    cancel_text: str = "❌ Отмена",
    cancel_callback: str = "cancel",
    prefix: str = "",
) -> InlineKeyboardMarkup:
    """Клавиатура для подтверждения действия"""
    from .base import BaseKeyboard

    # Убеждаемся, что префикс заканчивается на "_"
    prefix_with_underscore = prefix if prefix.endswith("_") else f"{prefix}_" if prefix else ""

    return BaseKeyboard.get_inline_keyboard(
        [
            {"text": confirm_text, "callback_data": f"{prefix_with_underscore}{confirm_callback}"},
            {"text": cancel_text, "callback_data": f"{prefix_with_underscore}{cancel_callback}"},
        ]
    )


# ============================================================
# КЛАВИАТУРЫ ДЛЯ НАВИГАЦИИ
# ============================================================


def get_back_keyboard(
    back_text: str = "🔙 Назад",
    back_callback: str = "back",
    prefix: str = "",
) -> InlineKeyboardMarkup:
    """Клавиатура с кнопкой 'Назад'"""
    from .base import BaseKeyboard

    prefix_with_underscore = prefix if prefix.endswith("_") else f"{prefix}_" if prefix else ""

    return BaseKeyboard.get_inline_keyboard(
        [{"text": back_text, "callback_data": f"{prefix_with_underscore}{back_callback}"}]
    )


def get_navigation_keyboard(
    back_callback: str | None = None,
    home_callback: str | None = None,
    home_text: str = "🏠 В главное меню",
    extra_buttons: list[tuple[str, str]] | None = None,
) -> InlineKeyboardMarkup:
    """Клавиатура с навигационными кнопками"""
    from .base import BaseKeyboard

    buttons = []

    if back_callback:
        buttons.append({"text": "🔙 Назад", "callback_data": back_callback})

    if home_callback:
        buttons.append({"text": home_text, "callback_data": home_callback})

    if extra_buttons:
        for text, callback_data in extra_buttons:
            buttons.append({"text": text, "callback_data": callback_data})

    return BaseKeyboard.get_inline_keyboard(buttons, row_width=len(buttons))


# ============================================================
# КЛАВИАТУРЫ ДЛЯ ПОИСКА
# ============================================================


def get_search_keyboard(
    cancel_text: str = "❌ Отменить поиск",
    cancel_callback: str = "cancel_search",
    prefix: str = "",
) -> InlineKeyboardMarkup:
    """Клавиатура для отмены поиска"""
    from .base import BaseKeyboard

    prefix_with_underscore = prefix if prefix.endswith("_") else f"{prefix}_" if prefix else ""

    return BaseKeyboard.get_inline_keyboard(
        [{"text": cancel_text, "callback_data": f"{prefix_with_underscore}{cancel_callback}"}]
    )


def get_search_cancel_keyboard() -> InlineKeyboardMarkup:
    """
    Клавиатура для отмены поиска (универсальная, без префикса).
    Используется как отдельная кнопка для отмены поиска в сообщениях.
    """
    return InlineKeyboardMarkup(
        inline_keyboard=[[InlineKeyboardButton(text="❌ Отменить поиск", callback_data="cancel_search")]]
    )


# ============================================================
# КЛАВИАТУРЫ ДЛЯ ПРИОРИТЕТОВ
# ============================================================


def get_priority_keyboard(
    callback_prefix: str = "priority",
    cancel_callback: str = "cancel",
    buttons_per_row: int = 2,
) -> InlineKeyboardMarkup:
    """Клавиатура для выбора приоритета"""
    from .base import BaseKeyboard

    # Убеждаемся, что префикс заканчивается на "_"
    prefix_with_underscore = callback_prefix if callback_prefix.endswith("_") else f"{callback_prefix}_"

    priorities = [
        ("🟢 Низкий", "low"),
        ("🟡 Средний", "medium"),
        ("🟠 Высокий", "high"),
        ("🔴 Критический", "critical"),
    ]

    buttons = [{"text": text, "callback_data": f"{prefix_with_underscore}{value}"} for text, value in priorities]
    buttons.append({"text": "❌ Отмена", "callback_data": f"{prefix_with_underscore}{cancel_callback}"})

    return BaseKeyboard.get_inline_keyboard(buttons, row_width=buttons_per_row)


# ============================================================
# УПРОЩЕННЫЕ АЛИАСЫ
# ============================================================


def get_back_to_menu_keyboard(parent_item_id: int | None = None) -> InlineKeyboardMarkup:
    """Клавиатура с кнопкой возврата в меню действий"""
    from .base import BaseKeyboard

    buttons = []
    if parent_item_id:
        buttons.append({"text": "🔙 Назад к действиям", "callback_data": f"action_back_{parent_item_id}"})
    buttons.append({"text": "❌ Закрыть", "callback_data": "close"})
    return BaseKeyboard.get_inline_keyboard(buttons, row_width=1)


__all__ = [
    # Основной класс-строитель
    "ListKeyboardBuilder",
    # Остальные клавиатуры
    "get_confirm_keyboard",
    "get_back_keyboard",
    "get_navigation_keyboard",
    "get_search_keyboard",
    "get_search_cancel_keyboard",
    "get_priority_keyboard",
    "get_back_to_menu_keyboard",
    # Константы
    "DEFAULT_BUTTONS_PER_ROW",
]
