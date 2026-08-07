from datetime import timedelta
from typing import Any

from sqlalchemy import and_, func, not_, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from ...exceptions import log_exceptions
from ...logger import db_logger
from ...models import ChatMessageModel, MessageType, datetime_now


class MessageRepository:
    """Репозиторий для работы с сообщениями (независимый)"""

    @staticmethod
    @log_exceptions(db_logger)
    async def get_expired_messages(
        session: AsyncSession, chat_id: int | None = None, limit: int = 1000
    ) -> list[ChatMessageModel]:
        """Получение сообщений, у которых истекло время жизни"""
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
        return list(result.scalars().all())

    @staticmethod
    @log_exceptions(db_logger)
    async def mark_messages_as_deleted(
        session: AsyncSession,
        message_ids: list[int],
        deleted_by_type: str = "expired",
        deleted_by_message_id: int | None = None,
    ) -> int:
        """Отметка сообщений как удаленных"""
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
    async def set_message_lifetime(session: AsyncSession, message_id: int, lifetime_seconds: int) -> bool:
        """Установка времени жизни для сообщения"""
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
    async def get_message_lifetime_stats(session: AsyncSession, chat_id: int | None = None) -> dict[str, Any]:
        """Получение статистики по времени жизни сообщений"""
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
        Получение сообщений согласно условий с возможностью исключения типов.

        Args:
            session: Сессия БД
            chat_id: чат, из которого нужно удалить сообщения
            before_minutes: Удалять сообщения старше указанного количества минут
            message_types: Список типов для включения (если None - все типы)
            exclude_message_types: Список типов для исключения (приоритет выше)
            limit: Максимальное количество сообщений

        Returns:
            List[ChatMessageModel]: Список сообщений
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
        return list(result.scalars().all())

    @staticmethod
    @log_exceptions(db_logger)
    async def mark_messages_deleted_by_ids(
        session: AsyncSession, message_ids: list[int], deleted_by_type: str = "cleanup"
    ) -> int:
        """Отметка конкретных сообщений как удаленных"""
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
    async def get_message_by_id(session: AsyncSession, message_id: int) -> ChatMessageModel | None:
        """Получение сообщения по ID"""
        stmt = select(ChatMessageModel).where(ChatMessageModel.FID == message_id)
        result = await session.execute(stmt)
        message: ChatMessageModel | None = result.scalar_one_or_none()
        return message

    @staticmethod
    @log_exceptions(db_logger)
    async def get_messages_by_chat(
        session: AsyncSession, chat_id: int, limit: int = 100, offset: int = 0, include_deleted: bool = False
    ) -> list[ChatMessageModel]:
        """Получение сообщений по чату"""
        stmt = select(ChatMessageModel).where(ChatMessageModel.FK_Chat == chat_id)

        if not include_deleted:
            stmt = stmt.where(ChatMessageModel.FFlagDeleted.is_(False))

        stmt = stmt.order_by(ChatMessageModel.FDateSent.desc())
        stmt = stmt.limit(limit).offset(offset)

        result = await session.execute(stmt)
        return list(result.scalars().all())


__all__ = ["MessageRepository"]
