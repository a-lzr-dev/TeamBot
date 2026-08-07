from aiogram.types import InlineKeyboardMarkup, ReplyKeyboardMarkup

from .base import BaseKeyboard


class AuthKeyboard:
    """Клавиатуры для авторизации"""

    @staticmethod
    def get_auth_request_keyboard() -> ReplyKeyboardMarkup:
        """Клавиатура для запроса контакта"""
        return BaseKeyboard.get_reply_keyboard(
            [{"text": "📱 Поделиться контактом", "request_contact": True}, {"text": "❌ Отмена"}]
        )

    @staticmethod
    def get_auth_needed_keyboard() -> InlineKeyboardMarkup:
        """Клавиатура для сообщения 'Требуется авторизация'"""
        return BaseKeyboard.get_inline_keyboard([{"text": "🔐 Авторизоваться", "callback_data": "auth_needed"}])

    @staticmethod
    def get_logout_keyboard() -> InlineKeyboardMarkup:
        """Клавиатура с кнопкой выхода"""
        return BaseKeyboard.get_inline_keyboard([{"text": "🚪 Выйти", "callback_data": "logout"}])


get_auth_request_keyboard = AuthKeyboard.get_auth_request_keyboard
get_auth_needed_keyboard = AuthKeyboard.get_auth_needed_keyboard
get_logout_keyboard = AuthKeyboard.get_logout_keyboard
