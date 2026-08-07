import json
from datetime import datetime, timedelta
from typing import Any

from sqlalchemy import and_, func, or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from ..db import db_manager
from ..exceptions import log_exceptions
from ..logger import app_logger
from ..models import ReminderModel, ReminderShareModel, datetime_now
from ..utils.crypto import decrypt_data, encrypt_data


class ReminderService:
    """Сервис для управления напоминаниями и делами"""

    @log_exceptions(app_logger)
    async def create_reminder(
        self,
        user_id: int,
        title: str,
        remind_at: datetime,
        description: str | None = None,
        category: str | None = None,
        remind_until: datetime | None = None,
        remind_interval: int | None = None,
        max_remind_count: int | None = None,
        code_word: str | None = None,
        notification_type: str = "private",
        chat_id: int | None = None,
        shared_with: list[int] | None = None,
        encrypt: bool = False,
        session: AsyncSession | None = None,
    ) -> ReminderModel:
        """Создание напоминания с поддержкой шифрования"""

        if session is None:
            async with db_manager.get_session() as sess:
                return await self.create_reminder(
                    user_id,
                    title,
                    remind_at,
                    description,
                    category,
                    remind_until,
                    remind_interval,
                    max_remind_count,
                    code_word,
                    notification_type,
                    chat_id,
                    shared_with,
                    encrypt,
                    sess,
                )

        # Подготовка данных
        encrypted_data = None
        is_encrypted = False

        if encrypt:
            try:
                # Шифруем конфиденциальные данные
                data_to_encrypt = json.dumps(
                    {"title": title, "description": description, "category": category}, ensure_ascii=False
                )
                encrypted_data = encrypt_data(data_to_encrypt)
                is_encrypted = True

                # Логируем успешное шифрование
                app_logger.debug(f"✅ Reminder data encrypted for user {user_id}")

            except Exception as e:
                app_logger.error(f"❌ Failed to encrypt reminder: {e}")
                # При ошибке шифрования - сохраняем открыто
                is_encrypted = False
                encrypted_data = None

        # Создание дела
        if is_encrypted:
            # Зашифрованное дело
            reminder = ReminderModel(
                FK_User=user_id,
                FTitle="🔒 Зашифровано",
                FDescription=None,
                FCategory=None,
                FRemindAt=remind_at,
                FRemindUntil=remind_until,
                FRemindInterval=remind_interval,
                FMaxRemindCount=max_remind_count,
                FCodeWord=code_word,
                FIsEncrypted=True,
                FEncryptedData=encrypted_data,
                FNotificationType=notification_type,
                FK_Chat=chat_id,
                FIsGroupReminder=bool(shared_with and len(shared_with) > 0),
            )
        else:
            # Открытое дело
            reminder = ReminderModel(
                FK_User=user_id,
                FTitle=title,
                FDescription=description,
                FCategory=category,
                FRemindAt=remind_at,
                FRemindUntil=remind_until,
                FRemindInterval=remind_interval,
                FMaxRemindCount=max_remind_count,
                FCodeWord=code_word,
                FIsEncrypted=False,
                FEncryptedData=None,
                FNotificationType=notification_type,
                FK_Chat=chat_id,
                FIsGroupReminder=bool(shared_with and len(shared_with) > 0),
            )

        session.add(reminder)
        await session.flush()

        # Создание связей с пользователями (для общих дел)
        if shared_with:
            for shared_user_id in shared_with:
                share = ReminderShareModel(FK_Reminder=reminder.FID, FK_User=shared_user_id)
                session.add(share)

        await session.commit()
        await session.refresh(reminder)

        return reminder

    @log_exceptions(app_logger)
    async def complete_reminder(
        self, reminder_id: int, user_id: int, successful: bool = True, session: AsyncSession | None = None
    ) -> tuple[bool, str | None]:
        """Завершение дела"""

        if session is None:
            async with db_manager.get_session() as sess:
                return await self.complete_reminder(reminder_id, user_id, successful, sess)

        # Проверка владельца
        stmt = select(ReminderModel).where(
            reminder_id == ReminderModel.FID,
            or_(
                ReminderModel.FK_User == user_id,
                ReminderModel.FID.in_(
                    select(ReminderShareModel.FK_Reminder).where(ReminderShareModel.FK_User == user_id)
                ),
            ),
        )
        result = await session.execute(stmt)
        reminder = result.scalar_one_or_none()

        if not reminder:
            return False, "Reminder not found or no permission"

        # Обновление
        reminder.FIsCompleted = True
        reminder.FIsSuccessful = successful
        reminder.FCompletedAt = datetime_now()

        # Если есть общие дела, обновляем и их
        if reminder.FIsGroupReminder:
            stmt = (
                update(ReminderShareModel)
                .where(ReminderShareModel.FK_Reminder == reminder_id, ReminderShareModel.FK_User == user_id)
                .values(FIsCompleted=True, FIsSuccessful=successful, FCompletedAt=datetime_now())
            )
            await session.execute(stmt)

        await session.commit()

        return True, "Reminder completed successfully"

    @log_exceptions(app_logger)
    async def get_reminders(
        self,
        user_id: int,
        date: datetime | None = None,
        category: str | None = None,
        include_completed: bool = False,
        session: AsyncSession | None = None,
    ) -> list[dict[str, Any]]:
        """Получение списка дел"""

        if session is None:
            async with db_manager.get_session() as sess:
                return await self.get_reminders(user_id, date, category, include_completed, sess)

        # Базовый запрос
        stmt = select(ReminderModel).where(
            or_(
                ReminderModel.FK_User == user_id,
                ReminderModel.FID.in_(
                    select(ReminderShareModel.FK_Reminder).where(ReminderShareModel.FK_User == user_id)
                ),
            ),
            not ReminderModel.FIsDeleted,
        )

        # Фильтр по дате
        if date:
            start_of_day = date.replace(hour=0, minute=0, second=0, microsecond=0)
            end_of_day = date.replace(hour=23, minute=59, second=59, microsecond=999999)
            stmt = stmt.where(or_(ReminderModel.FRemindAt >= start_of_day, ReminderModel.FRemindAt <= end_of_day))

        if category:
            stmt = stmt.where(ReminderModel.FCategory == category)

        if not include_completed:
            stmt = stmt.where(not ReminderModel.FIsCompleted)

        stmt = stmt.order_by(ReminderModel.FRemindAt)

        result = await session.execute(stmt)
        reminders = result.scalars().all()

        return [self._format_reminder(r) for r in reminders]

    @log_exceptions(app_logger)
    async def get_reminder_stats(
        self, user_id: int, period: str = "week", session: AsyncSession | None = None
    ) -> dict[str, Any]:
        """Получение статистики по делам"""

        if session is None:
            async with db_manager.get_session() as sess:
                return await self.get_reminder_stats(user_id, period, sess)

        now = datetime_now()

        # Определение периода
        if period == "day":
            start_date = now.replace(hour=0, minute=0, second=0, microsecond=0)
        elif period == "week":
            start_date = now - timedelta(days=7)
        elif period == "month":
            start_date = now - timedelta(days=30)
        else:  # year
            start_date = now - timedelta(days=365)

        # Статистика по делам
        stmt = select(
            func.count(ReminderModel.FID).label("total"),
            func.count(ReminderModel.FID).filter(ReminderModel.FIsCompleted).label("completed"),
            func.count(ReminderModel.FID)
            .filter(and_(ReminderModel.FIsCompleted, ReminderModel.FIsSuccessful))
            .label("successful"),
            func.count(ReminderModel.FID)
            .filter(and_(ReminderModel.FIsCompleted, not ReminderModel.FIsSuccessful))
            .label("unsuccessful"),
        ).where(
            or_(
                ReminderModel.FK_User == user_id,
                ReminderModel.FID.in_(
                    select(ReminderShareModel.FK_Reminder).where(ReminderShareModel.FK_User == user_id)
                ),
            ),
            ReminderModel.FCreatedAt >= start_date,
        )

        result = await session.execute(stmt)
        stats = result.first()

        # Детальная статистика по дням
        daily_stmt = (
            select(
                func.date(ReminderModel.FCompletedAt).label("date"),
                func.count(ReminderModel.FID).label("total"),
                func.count(ReminderModel.FID).filter(ReminderModel.FIsSuccessful).label("successful"),
            )
            .where(
                or_(
                    ReminderModel.FK_User == user_id,
                    ReminderModel.FID.in_(
                        select(ReminderShareModel.FK_Reminder).where(ReminderShareModel.FK_User == user_id)
                    ),
                ),
                ReminderModel.FIsCompleted,
                ReminderModel.FCompletedAt >= start_date,
            )
            .group_by(func.date(ReminderModel.FCompletedAt))
            .order_by(func.date(ReminderModel.FCompletedAt))
        )

        daily_result = await session.execute(daily_stmt)
        daily = [
            {"date": row.date.isoformat() if row.date else None, "total": row.total, "successful": row.successful}
            for row in daily_result.all()
        ]

        return {
            "total": stats.total or 0,
            "completed": stats.completed or 0,
            "successful": stats.successful or 0,
            "unsuccessful": stats.unsuccessful or 0,
            "success_rate": (stats.successful / stats.completed * 100) if stats.completed else 0,
            "daily": daily,
            "period": period,
        }

    @staticmethod
    def _format_reminder(reminder: ReminderModel) -> dict[str, Any]:
        """Форматирование дела для вывода"""
        result = {
            "id": reminder.FID,
            "is_encrypted": reminder.FIsEncrypted,
            "remind_at": reminder.FRemindAt.isoformat() if reminder.FRemindAt else None,
            "remind_until": reminder.FRemindUntil.isoformat() if reminder.FRemindUntil else None,
            "remind_interval": reminder.FRemindInterval,
            "is_completed": reminder.FIsCompleted,
            "is_successful": reminder.FIsSuccessful,
            "completed_at": reminder.FCompletedAt.isoformat() if reminder.FCompletedAt else None,
            "is_group": reminder.FIsGroupReminder,
            "code_word": reminder.FCodeWord,
            "notification_type": reminder.FNotificationType,
        }

        if reminder.FIsEncrypted and reminder.FEncryptedData:
            try:
                # Расшифровка
                decrypted = decrypt_data(reminder.FEncryptedData)
                data = json.loads(decrypted)
                result["title"] = data.get("title", "🔒 Зашифровано")
                result["description"] = data.get("description")
                result["category"] = data.get("category")
            except Exception as e:
                app_logger.error(f"Failed to decrypt reminder {reminder.FID}: {e}")
                result["title"] = "🔒 Ошибка расшифровки"
                result["description"] = None
                result["category"] = None
        else:
            result["title"] = reminder.FTitle
            result["description"] = reminder.FDescription
            result["category"] = reminder.FCategory

        return result


reminder_service = ReminderService()
