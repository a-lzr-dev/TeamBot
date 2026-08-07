from datetime import UTC, datetime
from enum import StrEnum
from typing import Any, Optional

from aiogram import enums
from sqlalchemy import (
    BigInteger,
    Boolean,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Integer,
    PrimaryKeyConstraint,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy import Enum as SQLEnum
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship

# ============ ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ ============


def datetime_now() -> datetime:
    """Возвращает текущее время без часового пояса"""
    return datetime.now(UTC).replace(tzinfo=None)


# ============ СУЩЕСТВУЮЩИЕ ENUM ============


class ChatType(StrEnum):
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
    USER_REQUEST = "user_request"  # Запросы от пользователей
    BOT_RESPONSE = "bot_response"  # Ответы бота на запросы
    BROADCAST_MESSAGE = "broadcast_message"  # Рассылки
    COMMAND = "command"  # Команды
    COMMAND_ADMIN = "command_admin"  # Комманды администрирования
    COMMAND_ACTION = "command_action"  # Комманды действия и группы
    COMMAND_ACTION_INFO = "command_action_info"  # Вспомогательные сообщения к действиям и группам
    COMMAND_AUTH = "command_auth"  # Комманды авторизации
    COMMAND_AUTOMATION = "command_automation"  # Комманды автоматизации
    REMINDER = "reminder"  # Напоминания
    SYSTEM_ALERT = "system_alert"  # Системные предупреждения
    SYSTEM_STATUS = "system_status"  # Системные статусы


class MessageActionType(StrEnum):
    COMMAND_CLEANUP = "command_cleanup"  # Очистка предыдущих сообщений комманд
    COMMAND_ADMIN_CLEANUP = "admin_cleanup"  # Очистка предыдущих админ-сообщений
    COMMAND_ACTION_CLEANUP = "action_cleanup"  # Очистка предыдущих сообщений действий и групп
    COMMAND_AUTH_CLEANUP = "auth_cleanup"  # Очистка предыдущих сообщений авторизации
    COMMAND_AUTOMATION_CLEANUP = "automation_cleanup"  # Очистка предыдущих сообщений автоматизации


class MessageSource(StrEnum):
    USER = "user"
    BOT = "bot"
    SYSTEM = "system"


# ============ НОВЫЕ ENUM ============


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


# ============ MIXIN КЛАССЫ ============


class UserMixin:
    FID: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=False)
    FUserName: Mapped[str] = mapped_column(String(64))
    FFirstName: Mapped[str | None] = mapped_column(String(128), nullable=True)
    FLastName: Mapped[str | None] = mapped_column(String(128), nullable=True)
    FFlagBot: Mapped[bool] = mapped_column(Boolean, default=False)


class ChatMemberMixin:
    FStatus: Mapped[ChatMemberStatus] = mapped_column(
        SQLEnum(ChatMemberStatus, name="chatmemberstatus"), default=ChatMemberStatus.MEMBER
    )
    FFlagActive: Mapped[bool] = mapped_column(Boolean, default=True)


# ============ БАЗОВАЯ МОДЕЛЬ ============


class BaseModel(DeclarativeBase):
    pass


# ============ ОСНОВНЫЕ МОДЕЛИ ============


class UserModel(BaseModel, UserMixin):
    """Пользователь"""

    __tablename__ = "TUsers"
    __table_args__ = (
        PrimaryKeyConstraint("FID", name="PK_Users"),
        UniqueConstraint("FUserName", name="UK_Users_FUserName"),
        UniqueConstraint("FPhone", name="UK_Users_FPhone"),
        Index("IX_Users_FK_Avanpost", "FK_Avanpost"),
        Index("IX_Users_FK_AvanpostGroup", "FK_AvanpostGroup"),
    )

    FK_Chat: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    FK_Language: Mapped[str | None] = mapped_column(String(2), nullable=True)
    FK_Avanpost: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    FK_AvanpostGroup: Mapped[int | None] = mapped_column(Integer, nullable=True)
    FPhone: Mapped[str | None] = mapped_column(String(20), nullable=True)  # Номер телефона
    FDateCreated: Mapped[datetime] = mapped_column(DateTime, default=datetime_now)
    FDateUpdated: Mapped[datetime] = mapped_column(DateTime, default=datetime_now, onupdate=datetime_now)
    FDateLastActivity: Mapped[datetime] = mapped_column(DateTime, default=datetime_now)

    ChatsMembers: Mapped[list["ChatMemberModel"]] = relationship(
        "ChatMemberModel", back_populates="user", cascade="all, delete-orphan"
    )

    UserMessages: Mapped[list["ChatMessageModel"]] = relationship(
        "ChatMessageModel", back_populates="user", foreign_keys="ChatMessageModel.FK_User"
    )

    # Связь с решенными ошибками
    ResolvedErrors: Mapped[list["ErrorModel"]] = relationship(
        "ErrorModel", foreign_keys="ErrorModel.FK_ResolvedBy", back_populates="resolved_by_user"
    )

    def __str__(self) -> str:
        return self.fullname

    def __repr__(self) -> str:
        return f"<User(id={self.FID}, username={self.FUserName}, fullname={self.fullname}, phone={self.FPhone})>"

    @property
    def fullname(self) -> str:
        if self.FFirstName and self.FLastName:
            return f"{self.FFirstName} {self.FLastName}"
        if self.FFirstName:
            return self.FFirstName  # type: ignore[no-any-return]
        if self.FLastName:
            return self.FLastName  # type: ignore[no-any-return]
        return self.FUserName  # type: ignore[no-any-return]

    @property
    def is_authenticated(self) -> bool:
        """Проверка, авторизован ли пользователь"""
        return self.FK_Avanpost is not None

    @property
    def display_name(self) -> str:
        """Отображаемое имя"""
        if self.fullname and self.fullname != self.FUserName:
            return f"{self.fullname} (@{self.FUserName})"
        return f"@{self.FUserName}"


class ChatModel(BaseModel):
    """Чат Telegram"""

    __tablename__ = "TChats"
    __table_args__ = (PrimaryKeyConstraint("FID", name="PK_Chats"),)

    FID: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=False)
    FType: Mapped[ChatType] = mapped_column(SQLEnum(ChatType, name="chattype"), nullable=False)
    FTitle: Mapped[str | None] = mapped_column(String(256), nullable=True)

    FFlagActive: Mapped[bool] = mapped_column(Boolean, default=True)
    FDateRestrictedUntil: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    FDateSynced: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    FDateCreated: Mapped[datetime] = mapped_column(DateTime, default=datetime_now)
    FDateUpdated: Mapped[datetime] = mapped_column(DateTime, default=datetime_now, onupdate=datetime_now)

    FCountMessages: Mapped[int] = mapped_column(Integer, default=0)
    FCountMembers: Mapped[int] = mapped_column(Integer, default=0)

    ChatsMembers: Mapped[list["ChatMemberModel"]] = relationship(
        "ChatMemberModel", back_populates="chat", cascade="all, delete-orphan"
    )

    ChatMessages: Mapped[list["ChatMessageModel"]] = relationship(
        "ChatMessageModel", back_populates="chat", cascade="all, delete-orphan"
    )

    # Связь с настройками уведомлений
    ChatsNotificationsSettings: Mapped[Optional["ChatNotificationSettingsModel"]] = relationship(
        "ChatNotificationSettingsModel", back_populates="chat", uselist=False, cascade="all, delete-orphan"
    )

    # Связь с фильтрами ошибок
    ErrorsFilters: Mapped[list["ErrorFilterModel"]] = relationship(
        "ErrorFilterModel", back_populates="chat", cascade="all, delete-orphan"
    )

    # Связь с напоминаниями
    Reminders: Mapped[list["ReminderModel"]] = relationship(
        "ReminderModel", back_populates="chat", foreign_keys="ReminderModel.FK_Chat"
    )

    def __repr__(self) -> str:
        return f"<Chat(id={self.FID}, type={self.FType}, title={self.FTitle})>"


class UserChatMemberModel(BaseModel, UserMixin, ChatMemberMixin):
    """Пользователь и участник чата (абстрактный)"""

    __abstract__ = True

    @classmethod
    def from_row(cls, row: Any) -> "UserChatMemberModel":
        member = cls()
        member.FID = row.FID
        member.FUserName = row.FUserName
        member.FFirstName = row.FFirstName
        member.FLastName = row.FLastName
        member.FFlagBot = row.FFlagBot
        member.FStatus = row.FStatus
        return member


class ChatMemberModel(BaseModel, ChatMemberMixin):
    """Участник чата"""

    __tablename__ = "TChatsMembers"
    __table_args__ = (
        ForeignKeyConstraint(["FK_Chat"], ["TChats.FID"], ondelete="CASCADE", name="FK_ChatsMembers_Chat"),
        ForeignKeyConstraint(["FK_User"], ["TUsers.FID"], ondelete="CASCADE", name="FK_ChatsMembers_User"),
        PrimaryKeyConstraint("FID", name="PK_ChatsMembers"),
    )

    FID: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    FK_Chat: Mapped[int] = mapped_column(BigInteger, nullable=False)
    FK_User: Mapped[int] = mapped_column(BigInteger, nullable=False)
    FDateJoined: Mapped[datetime] = mapped_column(DateTime, default=datetime_now)
    FDateUpdated: Mapped[datetime] = mapped_column(DateTime, default=datetime_now, onupdate=datetime_now)
    FDateRestrictedUntil: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    user: Mapped["UserModel"] = relationship("UserModel", back_populates="ChatsMembers")
    chat: Mapped["ChatModel"] = relationship("ChatModel", back_populates="ChatsMembers")

    ChatMemberMessages: Mapped[list["ChatMessageModel"]] = relationship(
        "ChatMessageModel", back_populates="chat_member", foreign_keys="ChatMessageModel.FK_ChatMember"
    )

    def __repr__(self) -> str:
        return f"<ChatMember(user_id={self.FK_User}, chat_id={self.FK_Chat}, status={self.FStatus})>"


class ChatMessageModel(BaseModel):
    """Сообщение в чате Telegram"""

    __tablename__ = "TChatsMessages"
    __table_args__ = (
        ForeignKeyConstraint(["FK_Chat"], ["TChats.FID"], ondelete="CASCADE", name="FK_ChatsMessages_Chat"),
        ForeignKeyConstraint(
            ["FK_ChatMember"], ["TChatsMembers.FID"], ondelete="SET NULL", name="FK_ChatsMessages_ChatMember"
        ),
        ForeignKeyConstraint(["FK_User"], ["TUsers.FID"], ondelete="SET NULL", name="FK_ChatsMessages_User"),
        ForeignKeyConstraint(
            ["FK_DeletedByMessage"], ["TChatsMessages.FID"], ondelete="SET NULL", name="FK_ChatsMessages_DeletedBy"
        ),
        PrimaryKeyConstraint("FID", name="PK_ChatsMessages"),
    )

    FID: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    FK_Chat: Mapped[int] = mapped_column(BigInteger, nullable=False)
    FK_User: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    FK_ChatMember: Mapped[int | None] = mapped_column(Integer, nullable=True)

    FK_MessageType: Mapped[MessageType] = mapped_column(SQLEnum(MessageType, name="messagetype"))

    FK_ReplyToMessage: Mapped[int | None] = mapped_column(BigInteger, nullable=True)

    FK_ContentType: Mapped[enums.ContentType] = mapped_column(
        SQLEnum(enums.ContentType, name="contenttype"), default=enums.ContentType.TEXT
    )

    FText: Mapped[str | None] = mapped_column(Text, nullable=True)
    FCaption: Mapped[str | None] = mapped_column(Text, nullable=True)

    FSource: Mapped[MessageSource] = mapped_column(
        SQLEnum(MessageSource, name="messagesource"), default=MessageSource.USER
    )

    FCommand: Mapped[str | None] = mapped_column(String(64), nullable=True)
    FCommandArgs: Mapped[str | None] = mapped_column(Text, nullable=True)

    FErrorMessage: Mapped[str | None] = mapped_column(Text, nullable=True)
    FErrorTraceback: Mapped[str | None] = mapped_column(Text, nullable=True)

    FCategory: Mapped[str | None] = mapped_column(String(32), nullable=True)
    FLifetimeSeconds: Mapped[int | None] = mapped_column(Integer, nullable=True)
    FExpiresAt: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    FDateSent: Mapped[datetime] = mapped_column(DateTime, default=datetime_now)
    FDateEdited: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    FDateDeleted: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    FFlagForwarded: Mapped[bool] = mapped_column(Boolean, default=False)
    FFlagReply: Mapped[bool] = mapped_column(Boolean, default=False)
    FFlagDeleted: Mapped[bool] = mapped_column(Boolean, default=False)

    FK_DeletedByMessage: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    FDeletedByType: Mapped[str | None] = mapped_column(String(32), nullable=True)

    FK_File: Mapped[str | None] = mapped_column(String(256), nullable=True)
    FK_FileUnique: Mapped[str | None] = mapped_column(String(256), nullable=True)
    FFileSize: Mapped[int | None] = mapped_column(Integer, nullable=True)
    FMimeType: Mapped[str | None] = mapped_column(String(64), nullable=True)

    chat: Mapped["ChatModel"] = relationship("ChatModel", back_populates="ChatMessages")
    user: Mapped[Optional["UserModel"]] = relationship("UserModel", back_populates="UserMessages")
    chat_member: Mapped[Optional["ChatMemberModel"]] = relationship(
        "ChatMemberModel", back_populates="ChatMemberMessages"
    )

    deleted_by_message: Mapped[Optional["ChatMessageModel"]] = relationship(
        "ChatMessageModel", remote_side=[FID], foreign_keys=[FK_DeletedByMessage], uselist=False
    )

    # Связь с ошибками через таблицу связей (N:M)
    error_links: Mapped[list["ErrorMessageLinkModel"]] = relationship(
        "ErrorMessageLinkModel",
        foreign_keys="ErrorMessageLinkModel.FK_Message",
        back_populates="message",
        cascade="all, delete-orphan",
    )

    def __repr__(self) -> str:
        status = "deleted" if self.FFlagDeleted else "active"
        deleted_by = f" by {self.FK_DeletedByMessage}" if self.FK_DeletedByMessage else ""
        return f"<ChatMessage(id={self.FID}, chat_id={self.FK_Chat}, type={self.FK_MessageType}, status={status}{deleted_by})>"

    @property
    def display_text(self) -> str:
        if self.FFlagDeleted:
            if self.FK_DeletedByMessage:
                return f"[DELETED by message {self.FK_DeletedByMessage}]"
            return "[DELETED MESSAGE]"
        if self.FText:
            return self.FText  # type: ignore[no-any-return]
        if self.FCaption:
            return self.FCaption  # type: ignore[no-any-return]
        return f"[{self.FK_MessageType.value}]"


# ============ НОВЫЕ МОДЕЛИ ============


class ErrorModel(BaseModel):
    """Внешняя ошибка из другой системы"""

    __tablename__ = "TErrors"
    __table_args__ = (
        PrimaryKeyConstraint("FID", name="PK_Errors"),
        Index("IX_Errors_ErrorCode", "FErrorCode"),
        Index("IX_Errors_Status", "FStatus"),
        Index("IX_Errors_CreatedAt", "FCreatedAt"),
        Index("IX_Errors_GroupHash", "FGroupHash"),
    )

    FID: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    FErrorCode: Mapped[str] = mapped_column(String(100), nullable=False)
    FErrorMessage: Mapped[str] = mapped_column(Text, nullable=False)
    FErrorDetails: Mapped[str | None] = mapped_column(Text, nullable=True)

    FSourceSystem: Mapped[str] = mapped_column(String(100), nullable=False)
    FSourceModule: Mapped[str | None] = mapped_column(String(100), nullable=True)

    FCategory: Mapped[ErrorCategory] = mapped_column(
        SQLEnum(ErrorCategory, name="errorcategory"), default=ErrorCategory.EXTERNAL
    )
    FSeverity: Mapped[ErrorSeverity] = mapped_column(
        SQLEnum(ErrorSeverity, name="errorseverity"), default=ErrorSeverity.ERROR
    )
    FStatus: Mapped[ErrorStatus] = mapped_column(SQLEnum(ErrorStatus, name="errorstatus"), default=ErrorStatus.NEW)

    FUserID: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    FUserLogin: Mapped[str | None] = mapped_column(String(100), nullable=True)

    FCountOccurrences: Mapped[int] = mapped_column(Integer, default=1)
    FFirstOccurrence: Mapped[datetime] = mapped_column(DateTime, default=datetime_now)
    FLastOccurrence: Mapped[datetime] = mapped_column(DateTime, default=datetime_now, onupdate=datetime_now)

    FResolvedBy: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    FResolvedAt: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    FResolvedNote: Mapped[str | None] = mapped_column(Text, nullable=True)

    FReopenedCount: Mapped[int] = mapped_column(Integer, default=0)
    FReopenedAt: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    FSilencedUntil: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    FIsSilenced: Mapped[bool] = mapped_column(Boolean, default=False)

    FNotifiedAt: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    FNotifiedUserIds: Mapped[str | None] = mapped_column(Text, nullable=True)

    FGroupHash: Mapped[str | None] = mapped_column(String(64), nullable=True)

    FCreatedAt: Mapped[datetime] = mapped_column(DateTime, default=datetime_now)
    FUpdatedAt: Mapped[datetime] = mapped_column(DateTime, default=datetime_now, onupdate=datetime_now)

    FK_ResolvedBy: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("TUsers.FID"), nullable=True)

    # Связи
    resolved_by_user: Mapped[Optional["UserModel"]] = relationship(
        "UserModel", foreign_keys=[FK_ResolvedBy], back_populates="ResolvedErrors"
    )

    # Связь с сообщениями через таблицу связей (N:M)
    error_links: Mapped[list["ErrorMessageLinkModel"]] = relationship(
        "ErrorMessageLinkModel",
        foreign_keys="ErrorMessageLinkModel.FK_Error",
        back_populates="error",
        cascade="all, delete-orphan",
    )


class ErrorMessageLinkModel(BaseModel):
    """Связь между ошибкой и сообщением (N:M)"""

    __tablename__ = "TErrorsMessagesLinks"
    __table_args__ = (
        PrimaryKeyConstraint("FID", name="PK_ErrorsMessagesLinks"),
        ForeignKeyConstraint(["FK_Error"], ["TErrors.FID"], ondelete="CASCADE", name="FK_ErrorsMessagesLinks_Error"),
        ForeignKeyConstraint(
            ["FK_Message"], ["TChatsMessages.FID"], ondelete="CASCADE", name="FK_ErrorsMessagesLinks_Message"
        ),
        Index("IX_ErrorsMessagesLinks_Error", "FK_Error"),
        Index("IX_ErrorsMessagesLinks_Message", "FK_Message"),
        UniqueConstraint("FK_Error", "FK_Message", name="UK_ErrorsMessagesLinks_Error_Message"),
    )

    FID: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    FK_Error: Mapped[int] = mapped_column(BigInteger, nullable=False)
    FK_Message: Mapped[int] = mapped_column(BigInteger, nullable=False)
    FDateCreated: Mapped[datetime] = mapped_column(DateTime, default=datetime_now)

    # Связи
    error: Mapped["ErrorModel"] = relationship("ErrorModel", foreign_keys=[FK_Error], back_populates="error_links")
    message: Mapped["ChatMessageModel"] = relationship(
        "ChatMessageModel", foreign_keys=[FK_Message], back_populates="error_links"
    )


class PeriodicTaskModel(BaseModel):
    """Модель для периодических задач и их уведомлений"""

    __tablename__ = "TPeriodicTasks"
    __table_args__ = (
        PrimaryKeyConstraint("FID", name="PK_PeriodicTasks"),
        Index("IX_PeriodicTasks_TaskName", "FTaskName"),
        Index("IX_PeriodicTasks_NextRun", "FNextRun"),
    )

    FID: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    FTaskName: Mapped[str] = mapped_column(String(200), nullable=False)
    FTaskDescription: Mapped[str | None] = mapped_column(Text, nullable=True)

    FCategory: Mapped[ErrorCategory] = mapped_column(
        SQLEnum(ErrorCategory, name="errorcategory"), default=ErrorCategory.PERIODIC_TASK
    )

    FSchedule: Mapped[str] = mapped_column(String(100), nullable=False)
    FIsActive: Mapped[bool] = mapped_column(Boolean, default=True)

    FLastRun: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    FNextRun: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    FLastSuccess: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    FLastError: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    FSuccessCount: Mapped[int] = mapped_column(Integer, default=0)
    FFailCount: Mapped[int] = mapped_column(Integer, default=0)
    FConsecutiveFailures: Mapped[int] = mapped_column(Integer, default=0)
    FMaxConsecutiveFailures: Mapped[int] = mapped_column(Integer, default=3)

    FExecutionTimeoutSeconds: Mapped[int] = mapped_column(Integer, default=300)
    FLastExecutionDuration: Mapped[int | None] = mapped_column(Integer, nullable=True)

    FErrorCount: Mapped[int] = mapped_column(Integer, default=0)
    FLastErrorText: Mapped[str | None] = mapped_column(Text, nullable=True)

    FNotifiedOnFailure: Mapped[bool] = mapped_column(Boolean, default=False)
    FNotifiedOnTimeout: Mapped[bool] = mapped_column(Boolean, default=False)

    FCreatedAt: Mapped[datetime] = mapped_column(DateTime, default=datetime_now)
    FUpdatedAt: Mapped[datetime] = mapped_column(DateTime, default=datetime_now, onupdate=datetime_now)


class ReminderModel(BaseModel):
    """Модель для напоминаний (дела, события)"""

    __tablename__ = "TReminders"
    __table_args__ = (
        PrimaryKeyConstraint("FID", name="PK_Reminders"),
        Index("IX_Reminders_UserID", "FK_User"),
        Index("IX_Reminders_RemindAt", "FRemindAt"),
        Index("IX_Reminders_IsCompleted", "FIsCompleted"),
        Index("IX_Reminders_GroupID", "FGroupID"),
        Index("IX_Reminders_CodeWord", "FCodeWord"),
    )

    FID: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    FK_User: Mapped[int] = mapped_column(BigInteger, ForeignKey("TUsers.FID"), nullable=False)

    FTitle: Mapped[str] = mapped_column(String(500), nullable=False)
    FDescription: Mapped[str | None] = mapped_column(Text, nullable=True)
    FCategory: Mapped[str | None] = mapped_column(String(100), nullable=True)

    FRemindAt: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    FRemindUntil: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    FRemindInterval: Mapped[int | None] = mapped_column(Integer, nullable=True)

    FLastReminded: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    FRemindCount: Mapped[int] = mapped_column(Integer, default=0)
    FMaxRemindCount: Mapped[int | None] = mapped_column(Integer, nullable=True)

    FIsCompleted: Mapped[bool] = mapped_column(Boolean, default=False)
    FIsSuccessful: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    FCompletedAt: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    FGroupID: Mapped[str | None] = mapped_column(String(64), nullable=True)
    FIsGroupReminder: Mapped[bool] = mapped_column(Boolean, default=False)

    FCodeWord: Mapped[str | None] = mapped_column(String(50), nullable=True)
    FIsEncrypted: Mapped[bool] = mapped_column(Boolean, default=False)
    FEncryptedData: Mapped[str | None] = mapped_column(Text, nullable=True)

    FNotificationType: Mapped[str] = mapped_column(String(20), default="private")
    FK_Chat: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("TChats.FID"), nullable=True)

    FIsActive: Mapped[bool] = mapped_column(Boolean, default=True)
    FIsDeleted: Mapped[bool] = mapped_column(Boolean, default=False)

    FCreatedAt: Mapped[datetime] = mapped_column(DateTime, default=datetime_now)
    FUpdatedAt: Mapped[datetime] = mapped_column(DateTime, default=datetime_now, onupdate=datetime_now)

    user: Mapped["UserModel"] = relationship("UserModel", foreign_keys=[FK_User])
    chat: Mapped[Optional["ChatModel"]] = relationship("ChatModel", foreign_keys=[FK_Chat], back_populates="Reminders")

    child_reminders: Mapped[list["ReminderModel"]] = relationship(
        "ReminderModel",
        remote_side=[FID],
        foreign_keys=[FGroupID],
        primaryjoin="ReminderModel.FID == ReminderModel.FGroupID",
        uselist=True,
    )


class ReminderShareModel(BaseModel):
    """Связь дела с пользователем (для общих дел)"""

    __tablename__ = "TRemindersShares"
    __table_args__ = (
        PrimaryKeyConstraint("FK_Reminder", "FK_User", name="PK_RemindersShares"),
        ForeignKeyConstraint(
            ["FK_Reminder"], ["TReminders.FID"], ondelete="CASCADE", name="FK_RemindersShares_Reminder"
        ),
        ForeignKeyConstraint(["FK_User"], ["TUsers.FID"], ondelete="CASCADE", name="FK_RemindersShares_User"),
        UniqueConstraint("FK_Reminder", "FK_User", name="UK_RemindersShares_Reminder_User"),
    )

    FK_Reminder: Mapped[int] = mapped_column(BigInteger, nullable=False)
    FK_User: Mapped[int] = mapped_column(BigInteger, nullable=False)

    FIsCompleted: Mapped[bool] = mapped_column(Boolean, default=False)
    FIsSuccessful: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    FCompletedAt: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    FCreatedAt: Mapped[datetime] = mapped_column(DateTime, default=datetime_now)
    FUpdatedAt: Mapped[datetime] = mapped_column(DateTime, default=datetime_now, onupdate=datetime_now)


class ErrorFilterModel(BaseModel):
    """Фильтр для ошибок (какие не показывать)"""

    __tablename__ = "TErrorsFilters"
    __table_args__ = (
        PrimaryKeyConstraint("FID", name="PK_ErrorFilters"),
        UniqueConstraint("FK_Chat", "FPattern", name="UK_ErrorsFilters_Chat_Pattern"),
        Index("IX_ErrorsFilters_Chat", "FK_Chat"),
        Index("IX_ErrorsFilters_Active", "FIsActive"),
    )

    FID: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    FK_Chat: Mapped[int] = mapped_column(BigInteger, ForeignKey("TChats.FID"), nullable=False)

    FPattern: Mapped[str] = mapped_column(String(200), nullable=False)
    FPatternType: Mapped[str] = mapped_column(String(20), default="contains")

    FCategory: Mapped[ErrorCategory | None] = mapped_column(SQLEnum(ErrorCategory, name="errorcategory"), nullable=True)
    FErrorCode: Mapped[str | None] = mapped_column(String(100), nullable=True)
    FSourceSystem: Mapped[str | None] = mapped_column(String(100), nullable=True)

    FIsActive: Mapped[bool] = mapped_column(Boolean, default=True)
    FIsRegex: Mapped[bool] = mapped_column(Boolean, default=False)

    FDescription: Mapped[str | None] = mapped_column(Text, nullable=True)

    FCreatedAt: Mapped[datetime] = mapped_column(DateTime, default=datetime_now)
    FUpdatedAt: Mapped[datetime] = mapped_column(DateTime, default=datetime_now, onupdate=datetime_now)

    chat: Mapped["ChatModel"] = relationship("ChatModel", back_populates="ErrorsFilters")


class ChatNotificationSettingsModel(BaseModel):
    """Настройки уведомлений для чата"""

    __tablename__ = "TChatsNotificationsSettings"
    __table_args__ = (
        PrimaryKeyConstraint("FK_Chat", name="PKChatsNotificationsSettings"),
        ForeignKeyConstraint(
            ["FK_Chat"], ["TChats.FID"], ondelete="CASCADE", name="FK_ChatsNotificationsSettings_Chat"
        ),
    )

    FK_Chat: Mapped[int] = mapped_column(BigInteger, primary_key=True)

    FSilenceStart: Mapped[str | None] = mapped_column(String(5), nullable=True)
    FSilenceEnd: Mapped[str | None] = mapped_column(String(5), nullable=True)
    FSilenceEnabled: Mapped[bool] = mapped_column(Boolean, default=False)

    FNotifyErrors: Mapped[bool] = mapped_column(Boolean, default=True)
    FNotifyPeriodicTasks: Mapped[bool] = mapped_column(Boolean, default=True)
    FNotifyTaskExecution: Mapped[bool] = mapped_column(Boolean, default=True)
    FNotifySystem: Mapped[bool] = mapped_column(Boolean, default=True)

    FNotifyUserOnError: Mapped[bool] = mapped_column(Boolean, default=True)
    FNotifyUserOnResolution: Mapped[bool] = mapped_column(Boolean, default=True)

    FNotificationLevel: Mapped[ErrorSeverity] = mapped_column(
        SQLEnum(ErrorSeverity, name="errorseverity"), default=ErrorSeverity.ERROR
    )

    FGroupingEnabled: Mapped[bool] = mapped_column(Boolean, default=True)
    FGroupingWindowMinutes: Mapped[int] = mapped_column(Integer, default=60)

    FEnableAutoReports: Mapped[bool] = mapped_column(Boolean, default=True)
    FAutoReportInterval: Mapped[int] = mapped_column(Integer, default=60)
    FAutoReportHourStart: Mapped[int] = mapped_column(Integer, default=9)
    FAutoReportHourEnd: Mapped[int] = mapped_column(Integer, default=18)

    FCreatedAt: Mapped[datetime] = mapped_column(DateTime, default=datetime_now)
    FUpdatedAt: Mapped[datetime] = mapped_column(DateTime, default=datetime_now, onupdate=datetime_now)

    chat: Mapped["ChatModel"] = relationship("ChatModel", back_populates="ChatsNotificationsSettings")


# ============ ЭКСПОРТ ============

__all__ = [
    # Базовые классы
    "BaseModel",
    "UserMixin",
    "ChatMemberMixin",
    # Enum классы
    "ChatType",
    "ChatMemberStatus",
    "MessageType",
    "MessageActionType",
    "MessageSource",
    "ErrorCategory",
    "ErrorSeverity",
    "ErrorStatus",
    # Основные модели
    "UserModel",
    "ChatModel",
    "ChatMemberModel",
    "UserChatMemberModel",
    "ChatMessageModel",
    "ChatNotificationSettingsModel",
    # Вспомогательные модели
    "ErrorModel",
    "ErrorMessageLinkModel",
    "ErrorFilterModel",
    "PeriodicTaskModel",
    "ReminderModel",
    "ReminderShareModel",
    # Вспомогательные функции
    "datetime_now",
]
