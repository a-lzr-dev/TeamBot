from datetime import datetime
from typing import Any

from ..models import ChatMemberStatus, ChatType

# ==================== CHAT TYPE CONVERTERS ====================


def chat_type_from_aiogram(aiogram_chat: Any | None) -> ChatType:
    """Преобразование объекта чата из Aiogram в ChatType"""
    if aiogram_chat is None:
        return ChatType.PRIVATE

    # Получение типа чата
    chat_type = getattr(aiogram_chat, "type", None)
    if chat_type is None:
        return ChatType.PRIVATE

    # Если строка
    if isinstance(chat_type, str):
        return chat_type_from_string(chat_type)

    # Если это enum или имеет value
    if hasattr(chat_type, "value"):
        chat_type = chat_type.value

    # Через метод класса
    result = ChatType.from_aiogram(chat_type)
    return result or ChatType.PRIVATE


def chat_type_from_string(value: str) -> ChatType:
    """Преобразование строкового представления в ChatType"""
    if not value:
        return ChatType.PRIVATE

    # Нормализация
    normalized = value.lower().strip()

    # Прямое преобразование
    if normalized in ChatType._value2member_map_:
        return ChatType(normalized)

    # Через метод класса
    result = ChatType.from_string(normalized)
    return result or ChatType.PRIVATE


def chat_type_from_telethon(entity: Any | None) -> ChatType:
    """Преобразование объекта чата из Telethon в ChatType"""
    if entity is None:
        return ChatType.PRIVATE

    try:
        # Проверка атрибутов в порядке приоритета
        if hasattr(entity, "megagroup") and entity.megagroup:
            return ChatType.SUPERGROUP
        if hasattr(entity, "channel") and entity.channel:
            return ChatType.CHANNEL
        if hasattr(entity, "group") and entity.group:
            return ChatType.GROUP
        if hasattr(entity, "is_user") and entity.is_user:
            return ChatType.PRIVATE
    except Exception:
        pass

    return ChatType.PRIVATE


def chat_type_from_dialog(dialog: Any | None) -> ChatType:
    """Преобразование объекта диалога из Telethon в ChatType"""
    if dialog is None:
        return ChatType.PRIVATE

    try:
        # Если есть entity, используем его
        if hasattr(dialog, "entity") and dialog.entity is not None:
            return chat_type_from_telethon(dialog.entity)

        # Fallback на основе свойств диалога
        if hasattr(dialog, "is_group") and dialog.is_group:
            return ChatType.GROUP
        if hasattr(dialog, "is_channel") and dialog.is_channel:
            return ChatType.CHANNEL
        if hasattr(dialog, "is_user") and dialog.is_user:
            return ChatType.PRIVATE
    except Exception:
        pass

    return ChatType.PRIVATE


def chat_type_to_str(chat_type: ChatType) -> str:
    """Обратное преобразование: ChatType -> строка"""
    if chat_type is None:
        return "private"
    return chat_type.value if hasattr(chat_type, "value") else str(chat_type)


# ==================== CHAT MEMBER STATUS CONVERTERS ====================


def member_status_from_aiogram(aiogram_status: Any | None) -> ChatMemberStatus:
    """Преобразование статуса участника из Aiogram в ChatMemberStatus"""
    if aiogram_status is None:
        return ChatMemberStatus.MEMBER

    # Если это строка
    if isinstance(aiogram_status, str):
        return member_status_from_string(aiogram_status)

    # Если это enum
    if hasattr(aiogram_status, "value"):
        aiogram_status = aiogram_status.value

    result = ChatMemberStatus.from_aiogram(aiogram_status)
    return result or ChatMemberStatus.MEMBER


def member_status_from_string(status_str: str) -> ChatMemberStatus:
    """Преобразование строкового представления статуса в ChatMemberStatus"""
    if not status_str:
        return ChatMemberStatus.MEMBER

    normalized = status_str.lower().strip()

    # Прямое преобразование
    if normalized in ChatMemberStatus._value2member_map_:
        return ChatMemberStatus(normalized)

    # Через метод класса
    result = ChatMemberStatus.from_string(normalized)
    return result or ChatMemberStatus.MEMBER


def member_status_from_telethon(participant: Any | None) -> ChatMemberStatus:
    """Преобразование участника из Telethon в ChatMemberStatus"""
    if participant is None:
        return ChatMemberStatus.MEMBER

    try:
        if hasattr(participant, "is_creator") and participant.is_creator:
            return ChatMemberStatus.CREATOR
        if hasattr(participant, "is_admin") and participant.is_admin:
            return ChatMemberStatus.ADMINISTRATOR
        if hasattr(participant, "is_member") and not participant.is_member:
            return ChatMemberStatus.LEFT
    except Exception:
        pass

    return ChatMemberStatus.MEMBER


def member_status_to_str(status: ChatMemberStatus) -> str:
    """Обратное преобразование: ChatMemberStatus -> строка"""
    if status is None:
        return "member"
    return status.value if hasattr(status, "value") else str(status)


# ==================== USER INFO EXTRACTORS ====================


def user_info_from_aiogram(aiogram_user: Any | None) -> dict[str, Any]:
    """Извлечение информации о пользователе из объекта Aiogram"""
    if aiogram_user is None:
        return {
            "user_id": 0,
            "username": None,
            "first_name": "",
            "last_name": None,
            "is_bot": False,
        }

    return {
        "user_id": getattr(aiogram_user, "id", 0),
        "username": getattr(aiogram_user, "username", None),
        "first_name": getattr(aiogram_user, "first_name", "") or "",
        "last_name": getattr(aiogram_user, "last_name", None),
        "is_bot": getattr(aiogram_user, "is_bot", False),
    }


def user_info_from_telethon(telethon_user: Any | None) -> dict[str, Any]:
    """Извлечение информации о пользователе из объекта Telethon"""
    if telethon_user is None:
        return {
            "user_id": 0,
            "username": None,
            "first_name": "",
            "last_name": None,
            "is_bot": False,
            "phone": None,
        }

    try:
        return {
            "user_id": getattr(telethon_user, "id", 0),
            "username": getattr(telethon_user, "username", None),
            "first_name": getattr(telethon_user, "first_name", "") or "",
            "last_name": getattr(telethon_user, "last_name", None),
            "is_bot": getattr(telethon_user, "bot", False),
            "phone": getattr(telethon_user, "phone", None),
        }
    except Exception:
        return {
            "user_id": getattr(telethon_user, "id", 0),
            "username": None,
            "first_name": "",
            "last_name": None,
            "is_bot": False,
            "phone": None,
        }


# ==================== MESSAGE INFO EXTRACTORS ====================


def safe_datetime_convert(dt: Any | None) -> datetime | None:
    """Безопасное преобразование даты с удалением timezone"""
    if dt is None:
        return None

    try:
        if hasattr(dt, "replace"):
            return dt.replace(tzinfo=None)  # type: ignore[no-any-return]
        return dt  # type: ignore[no-any-return]
    except Exception:
        return None


def get_message_text(message: Any | None) -> str | None:
    """Получение текста сообщения из Aiogram Message"""
    if message is None:
        return None

    # Проверяем наличие текста
    text = getattr(message, "text", None)
    if text:
        return text  # type: ignore[no-any-return]

    caption = getattr(message, "caption", None)
    if caption:
        return caption  # type: ignore[no-any-return]

    # Для poll
    poll = getattr(message, "poll", None)
    if poll:
        return getattr(poll, "question", None)

    return None


def get_content_type(message: Any | None) -> str:
    """Получение типа содержимого сообщения из Aiogram Message"""
    if message is None:
        return "text"

    # Получаем content_type
    content_type = getattr(message, "content_type", None)
    if content_type is None:
        return "text"

    # Если это строка
    if isinstance(content_type, str):
        return content_type

    # Если это enum
    if hasattr(content_type, "value"):
        return content_type.value  # type: ignore[no-any-return]

    return "text"


def get_media_info(message: Any | None) -> dict[str, Any]:
    """Получение информации о медиа-файле из Aiogram Message"""
    if message is None:
        return {}

    media_info = {}

    # Photo
    photo = getattr(message, "photo", None)
    if photo:
        # Берем последний (самый большой) фото
        if isinstance(photo, list) and photo:
            photo = photo[-1]
        media_info.update(
            {
                "file_id": getattr(photo, "file_id", None),
                "file_unique_id": getattr(photo, "file_unique_id", None),
                "file_size": getattr(photo, "file_size", None),
            }
        )
        return media_info

    # Document
    doc = getattr(message, "document", None)
    if doc:
        media_info.update(
            {
                "file_id": getattr(doc, "file_id", None),
                "file_unique_id": getattr(doc, "file_unique_id", None),
                "file_size": getattr(doc, "file_size", None),
                "mime_type": getattr(doc, "mime_type", None),
            }
        )
        return media_info

    # Video
    video = getattr(message, "video", None)
    if video:
        media_info.update(
            {
                "file_id": getattr(video, "file_id", None),
                "file_unique_id": getattr(video, "file_unique_id", None),
                "file_size": getattr(video, "file_size", None),
                "mime_type": getattr(video, "mime_type", None),
                "duration": getattr(video, "duration", None),
                "width": getattr(video, "width", None),
                "height": getattr(video, "height", None),
            }
        )
        return media_info

    # Audio
    audio = getattr(message, "audio", None)
    if audio:
        media_info.update(
            {
                "file_id": getattr(audio, "file_id", None),
                "file_unique_id": getattr(audio, "file_unique_id", None),
                "file_size": getattr(audio, "file_size", None),
                "mime_type": getattr(audio, "mime_type", None),
                "duration": getattr(audio, "duration", None),
            }
        )
        return media_info

    # Voice
    voice = getattr(message, "voice", None)
    if voice:
        media_info.update(
            {
                "file_id": getattr(voice, "file_id", None),
                "file_unique_id": getattr(voice, "file_unique_id", None),
                "file_size": getattr(voice, "file_size", None),
                "duration": getattr(voice, "duration", None),
            }
        )
        return media_info

    # Sticker
    sticker = getattr(message, "sticker", None)
    if sticker:
        media_info.update(
            {
                "file_id": getattr(sticker, "file_id", None),
                "file_unique_id": getattr(sticker, "file_unique_id", None),
                "file_size": getattr(sticker, "file_size", None),
                "width": getattr(sticker, "width", None),
                "height": getattr(sticker, "height", None),
            }
        )
        return media_info

    return media_info


# ==================== COMMAND EXTRACTORS ====================


def extract_command(message: Any | None) -> str | None:
    """Извлечение команды из сообщения"""
    if message is None:
        return None

    text = get_message_text(message)
    if not text or not text.startswith("/"):
        return None

    parts = text.split()
    if parts:
        return parts[0]
    return None


def extract_command_args(message: Any | None) -> str | None:
    """Извлечение аргументов команды"""
    if message is None:
        return None

    text = get_message_text(message)
    if not text or not text.startswith("/"):
        return None

    parts = text.split()
    if len(parts) > 1:
        return " ".join(parts[1:])
    return None


# ==================== VALIDATION HELPERS ====================


def validate_chat_id(chat_id: int | None) -> bool:
    """Валидация ID чата"""
    if chat_id is None:
        return False
    # ID чата может быть отрицательным (супергруппы)
    return abs(chat_id) > 0


def validate_user_id(user_id: int | None) -> bool:
    """Валидация ID пользователя"""
    if user_id is None:
        return False
    return user_id > 0


def validate_message_id(message_id: int | None) -> bool:
    """Валидация ID сообщения"""
    if message_id is None:
        return False
    return message_id > 0


__all__ = [
    # Chat Type
    "chat_type_from_aiogram",
    "chat_type_from_string",
    "chat_type_from_telethon",
    "chat_type_from_dialog",
    "chat_type_to_str",
    # Chat Member Status
    "member_status_from_aiogram",
    "member_status_from_string",
    "member_status_from_telethon",
    "member_status_to_str",
    # User
    "user_info_from_aiogram",
    "user_info_from_telethon",
    # Message
    "safe_datetime_convert",
    "get_message_text",
    "get_content_type",
    "get_media_info",
    # Command
    "extract_command",
    "extract_command_args",
    # Validation
    "validate_chat_id",
    "validate_user_id",
    "validate_message_id",
]
