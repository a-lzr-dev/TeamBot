from datetime import datetime, timedelta
from typing import Any, cast

from sqlalchemy import and_, delete, func, not_, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from ...exceptions import log_exceptions
from ...logger import db_logger
from ...models import ChatMessageModel, MessageType, datetime_now


class MessageRepository:
    """Репозиторий для работы с сообщениями"""

    # ==================== ОСНОВНЫЕ МЕТОДЫ ====================

    @staticmethod
    @log_exceptions(db_logger)
    async def get_message_by_id(session: AsyncSession, message_id: int) -> ChatMessageModel | None:
        """
        Получение сообщения по ID.

        Args:
            session: Сессия БД
            message_id: ID сообщения

        Returns:
            ChatMessageModel | None: Найденное сообщение или None
        """
        stmt = select(ChatMessageModel).where(ChatMessageModel.FID == message_id)
        result = await session.execute(stmt)
        return cast("ChatMessageModel | None", result.scalar_one_or_none())

    @staticmethod
    @log_exceptions(db_logger)
    async def get_messages_by_chat(
        session: AsyncSession, chat_id: int, limit: int = 100, offset: int = 0, include_deleted: bool = False
    ) -> list[ChatMessageModel]:
        """
        Получение сообщений по чату.

        Args:
            session: Сессия БД
            chat_id: ID чата
            limit: Лимит записей
            offset: Смещение
            include_deleted: Включать удаленные сообщения

        Returns:
            list[ChatMessageModel]: Список сообщений
        """
        stmt = select(ChatMessageModel).where(ChatMessageModel.FK_Chat == chat_id)

        if not include_deleted:
            stmt = stmt.where(ChatMessageModel.FFlagDeleted.is_(False))

        stmt = stmt.order_by(ChatMessageModel.FDateSent.desc())
        stmt = stmt.limit(limit).offset(offset)

        result = await session.execute(stmt)
        return cast("list[ChatMessageModel]", list(result.scalars().all()))

    @staticmethod
    @log_exceptions(db_logger)
    async def get_messages_by_filter(
        session: AsyncSession,
        chat_id: int | None = None,
        before_minutes: int = 60,
        message_types: list[MessageType] | None = None,
        exclude_message_types: list[MessageType] | None = None,
        limit: int | None = None,
    ) -> list[ChatMessageModel]:
        """
        Получение сообщений по фильтру с возможностью исключения типов.

        Args:
            session: Сессия БД
            chat_id: ID чата
            before_minutes: Сообщения старше указанного количества минут
            message_types: Список типов для включения (если None - все типы)
            exclude_message_types: Список типов для исключения (приоритет выше)
            limit: Максимальное количество сообщений

        Returns:
            list[ChatMessageModel]: Список сообщений
        """
        cutoff_time = datetime_now() - timedelta(minutes=before_minutes)

        conditions = [ChatMessageModel.FDateSent < cutoff_time, ChatMessageModel.FFlagDeleted.is_(False)]

        # Фильтр по ID чата
        if chat_id:
            conditions.append(ChatMessageModel.FK_Chat == chat_id)

        # Фильтр по типам (включение)
        if message_types:
            conditions.append(ChatMessageModel.FK_MessageType.in_(message_types))

        # Фильтр по типам (исключение)
        if exclude_message_types:
            conditions.append(not_(ChatMessageModel.FK_MessageType.in_(exclude_message_types)))

        stmt = select(ChatMessageModel).where(and_(*conditions)).order_by(ChatMessageModel.FDateSent)

        if limit:
            stmt = stmt.limit(limit)

        result = await session.execute(stmt)
        return cast("list[ChatMessageModel]", list(result.scalars().all()))

    # ==================== СТАТИСТИКА ====================

    @staticmethod
    @log_exceptions(db_logger)
    async def get_message_count_by_chat(session: AsyncSession, chat_id: int) -> int:
        """
        Получение количества активных сообщений в чате.

        Args:
            session: Сессия БД
            chat_id: ID чата

        Returns:
            int: Количество сообщений
        """
        stmt = (
            select(func.count())
            .select_from(ChatMessageModel)
            .where(ChatMessageModel.FK_Chat == chat_id, ChatMessageModel.FFlagDeleted.is_(False))
        )
        result = await session.execute(stmt)
        return result.scalar() or 0

    @staticmethod
    @log_exceptions(db_logger)
    async def get_message_lifetime_stats(session: AsyncSession, chat_id: int | None = None) -> dict[str, Any]:
        """
        Получение статистики по времени жизни сообщений.

        Args:
            session: Сессия БД
            chat_id: ID чата (опционально)

        Returns:
            dict: Статистика по времени жизни
        """
        stmt = select(
            func.count(ChatMessageModel.FID).label("total"),
            func.count(ChatMessageModel.FID).filter(ChatMessageModel.FFlagDeleted.is_(True)).label("deleted"),
            func.count(ChatMessageModel.FID).filter(ChatMessageModel.FExpiresAt.is_not(None)).label("with_expiration"),
            func.count(ChatMessageModel.FID)
            .filter(
                and_(
                    ChatMessageModel.FExpiresAt.is_not(None),
                    ChatMessageModel.FExpiresAt <= datetime_now(),
                    ChatMessageModel.FFlagDeleted.is_(False),
                )
            )
            .label("expired_not_deleted"),
        )

        if chat_id is not None:
            stmt = stmt.where(ChatMessageModel.FK_Chat == chat_id)

        result = await session.execute(stmt)
        stats = result.first()

        return {
            "total": stats.total or 0 if stats else 0,
            "deleted": stats.deleted or 0 if stats else 0,
            "with_expiration": stats.with_expiration or 0 if stats else 0,
            "expired_not_deleted": stats.expired_not_deleted or 0 if stats else 0,
            "expiration_rate": (stats.with_expiration / stats.total * 100) if stats and stats.total else 0,
        }

    # ==================== УПРАВЛЕНИЕ ВРЕМЕНЕМ ЖИЗНИ ====================

    @staticmethod
    @log_exceptions(db_logger)
    async def set_message_lifetime(session: AsyncSession, message_id: int, lifetime_seconds: int) -> bool:
        """
        Установка времени жизни для сообщения.

        Args:
            session: Сессия БД
            message_id: ID сообщения
            lifetime_seconds: Время жизни в секундах

        Returns:
            bool: Успешно ли установлено
        """
        stmt = select(ChatMessageModel).where(
            and_(ChatMessageModel.FID == message_id, ChatMessageModel.FFlagDeleted.is_(False))
        )
        result = await session.execute(stmt)
        message = result.scalar_one_or_none()

        if not message:
            return False

        now = datetime_now()
        message.FLifetimeSeconds = lifetime_seconds
        message.FExpiresAt = now + timedelta(seconds=lifetime_seconds)

        await session.commit()
        return True

    @staticmethod
    @log_exceptions(db_logger)
    async def get_expired_messages(
        session: AsyncSession, chat_id: int | None = None, limit: int = 1000
    ) -> list[ChatMessageModel]:
        """
        Получение сообщений, у которых истекло время жизни.

        Args:
            session: Сессия БД
            chat_id: ID чата (опционально)
            limit: Максимальное количество сообщений

        Returns:
            list[ChatMessageModel]: Список истекших сообщений
        """
        now = datetime_now()

        stmt = select(ChatMessageModel).where(
            and_(
                ChatMessageModel.FFlagDeleted.is_(False),
                ChatMessageModel.FExpiresAt.is_not(None),
                ChatMessageModel.FExpiresAt <= now,
            )
        )

        if chat_id is not None:
            stmt = stmt.where(ChatMessageModel.FK_Chat == chat_id)

        stmt = stmt.limit(limit)

        result = await session.execute(stmt)
        return cast("list[ChatMessageModel]", list(result.scalars().all()))

    # ==================== УДАЛЕНИЕ СООБЩЕНИЙ ====================

    @staticmethod
    @log_exceptions(db_logger)
    async def mark_messages_as_deleted(
        session: AsyncSession,
        message_ids: list[int],
        deleted_by_type: str = "expired",
        deleted_by_message_id: int | None = None,
    ) -> int:
        """
        Отметка сообщений как удаленных.

        Args:
            session: Сессия БД
            message_ids: Список ID сообщений
            deleted_by_type: Тип удаления
            deleted_by_message_id: ID сообщения-инициатора

        Returns:
            int: Количество отмеченных сообщений
        """
        if not message_ids:
            return 0

        now = datetime_now()

        stmt = (
            update(ChatMessageModel)
            .where(ChatMessageModel.FID.in_(message_ids))
            .values(
                FFlagDeleted=True,
                FDateDeleted=now,
                FDeletedByType=deleted_by_type,
                FK_DeletedByMessage=deleted_by_message_id,
            )
        )

        result = await session.execute(stmt)
        await session.commit()

        return result.rowcount if hasattr(result, "rowcount") else len(message_ids)

    @staticmethod
    @log_exceptions(db_logger)
    async def mark_messages_deleted_by_ids(
        session: AsyncSession, message_ids: list[int], deleted_by_type: str = "cleanup"
    ) -> int:
        """
        Отметка конкретных сообщений как удаленных.

        Args:
            session: Сессия БД
            message_ids: Список ID сообщений
            deleted_by_type: Тип удаления

        Returns:
            int: Количество отмеченных сообщений
        """
        if not message_ids:
            return 0

        now = datetime_now()

        stmt = (
            update(ChatMessageModel)
            .where(ChatMessageModel.FID.in_(message_ids))
            .values(FFlagDeleted=True, FDateDeleted=now, FDeletedByType=deleted_by_type)
        )

        result = await session.execute(stmt)
        await session.commit()

        return result.rowcount if hasattr(result, "rowcount") else len(message_ids)

    @staticmethod
    @log_exceptions(db_logger)
    async def restore_deleted_message(session: AsyncSession, message_id: int, chat_id: int | None = None) -> bool:
        """
        Восстановление удаленного сообщения.

        Args:
            session: Сессия БД
            message_id: ID сообщения
            chat_id: ID чата (опционально)

        Returns:
            bool: Успешно ли восстановлено
        """
        try:
            query = select(ChatMessageModel).where(
                ChatMessageModel.FID == message_id, ChatMessageModel.FFlagDeleted.is_(True)
            )
            if chat_id is not None:
                query = query.where(ChatMessageModel.FK_Chat == chat_id)

            result = await session.execute(query)
            message: ChatMessageModel | None = result.scalar_one_or_none()

            if message:
                message.FFlagDeleted = False
                message.FDateDeleted = None
                message.FK_DeletedByMessage = None
                message.FDeletedByType = None
                await session.commit()
                db_logger.info(f"✅ Message {message_id} restored")
                return True

            return False

        except Exception as e:
            db_logger.error(f"❌ Failed to restore message {message_id}: {e}")
            await session.rollback()
            raise

    # ==================== ДОПОЛНИТЕЛЬНЫЕ МЕТОДЫ ====================

    @staticmethod
    @log_exceptions(db_logger)
    async def get_messages_by_date_range(
        session: AsyncSession,
        chat_id: int | None = None,
        start_date: datetime | None = None,
        end_date: datetime | None = None,
        include_deleted: bool = False,
        limit: int = 100,
        offset: int = 0,
    ) -> list[ChatMessageModel]:
        """
        Получение сообщений за период.

        Args:
            session: Сессия БД
            chat_id: ID чата (опционально)
            start_date: Начальная дата
            end_date: Конечная дата
            include_deleted: Включать удаленные сообщения
            limit: Лимит записей
            offset: Смещение

        Returns:
            list[ChatMessageModel]: Список сообщений
        """
        conditions = []

        if chat_id is not None:
            conditions.append(ChatMessageModel.FK_Chat == chat_id)

        if not include_deleted:
            conditions.append(ChatMessageModel.FFlagDeleted.is_(False))

        if start_date is not None:
            conditions.append(ChatMessageModel.FDateSent >= start_date)

        if end_date is not None:
            conditions.append(ChatMessageModel.FDateSent <= end_date)

        stmt = select(ChatMessageModel)
        if conditions:
            stmt = stmt.where(and_(*conditions))

        stmt = stmt.order_by(ChatMessageModel.FDateSent.desc())
        stmt = stmt.limit(limit).offset(offset)

        result = await session.execute(stmt)
        return cast("list[ChatMessageModel]", list(result.scalars().all()))

    @staticmethod
    @log_exceptions(db_logger)
    async def get_messages_by_type(
        session: AsyncSession,
        message_type: MessageType,
        chat_id: int | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> list[ChatMessageModel]:
        """
        Получение сообщений по типу.

        Args:
            session: Сессия БД
            message_type: Тип сообщения
            chat_id: ID чата (опционально)
            limit: Лимит записей
            offset: Смещение

        Returns:
            list[ChatMessageModel]: Список сообщений
        """
        conditions = [ChatMessageModel.FK_MessageType == message_type, ChatMessageModel.FFlagDeleted.is_(False)]

        if chat_id is not None:
            conditions.append(ChatMessageModel.FK_Chat == chat_id)

        stmt = select(ChatMessageModel).where(and_(*conditions))
        stmt = stmt.order_by(ChatMessageModel.FDateSent.desc())
        stmt = stmt.limit(limit).offset(offset)

        result = await session.execute(stmt)
        return cast("list[ChatMessageModel]", list(result.scalars().all()))

    @staticmethod
    @log_exceptions(db_logger)
    async def get_last_message_in_chat(session: AsyncSession, chat_id: int) -> ChatMessageModel | None:
        """
        Получение последнего сообщения в чате.

        Args:
            session: Сессия БД
            chat_id: ID чата

        Returns:
            ChatMessageModel | None: Последнее сообщение или None
        """
        stmt = (
            select(ChatMessageModel)
            .where(ChatMessageModel.FK_Chat == chat_id, ChatMessageModel.FFlagDeleted.is_(False))
            .order_by(ChatMessageModel.FDateSent.desc())
            .limit(1)
        )
        result = await session.execute(stmt)
        return cast("ChatMessageModel | None", result.scalar_one_or_none())

    @staticmethod
    @log_exceptions(db_logger)
    async def get_message_count_by_type(
        session: AsyncSession, message_type: MessageType, chat_id: int | None = None
    ) -> int:
        """
        Получение количества сообщений по типу.

        Args:
            session: Сессия БД
            message_type: Тип сообщения
            chat_id: ID чата (опционально)

        Returns:
            int: Количество сообщений
        """
        conditions = [ChatMessageModel.FK_MessageType == message_type, ChatMessageModel.FFlagDeleted.is_(False)]

        if chat_id is not None:
            conditions.append(ChatMessageModel.FK_Chat == chat_id)

        stmt = select(func.count()).select_from(ChatMessageModel).where(and_(*conditions))
        result = await session.execute(stmt)
        return result.scalar() or 0

    @staticmethod
    @log_exceptions(db_logger)
    async def get_all_message_types_stats(session: AsyncSession, chat_id: int | None = None) -> dict[str, int]:
        """
        Получение статистики по всем типам сообщений.

        Args:
            session: Сессия БД
            chat_id: ID чата (опционально)

        Returns:
            dict: Статистика по типам сообщений
        """
        stats = {}
        for msg_type in MessageType:
            count = await MessageRepository.get_message_count_by_type(
                session=session, message_type=msg_type, chat_id=chat_id
            )
            stats[msg_type.value] = count

        return stats

    @staticmethod
    @log_exceptions(db_logger)
    async def delete_messages_permanently(session: AsyncSession, message_ids: list[int]) -> int:
        """
        Полное удаление сообщений из БД (без возможности восстановления).

        Args:
            session: Сессия БД
            message_ids: Список ID сообщений

        Returns:
            int: Количество удаленных сообщений
        """
        if not message_ids:
            return 0

        stmt = delete(ChatMessageModel).where(ChatMessageModel.FID.in_(message_ids))
        result = await session.execute(stmt)
        await session.commit()

        return result.rowcount if hasattr(result, "rowcount") else len(message_ids)

    @staticmethod
    @log_exceptions(db_logger)
    async def cleanup_expired_messages(session: AsyncSession, batch_size: int = 1000) -> dict[str, int]:
        """
        Очистка всех истекших сообщений.

        Args:
            session: Сессия БД
            batch_size: Размер пакета

        Returns:
            dict: Статистика очистки
        """
        total_deleted = 0
        total_found = 0

        while True:
            expired = await MessageRepository.get_expired_messages(session=session, limit=batch_size)

            if not expired:
                break

            message_ids = [msg.FID for msg in expired]
            total_found += len(message_ids)

            deleted = await MessageRepository.mark_messages_as_deleted(
                session=session, message_ids=message_ids, deleted_by_type="expired_cleanup"
            )
            total_deleted += deleted

            db_logger.debug(f"🧹 Cleaned {deleted} expired messages (total: {total_deleted})")

        return {"found": total_found, "deleted": total_deleted}


__all__ = ["MessageRepository"]
