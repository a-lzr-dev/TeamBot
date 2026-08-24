"""Репозиторий для получения статистики системы.

Содержит методы для получения статистики по всем компонентам системы:
- Полная статистика
- Чаты
- Пользователи
- Сообщения
- Ошибки
- Напоминания
- Заявки на автоматизацию
- Системная статистика
- Статистика таблиц БД
"""

from datetime import timedelta
from typing import Any

from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from ...logger import db_logger
from ...models import (
    ChatMessageModel,
    ChatModel,
    ErrorModel,
    MessageType,
    UserModel,
    UserReminderModel,
    datetime_now,
)
from ...utils.decorators import log_exceptions


class StatsRepository:
    """Репозиторий для получения статистики системы.

    Все методы используют SQLAlchemy для выполнения запросов к БД.
    """

    # ============================================================
    # ПОЛНАЯ СТАТИСТИКА
    # ============================================================

    @staticmethod
    @log_exceptions(db_logger)
    async def get_full_stats(session: AsyncSession) -> dict[str, Any]:
        """Получение полной статистики системы.

        Включает:
        - Чаты (всего, активные, неактивные)
        - Пользователи (всего, авторизованные, активные за 24ч)
        - Сообщения (всего, по типам, по дням, удаленные, с временем жизни)
        - Топ-5 чатов по количеству сообщений

        Returns:
            dict: Полная статистика по всем компонентам
        """
        db_logger.info("📊 [get_full_stats] Getting full statistics")

        # --- Чаты ---
        total_chats = await session.scalar(select(func.count()).select_from(ChatModel)) or 0
        active_chats = (
            await session.scalar(select(func.count()).select_from(ChatModel).where(ChatModel.FFlagActive)) or 0
        )

        # --- Пользователи ---
        total_users = await session.scalar(select(func.count()).select_from(UserModel)) or 0

        # Авторизованные пользователи (через связь с Avanpost)
        from ...models import AvanpostUserLinkModel

        authorized_users = (
            await session.scalar(
                select(func.count())
                .select_from(AvanpostUserLinkModel)
                .where(AvanpostUserLinkModel.FK_Link.is_not(None))
            )
            or 0
        )

        # Активные пользователи (за последние 24 часа)
        cutoff = datetime_now() - timedelta(hours=24)
        active_users = (
            await session.scalar(
                select(func.count()).select_from(UserModel).where(UserModel.FDateLastActivity >= cutoff)
            )
            or 0
        )

        # --- Сообщения ---
        total_messages = await session.scalar(select(func.count()).select_from(ChatMessageModel)) or 0

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

        # Удаленные сообщения
        deleted_messages = (
            await session.scalar(
                select(func.count()).select_from(ChatMessageModel).where(ChatMessageModel.FFlagDeleted.is_(True))
            )
            or 0
        )

        # Сообщения с временем жизни
        with_lifetime = (
            await session.scalar(
                select(func.count()).select_from(ChatMessageModel).where(ChatMessageModel.FLifetimeSeconds.is_not(None))
            )
            or 0
        )

        # Истекшие, но не удаленные
        expired_not_deleted = (
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
                    .where(
                        ChatMessageModel.FDateSent >= day_start,
                        ChatMessageModel.FDateSent <= day_end,
                    )
                )
                or 0
            )
            messages_by_day[day.strftime("%Y-%m-%d")] = count

        # --- Топ-5 чатов ---
        top_chats_stmt = (
            select(ChatModel.FID, ChatModel.FTitle, func.count(ChatMessageModel.FID).label("message_count"))
            .outerjoin(ChatMessageModel, ChatMessageModel.FK_Chat == ChatModel.FID)
            .group_by(ChatModel.FID, ChatModel.FTitle)
            .order_by(func.count(ChatMessageModel.FID).desc())
            .limit(5)
        )

        top_chats_result = await session.execute(top_chats_stmt)
        top_chats = []
        for row in top_chats_result.all():
            top_chats.append(
                {
                    "chat_id": row.FID,
                    "title": row.FTitle or f"Chat {row.FID}",
                    "message_count": row.message_count,
                }
            )

        stats = {
            "chats": {
                "total": total_chats,
                "active": active_chats,
                "inactive": total_chats - active_chats,
            },
            "users": {
                "total": total_users,
                "authorized": authorized_users,
                "active_24h": active_users,
            },
            "messages": {
                "total": total_messages,
                "by_type": messages_by_type,
                "by_day": messages_by_day,
                "deleted": deleted_messages,
                "with_lifetime": with_lifetime,
                "expired_not_deleted": expired_not_deleted,
            },
            "top_chats": top_chats,
        }

        db_logger.info(
            f"✅ [get_full_stats] Stats: chats={total_chats}, messages={total_messages}, users={total_users}"
        )
        return stats

    # ============================================================
    # СТАТИСТИКА ЧАТОВ
    # ============================================================

    @staticmethod
    @log_exceptions(db_logger)
    async def get_chats_stats(session: AsyncSession) -> dict[str, Any]:
        """Получение статистики по чатам.

        Returns:
            dict: Статистика по чатам (всего, активные, неактивные, по типам)
        """
        db_logger.info("📊 [get_chats_stats] Getting chats statistics")

        from collections import Counter

        chats = await session.execute(select(ChatModel))
        chats_list = chats.scalars().all()

        active_chats = [c for c in chats_list if c.FFlagActive]
        type_counts = Counter(c.FType.value if c.FType else "unknown" for c in chats_list)

        return {
            "total": len(chats_list),
            "active": len(active_chats),
            "inactive": len(chats_list) - len(active_chats),
            "by_type": dict(type_counts),
        }

    # ============================================================
    # СТАТИСТИКА ПОЛЬЗОВАТЕЛЕЙ
    # ============================================================

    @staticmethod
    @log_exceptions(db_logger)
    async def get_users_stats(session: AsyncSession) -> dict[str, Any]:
        """Получение статистики по пользователям.

        Returns:
            dict: Статистика по пользователям (всего, авторизованные, активные за 24ч)
        """
        db_logger.info("📊 [get_users_stats] Getting users statistics")

        from ...models import AvanpostUserLinkModel

        total_users = await session.scalar(select(func.count()).select_from(UserModel)) or 0

        authorized_users = (
            await session.scalar(
                select(func.count())
                .select_from(AvanpostUserLinkModel)
                .where(AvanpostUserLinkModel.FK_Link.is_not(None))
            )
            or 0
        )

        cutoff = datetime_now() - timedelta(hours=24)
        active_users = (
            await session.scalar(
                select(func.count()).select_from(UserModel).where(UserModel.FDateLastActivity >= cutoff)
            )
            or 0
        )

        return {
            "total": total_users,
            "authorized": authorized_users,
            "active_24h": active_users,
        }

    # ============================================================
    # СТАТИСТИКА СООБЩЕНИЙ
    # ============================================================

    @staticmethod
    @log_exceptions(db_logger)
    async def get_messages_stats(session: AsyncSession) -> dict[str, Any]:
        """Получение статистики по сообщениям.

        Returns:
            dict: Статистика по сообщениям (всего, по типам, по дням, удаленные, с временем жизни)
        """
        db_logger.info("📊 [get_messages_stats] Getting messages statistics")

        # Общая статистика по типам
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

        total = sum(messages_by_type.values())

        # Удаленные сообщения
        deleted = (
            await session.scalar(
                select(func.count()).select_from(ChatMessageModel).where(ChatMessageModel.FFlagDeleted.is_(True))
            )
            or 0
        )

        # С временем жизни
        with_lifetime = (
            await session.scalar(
                select(func.count()).select_from(ChatMessageModel).where(ChatMessageModel.FLifetimeSeconds.is_not(None))
            )
            or 0
        )

        # Истекшие, но не удаленные
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
                    .where(
                        ChatMessageModel.FDateSent >= day_start,
                        ChatMessageModel.FDateSent <= day_end,
                    )
                )
                or 0
            )
            messages_by_day[day.strftime("%Y-%m-%d")] = count

        return {
            "total": total,
            "by_type": messages_by_type,
            "by_day": messages_by_day,
            "deleted": deleted,
            "with_lifetime": with_lifetime,
            "expired_not_deleted": expired,
        }

    # ============================================================
    # СТАТИСТИКА ОШИБОК
    # ============================================================

    @staticmethod
    @log_exceptions(db_logger)
    async def get_errors_stats(session: AsyncSession) -> dict[str, Any]:
        """Получение статистики по ошибкам.

        Returns:
            dict: Статистика по ошибкам (всего, по статусам, по категориям, по серьезности)
        """
        db_logger.info("📊 [get_errors_stats] Getting errors statistics")

        from ...models import ErrorCategory, ErrorSeverity, ErrorStatus

        # Общая статистика
        total = await session.scalar(select(func.count()).select_from(ErrorModel)) or 0

        # По статусам
        status_stats = {}
        for status in ErrorStatus:
            count = (
                await session.scalar(select(func.count()).select_from(ErrorModel).where(ErrorModel.FStatus == status))
                or 0
            )
            status_stats[status.value] = count

        # По категориям
        category_stats = {}
        for category in ErrorCategory:
            count = (
                await session.scalar(
                    select(func.count()).select_from(ErrorModel).where(ErrorModel.FCategory == category)
                )
                or 0
            )
            category_stats[category.value] = count

        # По серьезности
        severity_stats = {}
        for severity in ErrorSeverity:
            count = (
                await session.scalar(
                    select(func.count()).select_from(ErrorModel).where(ErrorModel.FSeverity == severity)
                )
                or 0
            )
            severity_stats[severity.value] = count

        # Всего повторений
        total_occurrences = await session.scalar(select(func.sum(ErrorModel.FCountOccurrences))) or 0

        # Решенные
        resolved = status_stats.get("resolved", 0)

        return {
            "total": total,
            "by_status": status_stats,
            "by_category": category_stats,
            "by_severity": severity_stats,
            "total_occurrences": total_occurrences,
            "resolution_rate": (resolved / total * 100) if total > 0 else 0,
        }

    # ============================================================
    # СТАТИСТИКА НАПОМИНАНИЙ
    # ============================================================

    @staticmethod
    @log_exceptions(db_logger)
    async def get_reminders_stats(
        session: AsyncSession,
        user_id: int | None = None,
    ) -> dict[str, Any]:
        """Получение статистики по напоминаниям.

        Args:
            session: Сессия БД
            user_id: ID пользователя (опционально, для фильтрации)

        Returns:
            dict: Статистика по напоминаниям
        """
        db_logger.info(f"📊 [get_reminders_stats] Getting reminders statistics for user {user_id or 'all'}")

        stmt = select(
            func.count(UserReminderModel.FID).label("total"),
            func.count(UserReminderModel.FID).filter(UserReminderModel.FIsActive.is_(True)).label("active"),
            func.count(UserReminderModel.FID).filter(UserReminderModel.FIsCompleted.is_(True)).label("completed"),
            func.count(UserReminderModel.FID).filter(UserReminderModel.FIsEncrypted.is_(True)).label("encrypted"),
            func.count(UserReminderModel.FID)
            .filter(UserReminderModel.FIsGroupReminder.is_(True))
            .label("group_reminders"),
        ).where(UserReminderModel.FIsDeleted.is_(False))

        if user_id:
            stmt = stmt.where(UserReminderModel.FK_User == user_id)

        result = await session.execute(stmt)
        row = result.first()

        total = row.total or 0 if row else 0
        active = row.active or 0 if row else 0
        completed = row.completed or 0 if row else 0

        return {
            "total": total,
            "active": active,
            "completed": completed,
            "encrypted": row.encrypted or 0 if row else 0,
            "group_reminders": row.group_reminders or 0 if row else 0,
            "completion_rate": (completed / total * 100) if total > 0 else 0,
        }

    # ============================================================
    # СТАТИСТИКА АВТОМАТИЗАЦИИ
    # ============================================================

    @staticmethod
    @log_exceptions(db_logger)
    async def get_automation_stats(
        session: AsyncSession,
        user_id: int | None = None,
    ) -> dict[str, Any]:
        """Получение статистики по заявкам на автоматизацию.

        Args:
            session: Сессия БД
            user_id: ID пользователя (опционально, для фильтрации)

        Returns:
            dict: Статистика по заявкам
        """
        db_logger.info(f"📊 [get_automation_stats] Getting automation statistics for user {user_id or 'all'}")

        from ...models import UserRequestAutomationModel, UserRequestAutomationPriority, UserRequestAutomationStatus

        conditions = []
        if user_id:
            conditions.append(UserRequestAutomationModel.FK_User == user_id)

        # Общая статистика
        total = (
            await session.scalar(
                select(func.count()).select_from(UserRequestAutomationModel).where(*conditions)
                if conditions
                else select(func.count()).select_from(UserRequestAutomationModel)
            )
            or 0
        )

        # По статусам
        status_stats = {}
        for status in UserRequestAutomationStatus:
            stmt = (
                select(func.count())
                .select_from(UserRequestAutomationModel)
                .where(UserRequestAutomationModel.FStatus == status)
            )
            if user_id:
                stmt = stmt.where(UserRequestAutomationModel.FK_User == user_id)
            count = await session.scalar(stmt) or 0
            status_stats[status.value] = count

        # По приоритетам
        priority_stats = {}
        for priority in UserRequestAutomationPriority:
            stmt = (
                select(func.count())
                .select_from(UserRequestAutomationModel)
                .where(UserRequestAutomationModel.FPriority == priority)
            )
            if user_id:
                stmt = stmt.where(UserRequestAutomationModel.FK_User == user_id)
            count = await session.scalar(stmt) or 0
            priority_stats[priority.value] = count

        completed = status_stats.get("completed", 0)

        return {
            "total": total,
            "by_status": status_stats,
            "by_priority": priority_stats,
            "completion_rate": (completed / total * 100) if total > 0 else 0,
        }

    # ============================================================
    # СИСТЕМНАЯ СТАТИСТИКА
    # ============================================================

    @staticmethod
    @log_exceptions(db_logger)
    async def get_system_stats() -> dict[str, Any]:
        """Получение системной статистики (без БД).

        Returns:
            dict: Системная статистика (версия, Python, платформа, uptime, окружение)
        """
        import platform
        import sys

        from ...config import settings
        from ...core.application import get_app_manager

        app_manager = get_app_manager()
        status = await app_manager.get_status()

        return {
            "version": "1.0.0",
            "environment": settings.APP_ENV,
            "debug": settings.APP_DEBUG,
            "python_version": sys.version.split()[0],
            "platform": platform.system(),
            "platform_version": platform.version(),
            "uptime": status.get("app", {}).get("uptime"),
            "state": status.get("app", {}).get("state"),
            "tasks_count": status.get("app", {}).get("tasks_count", 0),
        }

    # ============================================================
    # СТАТИСТИКА ТАБЛИЦ БАЗЫ ДАННЫХ
    # ============================================================

    @staticmethod
    @log_exceptions(db_logger)
    async def get_table_stats(session: AsyncSession) -> dict[str, int]:
        """Получение количества записей во всех таблицах базы данных main.

        Returns:
            dict[str, int]: Словарь {имя_таблицы: количество_записей}
        """
        db_logger.info("📊 [get_table_stats] Getting table row counts")

        # Получение списка всех таблиц в схеме public
        table_query = text(
            """
            SELECT table_name
            FROM information_schema.tables
            WHERE table_schema = 'public'
              AND table_type = 'BASE TABLE'
            ORDER BY table_name
        """
        )

        result = await session.execute(table_query)
        tables = [row[0] for row in result.fetchall()]

        stats = {}
        for table in tables:
            try:
                count_query = text(f'SELECT COUNT(*) FROM "{table}"')
                count_result = await session.execute(count_query)
                count = count_result.scalar() or 0
                stats[table] = count
            except Exception as e:
                db_logger.warning(f"⚠️ [get_table_stats] Failed to count {table}: {e}")
                stats[table] = -1  # -1 означает ошибку

        db_logger.info(f"✅ [get_table_stats] Counted {len(stats)} tables")
        return stats


__all__ = ["StatsRepository"]
