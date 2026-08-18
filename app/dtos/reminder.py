from dataclasses import dataclass
from datetime import datetime
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from ..models import UserReminderModel


@dataclass
class ReminderNotificationDTO:
    """DTO для отправки уведомления о напоминании"""

    id: int
    user_id: int
    chat_id: int | None
    title: str
    description: str | None
    category: str | None
    remind_count: int
    max_remind_count: int | None
    remind_interval: int | None
    remind_at: datetime
    remind_until: datetime | None
    notification_type: str
    is_encrypted: bool
    is_group: bool

    @classmethod
    def from_model(cls, reminder: "UserReminderModel") -> "ReminderNotificationDTO":
        """Создание DTO из модели"""
        return cls(
            id=reminder.FID,
            user_id=reminder.FK_User,
            chat_id=reminder.FK_Chat,
            title=reminder.FTitle,
            description=reminder.FDescription,
            category=reminder.FCategory,
            remind_count=reminder.FRemindCount,
            max_remind_count=reminder.FMaxRemindCount,
            remind_interval=reminder.FRemindInterval,
            remind_at=reminder.FRemindAt,
            remind_until=reminder.FRemindUntil,
            notification_type=reminder.FNotificationType,
            is_encrypted=reminder.FIsEncrypted,
            is_group=reminder.FIsGroupReminder,
        )
