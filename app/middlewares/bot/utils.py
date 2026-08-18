from typing import Any

from aiogram.types import CallbackQuery, Message, TelegramObject, User


def get_user(event: TelegramObject) -> User | None:
    """Получение объекта пользователя из события"""
    if isinstance(event, Message | CallbackQuery) and event.from_user:
        return event.from_user
    return None


def get_user_id(event: TelegramObject) -> int | None:
    """Получение ID пользователя из события"""
    user = get_user(event)
    if user is None:
        return None
    user_id: int = user.id
    return user_id


def get_chat_id(event: TelegramObject) -> int | None:
    """Получение ID чата из события"""
    if isinstance(event, Message) and event.chat:
        chat_id = getattr(event.chat, "id", None)
        if isinstance(chat_id, int):
            return chat_id
        return None
    if isinstance(event, CallbackQuery) and event.message and event.message.chat:
        chat_id = getattr(event.message.chat, "id", None)
        if isinstance(chat_id, int):
            return chat_id
        return None
    return None


def get_message_preview(event: Any, max_length: int = 50) -> str | None:
    """Получение превью сообщения"""
    if not isinstance(event, Message):
        return None

    if event.text:
        text = str(event.text)
    elif event.caption:
        text = str(event.caption)
    else:
        return f"[{event.content_type}]"

    if len(text) > max_length:
        return text[:max_length] + "..."
    return text


__all__ = [
    "get_user",
    "get_user_id",
    "get_chat_id",
    "get_message_preview",
]
