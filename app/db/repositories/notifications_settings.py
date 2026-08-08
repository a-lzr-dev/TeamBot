from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ...exceptions import log_exceptions
from ...logger import db_logger
from ...models import ChatNotificationSettingsModel, ErrorSeverity


class NotificationSettingsRepository:
    """Репозиторий для работы с настройками уведомлений"""

    @staticmethod
    @log_exceptions(db_logger)
    async def get_by_chat_id(session: AsyncSession, chat_id: int) -> ChatNotificationSettingsModel | None:
        """
        Получение настроек уведомлений для чата.

        Args:
            session: Сессия БД
            chat_id: ID чата

        Returns:
            ChatNotificationSettingsModel | None: Настройки или None
        """
        stmt = select(ChatNotificationSettingsModel).where(ChatNotificationSettingsModel.FK_Chat == chat_id)
        result = await session.execute(stmt)
        return result.scalar_one_or_none()  # type: ignore[no-any-return]

    @staticmethod
    @log_exceptions(db_logger)
    async def create(
        session: AsyncSession,
        chat_id: int,
        silence_start: str | None = None,
        silence_end: str | None = None,
        silence_enabled: bool = False,
        notify_errors: bool = True,
        notify_periodic_tasks: bool = True,
        notify_task_execution: bool = True,
        notify_system: bool = True,
        notification_level: ErrorSeverity = ErrorSeverity.ERROR,
        grouping_enabled: bool = True,
        grouping_window_minutes: int = 60,
        auto_reports_enabled: bool = True,
        auto_report_interval: int = 60,
        auto_report_hour_start: int = 9,
        auto_report_hour_end: int = 18,
    ) -> ChatNotificationSettingsModel:
        """
        Создание новых настроек уведомлений для чата.

        Args:
            session: Сессия БД
            chat_id: ID чата
            silence_start: Начало тишины (HH:MM)
            silence_end: Конец тишины (HH:MM)
            silence_enabled: Включить тишину
            notify_errors: Уведомлять об ошибках
            notify_periodic_tasks: Уведомлять о периодических задачах
            notify_task_execution: Уведомлять о выполнении задач
            notify_system: Уведомлять о системных событиях
            notification_level: Уровень уведомлений
            grouping_enabled: Группировать ошибки
            grouping_window_minutes: Окно группировки в минутах
            auto_reports_enabled: Включить автоматические отчеты
            auto_report_interval: Интервал отчетов в минутах
            auto_report_hour_start: Начало рабочего времени
            auto_report_hour_end: Конец рабочего времени

        Returns:
            ChatNotificationSettingsModel: Созданные настройки
        """
        settings = ChatNotificationSettingsModel(
            FK_Chat=chat_id,
            FSilenceStart=silence_start,
            FSilenceEnd=silence_end,
            FSilenceEnabled=silence_enabled,
            FNotifyErrors=notify_errors,
            FNotifyPeriodicTasks=notify_periodic_tasks,
            FNotifyTaskExecution=notify_task_execution,
            FNotifySystem=notify_system,
            FNotificationLevel=notification_level,
            FGroupingEnabled=grouping_enabled,
            FGroupingWindowMinutes=grouping_window_minutes,
            FEnableAutoReports=auto_reports_enabled,
            FAutoReportInterval=auto_report_interval,
            FAutoReportHourStart=auto_report_hour_start,
            FAutoReportHourEnd=auto_report_hour_end,
        )
        session.add(settings)
        await session.flush()
        return settings

    @staticmethod
    @log_exceptions(db_logger)
    async def update(session: AsyncSession, chat_id: int, **kwargs: Any) -> ChatNotificationSettingsModel | None:
        """
        Обновление настроек уведомлений для чата.

        Args:
            session: Сессия БД
            chat_id: ID чата
            **kwargs: Поля для обновления

        Returns:
            ChatNotificationSettingsModel | None: Обновленные настройки или None
        """
        settings = await NotificationSettingsRepository.get_by_chat_id(session, chat_id)
        if not settings:
            return None

        for key, value in kwargs.items():
            if hasattr(settings, key):
                setattr(settings, key, value)

        await session.flush()
        return settings
