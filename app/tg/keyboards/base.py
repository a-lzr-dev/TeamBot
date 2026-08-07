from typing import Any

from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup, KeyboardButton, ReplyKeyboardMarkup

from ...logger import tg_logger


class BaseKeyboard:
    """Базовый класс для клавиатур"""

    @staticmethod
    def get_inline_keyboard(buttons: list[dict[str, str]], row_width: int = 3) -> InlineKeyboardMarkup:
        """
        Создание инлайн-клавиатуры из списка кнопок.

        Args:
            buttons: Список словарей с ключами 'text' и 'callback_data'
            row_width: Количество кнопок в ряду

        Returns:
            InlineKeyboardMarkup
        """
        if not buttons:
            return InlineKeyboardMarkup(inline_keyboard=[])

        keyboard = []
        row = []

        for btn in buttons:
            if "text" not in btn or "callback_data" not in btn:
                tg_logger.warning(f"⚠️ Skipping button without text or callback_data: {btn}")
                continue

            row.append(InlineKeyboardButton(text=btn["text"], callback_data=btn["callback_data"]))

            if len(row) >= row_width:
                keyboard.append(row)
                row = []

        if row:
            keyboard.append(row)

        return InlineKeyboardMarkup(inline_keyboard=keyboard)

    @staticmethod
    def get_reply_keyboard(
        buttons: list[str | dict[str, Any]],
        resize_keyboard: bool = True,
        one_time_keyboard: bool = True,
        row_width: int = 2,
    ) -> ReplyKeyboardMarkup:
        """
        Создание reply-клавиатуры.

        Args:
            buttons: Список строк или словарей с ключами 'text' и 'request_contact'
            resize_keyboard: Автоматически изменять размер
            one_time_keyboard: Скрыть после использования
            row_width: Количество кнопок в ряду

        Returns:
            ReplyKeyboardMarkup
        """
        keyboard = []
        row = []

        for btn in buttons:
            if isinstance(btn, str):
                row.append(KeyboardButton(text=btn))
            elif isinstance(btn, dict):
                text = btn.get("text", "")
                request_contact = btn.get("request_contact", False)
                row.append(KeyboardButton(text=text, request_contact=request_contact))

            if len(row) >= row_width:
                keyboard.append(row)
                row = []

        if row:
            keyboard.append(row)

        return ReplyKeyboardMarkup(
            keyboard=keyboard, resize_keyboard=resize_keyboard, one_time_keyboard=one_time_keyboard
        )

    @staticmethod
    def get_back_button(text: str = "🔙 Назад", callback_data: str = "back") -> InlineKeyboardMarkup:
        """Создание клавиатуры с одной кнопкой 'Назад'"""
        return BaseKeyboard.get_inline_keyboard([{"text": text, "callback_data": callback_data}])

    @staticmethod
    def get_home_button(text: str = "🏠 В главное меню", callback_data: str = "home") -> InlineKeyboardMarkup:
        """Создание клавиатуры с одной кнопкой 'В главное меню'"""
        return BaseKeyboard.get_inline_keyboard([{"text": text, "callback_data": callback_data}])

    @staticmethod
    def get_navigation_buttons(
        back_callback: str | None = None,
        home_callback: str = "action_home",
        extra_buttons: list[dict[str, str]] | None = None,
    ) -> InlineKeyboardMarkup:
        """Создание навигационной клавиатуры"""
        buttons = []

        if back_callback:
            buttons.append({"text": "🔙 Назад", "callback_data": back_callback})

        buttons.append({"text": "🏠 В главное меню", "callback_data": home_callback})

        if extra_buttons:
            buttons.extend(extra_buttons)

        return BaseKeyboard.get_inline_keyboard(buttons, row_width=len(buttons))

    @staticmethod
    def get_cancel_button(text: str = "❌ Отмена", callback_data: str = "cancel") -> InlineKeyboardMarkup:
        """Создание клавиатуры с кнопкой 'Отмена'"""
        return BaseKeyboard.get_inline_keyboard([{"text": text, "callback_data": callback_data}])


# Удобные алиасы
def get_inline_keyboard(buttons: list[dict[str, str]], row_width: int = 3) -> InlineKeyboardMarkup:
    return BaseKeyboard.get_inline_keyboard(buttons, row_width)


def get_reply_keyboard(buttons: list[str | dict[str, str]], **kwargs: Any) -> ReplyKeyboardMarkup:
    return BaseKeyboard.get_reply_keyboard(buttons, **kwargs)
