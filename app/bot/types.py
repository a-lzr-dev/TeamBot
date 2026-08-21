"""
Модуль типов и протоколов для Telegram бота.

Этот модуль содержит общие типы данных, протоколы и перечисления,
используемые в различных компонентах системы управления Telegram ботом.

Основные компоненты:
    - TelegramAccountType: Типы аккаунтов (бот/пользователь)
    - ClientStatus: Статусы клиентов Telegram
    - TelegramClientProtocol: Протокол для клиентов Telegram
    - MessageMediaInfo: Информация о медиа-файлах в сообщениях
    - ChatInfo: Информация о чатах
    - UserInfo: Информация о пользователях
    - SyncResult: Результаты синхронизации
    - ServiceStatus: Статус сервисов
"""

from datetime import datetime
from enum import StrEnum
from typing import TYPE_CHECKING, Any, Protocol, runtime_checkable

from ..utils.datetime import get_timestamp

if TYPE_CHECKING:
    from ..models import ChatMessageModel


# ============ Константы ============


class TelegramAccountType(StrEnum):
    """Тип аккаунта Telegram.

    Определяет, является ли аккаунт ботом или обычным пользователем.
    Влияет на доступные функции и возможности синхронизации.
    """

    BOT = "bot"  # Бот-аккаунт (ограниченные возможности синхронизации)
    USER = "user"  # Пользовательский аккаунт (полный доступ к синхронизации)


class ClientStatus(StrEnum):
    """Статус клиента Telegram.

    Используется для отслеживания состояния подключения к Telegram API.
    """

    INITIALIZED = "initialized"  # Клиент инициализирован, но не запущен
    STARTING = "starting"  # Процесс запуска клиента
    RUNNING = "running"  # Клиент работает и готов к использованию
    STOPPING = "stopping"  # Процесс остановки клиента
    STOPPED = "stopped"  # Клиент остановлен
    ERROR = "error"  # Клиент в состоянии ошибки
    DISCONNECTED = "disconnected"  # Соединение потеряно


# ============ Протоколы для клиентов ============


@runtime_checkable
class TelegramClientProtocol(Protocol):
    """
    Протокол для Telegram клиентов.

    Определяет интерфейс, которому должны соответствовать все реализации
    клиентов Telegram (Aiogram, Telethon и т.д.).
    """

    async def initialize(self, *args: Any, **kwargs: Any) -> None:
        """Инициализация клиента."""
        ...

    async def start(self) -> None:
        """Запуск клиента."""
        ...

    async def stop(self) -> None:
        """Остановка клиента."""
        ...

    async def is_connected(self) -> bool:
        """Проверка подключения к Telegram."""
        ...

    async def get_status(self) -> dict[str, Any]:
        """Получение статуса клиента."""
        ...

    async def send_message(self, chat_id: int, text: str, **kwargs: Any) -> dict[str, Any]:
        """Отправка сообщения в чат."""
        ...

    async def get_me(self) -> dict[str, Any]:
        """Получение информации о текущем аккаунте."""
        ...

    @property
    def client_type(self) -> str:
        """Тип клиента (aiogram, telethon и т.д.)."""
        ...

    @property
    def is_initialized(self) -> bool:
        """Инициализирован ли клиент."""
        ...

    @property
    def is_running(self) -> bool:
        """Запущен ли клиент."""
        ...


# ============ Типы для сервисов ============


class ServiceStatus:
    """
    Статус сервиса.

    Используется для мониторинга состояния различных сервисов системы.
    """

    def __init__(
        self, initialized: bool = False, client_available: bool = False, service: str = "unknown", **extra: Any
    ) -> None:
        self.initialized = initialized  # Инициализирован ли сервис
        self.client_available = client_available  # Доступен ли клиент
        self.service = service  # Название сервиса
        self.extra = extra  # Дополнительные параметры

    def to_dict(self) -> dict[str, Any]:
        """Преобразование статуса в словарь для ответов API."""
        return {
            "initialized": self.initialized,
            "client_available": self.client_available,
            "service": self.service,
            **self.extra,
        }


# ============ Типы для сообщений ============


class MessageMediaInfo:
    """
    Информация о медиа-файле в сообщении.

    Содержит метаданные о прикрепленных файлах (изображения, видео, документы).
    """

    def __init__(
        self,
        file_id: str | None = None,
        file_unique_id: str | None = None,
        file_size: int | None = None,
        mime_type: str | None = None,
        width: int | None = None,
        height: int | None = None,
        duration: int | None = None,
    ) -> None:
        self.file_id = file_id  # ID файла в Telegram
        self.file_unique_id = file_unique_id  # Уникальный ID файла
        self.file_size = file_size  # Размер файла в байтах
        self.mime_type = mime_type  # MIME тип файла
        self.width = width  # Ширина изображения/видео
        self.height = height  # Высота изображения/видео
        self.duration = duration  # Длительность аудио/видео (сек)

    def to_dict(self) -> dict[str, Any]:
        """Преобразование информации о медиа в словарь."""
        return {
            "file_id": self.file_id,
            "file_unique_id": self.file_unique_id,
            "file_size": self.file_size,
            "mime_type": self.mime_type,
            "width": self.width,
            "height": self.height,
            "duration": self.duration,
        }

    def apply_to_model(self, chat_message: "ChatMessageModel") -> None:
        """Применение информации о медиа к модели сообщения в БД."""
        from ..models import ChatMessageModel

        if not isinstance(chat_message, ChatMessageModel):
            return

        chat_message.FK_File = self.file_id
        chat_message.FK_FileUnique = self.file_unique_id
        chat_message.FFileSize = self.file_size
        chat_message.FMimeType = self.mime_type


# ============ Типы для чатов ============


class ChatInfo:
    """
    Информация о чате.

    Содержит основные данные о чате в Telegram.
    """

    def __init__(
        self,
        chat_id: int,
        title: str | None = None,
        chat_type: str = "private",
        username: str | None = None,
        participants_count: int | None = None,
        is_active: bool = True,
    ) -> None:
        self.chat_id = chat_id  # ID чата в Telegram
        self.title = title  # Название чата
        self.chat_type = chat_type  # Тип чата (private, group, supergroup, channel)
        self.username = username  # Username чата (если есть)
        self.participants_count = participants_count  # Количество участников
        self.is_active = is_active  # Активен ли чат

    def to_dict(self) -> dict[str, Any]:
        """Преобразование информации о чате в словарь."""
        return {
            "chat_id": self.chat_id,
            "title": self.title,
            "type": self.chat_type,
            "username": self.username,
            "participants_count": self.participants_count,
            "is_active": self.is_active,
        }


# ============ Типы для пользователей ============


class UserInfo:
    """
    Информация о пользователе Telegram.

    Содержит основные данные о пользователе в Telegram.
    """

    def __init__(
        self,
        user_id: int,
        username: str | None = None,
        first_name: str = "",
        last_name: str | None = None,
        is_bot: bool = False,
        phone: str | None = None,
    ) -> None:
        self.user_id = user_id  # ID пользователя в Telegram
        self.username = username  # Username пользователя
        self.first_name = first_name  # Имя пользователя
        self.last_name = last_name  # Фамилия пользователя
        self.is_bot = is_bot  # Является ли пользователь ботом
        self.phone = phone  # Номер телефона (если доступен)

    def to_dict(self) -> dict[str, Any]:
        """Преобразование информации о пользователе в словарь."""
        return {
            "user_id": self.user_id,
            "username": self.username,
            "first_name": self.first_name,
            "last_name": self.last_name,
            "is_bot": self.is_bot,
            "phone": self.phone,
        }

    @property
    def full_name(self) -> str:
        """Полное имя пользователя для отображения."""
        if self.first_name and self.last_name:
            return f"{self.first_name} {self.last_name}"
        elif self.first_name:
            return self.first_name
        elif self.last_name:
            return self.last_name
        elif self.username:
            return self.username
        return "Unknown User"


# ============ Типы для синхронизации ============


class SyncResult:
    """
    Результат синхронизации данных с Telegram.

    Содержит статистику и ошибки, возникшие в процессе синхронизации
    чатов и участников.
    """

    def __init__(self) -> None:
        self.processed: dict[str, int] = {"chats": 0, "members": 0}
        self.added: dict[str, int] = {"chats": 0, "members": 0}
        self.deactivated: dict[str, int] = {"chats": 0, "members": 0}
        self.skipped: int = 0
        self.errors: dict[str, int] = {"chats": 0, "members": 0}
        self._error_messages: list[str] = []

    def add_processed_chat(self) -> None:
        """Увеличение счетчика обработанных чатов."""
        self.processed["chats"] += 1

    def add_processed_member(self) -> None:
        """Увеличение счетчика обработанных участников."""
        self.processed["members"] += 1

    def add_added_chat(self) -> None:
        """Увеличение счетчика добавленных чатов."""
        self.added["chats"] += 1

    def add_added_member(self) -> None:
        """Увеличение счетчика добавленных участников."""
        self.added["members"] += 1

    def add_deactivated_chat(self) -> None:
        """Увеличение счетчика деактивированных чатов."""
        self.deactivated["chats"] += 1

    def add_deactivated_member(self) -> None:
        """Увеличение счетчика деактивированных участников."""
        self.deactivated["members"] += 1

    def add_error_chat(self, error: str) -> None:
        """Увеличение счетчика ошибок чатов с сохранением сообщения."""
        self.errors["chats"] += 1
        self._error_messages.append(f"Chat error: {error}")

    def add_error_member(self, error: str) -> None:
        """Увеличение счетчика ошибок участников с сохранением сообщения."""
        self.errors["members"] += 1
        self._error_messages.append(f"Member error: {error}")

    def add_skipped(self) -> None:
        """Увеличение счетчика пропущенных элементов."""
        self.skipped += 1

    def to_dict(self) -> dict[str, Any]:
        """Преобразование результата синхронизации в словарь."""
        result: dict[str, Any] = {
            "processed": self.processed,
            "added": self.added,
            "deactivated": self.deactivated,
            "skipped": self.skipped,
            "errors": self.errors,
        }

        if self._error_messages:
            result["error_messages"] = self._error_messages[:10]  # Только первые 10 ошибок

        return result

    def reset(self) -> None:
        """Сброс всех счетчиков результата синхронизации."""
        self.processed = {"chats": 0, "members": 0}
        self.added = {"chats": 0, "members": 0}
        self.deactivated = {"chats": 0, "members": 0}
        self.skipped = 0
        self.errors = {"chats": 0, "members": 0}
        self._error_messages = []

    @property
    def total_errors(self) -> int:
        """Общее количество ошибок."""
        return self.errors["chats"] + self.errors["members"]

    @property
    def total_processed(self) -> int:
        """Общее количество обработанных элементов."""
        return self.processed["chats"] + self.processed["members"]

    @property
    def total_added(self) -> int:
        """Общее количество добавленных элементов."""
        return self.added["chats"] + self.added["members"]

    @property
    def total_deactivated(self) -> int:
        """Общее количество деактивированных элементов."""
        return self.deactivated["chats"] + self.deactivated["members"]


# ============ Типы для конвертеров ============


class MessageConverterProtocol(Protocol):
    """Протокол для конвертеров сообщений из разных библиотек."""

    @staticmethod
    def get_content_type(message: Any) -> str:
        """Определение типа содержимого сообщения."""
        ...

    @staticmethod
    def get_media_info(message: Any) -> MessageMediaInfo:
        """Извлечение информации о медиа из сообщения."""
        ...

    @staticmethod
    def get_message_text(message: Any) -> str | None:
        """Извлечение текста из сообщения."""
        ...


# ============ Утилиты ============


def safe_datetime_convert(dt: Any) -> datetime | None:
    """
    Безопасное преобразование даты в объект datetime без часового пояса.

    Используется для нормализации дат из разных источников.
    """
    if dt is None:
        return None

    try:
        if hasattr(dt, "replace"):
            return dt.replace(tzinfo=None)  # type: ignore[no-any-return]
        return dt  # type: ignore[no-any-return]
    except Exception:
        return None


__all__ = [
    # Enum
    "TelegramAccountType",
    "ClientStatus",
    # Protocols
    "TelegramClientProtocol",
    # Service
    "ServiceStatus",
    # Message
    "MessageMediaInfo",
    "MessageConverterProtocol",
    # Chat
    "ChatInfo",
    # User
    "UserInfo",
    # Sync
    "SyncResult",
    # Utils
    "safe_datetime_convert",
    "get_timestamp",
]
