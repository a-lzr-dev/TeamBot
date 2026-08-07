from typing import Any

from ...core.converters import (
    chat_type_from_aiogram,
    chat_type_from_dialog,
    chat_type_from_string,
    chat_type_from_telethon,
    chat_type_to_str,
    extract_command,
    extract_command_args,
    get_content_type,
    get_media_info,
    get_message_text,
    member_status_from_aiogram,
    member_status_from_string,
    member_status_from_telethon,
    member_status_to_str,
    safe_datetime_convert,
    user_info_from_aiogram,
    user_info_from_telethon,
    validate_chat_id,
    validate_message_id,
    validate_user_id,
)
from ...logger import tg_logger
from ...models import ChatMessageModel, ChatModel, ChatType, UserModel

try:
    from telethon.tl.types import (
        Channel as TelethonChannel,
    )
    from telethon.tl.types import (
        Chat as TelethonChat,
    )
    from telethon.tl.types import (
        Message as TelethonMessage,
    )
    from telethon.tl.types import (
        User as TelethonUser,
    )
except ImportError:
    TelethonUser = Any
    TelethonChat = Any
    TelethonMessage = Any
    TelethonChannel = Any

try:
    from aiogram.types import (
        Chat as AiogramChat,
    )
    from aiogram.types import (
        Message as AiogramMessage,
    )
    from aiogram.types import (
        User as AiogramUser,
    )
except ImportError:
    AiogramUser = Any
    AiogramChat = Any
    AiogramMessage = Any


# ==================== ДОПОЛНИТЕЛЬНЫЕ КОНВЕРТЕРЫ ====================


def dict_to_user_model(data: dict[str, Any]) -> UserModel:
    """Создание модели пользователя из словаря"""
    return UserModel(
        FID=data.get("user_id", 0),
        FUserName=data.get("username", ""),
        FFirstName=data.get("first_name", ""),
        FLastName=data.get("last_name"),
        FFlagBot=data.get("is_bot", False),
    )


def chat_info_from_telethon(telethon_chat: Any) -> dict[str, Any]:
    """Извлечение информации о чате из объекта Telethon"""
    if telethon_chat is None:
        return {
            "chat_id": 0,
            "title": None,
            "type": "private",
            "username": None,
            "participants_count": None,
        }

    try:
        chat_type = chat_type_from_telethon(telethon_chat)
        return {
            "chat_id": getattr(telethon_chat, "id", 0),
            "title": getattr(telethon_chat, "title", None),
            "type": chat_type_to_str(chat_type),
            "username": getattr(telethon_chat, "username", None),
            "participants_count": getattr(telethon_chat, "participants_count", None),
        }
    except Exception as e:
        tg_logger.warning(f"⚠️ Error extracting chat info from Telethon: {e}")
        return {
            "chat_id": getattr(telethon_chat, "id", 0),
            "title": None,
            "type": "private",
            "username": None,
            "participants_count": None,
        }


def chat_info_from_aiogram(aiogram_chat: AiogramChat) -> dict[str, Any]:
    """Извлечение информации о чате из объекта Aiogram"""
    if aiogram_chat is None:
        return {
            "chat_id": 0,
            "title": None,
            "type": "private",
            "username": None,
        }

    chat_type = chat_type_from_aiogram(aiogram_chat)
    return {
        "chat_id": aiogram_chat.id,
        "title": aiogram_chat.title,
        "type": chat_type_to_str(chat_type),
        "username": aiogram_chat.username,
    }


def dict_to_chat_model(data: dict[str, Any]) -> ChatModel:
    """Создание модели чата из словаря"""
    chat_type = data.get("type")
    if isinstance(chat_type, str):
        chat_type = chat_type_from_string(chat_type)
    elif not isinstance(chat_type, ChatType):
        chat_type = ChatType.PRIVATE

    return ChatModel(
        FID=data.get("chat_id", 0),
        FTitle=data.get("title"),
        FType=chat_type,
        FCountMembers=data.get("participants_count", 0),
        FFlagActive=data.get("is_active", True),
    )


def message_info_from_telethon(telethon_message: TelethonMessage) -> dict[str, Any]:
    """Извлечение информации о сообщении из объекта Telethon"""
    if telethon_message is None:
        return {
            "message_id": 0,
            "chat_id": 0,
            "sender_id": None,
            "text": "",
            "date": None,
            "edit_date": None,
            "is_reply": False,
            "is_forwarded": False,
            "media_type": "unknown",
        }

    try:
        date = getattr(telethon_message, "date", None)
        edit_date = getattr(telethon_message, "edit_date", None)

        return {
            "message_id": getattr(telethon_message, "id", 0),
            "chat_id": getattr(telethon_message, "chat_id", 0),
            "sender_id": getattr(telethon_message, "sender_id", None),
            "text": getattr(telethon_message, "text", "") or getattr(telethon_message, "caption", "") or "",
            "date": safe_datetime_convert(date),
            "edit_date": safe_datetime_convert(edit_date),
            "is_reply": bool(getattr(telethon_message, "reply_to", None)),
            "is_forwarded": bool(getattr(telethon_message, "forward", None)),
            "media_type": _get_telethon_media_type(telethon_message),
        }
    except Exception as e:
        tg_logger.warning(f"⚠️ Error extracting message info from Telethon: {e}")
        return {
            "message_id": 0,
            "chat_id": 0,
            "sender_id": None,
            "text": "",
            "date": None,
            "edit_date": None,
            "is_reply": False,
            "is_forwarded": False,
            "media_type": "unknown",
        }


def message_info_from_aiogram(aiogram_message: AiogramMessage) -> dict[str, Any]:
    """Извлечение информации о сообщении из объекта Aiogram"""
    if aiogram_message is None:
        return {
            "message_id": 0,
            "chat_id": 0,
            "sender_id": None,
            "text": "",
            "date": None,
            "edit_date": None,
            "is_reply": False,
            "is_forwarded": False,
            "media_type": "unknown",
        }

    return {
        "message_id": aiogram_message.message_id,
        "chat_id": aiogram_message.chat.id if aiogram_message.chat else 0,
        "sender_id": aiogram_message.from_user.id if aiogram_message.from_user else None,
        "text": aiogram_message.text or aiogram_message.caption or "",
        "date": safe_datetime_convert(aiogram_message.date),
        "edit_date": safe_datetime_convert(aiogram_message.edit_date),
        "is_reply": bool(aiogram_message.reply_to_message),
        "is_forwarded": bool(aiogram_message.forward_from or aiogram_message.forward_from_chat),
        "media_type": _get_aiogram_media_type(aiogram_message),
    }


def save_media_info_to_model(chat_message: ChatMessageModel, telethon_message: TelethonMessage) -> None:
    """Сохранение информации о медиа-файле в модель сообщения"""
    if chat_message is None or telethon_message is None:
        return

    try:
        if hasattr(telethon_message, "photo") and telethon_message.photo:
            photo = telethon_message.photo[-1] if hasattr(telethon_message.photo, "__len__") else telethon_message.photo
            chat_message.FK_File = getattr(photo, "file_id", None)
            chat_message.FK_FileUnique = getattr(photo, "file_unique_id", None)
            chat_message.FFileSize = getattr(photo, "file_size", None)

        elif hasattr(telethon_message, "document") and telethon_message.document:
            doc = telethon_message.document
            chat_message.FK_File = getattr(doc, "file_id", None)
            chat_message.FK_FileUnique = getattr(doc, "file_unique_id", None)
            chat_message.FFileSize = getattr(doc, "file_size", None)
            chat_message.FMimeType = getattr(doc, "mime_type", None)

        elif hasattr(telethon_message, "video") and telethon_message.video:
            video = telethon_message.video
            chat_message.FK_File = getattr(video, "file_id", None)
            chat_message.FK_FileUnique = getattr(video, "file_unique_id", None)
            chat_message.FFileSize = getattr(video, "file_size", None)
            chat_message.FMimeType = getattr(video, "mime_type", None)

        elif hasattr(telethon_message, "audio") and telethon_message.audio:
            audio = telethon_message.audio
            chat_message.FK_File = getattr(audio, "file_id", None)
            chat_message.FK_FileUnique = getattr(audio, "file_unique_id", None)
            chat_message.FFileSize = getattr(audio, "file_size", None)
            chat_message.FMimeType = getattr(audio, "mime_type", None)

        elif hasattr(telethon_message, "voice") and telethon_message.voice:
            voice = telethon_message.voice
            chat_message.FK_File = getattr(voice, "file_id", None)
            chat_message.FK_FileUnique = getattr(voice, "file_unique_id", None)
            chat_message.FFileSize = getattr(voice, "file_size", None)

        elif hasattr(telethon_message, "sticker") and telethon_message.sticker:
            sticker = telethon_message.sticker
            chat_message.FK_File = getattr(sticker, "file_id", None)
            chat_message.FK_FileUnique = getattr(sticker, "file_unique_id", None)
            chat_message.FFileSize = getattr(sticker, "file_size", None)
    except Exception as e:
        tg_logger.debug(f"⚠️ Could not save media info: {e}")


# ==================== PRIVATE HELPERS ====================


def _get_telethon_media_type(message: TelethonMessage) -> str:
    """Определение типа медиа для сообщения Telethon"""
    try:
        if getattr(message, "text", None):
            return "text"
        elif getattr(message, "photo", None):
            return "photo"
        elif getattr(message, "document", None):
            doc = message.document
            if hasattr(doc, "mime_type") and doc.mime_type:
                mime = doc.mime_type.lower()
                if mime.startswith("video/"):
                    return "video"
                elif mime.startswith("audio/"):
                    return "audio"
                elif mime.startswith("image/"):
                    return "image"
                elif "application" in mime:
                    return "document"
            return "document"
        elif getattr(message, "video", None):
            return "video"
        elif getattr(message, "audio", None):
            return "audio"
        elif getattr(message, "voice", None):
            return "voice"
        elif getattr(message, "video_note", None):
            return "video_note"
        elif getattr(message, "sticker", None):
            return "sticker"
        elif getattr(message, "gif", None):
            return "animation"
        elif getattr(message, "contact", None):
            return "contact"
        elif getattr(message, "location", None):
            return "location"
        elif getattr(message, "poll", None):
            return "poll"
        elif getattr(message, "game", None):
            return "game"
    except Exception:
        pass

    return "unknown"


def _get_aiogram_media_type(message: AiogramMessage) -> str:
    """Определение типа медиа для сообщения Aiogram"""
    if not message:
        return "unknown"

    try:
        if message.text:
            return "text"
        elif message.photo:
            return "photo"
        elif message.document:
            if message.document.mime_type:
                mime = message.document.mime_type.lower()
                if mime.startswith("video/"):
                    return "video"
                elif mime.startswith("audio/"):
                    return "audio"
                elif mime.startswith("image/"):
                    return "image"
            return "document"
        elif message.video:
            return "video"
        elif message.audio:
            return "audio"
        elif message.voice:
            return "voice"
        elif message.sticker:
            return "sticker"
        elif message.animation:
            return "animation"
        elif message.contact:
            return "contact"
        elif message.location:
            return "location"
        elif message.poll:
            return "poll"
    except Exception:
        pass

    return "unknown"


# ==================== UTILITY CLASSES ====================


class UserConverter:
    """Утилиты для работы с пользователями"""

    @staticmethod
    def get_full_name(first_name: str | None = None, last_name: str | None = None, username: str | None = None) -> str:
        """Получение полного имени пользователя"""
        if first_name and last_name:
            return f"{first_name} {last_name}"
        elif first_name:
            return first_name
        elif last_name:
            return last_name
        elif username:
            return username
        return "Unknown User"

    @staticmethod
    def get_display_name(
        first_name: str | None = None,
        last_name: str | None = None,
        username: str | None = None,
        user_id: int | None = None,
    ) -> str:
        """Получение отображаемого имени пользователя"""
        full_name = UserConverter.get_full_name(first_name, last_name)

        if full_name and full_name != "Unknown User":
            return full_name
        elif username:
            return f"@{username}"
        elif user_id:
            return f"User {user_id}"
        return "Unknown User"

    @staticmethod
    def get_mention(
        user_id: int, first_name: str | None = None, last_name: str | None = None, username: str | None = None
    ) -> str:
        """Получение упоминания пользователя"""
        display_name = UserConverter.get_display_name(first_name, last_name, username)
        return f"[{display_name}](tg://user?id={user_id})"


# ==================== ЭКСПОРТ ====================

__all__ = [
    # Из core
    "chat_type_from_aiogram",
    "chat_type_from_string",
    "chat_type_from_telethon",
    "chat_type_from_dialog",
    "chat_type_to_str",
    "member_status_from_aiogram",
    "member_status_from_string",
    "member_status_from_telethon",
    "member_status_to_str",
    "user_info_from_aiogram",
    "user_info_from_telethon",
    "safe_datetime_convert",
    "get_message_text",
    "get_content_type",
    "get_media_info",
    "extract_command",
    "extract_command_args",
    "validate_chat_id",
    "validate_user_id",
    "validate_message_id",
    # Дополнительные
    "dict_to_user_model",
    "chat_info_from_telethon",
    "chat_info_from_aiogram",
    "dict_to_chat_model",
    "message_info_from_telethon",
    "message_info_from_aiogram",
    "save_media_info_to_model",
    # Классы
    "UserConverter",
]
