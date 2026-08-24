"""
Базовые модели и вспомогательные классы для работы с базой данных.

Назначение:
    Предоставляет базовые классы, enum'ы и mixin'ы для всех моделей SQLAlchemy.
    Содержит общие типы данных, используемые во всём приложении.

Основные разделы:
    1. Вспомогательные функции (datetime_now)
    2. Базовая модель SQLAlchemy
    3. Enum классы (типы чатов, статусы, категории ошибок и т.д.)
    4. Mixin классы для переиспользования полей

Технические особенности:
    - Использование SQLAlchemy 2.0 с аннотациями типов (Mapped)
    - Enum'ы наследуются от StrEnum для удобной работы со строками
    - Поддержка конвертации между Aiogram и Telethon типами
    - Временные метки с часовым поясом UTC

Архитектура:
    - Единый источник базовых моделей и enum'ов
    - Mixin'ы для композиции общих полей
"""

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

# ============================================================
# 1. ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ
# ============================================================


def datetime_now() -> datetime:
    """
    Возвращает текущее время без часового пояса.

    Использует UTC время и удаляет информацию о часовом поясе
    для совместимости с SQLAlchemy DateTime (без timezone).

    Returns:
        datetime: Текущее время в UTC без часового пояса
    """
    return datetime.now(UTC).replace(tzinfo=None)


# ============================================================
# 2. БАЗОВАЯ МОДЕЛЬ SQLALCHEMY
# ============================================================


class BaseModel(DeclarativeBase):
    """
    Базовая модель SQLAlchemy для всех моделей приложения.

    От неё наследуются все модели данных в приложении.
    """

    pass


# ============================================================
# 3. ENUM КЛАССЫ
# ============================================================

# ============================================================
# 3.1. ЧАТЫ И УЧАСТНИКИ
# ============================================================


class ChatType(StrEnum):
    """
    Типы чатов Telegram.

    Поддерживает конвертацию из типов Aiogram и Telethon.
    """

    SENDER = "sender"
    PRIVATE = "private"
    GROUP = "group"
    SUPERGROUP = "supergroup"
    CHANNEL = "channel"

    @classmethod
    def from_aiogram(cls, aiogram_type: Any) -> Optional["ChatType"]:
        """
        Конвертация типа чата из Aiogram.

        Args:
            aiogram_type: Тип чата из Aiogram

        Returns:
            Optional[ChatType]: Тип чата или None
        """
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
        """
        Конвертация из строки.

        Args:
            value: Строковое значение

        Returns:
            Optional[ChatType]: Тип чата или None
        """
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
        """
        Конвертация типа чата из Telethon.

        Args:
            telethon_entity: Сущность чата из Telethon

        Returns:
            Optional[ChatType]: Тип чата или None
        """
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
    """
    Статусы участников чата.

    Поддерживает конвертацию из статусов Aiogram и Telethon.
    """

    CREATOR = "creator"
    ADMINISTRATOR = "administrator"
    MEMBER = "member"
    RESTRICTED = "restricted"
    LEFT = "left"
    KICKED = "kicked"

    @classmethod
    def from_aiogram(cls, aiogram_status: Any) -> Optional["ChatMemberStatus"]:
        """
        Конвертация статуса участника из Aiogram.

        Args:
            aiogram_status: Статус из Aiogram

        Returns:
            Optional[ChatMemberStatus]: Статус или None
        """
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
        """
        Конвертация из строки.

        Args:
            value: Строковое значение

        Returns:
            Optional[ChatMemberStatus]: Статус или None
        """
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
        """
        Конвертация статуса участника из Telethon.

        Args:
            participant: Участник из Telethon

        Returns:
            Optional[ChatMemberStatus]: Статус или None
        """
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


# ============================================================
# 3.2. СООБЩЕНИЯ
# ============================================================


class MessageType(StrEnum):
    """Типы сообщений в системе."""

    USER_REQUEST = "user_request"  # Запрос от пользователя
    BOT_RESPONSE = "bot_response"  # Ответ бота
    BROADCAST_MESSAGE = "broadcast_message"  # Массовая рассылка
    COMMAND = "command"  # Обычная команда
    COMMAND_ADMIN = "command_admin"  # Административная команда
    COMMAND_ACTION = "command_action"  # Команда действия
    COMMAND_ACTION_INFO = "command_action_info"  # Информационная команда
    COMMAND_AUTH = "command_auth"  # Команда авторизации
    COMMAND_AUTOMATION = "command_automation"  # Команда автоматизации
    REMINDER = "reminder"  # Напоминание
    SYSTEM_ALERT = "system_alert"  # Системное оповещение
    SYSTEM_STATUS = "system_status"  # Статус системы


class MessageActionType(StrEnum):
    """Типы действий с сообщениями для очистки."""

    COMMAND_CLEANUP = "command_cleanup"
    COMMAND_ADMIN_CLEANUP = "admin_cleanup"
    COMMAND_ACTION_CLEANUP = "action_cleanup"
    COMMAND_AUTH_CLEANUP = "auth_cleanup"
    COMMAND_AUTOMATION_CLEANUP = "automation_cleanup"


class MessageSource(StrEnum):
    """Источники сообщений."""

    USER = "user"  # От пользователя
    BOT = "bot"  # От бота
    SYSTEM = "system"  # Системное


# ============================================================
# 3.3. ОШИБКИ
# ============================================================


class ErrorCategory(StrEnum):
    """Категории ошибок для классификации."""

    ARBITRARY = "arbitrary"  # Произвольная
    PERIODIC_TASK = "periodic_task"  # Периодическая задача
    TASK_EXECUTION = "task_execution"  # Выполнение задачи
    SYSTEM = "system"  # Системная
    EXTERNAL = "external"  # Внешняя


class ErrorSeverity(StrEnum):
    """Степень серьёзности ошибки."""

    CRITICAL = "critical"  # Критическая
    ERROR = "error"  # Ошибка
    WARNING = "warning"  # Предупреждение
    INFO = "info"  # Информационная


class ErrorStatus(StrEnum):
    """Статус ошибки в системе."""

    NEW = "new"  # Новая
    IN_PROGRESS = "in_progress"  # В работе
    RESOLVED = "resolved"  # Решена
    DISMISSED = "dismissed"  # Отклонена
    REOPENED = "reopened"  # Переоткрыта


# ============================================================
# 3.4. АВТОМАТИЗАЦИЯ
# ============================================================


class UserRequestAutomationStatus(StrEnum):
    """Статусы заявок на автоматизацию."""

    NEW = "new"  # Новая
    IN_PROGRESS = "in_progress"  # В работе
    COMPLETED = "completed"  # Выполнена
    CANCELLED = "cancelled"  # Отменена
    REJECTED = "rejected"  # Отклонена


class UserRequestAutomationPriority(StrEnum):
    """Приоритеты заявок на автоматизацию."""

    LOW = "low"  # Низкий
    MEDIUM = "medium"  # Средний
    HIGH = "high"  # Высокий
    CRITICAL = "critical"  # Критический


# ============================================================
# 4. MIXIN КЛАССЫ
# ============================================================


class UserMixin:
    """
    Базовые поля пользователя.

    Используется в моделях пользователей для унификации полей.
    """

    FID: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=False)
    FUserName: Mapped[str] = mapped_column(String(64))
    FFirstName: Mapped[str | None] = mapped_column(String(128), nullable=True)
    FLastName: Mapped[str | None] = mapped_column(String(128), nullable=True)
    FFlagBot: Mapped[bool] = mapped_column(Boolean, default=False)


class ChatMemberMixin:
    """
    Базовые поля участника чата.

    Используется в моделях участников чатов.
    """

    FStatus: Mapped[ChatMemberStatus] = mapped_column(
        SQLEnum(ChatMemberStatus, name="chatmemberstatus"), default=ChatMemberStatus.MEMBER
    )
    FFlagActive: Mapped[bool] = mapped_column(Boolean, default=True)


class TimestampMixin:
    """
    Mixin для добавления временных меток.

    Добавляет поля:
    - FCreatedAt: время создания
    - FUpdatedAt: время последнего обновления (автообновление)
    """

    FCreatedAt: Mapped[datetime] = mapped_column(DateTime, default=datetime_now)
    FUpdatedAt: Mapped[datetime] = mapped_column(DateTime, default=datetime_now, onupdate=datetime_now)


class SoftDeleteMixin:
    """
    Mixin для мягкого удаления.

    Добавляет поля:
    - FIsDeleted: флаг удаления
    - FDeletedAt: время удаления
    - FDeletedBy: ID пользователя, удалившего запись
    """

    FIsDeleted: Mapped[bool] = mapped_column(Boolean, default=False)
    FDeletedAt: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    FDeletedBy: Mapped[int | None] = mapped_column(Integer, nullable=True)


class ActiveMixin:
    """
    Mixin для активности.

    Добавляет поле FIsActive для отметки активности записи.
    """

    FIsActive: Mapped[bool] = mapped_column(Boolean, default=True)


# ============================================================
# 5. ЭКСПОРТ
# ============================================================

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
