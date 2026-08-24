"""
Репозиторий для работы с напоминаниями и делами пользователей.

Назначение:
    Предоставляет полный набор методов для управления напоминаниями и делами
    пользователей: создание, завершение, получение списка, поиск, обновление
    статуса, деактивация, удаление и статистика.

Основные разделы:
    1. Создание напоминаний (с поддержкой шифрования и общих дел)
    2. Завершение дел (с отметкой успешности)
    3. Получение списка дел (с фильтрацией и пагинацией)
    4. Получение дела по ID
    5. Поиск по кодовому слову
    6. Активные напоминания (для фоновой отправки)
    7. Обновление статуса (после отправки уведомления)
    8. Деактивация и удаление (мягкое/жёсткое)
    9. Статистика по делам
    10. Форматирование дела (с расшифровкой)
    11. Массовые операции (деактивация, удаление)

Технические особенности:
    - Все методы статические, используют AsyncSession
    - Поддержка шифрования конфиденциальных данных через encrypt_data/decrypt_data
    - Мягкое удаление (FIsDeleted) вместо физического удаления
    - Общие дела через UserReminderShareModel
    - Кодовые слова для быстрого поиска
    - Поддержка повторяющихся напоминаний (интервал, максимальное количество)
    - Автоматическое обновление времени последнего напоминания

Архитектура:
    - Работает с моделями UserReminderModel и UserReminderShareModel
    - Использует cryptography для шифрования данных
    - Интегрируется с reminder_service и reminder_notification_service
    - Поддерживает как личные, так и групповые дела
"""

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
    """Репозиторий для работы с напоминаниями и делами.

    Предоставляет методы для управления напоминаниями пользователей.
    Все методы асинхронны и принимают AsyncSession.
    """

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
        """Создание напоминания с поддержкой шифрования.

        Args:
            session: Асинхронная сессия SQLAlchemy
            user_id: ID пользователя-владельца
            title: Название напоминания
            remind_at: Время первого напоминания
            description: Описание (опционально)
            category: Категория (опционально)
            remind_until: Дата окончания оповещений (опционально)
            remind_interval: Интервал между напоминаниями в минутах (опционально)
            max_remind_count: Максимальное количество оповещений (опционально)
            code_word: Кодовое слово для поиска (опционально)
            notification_type: Тип уведомления (private, group, both)
            chat_id: ID чата для групповых уведомлений
            shared_with: Список ID пользователей для общего дела
            encrypt: Шифровать данные

        Returns:
            UserReminderModel: Созданное напоминание
        """
        db_logger.debug(f"🆕 [create_reminder] Creating reminder for user {user_id}: {title[:50]}...")

        encrypted_data = None
        is_encrypted = False

        if encrypt:
            try:
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

        if shared_with:
            for shared_user_id in shared_with:
                share = UserReminderShareModel(FK_Reminder=reminder.FID, FK_User=shared_user_id)
                session.add(share)

        await session.commit()
        await session.refresh(reminder)

        db_logger.info(f"✅ Created reminder #{reminder.FID} for user {user_id}")
        return reminder

    # ==================== ЗАВЕРШЕНИЕ ====================

    @staticmethod
    @log_exceptions(db_logger)
    async def complete_reminder(
        session: AsyncSession, reminder_id: int, user_id: int, successful: bool = True
    ) -> tuple[bool, str | None]:
        """Завершение дела.

        Args:
            session: Асинхронная сессия SQLAlchemy
            reminder_id: ID напоминания
            user_id: ID пользователя, завершающего дело
            successful: Успешно ли выполнено

        Returns:
            tuple[bool, str | None]: (успех, сообщение об ошибке)
        """
        db_logger.debug(f"✅ [complete_reminder] Completing reminder #{reminder_id} for user {user_id}")

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

        reminder.FIsCompleted = True
        reminder.FIsSuccessful = successful
        reminder.FCompletedAt = datetime_now()

        if reminder.FIsGroupReminder:
            update_stmt = (
                update(UserReminderShareModel)
                .where(UserReminderShareModel.FK_Reminder == reminder_id, UserReminderShareModel.FK_User == user_id)
                .values(FIsCompleted=True, FIsSuccessful=successful, FCompletedAt=datetime_now())
            )

            db_logger.debug(f"📝 SQL (update share): {update_stmt.compile(compile_kwargs={'literal_binds': True})}")

            await session.execute(update_stmt)

        await session.commit()

        db_logger.info(f"✅ Reminder #{reminder_id} completed by user {user_id}")
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
        """Получение списка дел пользователя.

        Args:
            session: Асинхронная сессия SQLAlchemy
            user_id: ID пользователя
            date: Фильтр по дате (опционально)
            category: Фильтр по категории (опционально)
            include_completed: Включать завершённые дела
            limit: Лимит записей (опционально)
            offset: Смещение

        Returns:
            list[UserReminderModel]: Список напоминаний
        """
        db_logger.debug(f"📋 [get_reminders] Getting reminders for user {user_id}")

        stmt = select(UserReminderModel).where(
            or_(
                UserReminderModel.FK_User == user_id,
                UserReminderModel.FID.in_(
                    select(UserReminderShareModel.FK_Reminder).where(UserReminderShareModel.FK_User == user_id)
                ),
            ),
            UserReminderModel.FIsDeleted.is_(False),
        )

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

        db_logger.debug(f"✅ Found {len(reminders)} reminders for user {user_id}")
        return reminders

    # ==================== ПОЛУЧЕНИЕ ПО ID ====================

    @staticmethod
    @log_exceptions(db_logger)
    async def get_reminder_by_id(session: AsyncSession, reminder_id: int) -> UserReminderModel | None:
        """Получение напоминания по ID.

        Args:
            session: Асинхронная сессия SQLAlchemy
            reminder_id: ID напоминания

        Returns:
            UserReminderModel | None: Напоминание или None
        """
        db_logger.debug(f"🔍 [get_reminder_by_id] Getting reminder by ID: {reminder_id}")

        stmt = select(UserReminderModel).where(UserReminderModel.FID == reminder_id)

        db_logger.debug(f"📝 SQL: {stmt.compile(compile_kwargs={'literal_binds': True})}")

        result = await session.execute(stmt)
        reminder: UserReminderModel | None = result.scalar_one_or_none()

        if reminder:
            db_logger.debug(f"✅ Found reminder #{reminder_id}")
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
        """Поиск дел по кодовому слову.

        Args:
            session: Асинхронная сессия SQLAlchemy
            user_id: ID пользователя
            code_word: Кодовое слово для поиска
            chat_id: ID чата для фильтрации (опционально)
            include_completed: Включать завершённые дела

        Returns:
            list[UserReminderModel]: Список найденных напоминаний
        """
        db_logger.debug(f"🔍 [find_by_code_word] Finding reminders by code word: {code_word} for user {user_id}")

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

        db_logger.debug(f"✅ Found {len(reminders)} reminders by code word '{code_word}'")
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
        """Получение активных напоминаний, время которых наступило.

        Args:
            session: Асинхронная сессия SQLAlchemy
            before_time: Время, до которого проверять (по умолчанию — сейчас)
            limit: Лимит записей
            offset: Смещение

        Returns:
            list[UserReminderModel]: Список активных напоминаний
        """
        db_logger.debug(f"🔍 [get_active_reminders] Getting active reminders before {before_time or 'now'}")

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

        db_logger.debug(f"✅ Found {len(reminders)} active reminders")
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
        """Обновление статуса напоминания после отправки уведомления.

        Args:
            session: Асинхронная сессия SQLAlchemy
            reminder_id: ID напоминания
            remind_count: Количество отправленных уведомлений
            last_reminded: Время последнего уведомления
            is_active: Активно ли
            remind_at: Новое время напоминания

        Returns:
            bool: Успешно ли обновлено
        """
        db_logger.debug(f"🔄 [update_reminder_status] Updating reminder #{reminder_id} status")

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
            db_logger.info(f"✅ Updated reminder #{reminder_id} status")
        else:
            db_logger.warning(f"⚠️ [update_reminder_status] Reminder #{reminder_id} not found")

        return success

    # ==================== ДЕАКТИВАЦИЯ ====================

    @staticmethod
    @log_exceptions(db_logger)
    async def deactivate_reminder(session: AsyncSession, reminder_id: int) -> bool:
        """Деактивация напоминания.

        Args:
            session: Асинхронная сессия SQLAlchemy
            reminder_id: ID напоминания

        Returns:
            bool: Успешно ли деактивировано
        """
        db_logger.debug(f"🔕 [deactivate_reminder] Deactivating reminder #{reminder_id}")

        update_stmt = update(UserReminderModel).where(UserReminderModel.FID == reminder_id).values(FIsActive=False)

        db_logger.debug(f"📝 SQL: {update_stmt.compile(compile_kwargs={'literal_binds': True})}")

        result = await session.execute(update_stmt)
        await session.commit()

        success = result.rowcount > 0 if hasattr(result, "rowcount") else True

        if success:
            db_logger.info(f"✅ Deactivated reminder #{reminder_id}")
        else:
            db_logger.warning(f"⚠️ [deactivate_reminder] Reminder #{reminder_id} not found")

        return success

    # ==================== УДАЛЕНИЕ ====================

    @staticmethod
    @log_exceptions(db_logger)
    async def delete_reminder(session: AsyncSession, reminder_id: int, soft: bool = True) -> bool:
        """Удаление напоминания (мягкое или жёсткое).

        Args:
            session: Асинхронная сессия SQLAlchemy
            reminder_id: ID напоминания
            soft: Мягкое удаление (пометить как удалённое) или жёсткое

        Returns:
            bool: Успешно ли удалено
        """
        db_logger.debug(f"🗑️ [delete_reminder] Deleting reminder #{reminder_id} (soft={soft})")

        if soft:
            update_stmt = (
                update(UserReminderModel)
                .where(UserReminderModel.FID == reminder_id)
                .values(FIsDeleted=True, FIsActive=False)
            )

            db_logger.debug(f"📝 SQL: {update_stmt.compile(compile_kwargs={'literal_binds': True})}")

            result = await session.execute(update_stmt)
        else:
            delete_stmt = delete(UserReminderShareModel).where(UserReminderShareModel.FK_Reminder == reminder_id)

            db_logger.debug(f"📝 SQL (delete shares): {delete_stmt.compile(compile_kwargs={'literal_binds': True})}")

            await session.execute(delete_stmt)

            delete_stmt_msg = delete(UserReminderModel).where(UserReminderModel.FID == reminder_id)

            db_logger.debug(
                f"📝 SQL (delete reminder): {delete_stmt_msg.compile(compile_kwargs={'literal_binds': True})}"
            )

            result = await session.execute(delete_stmt_msg)

        await session.commit()

        success = result.rowcount > 0 if hasattr(result, "rowcount") else True

        if success:
            db_logger.info(f"✅ Deleted reminder #{reminder_id}")
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
        """Получение статистики по делам пользователя.

        Args:
            session: Асинхронная сессия SQLAlchemy
            user_id: ID пользователя
            period: Период (day, week, month, year)

        Returns:
            dict: Статистика по делам
        """
        db_logger.debug(f"📊 [get_stats] Getting reminder stats for user {user_id}, period={period}")

        now = datetime_now()

        if period == "day":
            start_date = now.replace(hour=0, minute=0, second=0, microsecond=0)
        elif period == "week":
            start_date = now - timedelta(days=7)
        elif period == "month":
            start_date = now - timedelta(days=30)
        else:
            start_date = now - timedelta(days=365)

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

        db_logger.info(f"✅ Stats: total={total}, completed={completed}, rate={result_stats['success_rate']:.1f}%")
        return result_stats

    # ==================== ФОРМАТИРОВАНИЕ ====================

    @staticmethod
    def format_reminder(reminder: UserReminderModel) -> dict[str, Any]:
        """Форматирование дела для вывода с поддержкой расшифровки.

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
        """Массовая деактивация напоминаний.

        Args:
            session: Асинхронная сессия SQLAlchemy
            reminder_ids: Список ID напоминаний

        Returns:
            int: Количество деактивированных напоминаний
        """
        if not reminder_ids:
            db_logger.debug("ℹ️ [bulk_deactivate] No reminder IDs provided")
            return 0

        db_logger.debug(f"🔕 [bulk_deactivate] Deactivating {len(reminder_ids)} reminders")

        update_stmt = update(UserReminderModel).where(UserReminderModel.FID.in_(reminder_ids)).values(FIsActive=False)

        db_logger.debug(f"📝 SQL: {update_stmt.compile(compile_kwargs={'literal_binds': True})}")

        result = await session.execute(update_stmt)
        await session.commit()

        rowcount = result.rowcount if hasattr(result, "rowcount") else len(reminder_ids)

        db_logger.info(f"✅ Deactivated {rowcount} reminders")
        return rowcount

    @staticmethod
    @log_exceptions(db_logger)
    async def bulk_delete(
        session: AsyncSession,
        reminder_ids: list[int],
        soft: bool = True,
    ) -> int:
        """Массовое удаление напоминаний.

        Args:
            session: Асинхронная сессия SQLAlchemy
            reminder_ids: Список ID напоминаний
            soft: Мягкое или жёсткое удаление

        Returns:
            int: Количество удалённых напоминаний
        """
        if not reminder_ids:
            db_logger.debug("ℹ️ [bulk_delete] No reminder IDs provided")
            return 0

        db_logger.debug(f"🗑️ [bulk_delete] Deleting {len(reminder_ids)} reminders (soft={soft})")

        if soft:
            update_stmt = (
                update(UserReminderModel)
                .where(UserReminderModel.FID.in_(reminder_ids))
                .values(FIsDeleted=True, FIsActive=False)
            )

            db_logger.debug(f"📝 SQL: {update_stmt.compile(compile_kwargs={'literal_binds': True})}")

            result = await session.execute(update_stmt)
        else:
            delete_stmt = delete(UserReminderShareModel).where(UserReminderShareModel.FK_Reminder.in_(reminder_ids))

            db_logger.debug(f"📝 SQL (delete shares): {delete_stmt.compile(compile_kwargs={'literal_binds': True})}")

            await session.execute(delete_stmt)

            delete_stmt_msg = delete(UserReminderModel).where(UserReminderModel.FID.in_(reminder_ids))

            db_logger.debug(
                f"📝 SQL (delete reminders): {delete_stmt_msg.compile(compile_kwargs={'literal_binds': True})}"
            )

            result = await session.execute(delete_stmt_msg)

        await session.commit()

        rowcount = result.rowcount if hasattr(result, "rowcount") else len(reminder_ids)

        db_logger.info(f"✅ Deleted {rowcount} reminders")
        return rowcount


__all__ = ["ReminderRepository"]
