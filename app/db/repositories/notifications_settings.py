"""
Репозиторий для работы с настройками уведомлений в чатах.

Назначение:
    Предоставляет методы для управления настройками уведомлений для каждого чата.
    Настройки определяют, какие типы ошибок и событий должны отправляться в чат,
    уровень серьёзности, режим тишины, группировку ошибок и автоматические отчёты.

Основные функции:
    1. Получение настроек уведомлений для чата по ID
    2. Создание новых настроек с параметрами по умолчанию
    3. Обновление существующих настроек

Технические особенности:
    - Все методы статические, используют AsyncSession
    - Поддержка обновления через **kwargs для гибкости
    - Логирование всех операций с уровнями DEBUG/INFO/WARNING
    - Использование ErrorSeverity для уровня уведомлений

Архитектура:
    - Работает с моделью ChatNotificationSettingsModel
    - Используется в notification_service для проверки настроек
    - Интегрируется с системой уведомлений об ошибках
"""

from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ...logger import db_logger
from ...models import ChatNotificationSettingsModel, ErrorSeverity
from ...utils.decorators import log_exceptions


class NotificationSettingsRepository:
    """Репозиторий для работы с настройками уведомлений в чатах.

    Предоставляет методы для CRUD операций с настройками уведомлений.
    Все методы асинхронны и принимают AsyncSession.
    """

    @staticmethod
    @log_exceptions(db_logger)
    async def get_by_chat_id(session: AsyncSession, chat_id: int) -> ChatNotificationSettingsModel | None:
        """Получение настроек уведомлений для чата.

        Args:
            session: Асинхронная сессия SQLAlchemy
            chat_id: ID чата

        Returns:
            ChatNotificationSettingsModel | None: Настройки или None, если не найдены
        """
        db_logger.info(f"🔍 [get_by_chat_id] Getting notification settings for chat {chat_id}")

        stmt = select(ChatNotificationSettingsModel).where(ChatNotificationSettingsModel.FK_Chat == chat_id)

        db_logger.debug(f"📝 SQL: {stmt.compile(compile_kwargs={'literal_binds': True})}")

        result = await session.execute(stmt)
        settings: ChatNotificationSettingsModel | None = result.scalar_one_or_none()

        if settings:
            db_logger.info(f"✅ [get_by_chat_id] Found settings for chat {chat_id}")
        else:
            db_logger.warning(f"⚠️ [get_by_chat_id] No settings found for chat {chat_id}")

        return settings

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
        """Создание новых настроек уведомлений для чата.

        Args:
            session: Асинхронная сессия SQLAlchemy
            chat_id: ID чата
            silence_start: Начало режима тишины (формат HH:MM)
            silence_end: Конец режима тишины (формат HH:MM)
            silence_enabled: Включить режим тишины
            notify_errors: Уведомлять об ошибках
            notify_periodic_tasks: Уведомлять о периодических задачах
            notify_task_execution: Уведомлять о выполнении задач
            notify_system: Уведомлять о системных событиях
            notification_level: Минимальный уровень серьёзности для уведомлений
            grouping_enabled: Группировать схожие ошибки
            grouping_window_minutes: Окно группировки в минутах
            auto_reports_enabled: Включить автоматические отчёты
            auto_report_interval: Интервал отправки отчётов в минутах
            auto_report_hour_start: Начало рабочего времени для отчётов (час)
            auto_report_hour_end: Конец рабочего времени для отчётов (час)

        Returns:
            ChatNotificationSettingsModel: Созданные настройки
        """
        db_logger.info(f"🆕 [create] Creating notification settings for chat {chat_id}")

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

        db_logger.info(f"✅ [create] Created notification settings for chat {chat_id}")
        return settings

    @staticmethod
    @log_exceptions(db_logger)
    async def update(session: AsyncSession, chat_id: int, **kwargs: Any) -> ChatNotificationSettingsModel | None:
        """Обновление настроек уведомлений для чата.

        Args:
            session: Асинхронная сессия SQLAlchemy
            chat_id: ID чата
            **kwargs: Поля для обновления (любые поля модели)

        Returns:
            ChatNotificationSettingsModel | None: Обновлённые настройки или None
        """
        db_logger.info(f"🔄 [update] Updating notification settings for chat {chat_id}")

        settings = await NotificationSettingsRepository.get_by_chat_id(session, chat_id)
        if not settings:
            db_logger.warning(f"⚠️ [update] No settings found for chat {chat_id}")
            return None

        for key, value in kwargs.items():
            if hasattr(settings, key):
                setattr(settings, key, value)

        await session.flush()

        db_logger.info(f"✅ [update] Updated notification settings for chat {chat_id}")
        return settings  # type: ignore[no-any-return]
