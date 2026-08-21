import re
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ...logger import db_logger
from ...models import ErrorFilterModel, ErrorModel
from ...utils.decorators import log_exceptions


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
        db_logger.info(f"📋 [get_filters_by_chat] Getting filters for chat {chat_id}")

        stmt = select(ErrorFilterModel).where(ErrorFilterModel.FK_Chat == chat_id)

        if active_only:
            stmt = stmt.where(ErrorFilterModel.FIsActive.is_(True))

        db_logger.debug(f"📝 SQL: {stmt.compile(compile_kwargs={'literal_binds': True})}")

        result = await session.execute(stmt)
        filters = list(result.scalars().all())

        db_logger.info(f"✅ [get_filters_by_chat] Found {len(filters)} filters for chat {chat_id}")
        return filters

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
        db_logger.info(f"🔍 [is_error_filtered] Checking if error #{error.FID} is filtered in chat {chat_id}")

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
                            db_logger.debug(
                                f"✅ [is_error_filtered] Error #{error.FID} filtered by regex: {filter_.FPattern}"
                            )
                            return True
                    except re.error:
                        continue
                else:
                    pattern_type = filter_.FPatternType
                    if pattern_type == "exact":
                        if error.FErrorMessage == filter_.FPattern:
                            db_logger.debug(
                                f"✅ [is_error_filtered] Error #{error.FID} filtered by exact match: {filter_.FPattern}"
                            )
                            return True
                    elif pattern_type == "contains" and filter_.FPattern.lower() in error.FErrorMessage.lower():
                        db_logger.debug(
                            f"✅ [is_error_filtered] Error #{error.FID} filtered by contains: {filter_.FPattern}"
                        )
                        return True

        db_logger.debug(f"ℹ️ [is_error_filtered] Error #{error.FID} not filtered")
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
        db_logger.info(f"🆕 [create_filter] Creating filter for chat {chat_id}: pattern={pattern}")

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

        db_logger.info(f"✅ [create_filter] Created filter #{filter_.FID} for chat {chat_id}")
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
        db_logger.info(f"🔄 [update_filter] Updating filter #{filter_id}")

        stmt = select(ErrorFilterModel).where(ErrorFilterModel.FID == filter_id)

        db_logger.debug(f"📝 SQL: {stmt.compile(compile_kwargs={'literal_binds': True})}")

        result = await session.execute(stmt)
        filter_: ErrorFilterModel | None = result.scalar_one_or_none()

        if filter_ is None:
            db_logger.warning(f"⚠️ [update_filter] Filter #{filter_id} not found")
            return None

        for key, value in kwargs.items():
            if hasattr(filter_, key):
                setattr(filter_, key, value)

        await session.flush()

        db_logger.info(f"✅ [update_filter] Updated filter #{filter_id}")
        return filter_

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
        db_logger.info(f"🗑️ [delete_filter] Deleting filter #{filter_id}")

        stmt = select(ErrorFilterModel).where(ErrorFilterModel.FID == filter_id)

        db_logger.debug(f"📝 SQL: {stmt.compile(compile_kwargs={'literal_binds': True})}")

        result = await session.execute(stmt)
        filter_ = result.scalar_one_or_none()

        if not filter_:
            db_logger.warning(f"⚠️ [delete_filter] Filter #{filter_id} not found")
            return False

        filter_.FIsActive = False
        await session.flush()

        db_logger.info(f"✅ [delete_filter] Filter #{filter_id} deactivated")
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
        db_logger.info(f"🔄 [activate_filter] Activating filter #{filter_id}")

        stmt = select(ErrorFilterModel).where(ErrorFilterModel.FID == filter_id)

        db_logger.debug(f"📝 SQL: {stmt.compile(compile_kwargs={'literal_binds': True})}")

        result = await session.execute(stmt)
        filter_ = result.scalar_one_or_none()

        if not filter_:
            db_logger.warning(f"⚠️ [activate_filter] Filter #{filter_id} not found")
            return False

        filter_.FIsActive = True
        await session.flush()

        db_logger.info(f"✅ [activate_filter] Filter #{filter_id} activated")
        return True
