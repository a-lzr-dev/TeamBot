"""
Репозиторий для работы с рассылками.
"""

from typing import Any

from sqlalchemy import desc, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from ...logger import db_logger
from ...models import BroadcastMessageLinkModel, BroadcastModel, datetime_now
from ...utils.decorators import log_exceptions


class BroadcastRepository:
    """Репозиторий для работы с рассылками."""

    @staticmethod
    @log_exceptions(db_logger)
    async def create_broadcast(
        session: AsyncSession,
        user_id: int,
        title: str,
        text: str,
        parse_mode: str | None = None,
        total_chats: int = 0,
    ) -> BroadcastModel:
        """Создание новой рассылки."""
        broadcast = BroadcastModel(
            FK_User=user_id,
            FTitle=title[:200],
            FText=text,
            FParseMode=parse_mode,
            FTotalChats=total_chats,
            FStatus="pending",
        )
        session.add(broadcast)
        await session.flush()
        await session.refresh(broadcast)
        return broadcast

    @staticmethod
    @log_exceptions(db_logger)
    async def update_broadcast_status(
        session: AsyncSession,
        broadcast_id: int,
        status: str,
        success_count: int | None = None,
        failed_count: int | None = None,
    ) -> BroadcastModel | None:
        """Обновление статуса рассылки."""
        values: dict[str, Any] = {"FStatus": status}
        if status == "sent":
            values["FSentAt"] = datetime_now()
        if success_count is not None:
            values["FSuccessCount"] = success_count
        if failed_count is not None:
            values["FFailedCount"] = failed_count

        stmt = (
            update(BroadcastModel).where(BroadcastModel.FID == broadcast_id).values(**values).returning(BroadcastModel)
        )
        result = await session.execute(stmt)
        await session.flush()
        return result.scalar_one_or_none()  # type: ignore[no-any-return]

    @staticmethod
    @log_exceptions(db_logger)
    async def cancel_broadcast(
        session: AsyncSession,
        broadcast_id: int,
        cancelled_by: int,
    ) -> BroadcastModel | None:
        """Отмена рассылки."""
        stmt = (
            update(BroadcastModel)
            .where(
                BroadcastModel.FID == broadcast_id,
                BroadcastModel.FStatus == "pending",
            )
            .values(
                FStatus="cancelled",
                FCancelledAt=datetime_now(),
                FCancelledBy=cancelled_by,
            )
            .returning(BroadcastModel)
        )
        result = await session.execute(stmt)
        await session.flush()
        return result.scalar_one_or_none()  # type: ignore[no-any-return]

    @staticmethod
    @log_exceptions(db_logger)
    async def link_message(
        session: AsyncSession,
        broadcast_id: int,
        message_id: int,
        chat_id: int,
    ) -> BroadcastMessageLinkModel:
        """Связывание сообщения с рассылкой."""
        link = BroadcastMessageLinkModel(
            FK_Broadcast=broadcast_id,
            FK_Message=message_id,
            FK_Chat=chat_id,
        )
        session.add(link)
        await session.flush()
        await session.refresh(link)
        return link

    @staticmethod
    @log_exceptions(db_logger)
    async def get_recent_broadcasts(
        session: AsyncSession,
        limit: int = 10,
        include_cancelled: bool = False,
    ) -> list[BroadcastModel]:
        """Получение последних рассылок."""
        stmt = select(BroadcastModel).order_by(desc(BroadcastModel.FCreatedAt))

        if not include_cancelled:
            stmt = stmt.where(BroadcastModel.FStatus != "cancelled")

        stmt = stmt.limit(limit)
        result = await session.execute(stmt)
        return list(result.scalars().all())

    @staticmethod
    @log_exceptions(db_logger)
    async def get_broadcast_messages(
        session: AsyncSession,
        broadcast_id: int,
    ) -> list[BroadcastMessageLinkModel]:
        """Получение всех сообщений, связанных с рассылкой."""
        stmt = select(BroadcastMessageLinkModel).where(BroadcastMessageLinkModel.FK_Broadcast == broadcast_id)
        result = await session.execute(stmt)
        return list(result.scalars().all())

    @staticmethod
    @log_exceptions(db_logger)
    async def mark_messages_deleted(
        session: AsyncSession,
        broadcast_id: int,
    ) -> int:
        """Отметка всех сообщений рассылки как удалённых."""
        stmt = (
            update(BroadcastMessageLinkModel)
            .where(BroadcastMessageLinkModel.FK_Broadcast == broadcast_id)
            .values(
                FIsDeleted=True,
                FDeletedAt=datetime_now(),
            )
            .returning(BroadcastMessageLinkModel.FID)
        )
        result = await session.execute(stmt)
        await session.flush()
        return len(result.all())

    @staticmethod
    @log_exceptions(db_logger)
    async def get_broadcast_by_id(
        session: AsyncSession,
        broadcast_id: int,
    ) -> BroadcastModel | None:
        """Получение рассылки по ID."""
        stmt = select(BroadcastModel).where(BroadcastModel.FID == broadcast_id)
        result = await session.execute(stmt)
        return result.scalar_one_or_none()  # type: ignore[no-any-return]


__all__ = [
    "BroadcastRepository",
]
