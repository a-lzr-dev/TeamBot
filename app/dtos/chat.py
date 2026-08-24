"""
DTO (Data Transfer Objects) для работы с чатами и сообщениями.

Назначение:
    Предоставляет набор объектов для передачи данных о чатах и сообщениях
    между слоями приложения. Инкапсулирует структуру данных для различных
    сценариев использования:
    - Отображение списка чатов
    - Детальная информация о чате с последними сообщениями
    - Информация о сообщениях
    - Информация об удалённых сообщениях

Основные функции:
    1. ChatDTO - базовый DTO чата для списков и краткой информации
    2. ChatDetailDTO - расширенный DTO чата с последними сообщениями
    3. MessageDTO - DTO сообщения с информацией о времени жизни
    4. DeletedMessageDTO - DTO удалённого сообщения с деталями удаления

Технические особенности:
    - Все DTO реализованы как dataclass для удобства создания и сравнения
    - Поддержка преобразования из моделей (from_model)
    - Поддержка преобразования в словарь (to_dict) для JSON сериализации
    - Автоматическое форматирование дат в ISO формат с суффиксом "Z" (UTC)
    - Обрезание длинных текстов (первые 100 символов) для MessageDTO
    - Наследование ChatDetailDTO от ChatDTO с добавлением recent_messages

Архитектура:
    - Используются в API роутерах (bot_msgs, chat_details, stats)
    - Используются в сервисах для передачи данных клиентам
    - Используются в репозиториях для преобразования моделей
"""

from dataclasses import dataclass, field
from typing import Any

from ..models import ChatMessageModel, ChatModel


@dataclass
class ChatDTO:
    """DTO для чата.

    Используется для отображения базовой информации о чате в списках
    и API ответах.

    Attributes:
        chat_id (int): ID чата в Telegram
        title (str): Название чата
        type (str): Тип чата (private, group, supergroup, channel)
        is_active (bool): Активен ли чат
        members_count (int): Количество участников (по умолчанию 0)
        messages_count (int): Количество сообщений (по умолчанию 0)
        last_activity (str | None): Время последней активности (ISO)
        last_sync (str | None): Время последней синхронизации (ISO)
    """

    chat_id: int
    title: str
    type: str
    is_active: bool
    members_count: int = 0
    messages_count: int = 0
    last_activity: str | None = None
    last_sync: str | None = None

    @classmethod
    def from_model(cls, chat: ChatModel, members_count: int = 0, messages_count: int = 0) -> "ChatDTO":
        """Создание DTO из модели ChatModel.

        Args:
            chat (ChatModel): Модель чата
            members_count (int): Количество участников (опционально)
            messages_count (int): Количество сообщений (опционально)

        Returns:
            ChatDTO: Объект DTO с данными чата
        """
        return cls(
            chat_id=chat.FID,
            title=chat.FTitle or f"Chat {chat.FID}",
            type=chat.FType.value if chat.FType else "unknown",
            is_active=chat.FFlagActive,
            members_count=members_count,
            messages_count=messages_count,
            last_activity=chat.FDateUpdated.isoformat() + "Z" if chat.FDateUpdated else None,
            last_sync=chat.FDateSynced.isoformat() + "Z" if chat.FDateSynced else None,
        )

    def to_dict(self) -> dict[str, Any]:
        """Преобразование в словарь для JSON сериализации.

        Returns:
            dict[str, Any]: Словарь с данными чата
        """
        return {
            "chat_id": self.chat_id,
            "title": self.title,
            "type": self.type,
            "is_active": self.is_active,
            "members_count": self.members_count,
            "messages_count": self.messages_count,
            "last_activity": self.last_activity,
            "last_sync": self.last_sync,
        }


@dataclass
class ChatDetailDTO(ChatDTO):
    """DTO для детальной информации о чате.

    Расширяет ChatDTO, добавляя список последних сообщений.
    Используется для отображения полной информации о чате.

    Attributes:
        recent_messages (list[dict[str, Any]]): Список последних сообщений
            (по умолчанию пустой список)
    """

    recent_messages: list[dict[str, Any]] = field(default_factory=list)

    def __post_init__(self) -> None:
        """Инициализация после создания объекта.

        Гарантирует, что recent_messages всегда является списком.
        """
        if self.recent_messages is None:
            self.recent_messages = []

    @classmethod
    def from_model(
        cls,
        chat: ChatModel,
        members_count: int = 0,
        messages_count: int = 0,
        recent_messages: list[ChatMessageModel] | None = None,
    ) -> "ChatDetailDTO":
        """Создание DTO из модели чата.

        Args:
            chat (ChatModel): Модель чата
            members_count (int): Количество участников (опционально)
            messages_count (int): Количество сообщений (опционально)
            recent_messages (list[ChatMessageModel] | None): Последние сообщения

        Returns:
            ChatDetailDTO: Объект DTO с детальной информацией о чате
        """
        recent_messages_list = []
        if recent_messages:
            # Берём только первые 5 сообщений для краткости
            for msg in recent_messages[:5]:
                recent_messages_list.append(MessageDTO.from_model(msg).to_dict())

        return cls(
            chat_id=chat.FID,
            title=chat.FTitle or f"Chat {chat.FID}",
            type=chat.FType.value if chat.FType else "unknown",
            is_active=chat.FFlagActive,
            members_count=members_count,
            messages_count=messages_count,
            last_activity=chat.FDateUpdated.isoformat() + "Z" if chat.FDateUpdated else None,
            last_sync=chat.FDateSynced.isoformat() + "Z" if chat.FDateSynced else None,
            recent_messages=recent_messages_list,
        )


@dataclass
class MessageDTO:
    """DTO для сообщения.

    Используется для отображения информации о сообщении в API и интерфейсе.
    Содержит данные о времени жизни и статусе удаления.

    Attributes (обязательные):
        id (int): ID сообщения
        chat_id (int): ID чата
        user_id (int | None): ID пользователя-отправителя
        text (str | None): Текст сообщения (обрезается до 100 символов)
        type (str): Тип сообщения
        sent_at (str | None): Время отправки (ISO)
        is_deleted (bool): Удалено ли сообщение
        has_lifetime (bool): Есть ли время жизни

    Attributes (опциональные):
        expires_at (str | None): Время истечения (ISO)
        deleted_at (str | None): Время удаления (ISO)
        deleted_by_type (str | None): Тип удаления
    """

    id: int
    chat_id: int
    user_id: int | None
    text: str | None
    type: str
    sent_at: str | None
    is_deleted: bool
    has_lifetime: bool

    expires_at: str | None = None
    deleted_at: str | None = None
    deleted_by_type: str | None = None

    @classmethod
    def from_model(cls, message: ChatMessageModel) -> "MessageDTO":
        """Создание DTO из модели ChatMessageModel.

        Args:
            message (ChatMessageModel): Модель сообщения

        Returns:
            MessageDTO: Объект DTO с данными сообщения
        """
        return cls(
            id=message.FID,
            chat_id=message.FK_Chat,
            user_id=message.FK_User,
            text=message.FText[:100] + "..." if message.FText and len(message.FText) > 100 else message.FText,
            type=message.FK_MessageType.value if message.FK_MessageType else "unknown",
            sent_at=message.FDateSent.isoformat() + "Z" if message.FDateSent else None,
            is_deleted=message.FFlagDeleted,
            has_lifetime=message.FLifetimeSeconds is not None,
            expires_at=message.FExpiresAt.isoformat() + "Z" if message.FExpiresAt else None,
            deleted_at=message.FDateDeleted.isoformat() + "Z" if message.FDateDeleted else None,
            deleted_by_type=message.FDeletedByType,
        )

    def to_dict(self) -> dict[str, Any]:
        """Преобразование в словарь для JSON сериализации.

        Returns:
            dict[str, Any]: Словарь с данными сообщения
        """
        result = {
            "id": self.id,
            "chat_id": self.chat_id,
            "user_id": self.user_id,
            "text": self.text,
            "type": self.type,
            "sent_at": self.sent_at,
            "is_deleted": self.is_deleted,
            "has_lifetime": self.has_lifetime,
        }

        if self.expires_at is not None:
            result["expires_at"] = self.expires_at
        if self.deleted_at is not None:
            result["deleted_at"] = self.deleted_at
        if self.deleted_by_type is not None:
            result["deleted_by_type"] = self.deleted_by_type

        return result


@dataclass
class DeletedMessageDTO:
    """DTO для удалённого сообщения.

    Используется для отображения полной информации об удалённом сообщении,
    включая детали удаления (инициатор, причина, время).

    Attributes:
        id (int): ID сообщения
        chat_id (int): ID чата
        user_id (int | None): ID пользователя-отправителя
        text (str | None): Текст сообщения (обрезается до 100 символов)
        type (str): Тип сообщения
        sent_at (str | None): Время отправки (ISO)
        deleted_at (str | None): Время удаления (ISO)
        deleted_by_type (str | None): Тип удаления
        initiator_message_id (int | None): ID сообщения-инициатора удаления
        had_lifetime (bool): Было ли время жизни
        lifetime_seconds (int | None): Время жизни в секундах
        expired_at (str | None): Время истечения (ISO)
    """

    id: int
    chat_id: int
    user_id: int | None
    text: str | None
    type: str
    sent_at: str | None
    deleted_at: str | None
    deleted_by_type: str | None
    initiator_message_id: int | None
    had_lifetime: bool
    lifetime_seconds: int | None
    expired_at: str | None

    @classmethod
    def from_model(cls, message: ChatMessageModel) -> "DeletedMessageDTO":
        """Создание DTO из модели ChatMessageModel.

        Args:
            message (ChatMessageModel): Модель сообщения

        Returns:
            DeletedMessageDTO: Объект DTO с данными удалённого сообщения
        """
        return cls(
            id=message.FID,
            chat_id=message.FK_Chat,
            user_id=message.FK_User,
            text=message.FText[:100] + "..." if message.FText and len(message.FText) > 100 else message.FText,
            type=message.FK_MessageType.value if message.FK_MessageType else "unknown",
            sent_at=message.FDateSent.isoformat() + "Z" if message.FDateSent else None,
            deleted_at=message.FDateDeleted.isoformat() + "Z" if message.FDateDeleted else None,
            deleted_by_type=message.FDeletedByType,
            initiator_message_id=message.FK_DeletedByMessage,
            had_lifetime=message.FLifetimeSeconds is not None,
            lifetime_seconds=message.FLifetimeSeconds,
            expired_at=message.FExpiresAt.isoformat() + "Z" if message.FExpiresAt else None,
        )

    def to_dict(self) -> dict[str, Any]:
        """Преобразование в словарь для JSON сериализации.

        Returns:
            dict[str, Any]: Словарь с данными удалённого сообщения
        """
        return {
            "id": self.id,
            "chat_id": self.chat_id,
            "user_id": self.user_id,
            "text": self.text,
            "type": self.type,
            "sent_at": self.sent_at,
            "deleted_at": self.deleted_at,
            "deleted_by_type": self.deleted_by_type,
            "initiator_message_id": self.initiator_message_id,
            "had_lifetime": self.had_lifetime,
            "lifetime_seconds": self.lifetime_seconds,
            "expired_at": self.expired_at,
        }
