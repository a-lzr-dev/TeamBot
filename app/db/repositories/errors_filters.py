# app/db/repositories/filters.py

import re
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ...exceptions import log_exceptions
from ...logger import db_logger
from ...models import ErrorFilterModel, ErrorModel


class ErrorFilterRepository:
    """Репозиторий для работы с фильтрами ошибок"""

    @staticmethod
    @log_exceptions(db_logger)
    async def get_filters_by_chat(
        session: AsyncSession,
        chat_id: int,
        active_only: bool = True,
    ) -> list[ErrorFilterModel]:
        """
        Получение фильтров для чата.

        Args:
            session: Сессия БД
            chat_id: ID чата
            active_only: Только активные фильтры

        Returns:
            list[ErrorFilterModel]: Список фильтров
        """
        stmt = select(ErrorFilterModel).where(ErrorFilterModel.FK_Chat == chat_id)

        if active_only:
            stmt = stmt.where(ErrorFilterModel.FIsActive.is_(True))

        result = await session.execute(stmt)
        return list(result.scalars().all())

    @staticmethod
    @log_exceptions(db_logger)
    async def is_error_filtered(
        session: AsyncSession,
        chat_id: int,
        error: ErrorModel,
    ) -> bool:
        """
        Проверка, фильтруется ли ошибка.

        Args:
            session: Сессия БД
            chat_id: ID чата
            error: Ошибка

        Returns:
            bool: Фильтруется ли ошибка
        """
        filters = await ErrorFilterRepository.get_filters_by_chat(session, chat_id)

        for filter_ in filters:
            # Проверка категории
            if filter_.FCategory is not None and filter_.FCategory != error.FCategory:
                continue

            # Проверка кода ошибки
            if filter_.FErrorCode is not None and filter_.FErrorCode != error.FErrorCode:
                continue

            # Проверка системы-источника
            if filter_.FSourceSystem is not None and filter_.FSourceSystem != error.FSourceSystem:
                continue

            # Проверка паттерна
            if filter_.FPattern:
                if filter_.FIsRegex:
                    try:
                        if re.search(filter_.FPattern, error.FErrorMessage):
                            return True
                    except re.error:
                        continue
                else:
                    pattern_type = filter_.FPatternType
                    if pattern_type == "exact":
                        if error.FErrorMessage == filter_.FPattern:
                            return True
                    elif pattern_type == "contains" and filter_.FPattern.lower() in error.FErrorMessage.lower():
                        return True

        return False

    @staticmethod
    @log_exceptions(db_logger)
    async def create_filter(
        session: AsyncSession,
        chat_id: int,
        pattern: str,
        pattern_type: str = "contains",
        category: str | None = None,
        error_code: str | None = None,
        source_system: str | None = None,
        is_regex: bool = False,
        description: str | None = None,
    ) -> ErrorFilterModel:
        """
        Создание фильтра ошибок.

        Args:
            session: Сессия БД
            chat_id: ID чата
            pattern: Шаблон для фильтрации
            pattern_type: Тип шаблона (contains, exact, regex)
            category: Категория ошибки
            error_code: Код ошибки
            source_system: Система-источник
            is_regex: Использовать регулярное выражение
            description: Описание фильтра

        Returns:
            ErrorFilterModel: Созданный фильтр
        """
        filter_ = ErrorFilterModel(
            FK_Chat=chat_id,
            FPattern=pattern,
            FPatternType=pattern_type,
            FCategory=category,
            FErrorCode=error_code,
            FSourceSystem=source_system,
            FIsRegex=is_regex,
            FDescription=description,
            FIsActive=True,
        )
        session.add(filter_)
        await session.flush()
        return filter_

    @staticmethod
    @log_exceptions(db_logger)
    async def update_filter(
        session: AsyncSession,
        filter_id: int,
        **kwargs: Any,
    ) -> ErrorFilterModel | None:
        """
        Обновление фильтра.

        Args:
            session: Сессия БД
            filter_id: ID фильтра
            **kwargs: Поля для обновления

        Returns:
            ErrorFilterModel | None: Обновленный фильтр или None
        """
        stmt = select(ErrorFilterModel).where(ErrorFilterModel.FID == filter_id)
        result = await session.execute(stmt)
        filter_ = result.scalar_one_or_none()

        if not filter_:
            return None

        for key, value in kwargs.items():
            if hasattr(filter_, key):
                setattr(filter_, key, value)

        await session.flush()
        return filter_  # type: ignore[no-any-return]

    @staticmethod
    @log_exceptions(db_logger)
    async def delete_filter(
        session: AsyncSession,
        filter_id: int,
    ) -> bool:
        """
        Удаление фильтра (мягкое удаление).

        Args:
            session: Сессия БД
            filter_id: ID фильтра

        Returns:
            bool: Успешно ли удалено
        """
        stmt = select(ErrorFilterModel).where(ErrorFilterModel.FID == filter_id)
        result = await session.execute(stmt)
        filter_ = result.scalar_one_or_none()

        if not filter_:
            return False

        filter_.FIsActive = False
        await session.flush()
        return True

    @staticmethod
    @log_exceptions(db_logger)
    async def activate_filter(
        session: AsyncSession,
        filter_id: int,
    ) -> bool:
        """
        Активация фильтра.

        Args:
            session: Сессия БД
            filter_id: ID фильтра

        Returns:
            bool: Успешно ли активировано
        """
        stmt = select(ErrorFilterModel).where(ErrorFilterModel.FID == filter_id)
        result = await session.execute(stmt)
        filter_ = result.scalar_one_or_none()

        if not filter_:
            return False

        filter_.FIsActive = True
        await session.flush()
        return True
