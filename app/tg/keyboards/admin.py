from aiogram.types import InlineKeyboardMarkup

from .base import BaseKeyboard


class AdminKeyboard:
    """Клавиатуры для администраторов"""

    @staticmethod
    def get_broadcast_confirm_keyboard() -> InlineKeyboardMarkup:
        """Клавиатура для подтверждения рассылки"""
        return BaseKeyboard.get_inline_keyboard(
            [
                {"text": "✅ Да, отправить", "callback_data": "broadcast_confirm"},
                {"text": "❌ Отмена", "callback_data": "broadcast_cancel"},
            ]
        )

    @staticmethod
    def get_delete_confirm_keyboard() -> InlineKeyboardMarkup:
        """Клавиатура для подтверждения удаления"""
        return BaseKeyboard.get_inline_keyboard(
            [
                {"text": "✅ Да, удалить", "callback_data": "delete_confirm"},
                {"text": "❌ Отмена", "callback_data": "delete_cancel"},
            ]
        )


get_broadcast_confirm_keyboard = AdminKeyboard.get_broadcast_confirm_keyboard
get_delete_confirm_keyboard = AdminKeyboard.get_delete_confirm_keyboard
