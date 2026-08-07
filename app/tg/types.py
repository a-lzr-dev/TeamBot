from datetime import datetime
from enum import StrEnum
from typing import TYPE_CHECKING, Any, Protocol, runtime_checkable

from ..utils.datetime import get_timestamp

if TYPE_CHECKING:
    from ..models import ChatMessageModel


# ============ Константы ============


class TelegramAccountType(StrEnum):
    """Тип аккаунта Telegram"""

    BOT = "bot"
    USER = "user"


class ClientStatus(StrEnum):
    """Статус клиента"""

    INITIALIZED = "initialized"
    STARTING = "starting"
    RUNNING = "running"
    STOPPING = "stopping"
    STOPPED = "stopped"
    ERROR = "error"
    DISCONNECTED = "disconnected"


# ============ Протоколы для клиентов ============


@runtime_checkable
class TelegramClientProtocol(Protocol):
    """Протокол для Telegram клиентов"""

    async def initialize(self, *args: Any, **kwargs: Any) -> None: ...

    async def start(self) -> None: ...

    async def stop(self) -> None: ...

    async def is_connected(self) -> bool: ...

    async def get_status(self) -> dict[str, Any]: ...

    async def send_message(self, chat_id: int, text: str, **kwargs: Any) -> dict[str, Any]: ...  # ← добавлен Any

    async def get_me(self) -> dict[str, Any]: ...

    @property
    def client_type(self) -> str: ...

    @property
    def is_initialized(self) -> bool: ...

    @property
    def is_running(self) -> bool: ...


# ============ Типы для сервисов ============


class ServiceStatus:
    """Статус сервиса"""

    def __init__(
        self, initialized: bool = False, client_available: bool = False, service: str = "unknown", **extra: Any
    ) -> None:
        self.initialized = initialized
        self.client_available = client_available
        self.service = service
        self.extra = extra

    def to_dict(self) -> dict[str, Any]:
        """Преобразование в словарь"""
        return {
            "initialized": self.initialized,
            "client_available": self.client_available,
            "service": self.service,
            **self.extra,
        }


# ============ Типы для сообщений ============


class MessageMediaInfo:
    """Информация о медиа-файле в сообщении"""

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
        self.file_id = file_id
        self.file_unique_id = file_unique_id
        self.file_size = file_size
        self.mime_type = mime_type
        self.width = width
        self.height = height
        self.duration = duration

    def to_dict(self) -> dict[str, Any]:
        """Преобразование в словарь"""
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
        """Применение информации о медиа к модели сообщения"""
        from ..models import ChatMessageModel

        if not isinstance(chat_message, ChatMessageModel):
            return

        chat_message.FK_File = self.file_id
        chat_message.FK_FileUnique = self.file_unique_id
        chat_message.FFileSize = self.file_size
        chat_message.FMimeType = self.mime_type


# ============ Типы для чатов ============


class ChatInfo:
    """Информация о чате"""

    def __init__(
        self,
        chat_id: int,
        title: str | None = None,
        chat_type: str = "private",
        username: str | None = None,
        participants_count: int | None = None,
        is_active: bool = True,
    ) -> None:
        self.chat_id = chat_id
        self.title = title
        self.chat_type = chat_type
        self.username = username
        self.participants_count = participants_count
        self.is_active = is_active

    def to_dict(self) -> dict[str, Any]:
        """Преобразование в словарь"""
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
    """Информация о пользователе"""

    def __init__(
        self,
        user_id: int,
        username: str | None = None,
        first_name: str = "",
        last_name: str | None = None,
        is_bot: bool = False,
        phone: str | None = None,
    ) -> None:
        self.user_id = user_id
        self.username = username
        self.first_name = first_name
        self.last_name = last_name
        self.is_bot = is_bot
        self.phone = phone

    def to_dict(self) -> dict[str, Any]:
        """Преобразование в словарь"""
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
        """Полное имя пользователя"""
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
    """Результат синхронизации"""

    def __init__(self) -> None:
        self.processed: dict[str, int] = {"chats": 0, "members": 0}
        self.added: dict[str, int] = {"chats": 0, "members": 0}
        self.deactivated: dict[str, int] = {"chats": 0, "members": 0}
        self.skipped: int = 0
        self.errors: dict[str, int] = {"chats": 0, "members": 0}
        self._error_messages: list[str] = []

    def add_processed_chat(self) -> None:
        """Добавление обработанного чата"""
        self.processed["chats"] += 1

    def add_processed_member(self) -> None:
        """Добавление обработанного участника"""
        self.processed["members"] += 1

    def add_added_chat(self) -> None:
        """Добавление созданного чата"""
        self.added["chats"] += 1

    def add_added_member(self) -> None:
        """Добавление созданного участника"""
        self.added["members"] += 1

    def add_deactivated_chat(self) -> None:
        """Добавление деактивированного чата"""
        self.deactivated["chats"] += 1

    def add_deactivated_member(self) -> None:
        """Добавление деактивированного участника"""
        self.deactivated["members"] += 1

    def add_error_chat(self, error: str) -> None:
        """Добавление ошибки чата"""
        self.errors["chats"] += 1
        self._error_messages.append(f"Chat error: {error}")

    def add_error_member(self, error: str) -> None:
        """Добавление ошибки участника"""
        self.errors["members"] += 1
        self._error_messages.append(f"Member error: {error}")

    def add_skipped(self) -> None:
        """Добавление пропущенного элемента"""
        self.skipped += 1

    def to_dict(self) -> dict[str, Any]:
        """Преобразование в словарь"""
        result: dict[str, Any] = {
            "processed": self.processed,
            "added": self.added,
            "deactivated": self.deactivated,
            "skipped": self.skipped,
            "errors": self.errors,
        }

        if self._error_messages:
            result["error_messages"] = self._error_messages[:10]  # Только первые 10

        return result

    def reset(self) -> None:
        """Сброс всех счетчиков."""
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
    """Протокол для конвертеров сообщений"""

    @staticmethod
    def get_content_type(message: Any) -> str: ...  # ← добавлен Any

    @staticmethod
    def get_media_info(message: Any) -> MessageMediaInfo: ...  # ← добавлен Any

    @staticmethod
    def get_message_text(message: Any) -> str | None: ...  # ← добавлен Any


# ============ Утилиты ============


def safe_datetime_convert(dt: Any) -> datetime | None:  # ← добавлен тип для аргумента
    """Безопасное преобразование даты"""
    if dt is None:
        return None

    try:
        if hasattr(dt, "replace"):
            return dt.replace(tzinfo=None)  # type: ignore[no-any-return]
        return dt  # type: ignore[no-any-return]
    except Exception:
        return None


# get_timestamp УДАЛЕН отсюда - используем из app.utils.datetime


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
