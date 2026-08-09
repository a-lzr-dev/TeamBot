from datetime import UTC, datetime
from enum import StrEnum
from typing import Any, Optional

from sqlalchemy import (
    BigInteger,
    Boolean,
    DateTime,
    Integer,
    String,
)
from sqlalchemy import Enum as SQLEnum
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

# ============ ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ ============


def datetime_now() -> datetime:
    """Возвращает текущее время без часового пояса"""
    return datetime.now(UTC).replace(tzinfo=None)


# ============ БАЗОВАЯ МОДЕЛЬ ============


class BaseModel(DeclarativeBase):
    pass


# ============ БАЗОВЫЕ ENUM ============


class ChatType(StrEnum):
    """Типы чатов Telegram"""

    SENDER = "sender"
    PRIVATE = "private"
    GROUP = "group"
    SUPERGROUP = "supergroup"
    CHANNEL = "channel"

    @classmethod
    def from_aiogram(cls, aiogram_type: Any) -> Optional["ChatType"]:
        if isinstance(aiogram_type, ChatType):
            return aiogram_type
        mapping = {
            "private": cls.PRIVATE,
            "group": cls.GROUP,
            "supergroup": cls.SUPERGROUP,
            "channel": cls.CHANNEL,
            "sender": cls.SENDER,
        }
        if hasattr(aiogram_type, "value"):
            aiogram_type = aiogram_type.value
        return mapping.get(aiogram_type)

    @classmethod
    def from_string(cls, value: str) -> Optional["ChatType"]:
        mapping = {
            "private": cls.PRIVATE,
            "group": cls.GROUP,
            "supergroup": cls.SUPERGROUP,
            "channel": cls.CHANNEL,
            "sender": cls.SENDER,
        }
        return mapping.get(value.lower() if value else "")

    @classmethod
    def from_telethon(cls, telethon_entity: Any) -> Optional["ChatType"]:
        try:
            if hasattr(telethon_entity, "megagroup") and telethon_entity.megagroup:
                return cls.SUPERGROUP
            if hasattr(telethon_entity, "channel") and telethon_entity.channel:
                return cls.CHANNEL
            if hasattr(telethon_entity, "group") and telethon_entity.group:
                return cls.GROUP
            if hasattr(telethon_entity, "is_user") and telethon_entity.is_user:
                return cls.PRIVATE
        except Exception:
            pass
        return None


class ChatMemberStatus(StrEnum):
    """Статусы участников чата"""

    CREATOR = "creator"
    ADMINISTRATOR = "administrator"
    MEMBER = "member"
    RESTRICTED = "restricted"
    LEFT = "left"
    KICKED = "kicked"

    @classmethod
    def from_aiogram(cls, aiogram_status: Any) -> Optional["ChatMemberStatus"]:
        mapping = {
            "creator": cls.CREATOR,
            "administrator": cls.ADMINISTRATOR,
            "member": cls.MEMBER,
            "restricted": cls.RESTRICTED,
            "left": cls.LEFT,
            "kicked": cls.KICKED,
        }
        if hasattr(aiogram_status, "value"):
            aiogram_status = aiogram_status.value
        return mapping.get(aiogram_status)

    @classmethod
    def from_string(cls, value: str) -> Optional["ChatMemberStatus"]:
        mapping = {
            "creator": cls.CREATOR,
            "administrator": cls.ADMINISTRATOR,
            "member": cls.MEMBER,
            "restricted": cls.RESTRICTED,
            "left": cls.LEFT,
            "kicked": cls.KICKED,
        }
        return mapping.get(value.lower() if value else "")

    @classmethod
    def from_telethon(cls, participant: Any) -> Optional["ChatMemberStatus"]:
        try:
            if hasattr(participant, "is_creator") and participant.is_creator:
                return cls.CREATOR
            if hasattr(participant, "is_admin") and participant.is_admin:
                return cls.ADMINISTRATOR
            if hasattr(participant, "is_member") and not participant.is_member:
                return cls.LEFT
        except Exception:
            pass
        return cls.MEMBER


class MessageType(StrEnum):
    """Типы сообщений"""

    USER_REQUEST = "user_request"
    BOT_RESPONSE = "bot_response"
    BROADCAST_MESSAGE = "broadcast_message"
    COMMAND = "command"
    COMMAND_ADMIN = "command_admin"
    COMMAND_ACTION = "command_action"
    COMMAND_ACTION_INFO = "command_action_info"
    COMMAND_AUTH = "command_auth"
    COMMAND_AUTOMATION = "command_automation"
    REMINDER = "reminder"
    SYSTEM_ALERT = "system_alert"
    SYSTEM_STATUS = "system_status"


class MessageActionType(StrEnum):
    """Типы действий с сообщениями для очистки"""

    COMMAND_CLEANUP = "command_cleanup"
    COMMAND_ADMIN_CLEANUP = "admin_cleanup"
    COMMAND_ACTION_CLEANUP = "action_cleanup"
    COMMAND_AUTH_CLEANUP = "auth_cleanup"
    COMMAND_AUTOMATION_CLEANUP = "automation_cleanup"


class MessageSource(StrEnum):
    """Источники сообщений"""

    USER = "user"
    BOT = "bot"
    SYSTEM = "system"


class ErrorCategory(StrEnum):
    """Категории ошибок"""

    ARBITRARY = "arbitrary"
    PERIODIC_TASK = "periodic_task"
    TASK_EXECUTION = "task_execution"
    SYSTEM = "system"
    EXTERNAL = "external"


class ErrorSeverity(StrEnum):
    """Степень серьезности ошибки"""

    CRITICAL = "critical"
    ERROR = "error"
    WARNING = "warning"
    INFO = "info"


class ErrorStatus(StrEnum):
    """Статус ошибки"""

    NEW = "new"
    IN_PROGRESS = "in_progress"
    RESOLVED = "resolved"
    DISMISSED = "dismissed"
    REOPENED = "reopened"


# ============ ENUM КЛАССЫ (АВТОМАТИЗАЦИЯ) ============


class UserRequestAutomationStatus(StrEnum):
    """Статусы заявок на автоматизацию"""

    NEW = "new"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    CANCELLED = "cancelled"
    REJECTED = "rejected"


class UserRequestAutomationPriority(StrEnum):
    """Приоритеты заявок на автоматизацию"""

    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


# ============ MIXIN КЛАССЫ ============


class UserMixin:
    """Базовые поля пользователя"""

    FID: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=False)
    FUserName: Mapped[str] = mapped_column(String(64))
    FFirstName: Mapped[str | None] = mapped_column(String(128), nullable=True)
    FLastName: Mapped[str | None] = mapped_column(String(128), nullable=True)
    FFlagBot: Mapped[bool] = mapped_column(Boolean, default=False)


class ChatMemberMixin:
    """Базовые поля участника чата"""

    FStatus: Mapped[ChatMemberStatus] = mapped_column(
        SQLEnum(ChatMemberStatus, name="chatmemberstatus"), default=ChatMemberStatus.MEMBER
    )
    FFlagActive: Mapped[bool] = mapped_column(Boolean, default=True)


class TimestampMixin:
    """Mixin для добавления временных меток"""

    FCreatedAt: Mapped[datetime] = mapped_column(DateTime, default=datetime_now)
    FUpdatedAt: Mapped[datetime] = mapped_column(DateTime, default=datetime_now, onupdate=datetime_now)


class SoftDeleteMixin:
    """Mixin для мягкого удаления"""

    FIsDeleted: Mapped[bool] = mapped_column(Boolean, default=False)
    FDeletedAt: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    FDeletedBy: Mapped[int | None] = mapped_column(Integer, nullable=True)


class ActiveMixin:
    """Mixin для активности"""

    FIsActive: Mapped[bool] = mapped_column(Boolean, default=True)


# ============ ЭКСПОРТ ============

__all__ = [
    # Базовые
    "BaseModel",
    "datetime_now",
    # Mixin-ы
    "UserMixin",
    "ChatMemberMixin",
    "TimestampMixin",
    "SoftDeleteMixin",
    "ActiveMixin",
    # Enum-ы - базовые
    "ChatType",
    "ChatMemberStatus",
    "MessageType",
    "MessageActionType",
    "MessageSource",
    # Enum-ы - ошибки
    "ErrorCategory",
    "ErrorSeverity",
    "ErrorStatus",
    # Enum-ы - автоматизация
    "UserRequestAutomationStatus",
    "UserRequestAutomationPriority",
]
