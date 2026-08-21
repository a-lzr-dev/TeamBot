"""
Модуль конвертеров и валидаторов для работы с данными Telegram.

Этот модуль предоставляет функции и классы для:
1. Конвертации данных между различными форматами:
   - Из объектов Telegram API (Aiogram, Telethon) в словари/модели
   - Из словарей в модели данных
   - Определение типов чатов, статусов участников, медиа-файлов

2. Валидации данных:
   - Проверка ID чатов, пользователей, сообщений
   - Валидация текстов, команд, номеров телефонов, email
   - Rate limiting для ограничения запросов

3. Обработки текста:
   - Извлечение упоминаний, хэштегов, ссылок
   - Санитайзинг и обрезание текста
   - Парсинг команд и аргументов

Основные компоненты:
    - UserConverter: Утилиты для работы с пользователями
    - Validator: Базовые проверки данных
    - TextValidator: Валидация и обработка текста
    - CommandValidator: Работа с командами
    - DataValidator: Проверка структур данных
    - RateLimitValidator: Ограничение частоты запросов
"""

import re
from datetime import datetime, timedelta
from typing import Any

from ..core.converters import (
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
from ..logger import bot_logger
from ..models import ChatMessageModel, ChatModel, ChatType, UserModel

#  ================== 1. Конвертеры  ==================


def dict_to_user_model(data: dict[str, Any]) -> UserModel:
    """
    Создание модели пользователя из словаря.

    Используется для преобразования данных из внешних источников
    в объект UserModel для сохранения в базе данных.

    Args:
        data: Словарь с данными пользователя

    Returns:
        UserModel: Объект модели пользователя
    """
    return UserModel(
        FID=data.get("user_id", 0),
        FUserName=data.get("username", ""),
        FFirstName=data.get("first_name", ""),
        FLastName=data.get("last_name"),
        FFlagBot=data.get("is_bot", False),
    )


def chat_info_from_telethon(telethon_chat: Any) -> dict[str, Any]:
    """
    Извлечение информации о чате из объекта Telethon.

    Преобразует объект чата Telethon в универсальный словарь
    с основными полями.

    Args:
        telethon_chat: Объект чата Telethon

    Returns:
        dict: Словарь с информацией о чате
    """
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
        bot_logger.warning(f"⚠️ Error extracting chat info from Telethon: {e}")
        return {
            "chat_id": getattr(telethon_chat, "id", 0),
            "title": None,
            "type": "private",
            "username": None,
            "participants_count": None,
        }


def chat_info_from_aiogram(aiogram_chat: Any) -> dict[str, Any]:
    """
    Извлечение информации о чате из объекта Aiogram.

    Преобразует объект чата Aiogram в универсальный словарь.

    Args:
        aiogram_chat: Объект чата Aiogram

    Returns:
        dict: Словарь с информацией о чате
    """
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
    """
    Создание модели чата из словаря.

    Args:
        data: Словарь с данными чата

    Returns:
        ChatModel: Объект модели чата
    """
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


def message_info_from_telethon(telethon_message: Any) -> dict[str, Any]:
    """
    Извлечение информации о сообщении из объекта Telethon.

    Args:
        telethon_message: Объект сообщения Telethon

    Returns:
        dict: Словарь с информацией о сообщении
    """
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
        bot_logger.warning(f"⚠️ Error extracting message info from Telethon: {e}")
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


def message_info_from_aiogram(aiogram_message: Any) -> dict[str, Any]:
    """
    Извлечение информации о сообщении из объекта Aiogram.

    Args:
        aiogram_message: Объект сообщения Aiogram

    Returns:
        dict: Словарь с информацией о сообщении
    """
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


def save_media_info_to_model(chat_message: ChatMessageModel, telethon_message: Any) -> None:
    """
    Сохранение информации о медиа-файле в модель сообщения.

    Извлекает данные о прикрепленных файлах из объекта Telethon
    и сохраняет их в модель для дальнейшей записи в БД.

    Args:
        chat_message: Модель сообщения для заполнения
        telethon_message: Объект сообщения Telethon
    """
    if chat_message is None or telethon_message is None:
        return

    try:
        # Обработка фото
        if hasattr(telethon_message, "photo") and telethon_message.photo:
            photo = telethon_message.photo[-1] if hasattr(telethon_message.photo, "__len__") else telethon_message.photo
            chat_message.FK_File = getattr(photo, "file_id", None)
            chat_message.FK_FileUnique = getattr(photo, "file_unique_id", None)
            chat_message.FFileSize = getattr(photo, "file_size", None)

        # Обработка документа
        elif hasattr(telethon_message, "document") and telethon_message.document:
            doc = telethon_message.document
            chat_message.FK_File = getattr(doc, "file_id", None)
            chat_message.FK_FileUnique = getattr(doc, "file_unique_id", None)
            chat_message.FFileSize = getattr(doc, "file_size", None)
            chat_message.FMimeType = getattr(doc, "mime_type", None)

        # Обработка видео
        elif hasattr(telethon_message, "video") and telethon_message.video:
            video = telethon_message.video
            chat_message.FK_File = getattr(video, "file_id", None)
            chat_message.FK_FileUnique = getattr(video, "file_unique_id", None)
            chat_message.FFileSize = getattr(video, "file_size", None)
            chat_message.FMimeType = getattr(video, "mime_type", None)

        # Обработка аудио
        elif hasattr(telethon_message, "audio") and telethon_message.audio:
            audio = telethon_message.audio
            chat_message.FK_File = getattr(audio, "file_id", None)
            chat_message.FK_FileUnique = getattr(audio, "file_unique_id", None)
            chat_message.FFileSize = getattr(audio, "file_size", None)
            chat_message.FMimeType = getattr(audio, "mime_type", None)

        # Обработка голосового
        elif hasattr(telethon_message, "voice") and telethon_message.voice:
            voice = telethon_message.voice
            chat_message.FK_File = getattr(voice, "file_id", None)
            chat_message.FK_FileUnique = getattr(voice, "file_unique_id", None)
            chat_message.FFileSize = getattr(voice, "file_size", None)

        # Обработка стикера
        elif hasattr(telethon_message, "sticker") and telethon_message.sticker:
            sticker = telethon_message.sticker
            chat_message.FK_File = getattr(sticker, "file_id", None)
            chat_message.FK_FileUnique = getattr(sticker, "file_unique_id", None)
            chat_message.FFileSize = getattr(sticker, "file_size", None)
    except Exception as e:
        bot_logger.debug(f"⚠️ Could not save media info: {e}")


# Помощники для конвертеров


def _get_telethon_media_type(message: Any) -> str:
    """
    Определение типа медиа для сообщения Telethon.

    Args:
        message: Объект сообщения Telethon

    Returns:
        str: Тип медиа (text, photo, video, audio, document, и т.д.)
    """
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


def _get_aiogram_media_type(message: Any) -> str:
    """
    Определение типа медиа для сообщения Aiogram.

    Args:
        message: Объект сообщения Aiogram

    Returns:
        str: Тип медиа (text, photo, video, audio, document, и т.д.)
    """
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


#  ================== 2. Утилиты для работы с данными  ==================


class UserConverter:
    """Утилиты для работы с пользователями Telegram."""

    @staticmethod
    def get_full_name(first_name: str | None = None, last_name: str | None = None, username: str | None = None) -> str:
        """
        Получение полного имени пользователя.

        Args:
            first_name: Имя пользователя
            last_name: Фамилия пользователя
            username: Username пользователя

        Returns:
            str: Полное имя пользователя
        """
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
        """
        Получение отображаемого имени пользователя.

        Args:
            first_name: Имя пользователя
            last_name: Фамилия пользователя
            username: Username пользователя
            user_id: ID пользователя

        Returns:
            str: Отображаемое имя
        """
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
        """
        Получение упоминания пользователя в формате Markdown.

        Args:
            user_id: ID пользователя
            first_name: Имя пользователя
            last_name: Фамилия пользователя
            username: Username пользователя

        Returns:
            str: Упоминание в формате [имя](tg://user?id=id)
        """
        display_name = UserConverter.get_display_name(first_name, last_name, username)
        return f"[{display_name}](tg://user?id={user_id})"


#  ================== 3. Валидаторы  ==================


class Validator:
    """Базовый класс для валидаторов с общими проверками."""

    @staticmethod
    def validate_not_empty(value: Any, field_name: str) -> bool:
        """
        Проверка, что значение не пустое.

        Args:
            value: Проверяемое значение
            field_name: Название поля для логирования

        Returns:
            bool: True если значение не пустое
        """
        if value is None:
            bot_logger.warning(f"⚠️ {field_name} is None")
            return False

        if isinstance(value, str) and not value.strip():
            bot_logger.warning(f"⚠️ {field_name} is empty string")
            return False

        if isinstance(value, list | dict | set) and not value:
            bot_logger.warning(f"⚠️ {field_name} is empty collection")
            return False

        return True

    @staticmethod
    def validate_length(value: str, field_name: str, min_len: int = 1, max_len: int = 4096) -> bool:
        """
        Проверка длины строки.

        Args:
            value: Строка для проверки
            field_name: Название поля для логирования
            min_len: Минимальная длина
            max_len: Максимальная длина

        Returns:
            bool: True если длина в допустимых пределах
        """
        if not Validator.validate_not_empty(value, field_name):
            return False

        if len(value) < min_len:
            bot_logger.warning(f"⚠️ {field_name} is too short: {len(value)} < {min_len}")
            return False

        if len(value) > max_len:
            bot_logger.warning(f"⚠️ {field_name} is too long: {len(value)} > {max_len}")
            return False

        return True

    @staticmethod
    def validate_positive_int(value: int, field_name: str) -> bool:
        """
        Проверка, что число положительное.

        Args:
            value: Число для проверки
            field_name: Название поля для логирования

        Returns:
            bool: True если число положительное
        """
        if not isinstance(value, int):
            bot_logger.warning(f"⚠️ {field_name} is not an integer: {type(value)}")
            return False

        if value <= 0:
            bot_logger.warning(f"⚠️ {field_name} must be positive: {value}")
            return False

        return True

    @staticmethod
    def validate_chat_id(chat_id: int) -> bool:
        """Валидация ID чата."""
        return Validator.validate_positive_int(abs(chat_id), "chat_id")

    @staticmethod
    def validate_user_id(user_id: int) -> bool:
        """Валидация ID пользователя."""
        return Validator.validate_positive_int(user_id, "user_id")

    @staticmethod
    def validate_message_id(message_id: int) -> bool:
        """Валидация ID сообщения."""
        return Validator.validate_positive_int(message_id, "message_id")


class TextValidator:
    """Валидатор текстовых данных."""

    @staticmethod
    def sanitize_text(text: str, max_length: int = 4096) -> str:
        """
        Санитайзинг текста (очистка от опасных символов).

        Args:
            text: Исходный текст
            max_length: Максимальная длина

        Returns:
            str: Очищенный текст
        """
        if not text:
            return ""

        # Обрезание длины
        if len(text) > max_length:
            text = text[:max_length]

        # Удаление лишних пробелов
        text = " ".join(text.split())

        # Экранирование опасных символов (для HTML)
        text = text.replace("&", "&amp;")
        text = text.replace("<", "&lt;")
        text = text.replace(">", "&gt;")
        text = text.replace('"', "&quot;")

        return text

    @staticmethod
    def validate_parse_mode(parse_mode: str | None) -> str | None:
        """
        Валидация режима парсинга.

        Args:
            parse_mode: Режим парсинга

        Returns:
            str | None: Валидный режим или None
        """
        if parse_mode is None:
            return None

        valid_modes = ["HTML", "MARKDOWN", "MARKDOWN_V2"]
        parse_mode_upper = parse_mode.upper()

        if parse_mode_upper not in valid_modes:
            bot_logger.warning(f"⚠️ Invalid parse_mode: {parse_mode}, using HTML")
            return "HTML"

        return parse_mode_upper

    @staticmethod
    def extract_mentions(text: str) -> list[str]:
        """Извлечение упоминаний (@username) из текста."""
        if not text:
            return []

        pattern = r"@\w+"
        return re.findall(pattern, text)

    @staticmethod
    def extract_hashtags(text: str) -> list[str]:
        """Извлечение хэштегов (#tag) из текста."""
        if not text:
            return []

        pattern = r"#\w+"
        return re.findall(pattern, text)

    @staticmethod
    def extract_links(text: str) -> list[str]:
        """Извлечение ссылок (http://, https://) из текста."""
        if not text:
            return []

        pattern = r"https?://[^\s]+"
        return re.findall(pattern, text)

    @staticmethod
    def truncate_text(text: str, max_length: int = 100, suffix: str = "...") -> str:
        """
        Обрезание текста до указанной длины.

        Args:
            text: Исходный текст
            max_length: Максимальная длина
            suffix: Суффикс для обрезанного текста

        Returns:
            str: Обрезанный текст
        """
        if not text:
            return ""

        if len(text) <= max_length:
            return text

        return text[: max_length - len(suffix)] + suffix


class CommandValidator:
    """Валидатор команд Telegram."""

    @staticmethod
    def validate_command(command: str) -> bool:
        """
        Валидация команды.

        Args:
            command: Команда (должна начинаться с /)

        Returns:
            bool: True если команда валидна
        """
        if not command:
            return False

        if not command.startswith("/"):
            return False

        command_name = command[1:]
        return bool(re.fullmatch(r"^[a-zA-Z0-9_]+$", command_name))

    @staticmethod
    def parse_command(text: str) -> dict[str, Any]:
        """
        Парсинг команды и аргументов.

        Args:
            text: Текст с командой

        Returns:
            dict: Словарь с командами и аргументами
        """
        if not text or not text.startswith("/"):
            return {}

        parts = text.strip().split()

        if not parts:
            return {}

        command = parts[0]
        args = parts[1:] if len(parts) > 1 else []

        return {
            "command": command,
            "args": args,
            "args_text": " ".join(args) if args else "",
            "full_text": text,
        }

    @staticmethod
    def is_admin_command(command: str, admin_commands: list[str] | None = None) -> bool:
        """
        Проверка, является ли команда административной.

        Args:
            command: Команда для проверки
            admin_commands: Список административных команд

        Returns:
            bool: True если команда административная
        """
        if admin_commands is None:
            admin_commands = ["/sync", "/stats", "/broadcast"]

        return command in admin_commands


class DataValidator:
    """Валидатор структур данных."""

    @staticmethod
    def validate_dict_keys(data: dict[str, Any], required_keys: list[str]) -> bool:
        """
        Проверка наличия обязательных ключей в словаре.

        Args:
            data: Проверяемый словарь
            required_keys: Список обязательных ключей

        Returns:
            bool: True если все ключи присутствуют
        """
        for key in required_keys:
            if key not in data:
                bot_logger.warning(f"⚠️ Missing required key: {key}")
                return False

        return True

    @staticmethod
    def validate_dict_types(data: dict[str, Any], type_map: dict[str, type]) -> bool:
        """
        Проверка типов значений в словаре.

        Args:
            data: Проверяемый словарь
            type_map: Словарь {ключ: ожидаемый_тип}

        Returns:
            bool: True если все типы соответствуют
        """
        for key, expected_type in type_map.items():
            if key in data and not isinstance(data[key], expected_type):
                bot_logger.warning(
                    f"⚠️ Invalid type for {key}: expected {expected_type.__name__}, got {type(data[key]).__name__}"
                )
                return False

        return True

    @staticmethod
    def validate_phone_number(phone: str) -> bool:
        """
        Валидация номера телефона.

        Args:
            phone: Номер телефона

        Returns:
            bool: True если номер валиден
        """
        if not phone:
            return False

        cleaned = re.sub(r"[^\d+]", "", phone)
        return bool(re.fullmatch(r"^\+?\d{10,15}$", cleaned))

    @staticmethod
    def validate_email(email: str) -> bool:
        """
        Валидация email.

        Args:
            email: Email адрес

        Returns:
            bool: True если email валиден
        """
        if not email:
            return False

        pattern = r"^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$"
        return bool(re.fullmatch(pattern, email))

    @staticmethod
    def validate_username(username: str) -> bool:
        """
        Валидация username.

        Args:
            username: Username для проверки

        Returns:
            bool: True если username валиден
        """
        if not username:
            return False

        if username.startswith("@"):
            username = username[1:]

        return bool(re.fullmatch(r"^[a-zA-Z0-9_]{5,32}$", username))


class RateLimitValidator:
    """
    Валидатор для rate limiting.

    Отслеживает количество запросов от одного источника
    и ограничивает их частоту.
    """

    def __init__(self, limit: int = 10, period: int = 60) -> None:
        """
        Инициализация валидатора.

        Args:
            limit: Максимальное количество запросов
            period: Период в секундах
        """
        self.limit = limit
        self.period = period
        self._requests: dict[str, list[datetime]] = {}

    def is_allowed(self, key: str) -> bool:
        """
        Проверка, разрешен ли запрос.

        Args:
            key: Уникальный ключ источника

        Returns:
            bool: True если запрос разрешен
        """
        now = datetime.now()

        if key in self._requests:
            self._requests[key] = [
                req_time for req_time in self._requests[key] if (now - req_time).total_seconds() < self.period
            ]
        else:
            self._requests[key] = []

        if len(self._requests[key]) >= self.limit:
            return False

        self._requests[key].append(now)
        return True

    def get_remaining(self, key: str) -> int:
        """
        Получение оставшегося количества запросов.

        Args:
            key: Уникальный ключ источника

        Returns:
            int: Оставшееся количество запросов
        """
        if key not in self._requests:
            return self.limit

        return max(0, self.limit - len(self._requests[key]))

    def get_reset_time(self, key: str) -> datetime | None:
        """
        Получение времени сброса лимита.

        Args:
            key: Уникальный ключ источника

        Returns:
            datetime | None: Время сброса
        """
        if key not in self._requests or not self._requests[key]:
            return None

        oldest = min(self._requests[key])
        return oldest + timedelta(seconds=self.period)


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
    # Дополнительные конвертеры
    "dict_to_user_model",
    "chat_info_from_telethon",
    "chat_info_from_aiogram",
    "dict_to_chat_model",
    "message_info_from_telethon",
    "message_info_from_aiogram",
    "save_media_info_to_model",
    "UserConverter",
    # Валидаторы
    "Validator",
    "TextValidator",
    "CommandValidator",
    "DataValidator",
    "RateLimitValidator",
]
