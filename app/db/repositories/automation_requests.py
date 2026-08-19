from datetime import datetime
from typing import Any

from sqlalchemy import and_, delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from ...exceptions import log_exceptions
from ...logger import db_logger
from ...models import (
    UserRequestAutomationModel,
    UserRequestAutomationPriority,
    UserRequestAutomationStatus,
    datetime_now,
)


class AutomationRequestRepository:
    """Репозиторий для работы с заявками на автоматизацию"""

    # ==================== СОЗДАНИЕ ====================

    @staticmethod
    @log_exceptions(db_logger)
    async def create(
        session: AsyncSession,
        user_id: int,
        title: str,
        description: str,
        priority: UserRequestAutomationPriority = UserRequestAutomationPriority.MEDIUM,
        chat_id: int | None = None,
        note: str | None = None,
    ) -> UserRequestAutomationModel:
        """
        Создание новой заявки на автоматизацию.

        Args:
            session: Сессия БД
            user_id: ID пользователя
            title: Название заявки
            description: Описание заявки
            priority: Приоритет
            chat_id: ID чата для уведомлений
            note: Примечание

        Returns:
            UserRequestAutomationModel: Созданная заявка
        """
        request = UserRequestAutomationModel(
            FK_User=user_id,
            FTitle=title,
            FDescription=description,
            FPriority=priority,
            FStatus=UserRequestAutomationStatus.NEW,
            FK_Chat=chat_id,
            FNote=note,
        )
        session.add(request)
        await session.flush()
        await session.refresh(request)

        db_logger.info(f"✅ Created automation request #{request.FID} for user {user_id}")
        return request

    # ==================== ПОЛУЧЕНИЕ ====================

    @staticmethod
    @log_exceptions(db_logger)
    async def get_by_id(
        session: AsyncSession,
        request_id: int,
    ) -> UserRequestAutomationModel | None:
        """
        Получение заявки по ID.

        Args:
            session: Сессия БД
            request_id: ID заявки

        Returns:
            UserRequestAutomationModel | None: Найденная заявка или None
        """
        stmt = select(UserRequestAutomationModel).where(UserRequestAutomationModel.FID == request_id)
        result = await session.execute(stmt)
        model: UserRequestAutomationModel | None = result.scalar_one_or_none()
        return model

    @staticmethod
    @log_exceptions(db_logger)
    async def get_by_user(
        session: AsyncSession,
        user_id: int,
        status: UserRequestAutomationStatus | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> list[UserRequestAutomationModel]:
        """
        Получение заявок пользователя.

        Args:
            session: Сессия БД
            user_id: ID пользователя
            status: Фильтр по статусу (опционально)
            limit: Лимит записей
            offset: Смещение

        Returns:
            list[UserRequestAutomationModel]: Список заявок
        """
        stmt = select(UserRequestAutomationModel).where(UserRequestAutomationModel.FK_User == user_id)

        if status is not None:
            stmt = stmt.where(UserRequestAutomationModel.FStatus == status)

        stmt = stmt.order_by(UserRequestAutomationModel.FCreatedAt.desc())
        stmt = stmt.limit(limit).offset(offset)

        result = await session.execute(stmt)
        return list(result.scalars().all())

    @staticmethod
    @log_exceptions(db_logger)
    async def get_all(
        session: AsyncSession,
        status: UserRequestAutomationStatus | None = None,
        priority: UserRequestAutomationPriority | None = None,
        user_id: int | None = None,
        limit: int = 100,
        offset: int = 0,
        load_user: bool = True,
    ) -> list[UserRequestAutomationModel]:
        """
        Получение всех заявок с фильтрацией.

        Args:
            session: Сессия БД
            status: Фильтр по статусу
            priority: Фильтр по приоритету
            user_id: Фильтр по пользователю
            limit: Лимит записей
            offset: Смещение
            load_user: Подгружать имя пользователя (eager loading).

        Returns:
            list[UserRequestAutomationModel]: Список заявок
        """
        stmt = select(UserRequestAutomationModel)

        if load_user:
            stmt = stmt.options(selectinload(UserRequestAutomationModel.user))

        if status is not None:
            stmt = stmt.where(UserRequestAutomationModel.FStatus == status)

        if priority is not None:
            stmt = stmt.where(UserRequestAutomationModel.FPriority == priority)

        if user_id is not None:
            stmt = stmt.where(UserRequestAutomationModel.FK_User == user_id)

        stmt = stmt.order_by(UserRequestAutomationModel.FPriority.desc(), UserRequestAutomationModel.FCreatedAt.desc())
        stmt = stmt.limit(limit).offset(offset)

        result = await session.execute(stmt)
        return list(result.scalars().all())

    @staticmethod
    @log_exceptions(db_logger)
    async def get_by_status(
        session: AsyncSession,
        status: UserRequestAutomationStatus,
        limit: int = 100,
        offset: int = 0,
    ) -> list[UserRequestAutomationModel]:
        """
        Получение заявок по статусу.

        Args:
            session: Сессия БД
            status: Статус заявки
            limit: Лимит записей
            offset: Смещение

        Returns:
            list[UserRequestAutomationModel]: Список заявок
        """
        stmt = (
            select(UserRequestAutomationModel)
            .where(UserRequestAutomationModel.FStatus == status)
            .order_by(UserRequestAutomationModel.FPriority.desc(), UserRequestAutomationModel.FCreatedAt.asc())
            .limit(limit)
            .offset(offset)
        )
        result = await session.execute(stmt)
        return list(result.scalars().all())

    @staticmethod
    @log_exceptions(db_logger)
    async def get_pending(
        session: AsyncSession,
        limit: int = 100,
        offset: int = 0,
    ) -> list[UserRequestAutomationModel]:
        """
        Получение заявок, ожидающих обработки (NEW и IN_PROGRESS).

        Args:
            session: Сессия БД
            limit: Лимит записей
            offset: Смещение

        Returns:
            list[UserRequestAutomationModel]: Список заявок
        """
        stmt = (
            select(UserRequestAutomationModel)
            .where(
                UserRequestAutomationModel.FStatus.in_(
                    [
                        UserRequestAutomationStatus.NEW,
                        UserRequestAutomationStatus.IN_PROGRESS,
                    ]
                )
            )
            .order_by(UserRequestAutomationModel.FPriority.desc(), UserRequestAutomationModel.FCreatedAt.asc())
            .limit(limit)
            .offset(offset)
        )
        result = await session.execute(stmt)
        return list(result.scalars().all())

    # ==================== ОБНОВЛЕНИЕ ====================

    @staticmethod
    @log_exceptions(db_logger)
    async def update_status(
        session: AsyncSession,
        request_id: int,
        status: UserRequestAutomationStatus,
        note: str | None = None,
        completed_by: int | None = None,
    ) -> tuple[bool, UserRequestAutomationModel | None]:
        """
        Обновление статуса заявки.

        Args:
            session: Сессия БД
            request_id: ID заявки
            status: Новый статус
            note: Примечание
            completed_by: ID пользователя, завершившего заявку

        Returns:
            tuple[bool, UserRequestAutomationModel | None]: (успех, обновленная заявка)
        """
        request = await AutomationRequestRepository.get_by_id(session, request_id)

        if not request:
            return False, None

        request.FStatus = status
        request.FUpdatedAt = datetime_now()

        if note:
            request.FNote = note

        # Если заявка завершена или отклонена
        if status in [UserRequestAutomationStatus.COMPLETED, UserRequestAutomationStatus.REJECTED]:
            request.FCompletedAt = datetime_now()
            if completed_by:
                request.FCompletedBy = completed_by
            elif request.FK_User:
                request.FCompletedBy = request.FK_User

        await session.flush()
        await session.refresh(request)

        db_logger.info(f"✅ Updated request #{request_id} status to {status.value}")
        return True, request

    @staticmethod
    @log_exceptions(db_logger)
    async def update_priority(
        session: AsyncSession,
        request_id: int,
        priority: UserRequestAutomationPriority,
    ) -> tuple[bool, UserRequestAutomationModel | None]:
        """
        Обновление приоритета заявки.

        Args:
            session: Сессия БД
            request_id: ID заявки
            priority: Новый приоритет

        Returns:
            tuple[bool, UserRequestAutomationModel | None]: (успех, обновленная заявка)
        """
        request = await AutomationRequestRepository.get_by_id(session, request_id)

        if not request:
            return False, None

        request.FPriority = priority
        request.FUpdatedAt = datetime_now()

        await session.flush()
        await session.refresh(request)

        db_logger.info(f"✅ Updated request #{request_id} priority to {priority.value}")
        return True, request

    # ==================== СТАТИСТИКА ====================

    @staticmethod
    @log_exceptions(db_logger)
    async def get_stats(
        session: AsyncSession,
        user_id: int | None = None,
        start_date: datetime | None = None,
        end_date: datetime | None = None,
    ) -> dict[str, Any]:
        """
        Получение статистики по заявкам.

        Args:
            session: Сессия БД
            user_id: ID пользователя (опционально)
            start_date: Начальная дата
            end_date: Конечная дата

        Returns:
            dict: Статистика
        """
        conditions = []

        if user_id is not None:
            conditions.append(UserRequestAutomationModel.FK_User == user_id)

        if start_date is not None:
            conditions.append(UserRequestAutomationModel.FCreatedAt >= start_date)

        if end_date is not None:
            conditions.append(UserRequestAutomationModel.FCreatedAt <= end_date)

        stmt = select(
            func.count(UserRequestAutomationModel.FID).label("total"),
            func.count(UserRequestAutomationModel.FID)
            .filter(UserRequestAutomationModel.FStatus == UserRequestAutomationStatus.NEW)
            .label("new"),
            func.count(UserRequestAutomationModel.FID)
            .filter(UserRequestAutomationModel.FStatus == UserRequestAutomationStatus.IN_PROGRESS)
            .label("in_progress"),
            func.count(UserRequestAutomationModel.FID)
            .filter(UserRequestAutomationModel.FStatus == UserRequestAutomationStatus.COMPLETED)
            .label("completed"),
            func.count(UserRequestAutomationModel.FID)
            .filter(UserRequestAutomationModel.FStatus == UserRequestAutomationStatus.CANCELLED)
            .label("cancelled"),
            func.count(UserRequestAutomationModel.FID)
            .filter(UserRequestAutomationModel.FStatus == UserRequestAutomationStatus.REJECTED)
            .label("rejected"),
        )

        if conditions:
            stmt = stmt.where(and_(*conditions))

        result = await session.execute(stmt)
        stats = result.first()

        if stats is None:
            return {
                "total": 0,
                "new": 0,
                "in_progress": 0,
                "completed": 0,
                "cancelled": 0,
                "rejected": 0,
                "by_priority": {},
                "completion_rate": 0,
            }

        # Статистика по приоритетам
        priority_stmt = select(
            UserRequestAutomationModel.FPriority,
            func.count(UserRequestAutomationModel.FID).label("count"),
        )

        if conditions:
            priority_stmt = priority_stmt.where(and_(*conditions))

        priority_stmt = priority_stmt.group_by(UserRequestAutomationModel.FPriority)
        priority_result = await session.execute(priority_stmt)
        by_priority = {row.FPriority.value: row.count for row in priority_result.all()}

        # Безопасное получение значений с преобразованием в int
        total = int(stats.total) if stats.total is not None else 0
        new = int(stats.new) if stats.new is not None else 0
        in_progress = int(stats.in_progress) if stats.in_progress is not None else 0
        completed = int(stats.completed) if stats.completed is not None else 0
        cancelled = int(stats.cancelled) if stats.cancelled is not None else 0
        rejected = int(stats.rejected) if stats.rejected is not None else 0

        return {
            "total": total,
            "new": new,
            "in_progress": in_progress,
            "completed": completed,
            "cancelled": cancelled,
            "rejected": rejected,
            "by_priority": by_priority,
            "completion_rate": (completed / total * 100) if total > 0 else 0,
        }

    @staticmethod
    @log_exceptions(db_logger)
    async def delete(
        session: AsyncSession,
        request_id: int,
        soft: bool = True,
    ) -> bool:
        """
        Удаление заявки (мягкое или жесткое).

        Args:
            session: Сессия БД
            request_id: ID заявки
            soft: Мягкое удаление (только для совместимости, используем статус)

        Returns:
            bool: Успешно ли удалено
        """
        if soft:
            # Изменение статуса на CANCELLED
            request = await AutomationRequestRepository.get_by_id(session, request_id)
            if not request:
                return False

            request.FStatus = UserRequestAutomationStatus.CANCELLED
            request.FUpdatedAt = datetime_now()
            await session.flush()
            return True
        else:
            # Удаление
            stmt = delete(UserRequestAutomationModel).where(UserRequestAutomationModel.FID == request_id)
            result = await session.execute(stmt)
            await session.commit()
            return result.rowcount > 0 if hasattr(result, "rowcount") else True


__all__ = ["AutomationRequestRepository"]
