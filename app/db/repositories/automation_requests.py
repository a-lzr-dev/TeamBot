from datetime import datetime
from typing import Any

from sqlalchemy import and_, delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from ...exceptions import log_exceptions
from ...logger import db_logger
from ...models import (
    AutomationRequestModel,
    AutomationRequestPriority,
    AutomationRequestStatus,
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
        priority: AutomationRequestPriority = AutomationRequestPriority.MEDIUM,
        chat_id: int | None = None,
        note: str | None = None,
    ) -> AutomationRequestModel:
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
            AutomationRequestModel: Созданная заявка
        """
        request = AutomationRequestModel(
            FK_User=user_id,
            FTitle=title,
            FDescription=description,
            FPriority=priority,
            FStatus=AutomationRequestStatus.NEW,
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
    ) -> AutomationRequestModel | None:
        """
        Получение заявки по ID.

        Args:
            session: Сессия БД
            request_id: ID заявки

        Returns:
            AutomationRequestModel | None: Найденная заявка или None
        """
        stmt = select(AutomationRequestModel).where(AutomationRequestModel.FID == request_id)
        result = await session.execute(stmt)
        return result.scalar_one_or_none()  # type: ignore[no-any-return]

    @staticmethod
    @log_exceptions(db_logger)
    async def get_by_user(
        session: AsyncSession,
        user_id: int,
        status: AutomationRequestStatus | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> list[AutomationRequestModel]:
        """
        Получение заявок пользователя.

        Args:
            session: Сессия БД
            user_id: ID пользователя
            status: Фильтр по статусу (опционально)
            limit: Лимит записей
            offset: Смещение

        Returns:
            list[AutomationRequestModel]: Список заявок
        """
        stmt = select(AutomationRequestModel).where(AutomationRequestModel.FK_User == user_id)

        if status is not None:
            stmt = stmt.where(AutomationRequestModel.FStatus == status)

        stmt = stmt.order_by(AutomationRequestModel.FCreatedAt.desc())
        stmt = stmt.limit(limit).offset(offset)

        result = await session.execute(stmt)
        return list(result.scalars().all())

    @staticmethod
    @log_exceptions(db_logger)
    async def get_all(
        session: AsyncSession,
        status: AutomationRequestStatus | None = None,
        priority: AutomationRequestPriority | None = None,
        user_id: int | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> list[AutomationRequestModel]:
        """
        Получение всех заявок с фильтрацией.

        Args:
            session: Сессия БД
            status: Фильтр по статусу
            priority: Фильтр по приоритету
            user_id: Фильтр по пользователю
            limit: Лимит записей
            offset: Смещение

        Returns:
            list[AutomationRequestModel]: Список заявок
        """
        stmt = select(AutomationRequestModel)

        if status is not None:
            stmt = stmt.where(AutomationRequestModel.FStatus == status)

        if priority is not None:
            stmt = stmt.where(AutomationRequestModel.FPriority == priority)

        if user_id is not None:
            stmt = stmt.where(AutomationRequestModel.FK_User == user_id)

        stmt = stmt.order_by(AutomationRequestModel.FPriority.desc(), AutomationRequestModel.FCreatedAt.desc())
        stmt = stmt.limit(limit).offset(offset)

        result = await session.execute(stmt)
        return list(result.scalars().all())

    @staticmethod
    @log_exceptions(db_logger)
    async def get_by_status(
        session: AsyncSession,
        status: AutomationRequestStatus,
        limit: int = 100,
        offset: int = 0,
    ) -> list[AutomationRequestModel]:
        """
        Получение заявок по статусу.

        Args:
            session: Сессия БД
            status: Статус заявки
            limit: Лимит записей
            offset: Смещение

        Returns:
            list[AutomationRequestModel]: Список заявок
        """
        stmt = (
            select(AutomationRequestModel)
            .where(AutomationRequestModel.FStatus == status)
            .order_by(AutomationRequestModel.FPriority.desc(), AutomationRequestModel.FCreatedAt.asc())
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
    ) -> list[AutomationRequestModel]:
        """
        Получение заявок, ожидающих обработки (NEW и IN_PROGRESS).

        Args:
            session: Сессия БД
            limit: Лимит записей
            offset: Смещение

        Returns:
            list[AutomationRequestModel]: Список заявок
        """
        stmt = (
            select(AutomationRequestModel)
            .where(
                AutomationRequestModel.FStatus.in_(
                    [
                        AutomationRequestStatus.NEW,
                        AutomationRequestStatus.IN_PROGRESS,
                    ]
                )
            )
            .order_by(AutomationRequestModel.FPriority.desc(), AutomationRequestModel.FCreatedAt.asc())
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
        status: AutomationRequestStatus,
        note: str | None = None,
        completed_by: int | None = None,
    ) -> tuple[bool, AutomationRequestModel | None]:
        """
        Обновление статуса заявки.

        Args:
            session: Сессия БД
            request_id: ID заявки
            status: Новый статус
            note: Примечание
            completed_by: ID пользователя, завершившего заявку

        Returns:
            tuple[bool, AutomationRequestModel | None]: (успех, обновленная заявка)
        """
        request = await AutomationRequestRepository.get_by_id(session, request_id)

        if not request:
            return False, None

        request.FStatus = status
        request.FUpdatedAt = datetime_now()

        if note:
            request.FNote = note

        # Если заявка завершена или отклонена
        if status in [AutomationRequestStatus.COMPLETED, AutomationRequestStatus.REJECTED]:
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
        priority: AutomationRequestPriority,
    ) -> tuple[bool, AutomationRequestModel | None]:
        """
        Обновление приоритета заявки.

        Args:
            session: Сессия БД
            request_id: ID заявки
            priority: Новый приоритет

        Returns:
            tuple[bool, AutomationRequestModel | None]: (успех, обновленная заявка)
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
            conditions.append(AutomationRequestModel.FK_User == user_id)

        if start_date is not None:
            conditions.append(AutomationRequestModel.FCreatedAt >= start_date)

        if end_date is not None:
            conditions.append(AutomationRequestModel.FCreatedAt <= end_date)

        stmt = select(
            func.count(AutomationRequestModel.FID).label("total"),
            func.count(AutomationRequestModel.FID)
            .filter(AutomationRequestModel.FStatus == AutomationRequestStatus.NEW)
            .label("new"),
            func.count(AutomationRequestModel.FID)
            .filter(AutomationRequestModel.FStatus == AutomationRequestStatus.IN_PROGRESS)
            .label("in_progress"),
            func.count(AutomationRequestModel.FID)
            .filter(AutomationRequestModel.FStatus == AutomationRequestStatus.COMPLETED)
            .label("completed"),
            func.count(AutomationRequestModel.FID)
            .filter(AutomationRequestModel.FStatus == AutomationRequestStatus.CANCELLED)
            .label("cancelled"),
            func.count(AutomationRequestModel.FID)
            .filter(AutomationRequestModel.FStatus == AutomationRequestStatus.REJECTED)
            .label("rejected"),
        )

        if conditions:
            stmt = stmt.where(and_(*conditions))

        result = await session.execute(stmt)
        stats = result.first()

        # Статистика по приоритетам
        priority_stmt = select(
            AutomationRequestModel.FPriority,
            func.count(AutomationRequestModel.FID).label("count"),
        )

        if conditions:
            priority_stmt = priority_stmt.where(and_(*conditions))

        priority_stmt = priority_stmt.group_by(AutomationRequestModel.FPriority)
        priority_result = await session.execute(priority_stmt)
        by_priority = {row.FPriority.value: row.count for row in priority_result.all()}

        return {
            "total": stats.total or 0,
            "new": stats.new or 0,
            "in_progress": stats.in_progress or 0,
            "completed": stats.completed or 0,
            "cancelled": stats.cancelled or 0,
            "rejected": stats.rejected or 0,
            "by_priority": by_priority,
            "completion_rate": (stats.completed / stats.total * 100) if stats.total else 0,
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

            request.FStatus = AutomationRequestStatus.CANCELLED
            request.FUpdatedAt = datetime_now()
            await session.flush()
            return True
        else:
            # Удаление
            stmt = delete(AutomationRequestModel).where(AutomationRequestModel.FID == request_id)
            result = await session.execute(stmt)
            await session.commit()
            return result.rowcount > 0 if hasattr(result, "rowcount") else True


__all__ = ["AutomationRequestRepository"]
