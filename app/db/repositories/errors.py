import hashlib
from datetime import datetime, timedelta
from typing import Any

from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from ...logger import db_logger
from ...models import (
    ChatMessageModel,
    ChatModel,
    ErrorCategory,
    ErrorMessageLinkModel,
    ErrorModel,
    ErrorSeverity,
    ErrorStatus,
    MessageSource,
    MessageType,
    UserModel,
    datetime_now,
)
from ...utils.decorators import log_exceptions


class ErrorRepository:
    """Репозиторий для работы с ошибками"""

    # ==================== СОЗДАНИЕ ОШИБКИ ====================

    @staticmethod
    @log_exceptions(db_logger)
    async def create_error(
        session: AsyncSession,
        error_code: str,
        error_message: str,
        source_system: str,
        source_module: str | None = None,
        category: ErrorCategory = ErrorCategory.EXTERNAL,
        severity: ErrorSeverity = ErrorSeverity.ERROR,
        user_id: int | None = None,
        user_login: str | None = None,
        details: str | None = None,
        group_hash: str | None = None,
    ) -> ErrorModel:
        """
        Создание новой ошибки.

        Args:
            session: Сессия БД
            error_code: Код ошибки
            error_message: Сообщение об ошибке
            source_system: Система-источник
            source_module: Модуль-источник
            category: Категория ошибки
            severity: Степень серьезности
            user_id: ID пользователя
            user_login: Логин пользователя
            details: Детали ошибки
            group_hash: Хеш для группировки

        Returns:
            ErrorModel: Созданная ошибка
        """
        db_logger.info(f"🆕 [create_error] Creating error: code={error_code}, source={source_system}")

        if group_hash is None:
            group_hash = ErrorRepository.create_group_hash(error_code, error_message, source_system)

        error = ErrorModel(
            FErrorCode=error_code[:100],
            FErrorMessage=error_message[:500],
            FErrorDetails=details[:1000] if details else None,
            FSourceSystem=source_system[:100],
            FSourceModule=source_module[:100] if source_module else None,
            FCategory=category,
            FSeverity=severity,
            FStatus=ErrorStatus.NEW,
            FUserID=user_id,
            FUserLogin=user_login[:100] if user_login else None,
            FGroupHash=group_hash,
            FCountOccurrences=1,
            FFirstOccurrence=datetime_now(),
            FLastOccurrence=datetime_now(),
        )

        session.add(error)
        await session.flush()

        db_logger.info(f"✅ [create_error] Created error #{error.FID} with group_hash={group_hash[:8]}...")
        return error

    # ==================== ПОИСК И ПОЛУЧЕНИЕ ====================

    @staticmethod
    @log_exceptions(db_logger)
    async def get_error_by_id(
        session: AsyncSession,
        error_id: int,
    ) -> ErrorModel | None:
        """
        Получение ошибки по ID.

        Args:
            session: Сессия БД
            error_id: ID ошибки

        Returns:
            ErrorModel | None: Найденная ошибка или None
        """
        db_logger.info(f"🔍 [get_error_by_id] Getting error by ID: {error_id}")

        stmt = select(ErrorModel).where(ErrorModel.FID == error_id)

        db_logger.debug(f"📝 SQL: {stmt.compile(compile_kwargs={'literal_binds': True})}")

        result = await session.execute(stmt)
        error: ErrorModel | None = result.scalar_one_or_none()

        if error:
            db_logger.info(f"✅ [get_error_by_id] Found error #{error_id}")
        else:
            db_logger.warning(f"⚠️ [get_error_by_id] Error #{error_id} not found")

        return error

    @staticmethod
    @log_exceptions(db_logger)
    async def find_existing_error(
        session: AsyncSession,
        group_hash: str,
        statuses: list[ErrorStatus] | None = None,
    ) -> ErrorModel | None:
        """
        Поиск существующей ошибки по хешу и статусу.

        Args:
            session: Сессия БД
            group_hash: Хеш для группировки
            statuses: Список статусов для поиска

        Returns:
            ErrorModel | None: Найденная ошибка или None
        """
        db_logger.info(f"🔍 [find_existing_error] Finding existing error by hash: {group_hash[:8]}...")

        if statuses is None:
            statuses = [ErrorStatus.NEW, ErrorStatus.IN_PROGRESS]

        stmt = select(ErrorModel).where(
            ErrorModel.FGroupHash == group_hash,
            ErrorModel.FStatus.in_(statuses),
        )

        db_logger.debug(f"📝 SQL: {stmt.compile(compile_kwargs={'literal_binds': True})}")

        result = await session.execute(stmt)
        error: ErrorModel | None = result.scalar_one_or_none()

        if error:
            db_logger.info(f"✅ [find_existing_error] Found existing error #{error.FID}")
        else:
            db_logger.debug(f"ℹ️ [find_existing_error] No existing error found for hash {group_hash[:8]}...")

        return error

    @staticmethod
    @log_exceptions(db_logger)
    async def get_errors(
        session: AsyncSession,
        status: ErrorStatus | None = None,
        category: ErrorCategory | None = None,
        severity: ErrorSeverity | None = None,
        source_system: str | None = None,
        user_id: int | None = None,
        start_date: datetime | None = None,
        end_date: datetime | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> list[ErrorModel]:
        """
        Получение списка ошибок с фильтрацией.

        Args:
            session: Сессия БД
            status: Фильтр по статусу
            category: Фильтр по категории
            severity: Фильтр по серьезности
            source_system: Фильтр по системе-источнику
            user_id: Фильтр по ID пользователя
            start_date: Начальная дата
            end_date: Конечная дата
            limit: Лимит записей
            offset: Смещение

        Returns:
            list[ErrorModel]: Список ошибок
        """
        db_logger.info(f"📋 [get_errors] Getting errors with filters: status={status}, category={category}")

        stmt = select(ErrorModel)

        if status is not None:
            stmt = stmt.where(ErrorModel.FStatus == status)

        if category is not None:
            stmt = stmt.where(ErrorModel.FCategory == category)

        if severity is not None:
            stmt = stmt.where(ErrorModel.FSeverity == severity)

        if source_system is not None:
            stmt = stmt.where(ErrorModel.FSourceSystem == source_system)

        if user_id is not None:
            stmt = stmt.where(ErrorModel.FUserID == user_id)

        if start_date is not None:
            stmt = stmt.where(ErrorModel.FCreatedAt >= start_date)

        if end_date is not None:
            stmt = stmt.where(ErrorModel.FCreatedAt <= end_date)

        stmt = stmt.order_by(ErrorModel.FCreatedAt.desc()).limit(limit).offset(offset)

        db_logger.debug(f"📝 SQL: {stmt.compile(compile_kwargs={'literal_binds': True})}")

        result = await session.execute(stmt)
        errors = list(result.scalars().all())

        db_logger.info(f"✅ [get_errors] Found {len(errors)} errors")
        return errors

    @staticmethod
    @log_exceptions(db_logger)
    async def get_errors_by_status(
        session: AsyncSession,
        status: ErrorStatus,
        limit: int = 100,
        offset: int = 0,
    ) -> list[ErrorModel]:
        """
        Получение ошибок по статусу.

        Args:
            session: Сессия БД
            status: Статус ошибки
            limit: Лимит записей
            offset: Смещение

        Returns:
            list[ErrorModel]: Список ошибок
        """
        db_logger.info(f"📋 [get_errors_by_status] Getting errors by status: {status}")

        stmt = (
            select(ErrorModel)
            .where(ErrorModel.FStatus == status)
            .order_by(ErrorModel.FCreatedAt.desc())
            .limit(limit)
            .offset(offset)
        )

        db_logger.debug(f"📝 SQL: {stmt.compile(compile_kwargs={'literal_binds': True})}")

        result = await session.execute(stmt)
        errors = list(result.scalars().all())

        db_logger.info(f"✅ [get_errors_by_status] Found {len(errors)} errors with status {status}")
        return errors

    @staticmethod
    @log_exceptions(db_logger)
    async def get_errors_by_user(
        session: AsyncSession,
        user_id: int,
        status: ErrorStatus | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> list[ErrorModel]:
        """
        Получение ошибок пользователя.

        Args:
            session: Сессия БД
            user_id: ID пользователя
            status: Статус ошибки (опционально)
            limit: Лимит записей
            offset: Смещение

        Returns:
            list[ErrorModel]: Список ошибок
        """
        db_logger.info(f"📋 [get_errors_by_user] Getting errors for user {user_id}")

        stmt = select(ErrorModel).where(ErrorModel.FUserID == user_id)

        if status is not None:
            stmt = stmt.where(ErrorModel.FStatus == status)

        stmt = stmt.order_by(ErrorModel.FCreatedAt.desc()).limit(limit).offset(offset)

        db_logger.debug(f"📝 SQL: {stmt.compile(compile_kwargs={'literal_binds': True})}")

        result = await session.execute(stmt)
        errors = list(result.scalars().all())

        db_logger.info(f"✅ [get_errors_by_user] Found {len(errors)} errors for user {user_id}")
        return errors

    @staticmethod
    @log_exceptions(db_logger)
    async def get_errors_by_source(
        session: AsyncSession,
        source_system: str,
        status: ErrorStatus | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> list[ErrorModel]:
        """
        Получение ошибок по системе-источнику.

        Args:
            session: Сессия БД
            source_system: Система-источник
            status: Статус ошибки (опционально)
            limit: Лимит записей
            offset: Смещение

        Returns:
            list[ErrorModel]: Список ошибок
        """
        db_logger.info(f"📋 [get_errors_by_source] Getting errors from source: {source_system}")

        stmt = select(ErrorModel).where(ErrorModel.FSourceSystem == source_system)

        if status is not None:
            stmt = stmt.where(ErrorModel.FStatus == status)

        stmt = stmt.order_by(ErrorModel.FCreatedAt.desc()).limit(limit).offset(offset)

        db_logger.debug(f"📝 SQL: {stmt.compile(compile_kwargs={'literal_binds': True})}")

        result = await session.execute(stmt)
        errors = list(result.scalars().all())

        db_logger.info(f"✅ [get_errors_by_source] Found {len(errors)} errors from source {source_system}")
        return errors

    # ==================== ОБНОВЛЕНИЕ ОШИБКИ ====================

    @staticmethod
    @log_exceptions(db_logger)
    async def increment_occurrences(
        session: AsyncSession,
        error_id: int,
        details: str | None = None,
    ) -> ErrorModel | None:
        """
        Увеличение счетчика повторений ошибки.

        Args:
            session: Сессия БД
            error_id: ID ошибки
            details: Новые детали (опционально)

        Returns:
            ErrorModel | None: Обновленная ошибка или None
        """
        db_logger.info(f"🔄 [increment_occurrences] Incrementing occurrences for error #{error_id}")

        stmt = select(ErrorModel).where(ErrorModel.FID == error_id)

        db_logger.debug(f"📝 SQL: {stmt.compile(compile_kwargs={'literal_binds': True})}")

        result = await session.execute(stmt)
        error = result.scalar_one_or_none()

        # Проверка типа
        if error is None:
            db_logger.warning(f"⚠️ [increment_occurrences] Error #{error_id} not found")
            return None

        error.FCountOccurrences += 1
        error.FLastOccurrence = datetime_now()
        if details:
            error.FErrorDetails = details[:1000]

        await session.flush()

        db_logger.info(f"✅ [increment_occurrences] Error #{error_id} now has {error.FCountOccurrences} occurrences")
        return error  # type: ignore[no-any-return]

    @staticmethod
    @log_exceptions(db_logger)
    async def resolve_error(
        session: AsyncSession,
        error_id: int,
        resolved_by: int,
        resolved_note: str | None = None,
    ) -> tuple[bool, str | None]:
        """
        Отметка ошибки как решенной.

        Args:
            session: Сессия БД
            error_id: ID ошибки
            resolved_by: ID пользователя, который решает ошибку
            resolved_note: Примечание к решению

        Returns:
            tuple[bool, str | None]: (успех, сообщение об ошибке)
        """
        db_logger.info(f"✅ [resolve_error] Resolving error #{error_id} by user {resolved_by}")

        error = await ErrorRepository.get_error_by_id(session, error_id)

        if not error:
            db_logger.warning(f"⚠️ [resolve_error] Error #{error_id} not found")
            return False, "Error not found"

        if error.FStatus == ErrorStatus.RESOLVED:
            db_logger.warning(f"⚠️ [resolve_error] Error #{error_id} already resolved")
            return False, "Error already resolved"

        error.FStatus = ErrorStatus.RESOLVED
        error.FResolvedBy = resolved_by
        error.FResolvedAt = datetime_now()
        if resolved_note:
            error.FResolvedNote = resolved_note[:1000]

        await session.commit()

        db_logger.info(f"✅ [resolve_error] Error #{error_id} resolved by user {resolved_by}")
        return True, "Error resolved successfully"

    @staticmethod
    @log_exceptions(db_logger)
    async def reopen_error(
        session: AsyncSession,
        error_id: int,
    ) -> tuple[bool, str | None]:
        """
        Переоткрытие ранее решенной ошибки.

        Args:
            session: Сессия БД
            error_id: ID ошибки

        Returns:
            tuple[bool, str | None]: (успех, сообщение об ошибке)
        """
        db_logger.info(f"🔄 [reopen_error] Reopening error #{error_id}")

        error = await ErrorRepository.get_error_by_id(session, error_id)

        if not error:
            db_logger.warning(f"⚠️ [reopen_error] Error #{error_id} not found")
            return False, "Error not found"

        if error.FStatus != ErrorStatus.RESOLVED:
            db_logger.warning(f"⚠️ [reopen_error] Error #{error_id} is not resolved (status={error.FStatus})")
            return False, "Error is not resolved"

        error.FStatus = ErrorStatus.REOPENED
        error.FReopenedCount += 1
        error.FReopenedAt = datetime_now()
        error.FResolvedBy = None
        error.FResolvedAt = None

        await session.commit()

        db_logger.info(f"✅ [reopen_error] Error #{error_id} reopened (reopened_count={error.FReopenedCount})")
        return True, "Error reopened"

    @staticmethod
    @log_exceptions(db_logger)
    async def update_error_status(
        session: AsyncSession,
        error_id: int,
        status: ErrorStatus,
        note: str | None = None,
    ) -> ErrorModel | None:
        """
        Обновление статуса ошибки.

        Args:
            session: Сессия БД
            error_id: ID ошибки
            status: Новый статус
            note: Примечание

        Returns:
            ErrorModel | None: Обновленная ошибка или None
        """
        db_logger.info(f"🔄 [update_error_status] Updating error #{error_id} status to {status}")

        error = await ErrorRepository.get_error_by_id(session, error_id)

        if not error:
            db_logger.warning(f"⚠️ [update_error_status] Error #{error_id} not found")
            return None

        error.FStatus = status
        if note:
            error.FResolvedNote = note[:1000]

        await session.flush()

        db_logger.info(f"✅ [update_error_status] Error #{error_id} status updated to {status}")
        return error  # type: ignore[no-any-return]

    # ==================== СВЯЗЬ С СООБЩЕНИЯМИ ====================

    @staticmethod
    @log_exceptions(db_logger)
    async def link_message(
        session: AsyncSession,
        error_id: int,
        message_id: int,
    ) -> ErrorMessageLinkModel | None:
        """
        Связывание ошибки с сообщением.

        Args:
            session: Сессия БД
            error_id: ID ошибки
            message_id: ID сообщения

        Returns:
            ErrorMessageLinkModel | None: Созданная связь или None
        """
        db_logger.info(f"🔗 [link_message] Linking error #{error_id} with message #{message_id}")

        # Проверка, нет ли уже такой связи
        stmt = select(ErrorMessageLinkModel).where(
            ErrorMessageLinkModel.FK_Error == error_id,
            ErrorMessageLinkModel.FK_Message == message_id,
        )

        db_logger.debug(f"📝 SQL: {stmt.compile(compile_kwargs={'literal_binds': True})}")

        result = await session.execute(stmt)
        existing: ErrorMessageLinkModel | None = result.scalar_one_or_none()

        if existing is not None:
            db_logger.debug(f"ℹ️ [link_message] Link already exists between #{error_id} and #{message_id}")
            return existing

        link = ErrorMessageLinkModel(
            FK_Error=error_id,
            FK_Message=message_id,
        )
        session.add(link)
        await session.flush()

        db_logger.info(f"✅ [link_message] Created link between error #{error_id} and message #{message_id}")
        return link

    @staticmethod
    @log_exceptions(db_logger)
    async def unlink_message(
        session: AsyncSession,
        error_id: int,
        message_id: int,
    ) -> bool:
        """
        Удаление связи ошибки с сообщением.

        Args:
            session: Сессия БД
            error_id: ID ошибки
            message_id: ID сообщения

        Returns:
            bool: Успешно ли удалено
        """
        db_logger.info(f"🔗 [unlink_message] Unlinking error #{error_id} from message #{message_id}")

        stmt = delete(ErrorMessageLinkModel).where(
            ErrorMessageLinkModel.FK_Error == error_id,
            ErrorMessageLinkModel.FK_Message == message_id,
        )

        db_logger.debug(f"📝 SQL: {stmt.compile(compile_kwargs={'literal_binds': True})}")

        result = await session.execute(stmt)
        await session.commit()

        success = result.rowcount > 0 if hasattr(result, "rowcount") else False

        if success:
            db_logger.info(f"✅ [unlink_message] Unlinked error #{error_id} from message #{message_id}")
        else:
            db_logger.warning(f"⚠️ [unlink_message] Link not found between #{error_id} and #{message_id}")

        return success

    @staticmethod
    @log_exceptions(db_logger)
    async def unlink_all_messages(
        session: AsyncSession,
        error_id: int,
    ) -> int:
        """
        Удаление всех связей ошибки с сообщениями.

        Args:
            session: Сессия БД
            error_id: ID ошибки

        Returns:
            int: Количество удаленных связей
        """
        db_logger.info(f"🔗 [unlink_all_messages] Unlinking all messages from error #{error_id}")

        stmt = delete(ErrorMessageLinkModel).where(ErrorMessageLinkModel.FK_Error == error_id)

        db_logger.debug(f"📝 SQL: {stmt.compile(compile_kwargs={'literal_binds': True})}")

        result = await session.execute(stmt)
        await session.commit()

        rowcount = result.rowcount if hasattr(result, "rowcount") else 0

        db_logger.info(f"✅ [unlink_all_messages] Unlinked {rowcount} messages from error #{error_id}")
        return rowcount

    @staticmethod
    @log_exceptions(db_logger)
    async def get_linked_messages(
        session: AsyncSession,
        error_id: int,
    ) -> list[ChatMessageModel]:
        """
        Получение всех сообщений, связанных с ошибкой.

        Args:
            session: Сессия БД
            error_id: ID ошибки

        Returns:
            list[ChatMessageModel]: Список сообщений
        """
        db_logger.info(f"📋 [get_linked_messages] Getting messages linked to error #{error_id}")

        stmt = (
            select(ChatMessageModel)
            .join(ErrorMessageLinkModel, ErrorMessageLinkModel.FK_Message == ChatMessageModel.FID)
            .where(ErrorMessageLinkModel.FK_Error == error_id)
        )

        db_logger.debug(f"📝 SQL: {stmt.compile(compile_kwargs={'literal_binds': True})}")

        result = await session.execute(stmt)
        messages = list(result.scalars().all())

        db_logger.info(f"✅ [get_linked_messages] Found {len(messages)} messages linked to error #{error_id}")
        return messages

    @staticmethod
    @log_exceptions(db_logger)
    async def get_linked_message_count(
        session: AsyncSession,
        error_id: int,
    ) -> int:
        """
        Получение количества сообщений, связанных с ошибкой.

        Args:
            session: Сессия БД
            error_id: ID ошибки

        Returns:
            int: Количество сообщений
        """
        db_logger.info(f"📊 [get_linked_message_count] Getting linked message count for error #{error_id}")

        stmt = select(func.count()).select_from(ErrorMessageLinkModel).where(ErrorMessageLinkModel.FK_Error == error_id)

        db_logger.debug(f"📝 SQL: {stmt.compile(compile_kwargs={'literal_binds': True})}")

        result = await session.execute(stmt)
        count = result.scalar() or 0

        db_logger.info(f"✅ [get_linked_message_count] Error #{error_id} has {count} linked messages")
        return count

    # ==================== УДАЛЕНИЕ ОШИБКИ ====================

    @staticmethod
    @log_exceptions(db_logger)
    async def delete_error(
        session: AsyncSession,
        error_id: int,
        delete_linked: bool = True,
    ) -> bool:
        """
        Удаление ошибки.

        Args:
            session: Сессия БД
            error_id: ID ошибки
            delete_linked: Удалять ли связанные сообщения

        Returns:
            bool: Успешно ли удалено
        """
        db_logger.info(f"🗑️ [delete_error] Deleting error #{error_id}")

        error = await ErrorRepository.get_error_by_id(session, error_id)

        if not error:
            db_logger.warning(f"⚠️ [delete_error] Error #{error_id} not found")
            return False

        if delete_linked:
            # Удаление связей
            stmt = delete(ErrorMessageLinkModel).where(ErrorMessageLinkModel.FK_Error == error_id)

            db_logger.debug(f"📝 SQL (delete links): {stmt.compile(compile_kwargs={'literal_binds': True})}")

            await session.execute(stmt)

        # Удаление ошибки
        stmt = delete(ErrorModel).where(ErrorModel.FID == error_id)

        db_logger.debug(f"📝 SQL: {stmt.compile(compile_kwargs={'literal_binds': True})}")

        result = await session.execute(stmt)
        await session.commit()

        rowcount = getattr(result, "rowcount", 0)
        success = rowcount > 0 if isinstance(rowcount, int) else False

        if success:
            db_logger.info(f"✅ [delete_error] Error #{error_id} deleted")
        else:
            db_logger.warning(f"⚠️ [delete_error] Error #{error_id} not found")

        return success

    @staticmethod
    @log_exceptions(db_logger)
    async def delete_errors_batch(
        session: AsyncSession,
        error_ids: list[int],
        delete_linked: bool = True,
    ) -> int:
        """
        Пакетное удаление ошибок.

        Args:
            session: Сессия БД
            error_ids: Список ID ошибок
            delete_linked: Удалять ли связанные сообщения

        Returns:
            int: Количество удаленных ошибок
        """
        if not error_ids:
            db_logger.debug("ℹ️ [delete_errors_batch] No error IDs provided")
            return 0

        db_logger.info(f"🗑️ [delete_errors_batch] Batch deleting {len(error_ids)} errors")

        if delete_linked:
            # Удаление связей
            stmt = delete(ErrorMessageLinkModel).where(ErrorMessageLinkModel.FK_Error.in_(error_ids))

            db_logger.debug(f"📝 SQL (delete links): {stmt.compile(compile_kwargs={'literal_binds': True})}")

            await session.execute(stmt)

        # Удаление ошибки
        stmt = delete(ErrorModel).where(ErrorModel.FID.in_(error_ids))

        db_logger.debug(f"📝 SQL: {stmt.compile(compile_kwargs={'literal_binds': True})}")

        result = await session.execute(stmt)
        await session.commit()

        rowcount = result.rowcount if hasattr(result, "rowcount") else len(error_ids)

        db_logger.info(f"✅ [delete_errors_batch] Deleted {rowcount} errors")
        return rowcount

    # ==================== СТАТИСТИКА ====================

    @staticmethod
    @log_exceptions(db_logger)
    async def get_stats(
        session: AsyncSession,
        start_date: datetime | None = None,
        end_date: datetime | None = None,
        category: ErrorCategory | None = None,
    ) -> dict[str, Any]:
        """
        Получение статистики по ошибкам.

        Args:
            session: Сессия БД
            start_date: Начальная дата
            end_date: Конечная дата
            category: Категория ошибки

        Returns:
            dict: Статистика
        """
        db_logger.info(f"📊 [get_stats] Getting error stats: start={start_date}, end={end_date}")

        if not start_date:
            start_date = datetime_now() - timedelta(days=7)
        if not end_date:
            end_date = datetime_now()

        stmt = select(
            func.count(ErrorModel.FID).label("total"),
            func.sum(ErrorModel.FCountOccurrences).label("total_occurrences"),
            func.count(ErrorModel.FID).filter(ErrorModel.FStatus == ErrorStatus.NEW).label("new"),
            func.count(ErrorModel.FID).filter(ErrorModel.FStatus == ErrorStatus.IN_PROGRESS).label("in_progress"),
            func.count(ErrorModel.FID).filter(ErrorModel.FStatus == ErrorStatus.RESOLVED).label("resolved"),
            func.count(ErrorModel.FID).filter(ErrorModel.FStatus == ErrorStatus.REOPENED).label("reopened"),
            func.count(ErrorModel.FID).filter(ErrorModel.FStatus == ErrorStatus.DISMISSED).label("dismissed"),
        ).where(
            ErrorModel.FCreatedAt >= start_date,
            ErrorModel.FCreatedAt <= end_date,
        )

        if category is not None:
            stmt = stmt.where(ErrorModel.FCategory == category)

        db_logger.debug(f"📝 SQL: {stmt.compile(compile_kwargs={'literal_binds': True})}")

        result = await session.execute(stmt)
        stats = result.first()

        if stats is None:
            return {
                "total": 0,
                "total_occurrences": 0,
                "new": 0,
                "in_progress": 0,
                "resolved": 0,
                "reopened": 0,
                "dismissed": 0,
                "resolution_rate": 0,
                "period": {
                    "start": start_date.isoformat(),
                    "end": end_date.isoformat(),
                },
            }

        stats_dict = {
            "total": stats.total or 0,
            "total_occurrences": stats.total_occurrences or 0,
            "new": stats.new or 0,
            "in_progress": stats.in_progress or 0,
            "resolved": stats.resolved or 0,
            "reopened": stats.reopened or 0,
            "dismissed": stats.dismissed or 0,
            "resolution_rate": (stats.resolved / stats.total * 100) if stats.total else 0,
            "period": {
                "start": start_date.isoformat(),
                "end": end_date.isoformat(),
            },
        }

        db_logger.info(f"✅ [get_stats] Stats: total={stats_dict['total']}, resolved={stats_dict['resolved']}")
        return stats_dict

    @staticmethod
    @log_exceptions(db_logger)
    async def get_user_stats(
        session: AsyncSession,
        user_id: int,
    ) -> dict[str, Any]:
        """
        Получение статистики пользователя по решению ошибок.

        Args:
            session: Сессия БД
            user_id: ID пользователя

        Returns:
            dict: Статистика пользователя
        """
        db_logger.info(f"📊 [get_user_stats] Getting stats for user {user_id}")

        total_stmt = select(
            func.count(ErrorModel.FID).label("total"),
            func.count(ErrorModel.FID).filter(ErrorModel.FStatus == ErrorStatus.RESOLVED).label("resolved"),
        ).where(ErrorModel.FResolvedBy == user_id)

        db_logger.debug(f"📝 SQL (total): {total_stmt.compile(compile_kwargs={'literal_binds': True})}")

        total_result = await session.execute(total_stmt)
        total_stats = total_result.first()

        if total_stats is None:
            return {
                "user_id": user_id,
                "total_solved": 0,
                "total_errors": 0,
                "success_rate": 0,
                "daily": [],
            }

        # Статистика по дням
        daily_stmt = (
            select(
                func.date(ErrorModel.FResolvedAt).label("date"),
                func.count(ErrorModel.FID).label("resolved"),
            )
            .where(
                ErrorModel.FResolvedBy == user_id,
                ErrorModel.FResolvedAt.is_not(None),
            )
            .group_by(func.date(ErrorModel.FResolvedAt))
            .order_by(func.date(ErrorModel.FResolvedAt).desc())
            .limit(30)
        )

        db_logger.debug(f"📝 SQL (daily): {daily_stmt.compile(compile_kwargs={'literal_binds': True})}")

        daily_result = await session.execute(daily_stmt)
        daily = [
            {"date": row.date.isoformat() if row.date else None, "resolved": row.resolved} for row in daily_result.all()
        ]

        result = {
            "user_id": user_id,
            "total_solved": total_stats.resolved or 0,
            "total_errors": total_stats.total or 0,
            "success_rate": (total_stats.resolved / total_stats.total * 100) if total_stats.total else 0,
            "daily": daily,
        }

        db_logger.info(
            f"✅ [get_user_stats] User {user_id}: solved={result['total_solved']}, rate={result['success_rate']:.1f}%"
        )
        return result

    @staticmethod
    @log_exceptions(db_logger)
    async def get_top_resolvers(
        session: AsyncSession,
        start_date: datetime | None = None,
        end_date: datetime | None = None,
        limit: int = 5,
    ) -> list[dict[str, Any]]:
        """
        Получение топ-пользователей по решению ошибок.

        Args:
            session: Сессия БД
            start_date: Начальная дата
            end_date: Конечная дата
            limit: Количество записей

        Returns:
            list[dict]: Список лидеров
        """
        db_logger.info(f"🏆 [get_top_resolvers] Getting top {limit} resolvers")

        conditions = [ErrorModel.FStatus == ErrorStatus.RESOLVED]

        if start_date is not None:
            conditions.append(ErrorModel.FResolvedAt >= start_date)

        if end_date is not None:
            conditions.append(ErrorModel.FResolvedAt <= end_date)

        stmt = (
            select(
                UserModel.FFirstName.label("first_name"),
                UserModel.FLastName.label("last_name"),
                UserModel.FUserName.label("username"),
                func.count(ErrorModel.FID).label("solved"),
            )
            .join(ErrorModel, ErrorModel.FResolvedBy == UserModel.FID)
            .where(*conditions)
            .group_by(UserModel.FID, UserModel.FFirstName, UserModel.FLastName, UserModel.FUserName)
            .order_by(func.count(ErrorModel.FID).desc())
            .limit(limit)
        )

        db_logger.debug(f"📝 SQL: {stmt.compile(compile_kwargs={'literal_binds': True})}")

        result = await session.execute(stmt)
        resolvers = [
            {
                "first_name": row.first_name,
                "last_name": row.last_name,
                "username": row.username,
                "solved": row.solved,
            }
            for row in result.all()
        ]

        db_logger.info(f"✅ [get_top_resolvers] Found top {len(resolvers)} resolvers")
        return resolvers

    @staticmethod
    @log_exceptions(db_logger)
    async def get_category_stats(
        session: AsyncSession,
        start_date: datetime | None = None,
        end_date: datetime | None = None,
    ) -> dict[str, int]:
        """
        Получение статистики по категориям ошибок.

        Args:
            session: Сессия БД
            start_date: Начальная дата
            end_date: Конечная дата

        Returns:
            dict: Статистика по категориям
        """
        db_logger.info("📊 [get_category_stats] Getting category stats")

        if not start_date:
            start_date = datetime_now() - timedelta(days=7)
        if not end_date:
            end_date = datetime_now()

        stmt = (
            select(
                ErrorModel.FCategory,
                func.count(ErrorModel.FID).label("count"),
            )
            .where(
                ErrorModel.FCreatedAt >= start_date,
                ErrorModel.FCreatedAt <= end_date,
            )
            .group_by(ErrorModel.FCategory)
        )

        db_logger.debug(f"📝 SQL: {stmt.compile(compile_kwargs={'literal_binds': True})}")

        result = await session.execute(stmt)
        category_stats: dict[str, int] = {}
        for row in result.all():
            count_value = getattr(row, "count", 0)
            category_stats[row.FCategory.value] = int(count_value) if count_value is not None else 0

        db_logger.info(f"✅ [get_category_stats] Stats: {category_stats}")
        return category_stats

    @staticmethod
    @log_exceptions(db_logger)
    async def get_severity_stats(
        session: AsyncSession,
        start_date: datetime | None = None,
        end_date: datetime | None = None,
    ) -> dict[str, int]:
        """
        Получение статистики по уровням серьезности.

        Args:
            session: Сессия БД
            start_date: Начальная дата
            end_date: Конечная дата

        Returns:
            dict: Статистика по уровням серьезности
        """
        db_logger.info("📊 [get_severity_stats] Getting severity stats")

        if not start_date:
            start_date = datetime_now() - timedelta(days=7)
        if not end_date:
            end_date = datetime_now()

        stmt = (
            select(
                ErrorModel.FSeverity,
                func.count(ErrorModel.FID).label("count"),
            )
            .where(
                ErrorModel.FCreatedAt >= start_date,
                ErrorModel.FCreatedAt <= end_date,
            )
            .group_by(ErrorModel.FSeverity)
        )

        db_logger.debug(f"📝 SQL: {stmt.compile(compile_kwargs={'literal_binds': True})}")

        result = await session.execute(stmt)
        severity_stats: dict[str, int] = {}
        for row in result.all():
            count_value = getattr(row, "count", 0)
            severity_stats[row.FSeverity.value] = int(count_value) if count_value is not None else 0

        db_logger.info(f"✅ [get_severity_stats] Stats: {severity_stats}")
        return severity_stats

    # ==================== ВСПОМОГАТЕЛЬНЫЕ МЕТОДЫ ====================

    @staticmethod
    def create_group_hash(error_code: str, error_message: str, source: str) -> str:
        """
        Создание хеша для группировки ошибок.

        Args:
            error_code: Код ошибки
            error_message: Сообщение об ошибке
            source: Источник

        Returns:
            str: Хеш для группировки
        """
        content = f"{error_code}|{source}|{error_message[:100]}"
        return hashlib.md5(content.encode()).hexdigest()[:16]

    @staticmethod
    @log_exceptions(db_logger)
    async def chat_exists(
        session: AsyncSession,
        chat_id: int,
    ) -> bool:
        """
        Проверка существования чата в БД.

        Args:
            session: Сессия БД
            chat_id: ID чата

        Returns:
            bool: Существует ли чат
        """
        if not chat_id:
            return False

        db_logger.info(f"🔍 [chat_exists] Checking if chat {chat_id} exists")

        try:
            stmt = select(ChatModel).where(ChatModel.FID == chat_id)

            db_logger.debug(f"📝 SQL: {stmt.compile(compile_kwargs={'literal_binds': True})}")

            result = await session.execute(stmt)
            exists = result.scalar_one_or_none() is not None

            db_logger.info(f"✅ [chat_exists] Chat {chat_id} exists: {exists}")
            return exists
        except Exception as e:
            db_logger.warning(f"⚠️ [chat_exists] Failed to check chat existence: {e}")
            return False

    @staticmethod
    @log_exceptions(db_logger)
    async def save_message(
        session: AsyncSession,
        chat_id: int,
        error_type: str,
        error_message: str,
        user_id: int | None = None,
        message_id: int | None = None,
        traceback_text: str | None = None,
        category: ErrorCategory | None = None,
        error_id: int | None = None,
        component: str = "app",
    ) -> ChatMessageModel | None:
        """
        Сохранение сообщения об ошибке в чат.

        Args:
            session: Сессия БД
            chat_id: ID чата
            error_type: Тип ошибки
            error_message: Сообщение об ошибке
            user_id: ID пользователя
            message_id: ID сообщения
            traceback_text: Текст traceback
            category: Категория ошибки
            error_id: ID ошибки
            component: Компонент

        Returns:
            ChatMessageModel | None: Созданное сообщение или None
        """
        db_logger.info(f"💾 [save_message] Saving error message to chat {chat_id}: {error_type}")

        if not chat_id:
            db_logger.warning("⚠️ [save_message] Cannot save message: chat_id is None")
            return None

        message_text = f"❌ Ошибка в {component}: {error_type}"
        if error_message:
            message_text += f"\n{error_message[:200]}"
        if error_id:
            message_text += f"\nError ID: {error_id}"

        chat_message = ChatMessageModel(
            FID=message_id or 0,
            FK_Chat=chat_id,
            FK_User=user_id,
            FK_MessageType=MessageType.SYSTEM_ALERT,
            FSource=MessageSource.SYSTEM,
            FText=message_text[:4096],
            FErrorMessage=f"{error_type}: {error_message[:500]}",
            FErrorTraceback=traceback_text[:1000] if traceback_text else None,
            FCategory=category.value if category else "error",
            FDateSent=datetime_now(),
        )
        session.add(chat_message)
        await session.flush()

        db_logger.info(f"✅ [save_message] Saved error message to chat {chat_id}")
        return chat_message

    @staticmethod
    @log_exceptions(db_logger)
    async def get_error_by_group_hash(
        session: AsyncSession,
        group_hash: str,
    ) -> ErrorModel | None:
        """
        Получение ошибки по хешу группы.

        Args:
            session: Сессия БД
            group_hash: Хеш группы

        Returns:
            ErrorModel | None: Найденная ошибка или None
        """
        db_logger.info(f"🔍 [get_error_by_group_hash] Getting error by hash: {group_hash[:8]}...")

        stmt = select(ErrorModel).where(ErrorModel.FGroupHash == group_hash)

        db_logger.debug(f"📝 SQL: {stmt.compile(compile_kwargs={'literal_binds': True})}")

        result = await session.execute(stmt)
        error: ErrorModel | None = result.scalar_one_or_none()

        if error:
            db_logger.info(f"✅ [get_error_by_group_hash] Found error #{error.FID}")
        else:
            db_logger.warning(f"⚠️ [get_error_by_group_hash] No error found for hash {group_hash[:8]}...")

        return error

    @staticmethod
    @log_exceptions(db_logger)
    async def get_errors_by_date_range(
        session: AsyncSession,
        start_date: datetime,
        end_date: datetime,
        limit: int = 100,
        offset: int = 0,
    ) -> list[ErrorModel]:
        """
        Получение ошибок за период.

        Args:
            session: Сессия БД
            start_date: Начальная дата
            end_date: Конечная дата
            limit: Лимит записей
            offset: Смещение

        Returns:
            list[ErrorModel]: Список ошибок
        """
        db_logger.info(f"📋 [get_errors_by_date_range] Getting errors from {start_date} to {end_date}")

        stmt = (
            select(ErrorModel)
            .where(
                ErrorModel.FCreatedAt >= start_date,
                ErrorModel.FCreatedAt <= end_date,
            )
            .order_by(ErrorModel.FCreatedAt.desc())
            .limit(limit)
            .offset(offset)
        )

        db_logger.debug(f"📝 SQL: {stmt.compile(compile_kwargs={'literal_binds': True})}")

        result = await session.execute(stmt)
        errors = list(result.scalars().all())

        db_logger.info(f"✅ [get_errors_by_date_range] Found {len(errors)} errors in range")
        return errors

    @staticmethod
    @log_exceptions(db_logger)
    async def get_unresolved_errors(
        session: AsyncSession,
        limit: int = 100,
        offset: int = 0,
    ) -> list[ErrorModel]:
        """
        Получение нерешенных ошибок.

        Args:
            session: Сессия БД
            limit: Лимит записей
            offset: Смещение

        Returns:
            list[ErrorModel]: Список ошибок
        """
        db_logger.info("📋 [get_unresolved_errors] Getting unresolved errors")

        stmt = (
            select(ErrorModel)
            .where(ErrorModel.FStatus.in_([ErrorStatus.NEW, ErrorStatus.IN_PROGRESS, ErrorStatus.REOPENED]))
            .order_by(ErrorModel.FCreatedAt.desc())
            .limit(limit)
            .offset(offset)
        )

        db_logger.debug(f"📝 SQL: {stmt.compile(compile_kwargs={'literal_binds': True})}")

        result = await session.execute(stmt)
        errors = list(result.scalars().all())

        db_logger.info(f"✅ [get_unresolved_errors] Found {len(errors)} unresolved errors")
        return errors

    @staticmethod
    @log_exceptions(db_logger)
    async def get_errors_count_by_status(
        session: AsyncSession,
    ) -> dict[str, int]:
        """
        Получение количества ошибок по статусам.

        Args:
            session: Сессия БД

        Returns:
            dict: Количество ошибок по статусам
        """
        db_logger.info("📊 [get_errors_count_by_status] Getting error counts by status")

        stmt = select(
            ErrorModel.FStatus,
            func.count(ErrorModel.FID).label("count"),
        ).group_by(ErrorModel.FStatus)

        db_logger.debug(f"📝 SQL: {stmt.compile(compile_kwargs={'literal_binds': True})}")

        result = await session.execute(stmt)
        status_stats: dict[str, int] = {}
        for row in result.all():
            count_value = getattr(row, "count", 0)
            status_stats[row.FStatus.value] = int(count_value) if count_value is not None else 0

        db_logger.info(f"✅ [get_errors_count_by_status] Stats: {status_stats}")
        return status_stats


__all__ = ["ErrorRepository"]
