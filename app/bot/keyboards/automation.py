"""
Модуль клавиатур для автоматизации.

Назначение:
    Предоставляет набор клавиатур для функций автоматизации в Telegram боте:
    конвертация документов, создание заявок, просмотр и управление заявками.

Основные разделы:
    1.  Главное меню автоматизации:
        - get_main_menu_keyboard: навигация по функциям автоматизации
        - Кнопки: конвертация, заявка, мои заявки, назад

    2.  Выбор приоритета заявки:
        - get_priority_keyboard: четыре уровня приоритета + отмена
        - Цветовая индикация: 🟢 Низкий, 🟡 Средний, 🟠 Высокий, 🔴 Критический

    3.  Подтверждение действий:
        - get_convert_confirm_keyboard: подтверждение конвертации
        - get_request_confirm_keyboard: подтверждение создания заявки с редактированием

    4.  Навигация:
        - get_back_keyboard: возврат в меню автоматизации

Технические особенности:
    - Использование BaseKeyboard для унифицированного создания
    - Настраиваемое количество кнопок в ряду (row_width)
    - Единые префиксы callback_data: automation_*
    - Цветовая индикация приоритетов для визуального восприятия
    - Поддержка редактирования заявки перед отправкой

Архитектура:
    - Интеграция с BaseKeyboard для базовых операций
    - Статические методы для создания клавиатур
    - Удобные алиасы для быстрого доступа
    - Используется в обработчиках automation.py
"""

from aiogram.types import InlineKeyboardMarkup

from .base import BaseKeyboard


class AutomationKeyboard:
    """Клавиатуры для автоматизации."""

    @staticmethod
    def get_main_menu_keyboard() -> InlineKeyboardMarkup:
        """Главное меню автоматизации."""
        return BaseKeyboard.get_inline_keyboard(
            [
                {"text": "📄 Преобразовать DOC в PDF", "callback_data": "automation_convert"},
                {"text": "📝 Оставить заявку", "callback_data": "automation_request"},
                {"text": "📋 Мои заявки", "callback_data": "automation_my_requests"},
                {"text": "🔙 Назад", "callback_data": "automation_back"},
            ],
            row_width=1,
        )

    @staticmethod
    def get_priority_keyboard() -> InlineKeyboardMarkup:
        """Клавиатура выбора приоритета."""
        return BaseKeyboard.get_inline_keyboard(
            [
                {"text": "🟢 Низкий", "callback_data": "automation_priority_low"},
                {"text": "🟡 Средний", "callback_data": "automation_priority_medium"},
                {"text": "🟠 Высокий", "callback_data": "automation_priority_high"},
                {"text": "🔴 Критический", "callback_data": "automation_priority_critical"},
                {"text": "❌ Отмена", "callback_data": "automation_cancel"},
            ],
            row_width=2,
        )

    @staticmethod
    def get_convert_confirm_keyboard() -> InlineKeyboardMarkup:
        """Клавиатура подтверждения конвертации."""
        return BaseKeyboard.get_inline_keyboard(
            [
                {"text": "✅ Да, конвертировать", "callback_data": "automation_convert_confirm"},
                {"text": "❌ Отмена", "callback_data": "automation_cancel"},
            ]
        )

    @staticmethod
    def get_request_confirm_keyboard() -> InlineKeyboardMarkup:
        """Клавиатура подтверждения заявки."""
        return BaseKeyboard.get_inline_keyboard(
            [
                {"text": "✅ Отправить заявку", "callback_data": "automation_request_confirm"},
                {"text": "✏️ Редактировать", "callback_data": "automation_request_edit"},
                {"text": "❌ Отмена", "callback_data": "automation_cancel"},
            ]
        )

    @staticmethod
    async def get_back_keyboard() -> InlineKeyboardMarkup:
        """Клавиатура возврата."""
        return BaseKeyboard.get_inline_keyboard(
            [{"text": "🔙 В меню автоматизации", "callback_data": "automation_menu"}]
        )


get_automation_menu_keyboard = AutomationKeyboard.get_main_menu_keyboard
get_priority_keyboard = AutomationKeyboard.get_priority_keyboard
get_convert_confirm_keyboard = AutomationKeyboard.get_convert_confirm_keyboard
get_request_confirm_keyboard = AutomationKeyboard.get_request_confirm_keyboard
