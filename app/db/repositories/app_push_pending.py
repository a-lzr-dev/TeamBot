"""Репозиторий для работы с очередью отложенных push-уведомлений (TPushPending).

Используется, когда клиент офлайн и FCM недоступен: сигнал кладётся
в TPushPending и отдаётся клиенту при следующем register/WS-connect.
"""

from __future__ import annotations

from datetime import timedelta
from typing import Any

from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from ...logger import db_logger
from ...models import AppPushPendingModel, datetime_now


class AppPushPendingRepository:
    """Очередь отложенных push-сигналов (TPushPending)."""

    @staticmethod
    async def add(
        session: AsyncSession,
        user_id: str,
        payload: dict[str, Any],
    ) -> AppPushPendingModel:
        """Добавить pending-сигнал для пользователя."""
        model = AppPushPendingModel(
            FUserID=user_id,
            FType=payload.get("type"),
            FTopic=payload.get("topic"),
            FSeq=payload.get("seq"),
            FCreatedAt=datetime_now(),
            FAttemptCount=0,
        )
        session.add(model)
        await session.flush()
        db_logger.info(
            "pending_push: added user=%s type=%s topic=%s",
            user_id,
            payload.get("type"),
            payload.get("topic"),
        )
        return model

    @staticmethod
    async def take_for_user(
        session: AsyncSession,
        user_id: str,
        *,
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        """Забрать и удалить pending-сигналы пользователя.

        Возвращает список payload'ов ({"type": ..., "topic": ...}),
        которые клиент должен обработать.
        """
        stmt = (
            select(AppPushPendingModel)
            .where(AppPushPendingModel.FUserID == user_id)
            .order_by(AppPushPendingModel.FCreatedAt)
            .limit(limit)
        )
        result = await session.execute(stmt)
        rows = list(result.scalars().all())
        if not rows:
            return []

        payloads: list[dict[str, Any]] = []
        ids: list[int] = []
        for row in rows:
            payloads.append(
                {
                    "type": row.FType or "sync",
                    "topic": row.FTopic,
                    "seq": row.FSeq,
                }
            )
            ids.append(row.FID)

        await session.execute(delete(AppPushPendingModel).where(AppPushPendingModel.FID.in_(ids)))
        await session.flush()
        db_logger.info("pending_push: taken user=%s count=%d", user_id, len(payloads))
        return payloads

    @staticmethod
    async def cleanup_older_than(
        session: AsyncSession,
        days: int = 7,
    ) -> int:
        """Удалить pending старше N дней (не отданные клиенту)."""
        threshold = datetime_now() - timedelta(days=days)
        stmt = delete(AppPushPendingModel).where(AppPushPendingModel.FCreatedAt < threshold)
        result = await session.execute(stmt)
        await session.commit()
        deleted = getattr(result, "rowcount", 0) or 0
        if deleted:
            db_logger.info(
                "pending_push: cleanup deleted=%d (older than %dd)",
                deleted,
                days,
            )
        return int(deleted)

    @staticmethod
    async def count_for_user(
        session: AsyncSession,
        user_id: str,
    ) -> int:
        stmt = select(func.count()).select_from(AppPushPendingModel).where(AppPushPendingModel.FUserID == user_id)
        result = await session.execute(stmt)
        return int(result.scalar() or 0)


app_push_pending_repo = AppPushPendingRepository()

__all__ = ["AppPushPendingRepository", "app_push_pending_repo"]
