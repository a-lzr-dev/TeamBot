# app/dtos/error.py
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from app.models import ChatMessageModel, ErrorModel


@dataclass
class ErrorMessageDTO:
    """DTO для сообщений, связанных с ошибками"""

    id: int
    chat_id: int
    user_id: int | None
    text: str | None
    is_deleted: bool
    deleted_at: datetime | None
    deleted_by_type: str | None

    @classmethod
    def from_model(cls, message: "ChatMessageModel") -> "ErrorMessageDTO":
        """Создание DTO из модели"""
        return cls(
            id=message.FID,
            chat_id=message.FK_Chat,
            user_id=message.FK_User,
            text=message.FText,
            is_deleted=message.FFlagDeleted,
            deleted_at=message.FDateDeleted,
            deleted_by_type=message.FDeletedByType,
        )


@dataclass
class ErrorDeleteResult:
    """Результат удаления сообщений ошибки"""

    success: bool
    error_id: int
    messages_found: int = 0
    messages_deleted_db: int = 0
    messages_deleted_telegram: int = 0
    links_deleted: int = 0
    errors: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        """Преобразование в словарь"""
        return {
            "success": self.success,
            "error_id": self.error_id,
            "messages_found": self.messages_found,
            "messages_deleted_db": self.messages_deleted_db,
            "messages_deleted_telegram": self.messages_deleted_telegram,
            "links_deleted": self.links_deleted,
            "errors": self.errors or [],
        }


@dataclass
class ErrorDTO:
    """DTO для ошибки"""

    id: int
    error_code: str
    error_message: str
    error_details: str | None
    source_system: str
    source_module: str | None
    category: str
    severity: str
    status: str
    user_id: int | None
    user_login: str | None
    count_occurrences: int
    first_occurrence: str | None
    last_occurrence: str | None
    resolved_by: int | None
    resolved_at: str | None
    resolved_note: str | None
    group_hash: str | None
    created_at: str | None
    updated_at: str | None

    @classmethod
    def from_model(cls, error: ErrorModel) -> "ErrorDTO":
        """Создание DTO из модели"""
        return cls(
            id=error.FID,
            error_code=error.FErrorCode,
            error_message=error.FErrorMessage,
            error_details=error.FErrorDetails,
            source_system=error.FSourceSystem,
            source_module=error.FSourceModule,
            category=error.FCategory.value if error.FCategory else "unknown",
            severity=error.FSeverity.value if error.FSeverity else "error",
            status=error.FStatus.value if error.FStatus else "new",
            user_id=error.FUserID,
            user_login=error.FUserLogin,
            count_occurrences=error.FCountOccurrences,
            first_occurrence=error.FFirstOccurrence.isoformat() + "Z" if error.FFirstOccurrence else None,
            last_occurrence=error.FLastOccurrence.isoformat() + "Z" if error.FLastOccurrence else None,
            resolved_by=error.FResolvedBy,
            resolved_at=error.FResolvedAt.isoformat() + "Z" if error.FResolvedAt else None,
            resolved_note=error.FResolvedNote,
            group_hash=error.FGroupHash,
            created_at=error.FCreatedAt.isoformat() + "Z" if error.FCreatedAt else None,
            updated_at=error.FUpdatedAt.isoformat() + "Z" if error.FUpdatedAt else None,
        )

    def to_dict(self) -> dict[str, Any]:
        """Преобразование в словарь"""
        return {
            "id": self.id,
            "error_code": self.error_code,
            "error_message": self.error_message,
            "error_details": self.error_details,
            "source_system": self.source_system,
            "source_module": self.source_module,
            "category": self.category,
            "severity": self.severity,
            "status": self.status,
            "user_id": self.user_id,
            "user_login": self.user_login,
            "count_occurrences": self.count_occurrences,
            "first_occurrence": self.first_occurrence,
            "last_occurrence": self.last_occurrence,
            "resolved_by": self.resolved_by,
            "resolved_at": self.resolved_at,
            "resolved_note": self.resolved_note,
            "group_hash": self.group_hash,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }


@dataclass
class CreateErrorDTO:
    """DTO для создания ошибки"""

    error_code: str
    error_message: str
    source_system: str
    source_module: str | None = None
    category: str = "external"
    severity: str = "error"
    user_id: int | None = None
    user_login: str | None = None
    details: str | None = None
    group_hash: str | None = None
    chat_ids: list[int] | None = None
    send_to_telegram: bool = True


@dataclass
class ErrorNotificationDTO:
    """DTO для уведомления об ошибке"""

    id: int
    error_code: str
    error_message: str
    source_system: str
    source_module: str | None
    severity: str
    status: str
    user_id: int | None
    user_login: str | None
    count_occurrences: int
    last_occurrence: str

    @classmethod
    def from_model(cls, error: ErrorModel) -> "ErrorNotificationDTO":
        """Создание DTO из модели"""
        return cls(
            id=error.FID,
            error_code=error.FErrorCode,
            error_message=error.FErrorMessage,
            source_system=error.FSourceSystem,
            source_module=error.FSourceModule,
            severity=error.FSeverity.value if error.FSeverity else "error",
            status=error.FStatus.value if error.FStatus else "new",
            user_id=error.FUserID,
            user_login=error.FUserLogin,
            count_occurrences=error.FCountOccurrences,
            last_occurrence=error.FLastOccurrence.isoformat() + "Z"
            if error.FLastOccurrence
            else datetime.now().isoformat() + "Z",
        )

    def format_message(self) -> str:
        """Форматирование сообщения для отправки"""
        severity_emoji = {
            "critical": "🚨",
            "error": "❌",
            "warning": "⚠️",
            "info": "ℹ️",
        }.get(self.severity, "📌")

        status_emoji = {
            "new": "🆕",
            "in_progress": "🔄",
            "resolved": "✅",
            "dismissed": "⏭️",
            "reopened": "🔁",
        }.get(self.status, "❌")

        message = f"{severity_emoji} **Ошибка в логах приложения**\n\n"
        message += f"{status_emoji} **ID:** #{self.id}\n"
        message += f"📊 **Уровень:** <code>{self.severity.upper()}</code>\n"
        message += f"🔑 **Код:** <code>{self.error_code}</code>\n\n"
        message += f"📝 **Сообщение:**\n<pre>{self.error_message[:300]}</pre>\n"
        message += f"🖥️ **Система:** {self.source_system}\n"

        if self.source_module:
            message += f"📦 **Модуль:** {self.source_module}\n"

        if self.user_id:
            message += f"👤 **User ID:** {self.user_id}\n"

        if self.count_occurrences > 1:
            message += f"🔄 **Повторов:** {self.count_occurrences}\n"

        message += f"\n📅 **Время:** {self.last_occurrence}\n\n"
        message += f"🔗 Используйте <code>/resolve_{self.id}</code> для отметки как решенное"

        return message
