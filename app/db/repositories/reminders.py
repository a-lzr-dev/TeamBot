import json
from datetime import datetime, timedelta
from typing import Any

from sqlalchemy import and_, delete, func, or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from ...logger import db_logger
from ...models import UserReminderModel, UserReminderShareModel, datetime_now
from ...utils.crypto import decrypt_data, encrypt_data
from ...utils.decorators import log_exceptions


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
        db_logger.info(f"🆕 [create_reminder] Creating reminder for user {user_id}: {title[:50]}...")

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

        db_logger.info(f"✅ [create_reminder] Created reminder #{reminder.FID} for user {user_id}")
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
        db_logger.info(f"✅ [complete_reminder] Completing reminder #{reminder_id} for user {user_id}")

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

        db_logger.debug(f"📝 SQL: {stmt.compile(compile_kwargs={'literal_binds': True})}")

        result = await session.execute(stmt)
        reminder = result.scalar_one_or_none()

        if not reminder:
            db_logger.warning(
                f"⚠️ [complete_reminder] Reminder #{reminder_id} not found or no permission for user {user_id}"
            )
            return False, "Reminder not found or no permission"

        # Обновление
        reminder.FIsCompleted = True
        reminder.FIsSuccessful = successful
        reminder.FCompletedAt = datetime_now()

        # Обновление общих дел
        if reminder.FIsGroupReminder:
            update_stmt = (
                update(UserReminderShareModel)
                .where(UserReminderShareModel.FK_Reminder == reminder_id, UserReminderShareModel.FK_User == user_id)
                .values(FIsCompleted=True, FIsSuccessful=successful, FCompletedAt=datetime_now())
            )

            db_logger.debug(f"📝 SQL (update share): {update_stmt.compile(compile_kwargs={'literal_binds': True})}")

            await session.execute(update_stmt)

        await session.commit()

        db_logger.info(f"✅ [complete_reminder] Reminder #{reminder_id} completed by user {user_id}")
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
        db_logger.info(f"📋 [get_reminders] Getting reminders for user {user_id}")

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

        db_logger.debug(f"📝 SQL: {stmt.compile(compile_kwargs={'literal_binds': True})}")

        result = await session.execute(stmt)
        reminders = list(result.scalars().all())

        db_logger.info(f"✅ [get_reminders] Found {len(reminders)} reminders for user {user_id}")
        return reminders

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
        db_logger.info(f"🔍 [get_reminder_by_id] Getting reminder by ID: {reminder_id}")

        stmt = select(UserReminderModel).where(UserReminderModel.FID == reminder_id)

        db_logger.debug(f"📝 SQL: {stmt.compile(compile_kwargs={'literal_binds': True})}")

        result = await session.execute(stmt)
        reminder: UserReminderModel | None = result.scalar_one_or_none()

        if reminder:
            db_logger.info(f"✅ [get_reminder_by_id] Found reminder #{reminder_id}")
        else:
            db_logger.warning(f"⚠️ [get_reminder_by_id] Reminder #{reminder_id} not found")

        return reminder

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
        db_logger.info(f"🔍 [find_by_code_word] Finding reminders by code word: {code_word} for user {user_id}")

        stmt = select(UserReminderModel).where(
            or_(
                UserReminderModel.FK_User == user_id,
                UserReminderModel.FID.in_(
                    select(UserReminderShareModel.FK_Reminder).where(UserReminderShareModel.FK_User == user_id)
                ),
            ),
            UserReminderModel.FCodeWord == code_word,
            UserReminderModel.FIsActive.is_(True),
            UserReminderModel.FIsDeleted.is_(False),
        )

        if not include_completed:
            stmt = stmt.where(UserReminderModel.FIsCompleted.is_(False))

        if chat_id:
            stmt = stmt.where(
                or_(UserReminderModel.FK_Chat == chat_id, UserReminderModel.FNotificationType == "private")
            )

        db_logger.debug(f"📝 SQL: {stmt.compile(compile_kwargs={'literal_binds': True})}")

        result = await session.execute(stmt)
        reminders = list(result.scalars().all())

        db_logger.info(f"✅ [find_by_code_word] Found {len(reminders)} reminders by code word '{code_word}'")
        return reminders

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
        db_logger.info(f"🔍 [get_active_reminders] Getting active reminders before {before_time or 'now'}")

        if before_time is None:
            before_time = datetime_now()

        stmt = (
            select(UserReminderModel)
            .where(
                and_(
                    UserReminderModel.FRemindAt <= before_time,
                    UserReminderModel.FIsCompleted.is_(False),
                    UserReminderModel.FIsActive.is_(True),
                    UserReminderModel.FIsDeleted.is_(False),
                )
            )
            .order_by(UserReminderModel.FRemindAt)
            .limit(limit)
            .offset(offset)
        )

        db_logger.debug(f"📝 SQL: {stmt.compile(compile_kwargs={'literal_binds': True})}")

        result = await session.execute(stmt)
        reminders = list(result.scalars().all())

        db_logger.info(f"✅ [get_active_reminders] Found {len(reminders)} active reminders")
        return reminders

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
        db_logger.info(f"🔄 [update_reminder_status] Updating reminder #{reminder_id} status")

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
            db_logger.warning(f"⚠️ [update_reminder_status] No values to update for reminder #{reminder_id}")
            return False

        update_stmt = update(UserReminderModel).where(UserReminderModel.FID == reminder_id).values(**values)

        db_logger.debug(f"📝 SQL: {update_stmt.compile(compile_kwargs={'literal_binds': True})}")

        result = await session.execute(update_stmt)
        await session.commit()

        success = result.rowcount > 0 if hasattr(result, "rowcount") else True

        if success:
            db_logger.info(f"✅ [update_reminder_status] Updated reminder #{reminder_id} status")
        else:
            db_logger.warning(f"⚠️ [update_reminder_status] Reminder #{reminder_id} not found")

        return success

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
        db_logger.info(f"🔕 [deactivate_reminder] Deactivating reminder #{reminder_id}")

        update_stmt = update(UserReminderModel).where(UserReminderModel.FID == reminder_id).values(FIsActive=False)

        db_logger.debug(f"📝 SQL: {update_stmt.compile(compile_kwargs={'literal_binds': True})}")

        result = await session.execute(update_stmt)
        await session.commit()

        success = result.rowcount > 0 if hasattr(result, "rowcount") else True

        if success:
            db_logger.info(f"✅ [deactivate_reminder] Deactivated reminder #{reminder_id}")
        else:
            db_logger.warning(f"⚠️ [deactivate_reminder] Reminder #{reminder_id} not found")

        return success

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
        db_logger.info(f"🗑️ [delete_reminder] Deleting reminder #{reminder_id} (soft={soft})")

        if soft:
            update_stmt = (
                update(UserReminderModel)
                .where(UserReminderModel.FID == reminder_id)
                .values(FIsDeleted=True, FIsActive=False)
            )

            db_logger.debug(f"📝 SQL: {update_stmt.compile(compile_kwargs={'literal_binds': True})}")

            result = await session.execute(update_stmt)
        else:
            # Удаление связей
            delete_stmt = delete(UserReminderShareModel).where(UserReminderShareModel.FK_Reminder == reminder_id)

            db_logger.debug(f"📝 SQL (delete shares): {delete_stmt.compile(compile_kwargs={'literal_binds': True})}")

            await session.execute(delete_stmt)

            # Удаление напоминания
            delete_stmt_msg = delete(UserReminderModel).where(UserReminderModel.FID == reminder_id)

            db_logger.debug(
                f"📝 SQL (delete reminder): {delete_stmt_msg.compile(compile_kwargs={'literal_binds': True})}"
            )

            result = await session.execute(delete_stmt_msg)

        await session.commit()

        success = result.rowcount > 0 if hasattr(result, "rowcount") else True

        if success:
            db_logger.info(f"✅ [delete_reminder] Deleted reminder #{reminder_id}")
        else:
            db_logger.warning(f"⚠️ [delete_reminder] Reminder #{reminder_id} not found")

        return success

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
        db_logger.info(f"📊 [get_stats] Getting reminder stats for user {user_id}, period={period}")

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
            func.count(UserReminderModel.FID).filter(UserReminderModel.FIsCompleted.is_(True)).label("completed"),
            func.count(UserReminderModel.FID)
            .filter(and_(UserReminderModel.FIsCompleted.is_(True), UserReminderModel.FIsSuccessful.is_(True)))
            .label("successful"),
            func.count(UserReminderModel.FID)
            .filter(and_(UserReminderModel.FIsCompleted.is_(True), UserReminderModel.FIsSuccessful.is_(False)))
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

        db_logger.debug(f"📝 SQL: {stmt.compile(compile_kwargs={'literal_binds': True})}")

        result = await session.execute(stmt)
        stats = result.first()

        # Детальная статистика по дням
        daily_stmt = (
            select(
                func.date(UserReminderModel.FCompletedAt).label("date"),
                func.count(UserReminderModel.FID).label("total"),
                func.count(UserReminderModel.FID).filter(UserReminderModel.FIsSuccessful.is_(True)).label("successful"),
            )
            .where(
                or_(
                    UserReminderModel.FK_User == user_id,
                    UserReminderModel.FID.in_(
                        select(UserReminderShareModel.FK_Reminder).where(UserReminderShareModel.FK_User == user_id)
                    ),
                ),
                UserReminderModel.FIsCompleted.is_(True),
                UserReminderModel.FCompletedAt >= start_date,
            )
            .group_by(func.date(UserReminderModel.FCompletedAt))
            .order_by(func.date(UserReminderModel.FCompletedAt))
        )

        db_logger.debug(f"📝 SQL (daily): {daily_stmt.compile(compile_kwargs={'literal_binds': True})}")

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

        result_stats = {
            "total": total,
            "completed": completed,
            "successful": successful,
            "unsuccessful": unsuccessful,
            "success_rate": (successful / completed * 100) if completed > 0 else 0,
            "daily": daily,
            "period": period,
        }

        db_logger.info(
            f"✅ [get_stats] Stats: total={total}, completed={completed}, rate={result_stats['success_rate']:.1f}%"
        )
        return result_stats

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
            db_logger.debug("ℹ️ [bulk_deactivate] No reminder IDs provided")
            return 0

        db_logger.info(f"🔕 [bulk_deactivate] Deactivating {len(reminder_ids)} reminders")

        update_stmt = update(UserReminderModel).where(UserReminderModel.FID.in_(reminder_ids)).values(FIsActive=False)

        db_logger.debug(f"📝 SQL: {update_stmt.compile(compile_kwargs={'literal_binds': True})}")

        result = await session.execute(update_stmt)
        await session.commit()

        rowcount = result.rowcount if hasattr(result, "rowcount") else len(reminder_ids)

        db_logger.info(f"✅ [bulk_deactivate] Deactivated {rowcount} reminders")
        return rowcount

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
            db_logger.debug("ℹ️ [bulk_delete] No reminder IDs provided")
            return 0

        db_logger.info(f"🗑️ [bulk_delete] Deleting {len(reminder_ids)} reminders (soft={soft})")

        if soft:
            update_stmt = (
                update(UserReminderModel)
                .where(UserReminderModel.FID.in_(reminder_ids))
                .values(FIsDeleted=True, FIsActive=False)
            )

            db_logger.debug(f"📝 SQL: {update_stmt.compile(compile_kwargs={'literal_binds': True})}")

            result = await session.execute(update_stmt)
        else:
            # Удаление связей
            delete_stmt = delete(UserReminderShareModel).where(UserReminderShareModel.FK_Reminder.in_(reminder_ids))

            db_logger.debug(f"📝 SQL (delete shares): {delete_stmt.compile(compile_kwargs={'literal_binds': True})}")

            await session.execute(delete_stmt)

            # Удаление напоминаний
            delete_stmt_msg = delete(UserReminderModel).where(UserReminderModel.FID.in_(reminder_ids))

            db_logger.debug(
                f"📝 SQL (delete reminders): {delete_stmt_msg.compile(compile_kwargs={'literal_binds': True})}"
            )

            result = await session.execute(delete_stmt_msg)

        await session.commit()

        rowcount = result.rowcount if hasattr(result, "rowcount") else len(reminder_ids)

        db_logger.info(f"✅ [bulk_delete] Deleted {rowcount} reminders")
        return rowcount


__all__ = ["ReminderRepository"]
