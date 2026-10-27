"""Read-only репозиторий для БД Tinode.

Используется, если нужны дополнительные запросы (например, проверка
существования топика перед отправкой). В первой версии может быть пустым.
"""

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

# from ...logger import app_logger
from ...ws.models import TinodeSubscriptionModel, TinodeTopicModel


class TinodeReadRepository:
    """Только SELECT — никаких create/update/delete."""

    @staticmethod
    async def topic_exists(session: AsyncSession, topic: str) -> bool:
        stmt = select(TinodeTopicModel.id).where(TinodeTopicModel.name == topic).limit(1)
        result = await session.execute(stmt)
        return result.scalar_one_or_none() is not None

    @staticmethod
    async def get_topic_subscribers(session: AsyncSession, topic: str) -> list[str]:
        stmt = (
            select(TinodeSubscriptionModel.user)
            .where(TinodeSubscriptionModel.topic == topic)
            .where(TinodeSubscriptionModel.deletedat.is_(None))
            .where(TinodeSubscriptionModel.user.is_not(None))
        )
        result = await session.execute(stmt)
        return [row[0] for row in result.all() if row[0]]


__all__ = ["TinodeReadRepository"]
