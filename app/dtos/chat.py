from dataclasses import dataclass, field
from typing import Any

from ..models import ChatMessageModel, ChatModel


@dataclass
class ChatDTO:
    """DTO для чата"""

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
        """Создание DTO из модели"""
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
        """Преобразование в словарь"""
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
    """DTO для детальной информации о чате"""

    recent_messages: list[dict[str, Any]] = field(default_factory=list)

    def __post_init__(self) -> None:
        """Инициализация после создания объекта"""
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
        """Создание DTO из модели"""
        recent_messages_list = []
        if recent_messages:
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
            recent_messages=recent_messages_list,  # ← поле из ChatDetailDTO
        )


@dataclass
class MessageDTO:
    """DTO для сообщения"""

    # Все поля БЕЗ дефолта
    id: int
    chat_id: int
    user_id: int | None
    text: str | None
    type: str
    sent_at: str | None
    is_deleted: bool
    has_lifetime: bool

    # Все поля С дефолтом
    expires_at: str | None = None
    deleted_at: str | None = None
    deleted_by_type: str | None = None

    @classmethod
    def from_model(cls, message: ChatMessageModel) -> "MessageDTO":
        """Создание DTO из модели"""
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
        """Преобразование в словарь"""
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
    """DTO для удаленного сообщения"""

    # Все поля БЕЗ дефолта
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
        """Создание DTO из модели"""
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
        """Преобразование в словарь"""
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
