from datetime import timedelta
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from ...exceptions import log_exceptions
from ...logger import db_logger
from ...models import ChatMessageModel, ChatModel, MessageType, UserModel, datetime_now


class StatsRepository:
    """Репозиторий для статистики"""

    @staticmethod
    @log_exceptions(db_logger)
    async def get_full_stats(session: AsyncSession) -> dict[str, Any]:
        """Получение полной статистики"""

        # Чаты
        total_chats = await session.scalar(select(func.count()).select_from(ChatModel)) or 0
        active_chats = (
            await session.scalar(select(func.count()).select_from(ChatModel).where(ChatModel.FFlagActive)) or 0
        )

        # Сообщения
        total_messages = await session.scalar(select(func.count()).select_from(ChatMessageModel)) or 0

        # Пользователи
        total_users = await session.scalar(select(func.count()).select_from(UserModel)) or 0

        # Сообщения по типам
        messages_by_type = {}
        for msg_type in MessageType:
            count = (
                await session.scalar(
                    select(func.count())
                    .select_from(ChatMessageModel)
                    .where(ChatMessageModel.FK_MessageType == msg_type)
                )
                or 0
            )
            messages_by_type[msg_type.value] = count

        # Статистика по времени жизни
        with_lifetime = (
            await session.scalar(
                select(func.count()).select_from(ChatMessageModel).where(ChatMessageModel.FLifetimeSeconds.is_not(None))
            )
            or 0
        )

        expired = (
            await session.scalar(
                select(func.count())
                .select_from(ChatMessageModel)
                .where(
                    ChatMessageModel.FExpiresAt.is_not(None),
                    ChatMessageModel.FExpiresAt <= datetime_now(),
                    ChatMessageModel.FFlagDeleted.is_(False),
                )
            )
            or 0
        )

        # Сообщения по дням (последние 7 дней)
        now = datetime_now()
        messages_by_day = {}
        for i in range(7):
            day = now - timedelta(days=i)
            day_start = day.replace(hour=0, minute=0, second=0, microsecond=0)
            day_end = day.replace(hour=23, minute=59, second=59, microsecond=999999)

            count = (
                await session.scalar(
                    select(func.count())
                    .select_from(ChatMessageModel)
                    .where(ChatMessageModel.FDateSent >= day_start, ChatMessageModel.FDateSent <= day_end)
                )
                or 0
            )
            messages_by_day[day.strftime("%Y-%m-%d")] = count

        # Топ чатов
        top_chats_stmt = (
            select(ChatModel.FID, ChatModel.FTitle, func.count(ChatMessageModel.FID).label("message_count"))
            .outerjoin(ChatMessageModel, ChatMessageModel.FK_Chat == ChatModel.FID)
            .group_by(ChatModel.FID, ChatModel.FTitle)
            .order_by(func.count(ChatMessageModel.FID).desc())
            .limit(5)
        )
        top_chats_result = await session.execute(top_chats_stmt)
        top_chats_list = []
        for row in top_chats_result.all():
            top_chats_list.append(
                {"chat_id": row.FID, "title": row.FTitle or f"Chat {row.FID}", "message_count": row.message_count}
            )

        return {
            "chats": {"total": total_chats, "active": active_chats, "inactive": total_chats - active_chats},
            "messages": {
                "total": total_messages,
                "by_type": messages_by_type,
                "by_day": messages_by_day,
                "with_lifetime": with_lifetime,
                "expired_not_deleted": expired,
            },
            "users": {"total": total_users},
            "top_chats": top_chats_list,
        }
