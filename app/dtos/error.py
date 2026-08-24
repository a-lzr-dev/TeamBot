"""
DTO (Data Transfer Objects) для работы с ошибками.

Назначение:
    Предоставляет набор объектов для передачи данных об ошибках между слоями приложения.
    Инкапсулирует структуру данных ошибок для различных сценариев использования:
    - Создание ошибок
    - Отображение ошибок
    - Уведомления об ошибках
    - Удаление сообщений ошибок

Основные функции:
    1. ErrorDTO - полный DTO ошибки для отображения и API
    2. CreateErrorDTO - DTO для создания новой ошибки
    3. ErrorNotificationDTO - DTO для отправки уведомлений в Telegram
    4. ErrorMessageDTO - DTO для сообщений, связанных с ошибками
    5. ErrorDeleteResult - DTO для результата удаления сообщений ошибки

Технические особенности:
    - Все DTO реализованы как dataclass для удобства создания и сравнения
    - Поддержка преобразования из моделей (from_model)
    - Поддержка преобразования в словарь (to_dict) для JSON сериализации
    - Встроенное форматирование сообщений для уведомлений (format_message)

Архитектура:
    - Используются в error_service для передачи данных
    - Используются в API роутерах для ответов клиентам
    - Используются в log_handler_service для уведомлений
"""

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from app.models import ChatMessageModel, ErrorModel


@dataclass
class ErrorMessageDTO:
    """DTO для сообщений, связанных с ошибками.

    Используется для передачи данных о сообщениях, привязанных к ошибке.

    Attributes:
        id (int): ID сообщения
        chat_id (int): ID чата
        user_id (int | None): ID пользователя (отправителя)
        text (str | None): Текст сообщения
        is_deleted (bool): Флаг удаления
        deleted_at (datetime | None): Дата удаления
        deleted_by_type (str | None): Тип удаления (system, admin, user, expired)
    """

    id: int
    chat_id: int
    user_id: int | None
    text: str | None
    is_deleted: bool
    deleted_at: datetime | None
    deleted_by_type: str | None

    @classmethod
    def from_model(cls, message: "ChatMessageModel") -> "ErrorMessageDTO":
        """Создание DTO из модели ChatMessageModel.

        Args:
            message (ChatMessageModel): Модель сообщения

        Returns:
            ErrorMessageDTO: Объект DTO с данными сообщения
        """
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
    """Результат удаления сообщений ошибки.

    Используется для возврата статистики удаления сообщений, связанных с ошибкой.

    Attributes:
        success (bool): Успешность операции
        error_id (int): ID ошибки
        messages_found (int): Количество найденных сообщений
        messages_deleted_db (int): Количество удалённых в БД
        messages_deleted_telegram (int): Количество удалённых из Telegram
        links_deleted (int): Количество удалённых связей
        errors (list[str]): Список ошибок при удалении
    """

    success: bool
    error_id: int
    messages_found: int = 0
    messages_deleted_db: int = 0
    messages_deleted_telegram: int = 0
    links_deleted: int = 0
    errors: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        """Преобразование в словарь для JSON сериализации.

        Returns:
            dict[str, Any]: Словарь с данными результата
        """
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
    """Полный DTO для ошибки.

    Используется для отображения ошибки в API и пользовательском интерфейсе.
    Содержит все поля модели ErrorModel в удобном для сериализации формате.

    Attributes:
        id (int): ID ошибки
        error_code (str): Код ошибки
        error_message (str): Сообщение об ошибке
        error_details (str | None): Детали ошибки
        source_system (str): Система-источник
        source_module (str | None): Модуль-источник
        category (str): Категория ошибки
        severity (str): Серьёзность ошибки
        status (str): Статус ошибки
        user_id (int | None): ID пользователя
        user_login (str | None): Логин пользователя
        count_occurrences (int): Количество повторений
        first_occurrence (str | None): Первое появление (ISO)
        last_occurrence (str | None): Последнее появление (ISO)
        resolved_by (int | None): Кто решил ошибку
        resolved_at (str | None): Дата решения (ISO)
        resolved_note (str | None): Примечание к решению
        group_hash (str | None): Хеш для группировки
        created_at (str | None): Дата создания (ISO)
        updated_at (str | None): Дата обновления (ISO)
    """

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
        """Создание DTO из модели ErrorModel.

        Args:
            error (ErrorModel): Модель ошибки

        Returns:
            ErrorDTO: Объект DTO с данными ошибки
        """
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
        """Преобразование в словарь для JSON сериализации.

        Returns:
            dict[str, Any]: Словарь с данными ошибки
        """
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
    """DTO для создания новой ошибки.

    Используется в error_service для создания ошибки из внешнего источника.

    Attributes:
        error_code (str): Код ошибки
        error_message (str): Сообщение об ошибке
        source_system (str): Система-источник
        source_module (str | None): Модуль-источник (опционально)
        category (str): Категория ошибки (по умолчанию "external")
        severity (str): Серьёзность ошибки (по умолчанию "error")
        user_id (int | None): ID пользователя (опционально)
        user_login (str | None): Логин пользователя (опционально)
        details (str | None): Детали ошибки (опционально)
        group_hash (str | None): Хеш для группировки (опционально)
        chat_ids (list[int] | None): ID чатов для уведомлений
        send_to_telegram (bool): Отправлять ли уведомление в Telegram
    """

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
    """DTO для уведомления об ошибке в Telegram.

    Содержит минимальный набор данных, необходимых для отправки
    уведомления в чат техподдержки. Включает метод форматирования
    сообщения в HTML для отправки через Bot API.

    Attributes:
        id (int): ID ошибки
        error_code (str): Код ошибки
        error_message (str): Сообщение об ошибке
        source_system (str): Система-источник
        source_module (str | None): Модуль-источник
        severity (str): Серьёзность ошибки
        status (str): Статус ошибки
        user_id (int | None): ID пользователя
        user_login (str | None): Логин пользователя
        count_occurrences (int): Количество повторений
        last_occurrence (str): Время последнего появления (ISO)
    """

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
        """Создание DTO из модели ErrorModel.

        Args:
            error (ErrorModel): Модель ошибки

        Returns:
            ErrorNotificationDTO: Объект DTO для уведомления
        """
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
        """Форматирование сообщения для отправки в Telegram.

        Создаёт HTML-сообщение с эмодзи, выделением важной информации
        и ссылкой для быстрого решения ошибки.

        Returns:
            str: Отформатированное сообщение в HTML
        """
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
