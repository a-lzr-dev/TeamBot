from datetime import datetime
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from ..db import ReminderRepository
from ..exceptions import log_exceptions
from ..logger import app_logger
from ..models import ReminderModel


class ReminderService:
    """Сервис для управления напоминаниями и делами"""

    def __init__(self) -> None:
        self._repository = ReminderRepository()

    @log_exceptions(app_logger)
    async def create_reminder(
        self,
        user_id: int,
        title: str,
        remind_at: datetime,
        session: AsyncSession,
        description: str | None = None,
        category: str | None = None,
        remind_until: datetime | None = None,
        remind_interval: int | None = None,
        max_remind_count: int | None = None,
        code_word: str | None = None,
        notification_type: str = "private",
        chat_id: int | None = None,
        shared_with: list[int] | None = None,
        encrypt: bool = False,
    ) -> ReminderModel:
        """Создание напоминания"""
        return await self._repository.create_reminder(
            user_id=user_id,
            title=title,
            remind_at=remind_at,
            description=description,
            category=category,
            remind_until=remind_until,
            remind_interval=remind_interval,
            max_remind_count=max_remind_count,
            code_word=code_word,
            notification_type=notification_type,
            chat_id=chat_id,
            shared_with=shared_with,
            encrypt=encrypt,
            session=session,
        )

    @log_exceptions(app_logger)
    async def complete_reminder(
        self,
        reminder_id: int,
        user_id: int,
        session: AsyncSession,
        successful: bool = True,
    ) -> tuple[bool, str | None]:
        """Завершение дела"""
        return await self._repository.complete_reminder(
            reminder_id=reminder_id,
            user_id=user_id,
            successful=successful,
            session=session,
        )

    @log_exceptions(app_logger)
    async def get_reminders(
        self,
        user_id: int,
        session: AsyncSession,
        date: datetime | None = None,
        category: str | None = None,
        include_completed: bool = False,
        limit: int | None = None,
        offset: int = 0,
    ) -> list[dict[str, Any]]:
        """Получение списка дел"""
        reminders = await self._repository.get_reminders(
            user_id=user_id,
            date=date,
            category=category,
            include_completed=include_completed,
            limit=limit,
            offset=offset,
            session=session,
        )

        return [ReminderRepository.format_reminder(r) for r in reminders]

    @log_exceptions(app_logger)
    async def get_reminder_by_id(
        self,
        reminder_id: int,
        session: AsyncSession,
    ) -> dict[str, Any] | None:
        """Получение дела по ID"""
        reminder = await self._repository.get_reminder_by_id(reminder_id, session)

        if not reminder:
            return None

        return ReminderRepository.format_reminder(reminder)

    @log_exceptions(app_logger)
    async def find_by_code_word(
        self,
        user_id: int,
        code_word: str,
        session: AsyncSession,
        chat_id: int | None = None,
        include_completed: bool = False,
    ) -> list[dict[str, Any]]:
        """Поиск дел по кодовому слову"""
        reminders = await self._repository.find_by_code_word(
            user_id=user_id,
            code_word=code_word,
            chat_id=chat_id,
            include_completed=include_completed,
            session=session,
        )

        return [ReminderRepository.format_reminder(r) for r in reminders]

    @log_exceptions(app_logger)
    async def get_active_reminders(
        self,
        session: AsyncSession,
        before_time: datetime | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> list[ReminderModel]:
        """Получение активных напоминаний"""
        return await self._repository.get_active_reminders(
            before_time=before_time,
            limit=limit,
            offset=offset,
            session=session,
        )

    @log_exceptions(app_logger)
    async def update_reminder_status(
        self,
        *,
        reminder_id: int,
        session: AsyncSession,
        remind_count: int | None = None,
        last_reminded: datetime | None = None,
        is_active: bool | None = None,
        remind_at: datetime | None = None,
    ) -> bool:
        """Обновление статуса напоминания"""
        return await self._repository.update_reminder_status(
            reminder_id=reminder_id,
            remind_count=remind_count,
            last_reminded=last_reminded,
            is_active=is_active,
            remind_at=remind_at,
            session=session,
        )

    @log_exceptions(app_logger)
    async def deactivate_reminder(
        self,
        reminder_id: int,
        session: AsyncSession,
    ) -> bool:
        """Деактивация напоминания"""
        return await self._repository.deactivate_reminder(reminder_id, session)

    @log_exceptions(app_logger)
    async def delete_reminder(
        self,
        *,
        reminder_id: int,
        session: AsyncSession,
        soft: bool = True,
    ) -> bool:
        """Удаление напоминания"""
        return await self._repository.delete_reminder(reminder_id, soft, session)

    @log_exceptions(app_logger)
    async def get_reminder_stats(
        self,
        *,
        user_id: int,
        session: AsyncSession,
        period: str = "week",
    ) -> dict[str, Any]:
        """Получение статистики по делам"""
        return await self._repository.get_stats(
            user_id=user_id,
            period=period,
            session=session,
        )


reminder_service = ReminderService()
