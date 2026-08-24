"""
Модуль административных клавиатур.

Назначение:
    Предоставляет набор клавиатур для административных функций
    в Telegram боте: подтверждение массовой рассылки и подтверждение удаления.

Основные разделы:
    1.  Подтверждение массовой рассылки:
        - get_broadcast_confirm_keyboard: две кнопки (отправить/отмена)
        - Используется для финального подтверждения перед отправкой

    2.  Подтверждение удаления:
        - get_delete_confirm_keyboard: две кнопки (удалить/отмена)
        - Защита от случайного удаления важных данных

Технические особенности:
    - Использование BaseKeyboard для унифицированного создания
    - Две кнопки в одном ряду для быстрого выбора
    - Единые префиксы callback_data: broadcast_*, delete_*
    - Удобные алиасы для быстрого доступа

Архитектура:
    - Интеграция с BaseKeyboard для базовых операций
    - Статические методы для создания клавиатур
    - Используется в обработчиках admin.py и broadcast.py
"""

from aiogram.types import InlineKeyboardMarkup

from .base import BaseKeyboard


class AdminKeyboard:
    """Клавиатуры для администраторов."""

    @staticmethod
    def get_broadcast_confirm_keyboard() -> InlineKeyboardMarkup:
        """Клавиатура для подтверждения рассылки."""
        return BaseKeyboard.get_inline_keyboard(
            [
                {"text": "✅ Да, отправить", "callback_data": "broadcast_confirm"},
                {"text": "❌ Отмена", "callback_data": "broadcast_cancel"},
            ]
        )

    @staticmethod
    def get_delete_confirm_keyboard() -> InlineKeyboardMarkup:
        """Клавиатура для подтверждения удаления."""
        return BaseKeyboard.get_inline_keyboard(
            [
                {"text": "✅ Да, удалить", "callback_data": "delete_confirm"},
                {"text": "❌ Отмена", "callback_data": "delete_cancel"},
            ]
        )


get_broadcast_confirm_keyboard = AdminKeyboard.get_broadcast_confirm_keyboard
get_delete_confirm_keyboard = AdminKeyboard.get_delete_confirm_keyboard
