import json
from datetime import datetime, timedelta
from typing import Any

from sqlalchemy import and_, delete, func, or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from ...exceptions import log_exceptions
from ...logger import db_logger
from ...models import UserReminderModel, UserReminderShareModel, datetime_now
from ...utils.crypto import decrypt_data, encrypt_data


class ReminderRepository:
    """Репозиторий для работы с напоминаниями и делами"""

    # ==================== СОЗДАНИЕ ====================

    @staticmethod
    @log_exceptions(db_logger)
    async def create_reminder(
        session: AsyncSession,
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
    ) -> UserReminderModel:
        """
        Создание напоминания с поддержкой шифрования.

        Args:
            session: Сессия БД
            user_id: ID пользователя
            title: Название
            remind_at: Время напоминания
            description: Описание
            category: Категория
            remind_until: Дата окончания оповещений
            remind_interval: Интервал в минутах
            max_remind_count: Максимальное количество оповещений
            code_word: Кодовое слово
            notification_type: Тип уведомления
            chat_id: ID чата
            shared_with: Список ID пользователей для общего дела
            encrypt: Шифровать данные

        Returns:
            UserReminderModel: Созданное напоминание
        """
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
                db_logger.debug(f"✅ Reminder data encrypted for user {user_id}")
            except Exception as e:
                db_logger.error(f"❌ Failed to encrypt reminder: {e}")
                is_encrypted = False
                encrypted_data = None

        # Создание дела
        if is_encrypted:
            reminder = UserReminderModel(
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
            reminder = UserReminderModel(
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
                share = UserReminderShareModel(FK_Reminder=reminder.FID, FK_User=shared_user_id)
                session.add(share)

        await session.commit()
        await session.refresh(reminder)

        return reminder

    # ==================== ЗАВЕРШЕНИЕ ====================

    @staticmethod
    @log_exceptions(db_logger)
    async def complete_reminder(
        session: AsyncSession, reminder_id: int, user_id: int, successful: bool = True
    ) -> tuple[bool, str | None]:
        """
        Завершение дела.

        Args:
            session: Сессия БД
            reminder_id: ID напоминания
            user_id: ID пользователя
            successful: Успешно ли выполнено

        Returns:
            Tuple[bool, str | None]: (успех, сообщение об ошибке)
        """
        # Проверка владельца
        stmt = select(UserReminderModel).where(
            UserReminderModel.FID == reminder_id,
            or_(
                UserReminderModel.FK_User == user_id,
                UserReminderModel.FID.in_(
                    select(UserReminderShareModel.FK_Reminder).where(UserReminderShareModel.FK_User == user_id)
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

        # Обновление общих дел
        if reminder.FIsGroupReminder:
            stmt = (
                update(UserReminderShareModel)
                .where(UserReminderShareModel.FK_Reminder == reminder_id, UserReminderShareModel.FK_User == user_id)
                .values(FIsCompleted=True, FIsSuccessful=successful, FCompletedAt=datetime_now())
            )
            await session.execute(stmt)

        await session.commit()

        return True, "Reminder completed successfully"

    # ==================== ПОЛУЧЕНИЕ СПИСКА ====================

    @staticmethod
    @log_exceptions(db_logger)
    async def get_reminders(
        session: AsyncSession,
        user_id: int,
        date: datetime | None = None,
        category: str | None = None,
        include_completed: bool = False,
        limit: int | None = None,
        offset: int = 0,
    ) -> list[UserReminderModel]:
        """
        Получение списка дел пользователя.

        Args:
            session: Сессия БД
            user_id: ID пользователя
            date: Фильтр по дате
            category: Фильтр по категории
            include_completed: Включать завершенные
            limit: Лимит записей
            offset: Смещение

        Returns:
            List[ReminderModel]: Список напоминаний
        """
        # Базовый запрос
        stmt = select(UserReminderModel).where(
            or_(
                UserReminderModel.FK_User == user_id,
                UserReminderModel.FID.in_(
                    select(UserReminderShareModel.FK_Reminder).where(UserReminderShareModel.FK_User == user_id)
                ),
            ),
            UserReminderModel.FIsDeleted.is_(False),
        )

        # Фильтр по дате
        if date:
            start_of_day = date.replace(hour=0, minute=0, second=0, microsecond=0)
            end_of_day = date.replace(hour=23, minute=59, second=59, microsecond=999999)
            stmt = stmt.where(
                or_(UserReminderModel.FRemindAt >= start_of_day, UserReminderModel.FRemindAt <= end_of_day)
            )

        if category:
            stmt = stmt.where(UserReminderModel.FCategory == category)

        if not include_completed:
            stmt = stmt.where(UserReminderModel.FIsCompleted.is_(False))

        stmt = stmt.order_by(UserReminderModel.FRemindAt)

        if limit:
            stmt = stmt.limit(limit)

        if offset:
            stmt = stmt.offset(offset)

        result = await session.execute(stmt)
        return list(result.scalars().all())

    # ==================== ПОЛУЧЕНИЕ ПО ID ====================

    @staticmethod
    @log_exceptions(db_logger)
    async def get_reminder_by_id(session: AsyncSession, reminder_id: int) -> UserReminderModel | None:
        """
        Получение напоминания по ID.

        Args:
            session: Сессия БД
            reminder_id: ID напоминания

        Returns:
            UserReminderModel | None: Напоминание или None
        """
        stmt = select(UserReminderModel).where(UserReminderModel.FID == reminder_id)
        result = await session.execute(stmt)
        return result.scalar_one_or_none()  # type: ignore[no-any-return]

    # ==================== ПОИСК ПО КОДОВОМУ СЛОВУ ====================

    @staticmethod
    @log_exceptions(db_logger)
    async def find_by_code_word(
        session: AsyncSession,
        user_id: int,
        code_word: str,
        chat_id: int | None = None,
        include_completed: bool = False,
    ) -> list[UserReminderModel]:
        """
        Поиск дел по кодовому слову.

        Args:
            session: Сессия БД
            user_id: ID пользователя
            code_word: Кодовое слово
            chat_id: ID чата (опционально)
            include_completed: Включать завершенные

        Returns:
            List[ReminderModel]: Список найденных напоминаний
        """
        stmt = select(UserReminderModel).where(
            or_(
                UserReminderModel.FK_User == user_id,
                UserReminderModel.FID.in_(
                    select(UserReminderShareModel.FK_Reminder).where(UserReminderShareModel.FK_User == user_id)
                ),
            ),
            UserReminderModel.FCodeWord == code_word,
            UserReminderModel.FIsActive,
            UserReminderModel.FIsDeleted.is_(False),
        )

        if not include_completed:
            stmt = stmt.where(UserReminderModel.FIsCompleted.is_(False))

        if chat_id:
            stmt = stmt.where(
                or_(UserReminderModel.FK_Chat == chat_id, UserReminderModel.FNotificationType == "private")
            )

        result = await session.execute(stmt)
        return list(result.scalars().all())

    # ==================== АКТИВНЫЕ НАПОМИНАНИЯ ====================

    @staticmethod
    @log_exceptions(db_logger)
    async def get_active_reminders(
        session: AsyncSession,
        before_time: datetime | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> list[UserReminderModel]:
        """
        Получение активных напоминаний, время которых наступило.

        Args:
            session: Сессия БД
            before_time: Время, до которого проверять (по умолчанию - сейчас)
            limit: Лимит записей
            offset: Смещение

        Returns:
            List[ReminderModel]: Список активных напоминаний
        """
        if before_time is None:
            before_time = datetime_now()

        stmt = (
            select(UserReminderModel)
            .where(
                and_(
                    UserReminderModel.FRemindAt <= before_time,
                    UserReminderModel.FIsCompleted.is_(False),
                    UserReminderModel.FIsActive,
                    UserReminderModel.FIsDeleted.is_(False),
                )
            )
            .order_by(UserReminderModel.FRemindAt)
            .limit(limit)
            .offset(offset)
        )

        result = await session.execute(stmt)
        return list(result.scalars().all())

    # ==================== ОБНОВЛЕНИЕ СТАТУСА ====================

    @staticmethod
    @log_exceptions(db_logger)
    async def update_reminder_status(
        session: AsyncSession,
        reminder_id: int,
        remind_count: int | None = None,
        last_reminded: datetime | None = None,
        is_active: bool | None = None,
        remind_at: datetime | None = None,
    ) -> bool:
        """
        Обновление статуса напоминания после отправки уведомления.

        Args:
            session: Сессия БД
            reminder_id: ID напоминания
            remind_count: Количество отправленных уведомлений
            last_reminded: Время последнего уведомления
            is_active: Активно ли
            remind_at: Новое время напоминания

        Returns:
            bool: Успешно ли обновлено
        """
        values: dict[str, Any] = {}

        if remind_count is not None:
            values["FRemindCount"] = remind_count

        if last_reminded is not None:
            values["FLastReminded"] = last_reminded

        if is_active is not None:
            values["FIsActive"] = is_active

        if remind_at is not None:
            values["FRemindAt"] = remind_at

        if not values:
            return False

        stmt = update(UserReminderModel).where(UserReminderModel.FID == reminder_id).values(**values)
        result = await session.execute(stmt)
        await session.commit()

        return result.rowcount > 0 if hasattr(result, "rowcount") else True

    # ==================== ДЕАКТИВАЦИЯ ====================

    @staticmethod
    @log_exceptions(db_logger)
    async def deactivate_reminder(session: AsyncSession, reminder_id: int) -> bool:
        """
        Деактивация напоминания.

        Args:
            session: Сессия БД
            reminder_id: ID напоминания

        Returns:
            bool: Успешно ли деактивировано
        """
        stmt = update(UserReminderModel).where(UserReminderModel.FID == reminder_id).values(FIsActive=False)
        result = await session.execute(stmt)
        await session.commit()

        return result.rowcount > 0 if hasattr(result, "rowcount") else True

    # ==================== УДАЛЕНИЕ ====================

    @staticmethod
    @log_exceptions(db_logger)
    async def delete_reminder(session: AsyncSession, reminder_id: int, soft: bool = True) -> bool:
        """
        Удаление напоминания (мягкое или жесткое).

        Args:
            session: Сессия БД
            reminder_id: ID напоминания
            soft: Мягкое удаление (пометить как удаленное) или жесткое

        Returns:
            bool: Успешно ли удалено
        """
        if soft:
            stmt = (
                update(UserReminderModel)
                .where(UserReminderModel.FID == reminder_id)
                .values(FIsDeleted=True, FIsActive=False)
            )
            result = await session.execute(stmt)
        else:
            # Удаление связей
            stmt = delete(UserReminderShareModel).where(UserReminderShareModel.FK_Reminder == reminder_id)
            await session.execute(stmt)

            # Удаление напоминания
            stmt = delete(UserReminderModel).where(UserReminderModel.FID == reminder_id)
            result = await session.execute(stmt)

        await session.commit()

        return result.rowcount > 0 if hasattr(result, "rowcount") else True

    # ==================== СТАТИСТИКА ====================

    @staticmethod
    @log_exceptions(db_logger)
    async def get_stats(
        session: AsyncSession,
        user_id: int,
        period: str = "week",
    ) -> dict[str, Any]:
        """
        Получение статистики по делам пользователя.

        Args:
            session: Сессия БД
            user_id: ID пользователя
            period: Период (day, week, month, year)

        Returns:
            dict: Статистика
        """
        now = datetime_now()

        # Определение периода
        start_date: datetime
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
            func.count(UserReminderModel.FID).label("total"),
            func.count(UserReminderModel.FID).filter(UserReminderModel.FIsCompleted).label("completed"),
            func.count(UserReminderModel.FID)
            .filter(and_(UserReminderModel.FIsCompleted, UserReminderModel.FIsSuccessful))
            .label("successful"),
            func.count(UserReminderModel.FID)
            .filter(and_(UserReminderModel.FIsCompleted, UserReminderModel.FIsSuccessful.is_(False)))
            .label("unsuccessful"),
        ).where(
            or_(
                UserReminderModel.FK_User == user_id,
                UserReminderModel.FID.in_(
                    select(UserReminderShareModel.FK_Reminder).where(UserReminderShareModel.FK_User == user_id)
                ),
            ),
            UserReminderModel.FCreatedAt >= start_date,
        )

        result = await session.execute(stmt)
        stats = result.first()

        # Детальная статистика по дням
        daily_stmt = (
            select(
                func.date(UserReminderModel.FCompletedAt).label("date"),
                func.count(UserReminderModel.FID).label("total"),
                func.count(UserReminderModel.FID).filter(UserReminderModel.FIsSuccessful).label("successful"),
            )
            .where(
                or_(
                    UserReminderModel.FK_User == user_id,
                    UserReminderModel.FID.in_(
                        select(UserReminderShareModel.FK_Reminder).where(UserReminderShareModel.FK_User == user_id)
                    ),
                ),
                UserReminderModel.FIsCompleted,
                UserReminderModel.FCompletedAt >= start_date,
            )
            .group_by(func.date(UserReminderModel.FCompletedAt))
            .order_by(func.date(UserReminderModel.FCompletedAt))
        )

        daily_result = await session.execute(daily_stmt)
        daily = [
            {
                "date": row.date.isoformat() if row.date else None,
                "total": row.total or 0,
                "successful": row.successful or 0,
            }
            for row in daily_result.all()
        ]

        total = stats.total if stats and stats.total is not None else 0
        completed = stats.completed if stats and stats.completed is not None else 0
        successful = stats.successful if stats and stats.successful is not None else 0
        unsuccessful = stats.unsuccessful if stats and stats.unsuccessful is not None else 0

        return {
            "total": total,
            "completed": completed,
            "successful": successful,
            "unsuccessful": unsuccessful,
            "success_rate": (successful / completed * 100) if completed > 0 else 0,
            "daily": daily,
            "period": period,
        }

    # ==================== ФОРМАТИРОВАНИЕ ====================

    @staticmethod
    def format_reminder(reminder: UserReminderModel) -> dict[str, Any]:
        """
        Форматирование дела для вывода с поддержкой расшифровки.

        Args:
            reminder: Модель напоминания

        Returns:
            dict: Отформатированное напоминание
        """
        result: dict[str, Any] = {
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
                db_logger.error(f"Failed to decrypt reminder {reminder.FID}: {e}")
                result["title"] = "🔒 Ошибка расшифровки"
                result["description"] = None
                result["category"] = None
        else:
            result["title"] = reminder.FTitle
            result["description"] = reminder.FDescription
            result["category"] = reminder.FCategory

        return result

    # ==================== МАССОВЫЕ ОПЕРАЦИИ ====================

    @staticmethod
    @log_exceptions(db_logger)
    async def bulk_deactivate(
        session: AsyncSession,
        reminder_ids: list[int],
    ) -> int:
        """
        Массовая деактивация напоминаний.

        Args:
            session: Сессия БД
            reminder_ids: Список ID напоминаний

        Returns:
            int: Количество деактивированных напоминаний
        """
        if not reminder_ids:
            return 0

        stmt = update(UserReminderModel).where(UserReminderModel.FID.in_(reminder_ids)).values(FIsActive=False)
        result = await session.execute(stmt)
        await session.commit()

        return result.rowcount if hasattr(result, "rowcount") else len(reminder_ids)

    @staticmethod
    @log_exceptions(db_logger)
    async def bulk_delete(
        session: AsyncSession,
        reminder_ids: list[int],
        soft: bool = True,
    ) -> int:
        """
        Массовое удаление напоминаний.

        Args:
            session: Сессия БД
            reminder_ids: Список ID напоминаний
            soft: Мягкое или жесткое удаление

        Returns:
            int: Количество удаленных напоминаний
        """
        if not reminder_ids:
            return 0

        if soft:
            stmt = (
                update(UserReminderModel)
                .where(UserReminderModel.FID.in_(reminder_ids))
                .values(FIsDeleted=True, FIsActive=False)
            )
            result = await session.execute(stmt)
        else:
            # Удаление связей
            stmt = delete(UserReminderShareModel).where(UserReminderShareModel.FK_Reminder.in_(reminder_ids))
            await session.execute(stmt)

            # Удаление напоминаний
            stmt = delete(UserReminderModel).where(UserReminderModel.FID.in_(reminder_ids))
            result = await session.execute(stmt)

        await session.commit()

        return result.rowcount if hasattr(result, "rowcount") else len(reminder_ids)


__all__ = ["ReminderRepository"]
