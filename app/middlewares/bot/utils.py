"""
Утилиты для извлечения информации из событий Telegram.

Назначение:
    Предоставляет вспомогательные функции для безопасного извлечения
    данных из объектов событий Aiogram (Message, CallbackQuery и т.д.).

Основные функции:
    1. Получение объекта пользователя из события
    2. Получение ID пользователя из события
    3. Получение ID чата из события
    4. Получение превью сообщения (текста или caption)

Технические особенности:
    - Безопасное извлечение данных с проверкой наличия атрибутов
    - Поддержка Message и CallbackQuery событий
    - Обрезание длинных текстов для логирования
    - Возврат None при отсутствии данных

Архитектура:
    - Модуль с утилитами для middleware
    - Используется в LoggingMiddleware и других middleware
"""

from typing import Any

from aiogram.types import CallbackQuery, Message, TelegramObject, User

# ============================================================
# 1. ПОЛУЧЕНИЕ ПОЛЬЗОВАТЕЛЯ
# ============================================================


def get_user(event: TelegramObject) -> User | None:
    """
    Получение объекта пользователя из события.

    Поддерживает Message и CallbackQuery события.

    Args:
        event: Объект события от Telegram

    Returns:
        User | None: Объект пользователя или None
    """
    if isinstance(event, Message | CallbackQuery) and event.from_user:
        return event.from_user
    return None


# ============================================================
# 2. ПОЛУЧЕНИЕ ID ПОЛЬЗОВАТЕЛЯ
# ============================================================


def get_user_id(event: TelegramObject) -> int | None:
    """
    Получение ID пользователя из события.

    Args:
        event: Объект события от Telegram

    Returns:
        int | None: ID пользователя или None
    """
    user = get_user(event)
    if user is None:
        return None
    user_id: int = user.id
    return user_id


# ============================================================
# 3. ПОЛУЧЕНИЕ ID ЧАТА
# ============================================================


def get_chat_id(event: TelegramObject) -> int | None:
    """
    Получение ID чата из события.

    Поддерживает Message и CallbackQuery события.

    Args:
        event: Объект события от Telegram

    Returns:
        int | None: ID чата или None
    """
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


# ============================================================
# 4. ПОЛУЧЕНИЕ ПРЕВЬЮ СООБЩЕНИЯ
# ============================================================


def get_message_preview(event: Any, max_length: int = 50) -> str | None:
    """
    Получение превью сообщения для логирования.

    Извлекает текст или caption из сообщения и обрезает до указанной длины.

    Args:
        event: Объект события (должен быть Message)
        max_length: Максимальная длина превью (по умолчанию 50)

    Returns:
        str | None: Превью сообщения или None
    """
    if not isinstance(event, Message):
        return None

    # Извлечение текста
    if event.text:
        text = str(event.text)
    elif event.caption:
        text = str(event.caption)
    else:
        return f"[{event.content_type}]"

    # Обрезание длинного текста
    if len(text) > max_length:
        return text[:max_length] + "..."
    return text


__all__ = [
    "get_user",
    "get_user_id",
    "get_chat_id",
    "get_message_preview",
]
