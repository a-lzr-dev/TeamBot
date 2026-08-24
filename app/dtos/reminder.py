"""
DTO (Data Transfer Object) для уведомлений о напоминаниях.

Назначение:
    Предоставляет объект для передачи данных о напоминании из сервисного слоя
    в слой уведомлений. Инкапсулирует все необходимые данные для отправки
    уведомления пользователю.

Основные функции:
    1. Хранение всех данных напоминания, необходимых для отправки уведомления
    2. Преобразование из модели UserReminderModel в DTO через from_model()
    3. Поддержка всех типов напоминаний (личные, групповые, зашифрованные)

Технические особенности:
    - Реализован как dataclass для удобства создания и сравнения объектов
    - Использует TYPE_CHECKING для избежания циклических импортов
    - Все поля явно типизированы для обеспечения типобезопасности
    - Поддерживает опциональные поля (chat_id, description, category и др.)

Архитектура:
    - Используется в reminder_service для передачи данных в notification_service
    - Создаётся из модели UserReminderModel через from_model()
    - Используется reminder_notification_service для отправки уведомлений
"""

from dataclasses import dataclass
from datetime import datetime
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from ..models import UserReminderModel


@dataclass
class ReminderNotificationDTO:
    """DTO для отправки уведомления о напоминании.

    Содержит все необходимые данные для формирования и отправки
    уведомления пользователю о наступившем напоминании.

    Attributes:
        id (int): ID напоминания в базе данных
        user_id (int): ID пользователя-владельца
        chat_id (int | None): ID чата для групповых уведомлений
        title (str): Название напоминания
        description (str | None): Описание напоминания (опционально)
        category (str | None): Категория для группировки (опционально)
        remind_count (int): Количество отправленных уведомлений
        max_remind_count (int | None): Максимальное количество уведомлений
        remind_interval (int | None): Интервал между уведомлениями в минутах
        remind_at (datetime): Время текущего напоминания
        remind_until (datetime | None): Дата окончания оповещений
        notification_type (str): Тип уведомления (private, group, both)
        is_encrypted (bool): Флаг шифрования данных
        is_group (bool): Флаг общего дела (shared)
    """

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
        """Создание DTO из модели.

        Преобразует модель UserReminderModel в объект DTO для передачи
        данных между слоями приложения.

        Args:
            reminder (UserReminderModel): Модель напоминания из БД

        Returns:
            ReminderNotificationDTO: Объект DTO с данными напоминания

        Note:
            Зашифрованные данные (title, description, category) передаются
            как есть. Расшифровка выполняется на стороне сервиса уведомлений
            при необходимости.
        """
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
