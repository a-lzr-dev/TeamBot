"""
Сервис для управления напоминаниями и делами.

Отвечает за:
1. Создание напоминаний (личных и общих)
2. Завершение дел
3. Получение списка дел с фильтрацией
4. Поиск по кодовому слову
5. Управление статусом напоминаний
6. Статистику по делам
"""

from datetime import datetime
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from ..db import ReminderRepository
from ..logger import app_logger
from ..models import UserReminderModel
from ..utils.decorators import log_exceptions


class ReminderService:
    """
    Сервис для управления напоминаниями и делами.

    Предоставляет методы для CRUD операций с напоминаниями,
    а также для получения статистики и поиска.
    """

    def __init__(self) -> None:
        """Инициализация сервиса с репозиторием."""
        self._repository = ReminderRepository()

    # ============================================================
    # СОЗДАНИЕ
    # ============================================================

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
    ) -> UserReminderModel:
        """
        Создание нового напоминания.

        Args:
            user_id: ID пользователя-владельца
            title: Название напоминания
            remind_at: Время первого напоминания
            session: Сессия БД
            description: Описание (опционально)
            category: Категория (опционально)
            remind_until: Дата окончания оповещений (опционально)
            remind_interval: Интервал между напоминаниями в минутах (опционально)
            max_remind_count: Максимальное количество оповещений (опционально)
            code_word: Кодовое слово для поиска (опционально)
            notification_type: Тип уведомления (private, group, both)
            chat_id: ID чата для групповых уведомлений
            shared_with: Список ID пользователей для общего дела
            encrypt: Шифровать данные

        Returns:
            UserReminderModel: Созданное напоминание

        Note:
            При encrypt=True название, описание и категория шифруются.
        """
        return await self._repository.create_reminder(  # type: ignore[no-any-return]
            session=session,
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
        )

    # ============================================================
    # ЗАВЕРШЕНИЕ
    # ============================================================

    @log_exceptions(app_logger)
    async def complete_reminder(
        self,
        reminder_id: int,
        user_id: int,
        session: AsyncSession,
        successful: bool = True,
    ) -> tuple[bool, str | None]:
        """
        Завершение дела.

        Args:
            reminder_id: ID напоминания
            user_id: ID пользователя, завершающего дело
            session: Сессия БД
            successful: Успешно ли выполнено

        Returns:
            tuple[bool, str | None]: (успех, сообщение об ошибке)

        Note:
            Проверяет права пользователя (владелец или участник общего дела).
        """
        return await self._repository.complete_reminder(  # type: ignore[no-any-return]
            session=session,
            reminder_id=reminder_id,
            user_id=user_id,
            successful=successful,
        )

    # ============================================================
    # ПОЛУЧЕНИЕ СПИСКА
    # ============================================================

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
        """
        Получение списка дел пользователя.

        Args:
            user_id: ID пользователя
            session: Сессия БД
            date: Фильтр по дате (опционально)
            category: Фильтр по категории (опционально)
            include_completed: Включать завершенные дела
            limit: Лимит записей
            offset: Смещение

        Returns:
            list[dict[str, Any]]: Список отформатированных напоминаний

        Note:
            Возвращает как личные дела пользователя, так и общие,
            в которых он участвует.
        """
        reminders = await self._repository.get_reminders(
            session=session,
            user_id=user_id,
            date=date,
            category=category,
            include_completed=include_completed,
            limit=limit,
            offset=offset,
        )

        # Форматирование каждого напоминания (с расшифровкой при необходимости)
        return [ReminderRepository.format_reminder(r) for r in reminders]

    # ============================================================
    # ПОЛУЧЕНИЕ ПО ID
    # ============================================================

    @log_exceptions(app_logger)
    async def get_reminder_by_id(
        self,
        reminder_id: int,
        session: AsyncSession,
    ) -> dict[str, Any] | None:
        """
        Получение дела по ID.

        Args:
            reminder_id: ID напоминания
            session: Сессия БД

        Returns:
            dict[str, Any] | None: Отформатированное напоминание или None

        Note:
            Не проверяет права доступа — только получение данных.
        """
        reminder = await self._repository.get_reminder_by_id(
            session=session,
            reminder_id=reminder_id,
        )

        if not reminder:
            return None

        return ReminderRepository.format_reminder(reminder)

    # ============================================================
    # ПОИСК ПО КОДОВОМУ СЛОВУ
    # ============================================================

    @log_exceptions(app_logger)
    async def find_by_code_word(
        self,
        user_id: int,
        code_word: str,
        session: AsyncSession,
        chat_id: int | None = None,
        include_completed: bool = False,
    ) -> list[dict[str, Any]]:
        """
        Поиск дел по кодовому слову.

        Args:
            user_id: ID пользователя
            code_word: Кодовое слово для поиска
            session: Сессия БД
            chat_id: ID чата для фильтрации (опционально)
            include_completed: Включать завершенные дела

        Returns:
            list[dict[str, Any]]: Список найденных напоминаний

        Note:
            Кодовое слово — это уникальный идентификатор,
            который можно использовать для быстрого доступа к делу.
        """
        reminders = await self._repository.find_by_code_word(
            session=session,
            user_id=user_id,
            code_word=code_word,
            chat_id=chat_id,
            include_completed=include_completed,
        )

        return [ReminderRepository.format_reminder(r) for r in reminders]

    # ============================================================
    # АКТИВНЫЕ НАПОМИНАНИЯ
    # ============================================================

    @log_exceptions(app_logger)
    async def get_active_reminders(
        self,
        session: AsyncSession,
        before_time: datetime | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> list[UserReminderModel]:
        """
        Получение активных напоминаний, время которых наступило.

        Args:
            session: Сессия БД
            before_time: Время, до которого проверять (по умолчанию — сейчас)
            limit: Лимит записей
            offset: Смещение

        Returns:
            list[UserReminderModel]: Список активных напоминаний

        Note:
            Используется фоновым сервисом для отправки уведомлений.
        """
        return await self._repository.get_active_reminders(  # type: ignore[no-any-return]
            session=session,
            before_time=before_time,
            limit=limit,
            offset=offset,
        )

    # ============================================================
    # ОБНОВЛЕНИЕ СТАТУСА
    # ============================================================

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
        """
        Обновление статуса напоминания.

        Args:
            reminder_id: ID напоминания
            session: Сессия БД
            remind_count: Количество отправленных уведомлений
            last_reminded: Время последнего уведомления
            is_active: Активно ли
            remind_at: Новое время напоминания

        Returns:
            bool: Успешно ли обновлено

        Note:
            Используется после отправки уведомления для обновления
            счетчика и планирования следующего напоминания.
        """
        return await self._repository.update_reminder_status(  # type: ignore[no-any-return]
            session=session,
            reminder_id=reminder_id,
            remind_count=remind_count,
            last_reminded=last_reminded,
            is_active=is_active,
            remind_at=remind_at,
        )

    # ============================================================
    # ДЕАКТИВАЦИЯ
    # ============================================================

    @log_exceptions(app_logger)
    async def deactivate_reminder(
        self,
        reminder_id: int,
        session: AsyncSession,
    ) -> bool:
        """
        Деактивация напоминания.

        Args:
            reminder_id: ID напоминания
            session: Сессия БД

        Returns:
            bool: Успешно ли деактивировано

        Note:
            Деактивированное напоминание не будет отправлять уведомления.
            Используется при достижении лимита повторений или окончании срока.
        """
        return await self._repository.deactivate_reminder(  # type: ignore[no-any-return]
            session=session,
            reminder_id=reminder_id,
        )

    # ============================================================
    # УДАЛЕНИЕ
    # ============================================================

    @log_exceptions(app_logger)
    async def delete_reminder(
        self,
        *,
        reminder_id: int,
        session: AsyncSession,
        soft: bool = True,
    ) -> bool:
        """
        Удаление напоминания.

        Args:
            reminder_id: ID напоминания
            session: Сессия БД
            soft: Мягкое удаление (пометить как удаленное) или жесткое

        Returns:
            bool: Успешно ли удалено

        Note:
            При мягком удалении запись сохраняется с флагом FIsDeleted=True.
            При жестком — запись удаляется из БД полностью.
        """
        return await self._repository.delete_reminder(  # type: ignore[no-any-return]
            session=session,
            reminder_id=reminder_id,
            soft=soft,
        )

    # ============================================================
    # СТАТИСТИКА
    # ============================================================

    @log_exceptions(app_logger)
    async def get_reminder_stats(
        self,
        *,
        user_id: int,
        session: AsyncSession,
        period: str = "week",
    ) -> dict[str, Any]:
        """
        Получение статистики по делам пользователя.

        Args:
            user_id: ID пользователя
            session: Сессия БД
            period: Период (day, week, month, year)

        Returns:
            dict[str, Any]: Статистика с полями:
                - total: всего дел
                - completed: завершено
                - successful: успешно завершено
                - unsuccessful: неудачно завершено
                - success_rate: процент успешности
                - daily: статистика по дням
                - period: выбранный период

        Note:
            Учитывает как личные дела пользователя, так и общие,
            в которых он участвует.
        """
        return await self._repository.get_stats(  # type: ignore[no-any-return]
            session=session,
            user_id=user_id,
            period=period,
        )


reminder_service = ReminderService()
