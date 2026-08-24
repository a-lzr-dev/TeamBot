"""
Модуль клавиатур для авторизации пользователей.

Назначение:
    Предоставляет набор клавиатур для процесса авторизации пользователей
    в Telegram боте: запрос контакта, уведомление о необходимости
    авторизации и выход из системы.

Основные разделы:
    1.  Запрос контакта (ReplyKeyboardMarkup):
        - get_auth_request_keyboard: кнопка "Поделиться контактом"
        - Кнопка "Отмена" для отказа от авторизации
        - Использует request_contact для получения номера телефона

    2.  Уведомление о необходимости авторизации (InlineKeyboardMarkup):
        - get_auth_needed_keyboard: кнопка "Авторизоваться"
        - Перенаправляет на процесс авторизации через /start

    3.  Выход из системы (InlineKeyboardMarkup):
        - get_logout_keyboard: кнопка "Выйти"
        - Очищает сессию пользователя

Технические особенности:
    - Использование BaseKeyboard для унифицированного создания
    - ReplyKeyboardMarkup для кнопок с запросом контакта
    - InlineKeyboardMarkup для интерактивных кнопок
    - Единые префиксы callback_data: auth_*, logout
    - Удобные алиасы для быстрого доступа

Архитектура:
    - Интеграция с BaseKeyboard для базовых операций
    - Статические методы для создания клавиатур
    - Используется в обработчиках auth.py
"""

from aiogram.types import InlineKeyboardMarkup, ReplyKeyboardMarkup

from .base import BaseKeyboard


class AuthKeyboard:
    """Клавиатуры для авторизации."""

    @staticmethod
    def get_auth_request_keyboard() -> ReplyKeyboardMarkup:
        """Клавиатура для запроса контакта."""
        return BaseKeyboard.get_reply_keyboard(
            [{"text": "📱 Поделиться контактом", "request_contact": True}, {"text": "❌ Отмена"}]
        )

    @staticmethod
    def get_auth_needed_keyboard() -> InlineKeyboardMarkup:
        """Клавиатура для сообщения 'Требуется авторизация'."""
        return BaseKeyboard.get_inline_keyboard([{"text": "🔐 Авторизоваться", "callback_data": "auth_needed"}])

    @staticmethod
    def get_logout_keyboard() -> InlineKeyboardMarkup:
        """Клавиатура с кнопкой выхода."""
        return BaseKeyboard.get_inline_keyboard([{"text": "🚪 Выйти", "callback_data": "logout"}])


get_auth_request_keyboard = AuthKeyboard.get_auth_request_keyboard
get_auth_needed_keyboard = AuthKeyboard.get_auth_needed_keyboard
get_logout_keyboard = AuthKeyboard.get_logout_keyboard
