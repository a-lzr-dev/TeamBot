from datetime import datetime
from typing import Any

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from ...logger import db_logger
from ...models import AvanpostDirSysDataTypeModel, AvanpostSysUpdateModel, AvanpostSysUserUpdateModel
from ...utils.decorators import log_exceptions


class SystemRepository:
    """Репозиторий для работы с системными таблицами синхронизации"""

    # ==================== ТИПЫ ДАННЫХ ====================

    @staticmethod
    @log_exceptions(db_logger)
    async def get_all_data_types(
        session: AsyncSession,
    ) -> list[AvanpostDirSysDataTypeModel]:
        """
        Получение всех типов данных синхронизации.

        Args:
            session: Сессия БД

        Returns:
            list[AvanpostDirSysDataTypeModel]: Список всех типов данных
        """
        db_logger.info("📋 [get_all_data_types] Getting all data types")

        stmt = select(AvanpostDirSysDataTypeModel).order_by(AvanpostDirSysDataTypeModel.FID)

        db_logger.debug(f"📝 SQL: {stmt.compile(compile_kwargs={'literal_binds': True})}")

        result = await session.execute(stmt)
        data_types = list(result.scalars().all())

        db_logger.info(f"✅ [get_all_data_types] Found {len(data_types)} data types")
        return data_types

    @staticmethod
    @log_exceptions(db_logger)
    async def get_data_types_dict(
        session: AsyncSession,
    ) -> dict[int, dict[str, Any]]:
        """
        Получение всех типов данных в виде словаря для кеширования.

        Args:
            session: Сессия БД

        Returns:
            dict[int, dict]: Словарь {data_type_id: {name, table, user_related, deferred_sync}}
        """
        db_logger.info("📋 [get_data_types_dict] Getting data types as dict")

        stmt = select(
            AvanpostDirSysDataTypeModel.FID,
            AvanpostDirSysDataTypeModel.FName,
            AvanpostDirSysDataTypeModel.FTableName,
            AvanpostDirSysDataTypeModel.FUserRelated,
            AvanpostDirSysDataTypeModel.FDeferredSync,
        )

        db_logger.debug(f"📝 SQL: {stmt.compile(compile_kwargs={'literal_binds': True})}")

        result = await session.execute(stmt)
        rows = result.all()

        data_types = {
            row.FID: {
                "name": row.FName,
                "table": row.FTableName,
                "user_related": row.FUserRelated,
                "deferred_sync": row.FDeferredSync,
            }
            for row in rows
        }

        db_logger.info(f"✅ [get_data_types_dict] Found {len(data_types)} data types")
        return data_types

    @staticmethod
    @log_exceptions(db_logger)
    async def get_data_type_by_id(
        session: AsyncSession,
        data_type_id: int,
    ) -> AvanpostDirSysDataTypeModel | None:
        """
        Получение типа данных по ID.

        Args:
            session: Сессия БД
            data_type_id: ID типа данных

        Returns:
            AvanpostDirSysDataTypeModel | None: Модель типа данных или None
        """
        db_logger.info(f"🔍 [get_data_type_by_id] Getting data type by ID: {data_type_id}")

        stmt = select(AvanpostDirSysDataTypeModel).where(AvanpostDirSysDataTypeModel.FID == data_type_id)

        db_logger.debug(f"📝 SQL: {stmt.compile(compile_kwargs={'literal_binds': True})}")

        result = await session.execute(stmt)
        data_type: AvanpostDirSysDataTypeModel | None = result.scalar_one_or_none()

        if data_type:
            db_logger.info(f"✅ [get_data_type_by_id] Found data type {data_type_id}")
        else:
            db_logger.warning(f"⚠️ [get_data_type_by_id] Data type {data_type_id} not found")

        return data_type

    @staticmethod
    @log_exceptions(db_logger)
    async def get_data_type_ids(
        session: AsyncSession,
    ) -> list[int]:
        """
        Получение всех ID типов данных.

        Args:
            session: Сессия БД

        Returns:
            list[int]: Список ID типов данных
        """
        db_logger.info("📋 [get_data_type_ids] Getting all data type IDs")

        stmt = select(AvanpostDirSysDataTypeModel.FID).order_by(AvanpostDirSysDataTypeModel.FID)

        db_logger.debug(f"📝 SQL: {stmt.compile(compile_kwargs={'literal_binds': True})}")

        result = await session.execute(stmt)
        ids = [row[0] for row in result.all()]

        db_logger.info(f"✅ [get_data_type_ids] Found {len(ids)} data type IDs")
        return ids

    @staticmethod
    @log_exceptions(db_logger)
    async def create_data_type(
        session: AsyncSession,
        data_type_id: int,
        name: str,
        table_name: str | None = None,
        user_related: bool = False,
        deferred_sync: bool = False,
    ) -> AvanpostDirSysDataTypeModel:
        """
        Создание нового типа данных.

        Args:
            session: Сессия БД
            data_type_id: ID типа данных
            name: Название
            table_name: Имя таблицы
            user_related: Связан ли с пользователем
            deferred_sync: Отложенная синхронизация

        Returns:
            AvanpostDirSysDataTypeModel: Созданная модель
        """
        db_logger.info(f"🆕 [create_data_type] Creating data type {data_type_id}: {name}")

        data_type = AvanpostDirSysDataTypeModel(
            FID=data_type_id,
            FName=name,
            FTableName=table_name,
            FUserRelated=user_related,
            FDeferredSync=deferred_sync,
        )
        session.add(data_type)
        await session.flush()
        await session.refresh(data_type)

        db_logger.info(f"✅ [create_data_type] Created data type {data_type_id}")
        return data_type

    @staticmethod
    @log_exceptions(db_logger)
    async def create_data_types_bulk(
        session: AsyncSession,
        data_types: list[dict[str, Any]],
    ) -> int:
        """
        Массовое создание типов данных.

        Args:
            session: Сессия БД
            data_types: Список словарей с данными

        Returns:
            int: Количество созданных записей
        """
        if not data_types:
            db_logger.debug("ℹ️ [create_data_types_bulk] No data types to create")
            return 0

        db_logger.info(f"📋 [create_data_types_bulk] Creating {len(data_types)} data types")

        created = 0
        for data in data_types:
            try:
                # Проверяем существование
                existing = await SystemRepository.get_data_type_by_id(
                    session=session,
                    data_type_id=data["FID"],
                )
                if not existing:
                    await SystemRepository.create_data_type(
                        session=session,
                        data_type_id=data["FID"],
                        name=data["FName"],
                        table_name=data.get("FTableName"),
                        user_related=data.get("FUserRelated", False),
                        deferred_sync=data.get("FDeferredSync", False),
                    )
                    created += 1
            except Exception as e:
                db_logger.warning(f"⚠️ [create_data_types_bulk] Failed to create data type {data.get('FID')}: {e}")

        if created > 0:
            db_logger.info(f"✅ [create_data_types_bulk] Created {created} new data types")
        else:
            db_logger.debug("ℹ️ [create_data_types_bulk] No new data types created")

        return created

    # ==================== СИСТЕМНЫЕ НАСТРОЙКИ СИНХРОНИЗАЦИИ ====================

    @staticmethod
    @log_exceptions(db_logger)
    async def get_sync_time(
        session: AsyncSession,
        data_type_id: int,
    ) -> datetime | None:
        """
        Получение времени последней синхронизации для типа данных.

        Args:
            session: Сессия БД
            data_type_id: ID типа данных

        Returns:
            datetime | None: Время синхронизации или None
        """
        db_logger.info(f"🔍 [get_sync_time] Getting sync time for type {data_type_id}")

        stmt = select(AvanpostSysUpdateModel.FDate).where(AvanpostSysUpdateModel.FK_Type == data_type_id)

        db_logger.debug(f"📝 SQL: {stmt.compile(compile_kwargs={'literal_binds': True})}")

        result = await session.execute(stmt)
        sync_time = result.scalar_one_or_none()

        if sync_time is None:
            db_logger.warning(f"⚠️ [get_sync_time] No sync time found for type {data_type_id}")
            return None

        if not isinstance(sync_time, datetime):
            return None

        db_logger.info(f"✅ [get_sync_time] Sync time for type {data_type_id}: {sync_time}")
        return sync_time

    @staticmethod
    @log_exceptions(db_logger)
    async def get_sync_times(
        session: AsyncSession,
        data_types: list[int],
        show_logs: bool = True,
    ) -> dict[int, datetime]:
        """
        Получение времени синхронизации для списка типов данных.
        Оптимизировано: один запрос вместо N.

        Args:
            session: Сессия БД
            data_types: Список ID типов данных
            show_logs: Отображение подробного логирования (Debug уровень)

        Returns:
            dict[int, datetime]: Словарь {data_type_id: last_sync_time}
        """
        if show_logs:
            db_logger.info(f"📋 [get_sync_times] Getting sync times for {len(data_types)} types (optimized)")

        result: dict[int, datetime] = {}
        default_time = datetime(1900, 1, 1)

        if not data_types:
            return result

        stmt = select(AvanpostSysUpdateModel).where(AvanpostSysUpdateModel.FK_Type.in_(data_types))

        if show_logs:
            db_logger.debug(f"📝 SQL: {stmt.compile(compile_kwargs={'literal_binds': True})}")

        result_query = await session.execute(stmt)
        records = result_query.scalars().all()

        # Создание словаря из полученных записей
        existing = {record.FK_Type: record.FDate for record in records}

        # Проход по всем типам и заполнение результата
        for dt_id in data_types:
            if dt_id in existing:
                result[dt_id] = existing[dt_id]
            else:
                # Создание с временем по умолчанию
                result[dt_id] = default_time
                new_record = AvanpostSysUpdateModel(
                    FK_Type=dt_id,
                    FDate=default_time,
                )
                session.add(new_record)

        await session.flush()

        if show_logs:
            db_logger.info(
                f"✅ [get_sync_times] Found {len(existing)} existing sync records, created {len(data_types) - len(existing)} new"
            )

        return result

    @staticmethod
    @log_exceptions(db_logger)
    async def create_sync_record(
        session: AsyncSession,
        data_type_id: int,
        sync_time: datetime | None = None,
    ) -> AvanpostSysUpdateModel | None:
        """
        Создание записи синхронизации для типа данных.

        Args:
            session: Сессия БД
            data_type_id: ID типа данных
            sync_time: Время синхронизации (по умолчанию - 1900-01-01)

        Returns:
            AvanpostSysUpdateModel: Созданная запись
        """
        db_logger.info(f"🆕 [create_sync_record] Creating sync record for type {data_type_id}")

        if sync_time is None:
            sync_time = datetime(1900, 1, 1)

        # Проверяем существование
        existing = await SystemRepository.get_sync_time(session, data_type_id)
        if existing is not None:
            db_logger.debug(f"ℹ️ [create_sync_record] Sync record for type {data_type_id} already exists")
            return None

        record = AvanpostSysUpdateModel(
            FK_Type=data_type_id,
            FDate=sync_time,
        )
        session.add(record)
        await session.flush()
        await session.refresh(record)

        db_logger.info(f"✅ [create_sync_record] Created sync record for type {data_type_id}")
        return record

    @staticmethod
    @log_exceptions(db_logger)
    async def create_sync_records_bulk(
        session: AsyncSession,
        data_type_ids: list[int],
        sync_time: datetime | None = None,
    ) -> int:
        """
        Массовое создание записей синхронизации.
        Логирует только итоговое количество.

        Args:
            session: Сессия БД
            data_type_ids: Список ID типов данных
            sync_time: Время синхронизации (по умолчанию - 1900-01-01)

        Returns:
            int: Количество созданных записей
        """
        if not data_type_ids:
            db_logger.debug("ℹ️ [create_sync_records_bulk] No data type IDs provided")
            return 0

        db_logger.info(f"📋 [create_sync_records_bulk] Creating sync records for {len(data_type_ids)} types")

        if sync_time is None:
            sync_time = datetime(1900, 1, 1)

        created = 0
        existing_times = await SystemRepository.get_sync_times(session, data_type_ids)

        for dt_id in data_type_ids:
            if dt_id not in existing_times:
                record = AvanpostSysUpdateModel(
                    FK_Type=dt_id,
                    FDate=sync_time,
                )
                session.add(record)
                created += 1

        if created > 0:
            await session.flush()
            db_logger.info(f"✅ [create_sync_records_bulk] Created {created} system sync records")
        else:
            db_logger.debug("ℹ️ [create_sync_records_bulk] No new sync records created")

        return created

    @staticmethod
    @log_exceptions(db_logger)
    async def update_sync_time(
        session: AsyncSession,
        data_type_id: int,
        sync_time: datetime,
        show_logs: bool = True,
    ) -> None:
        """
        Обновление времени синхронизации для типа данных.

        Args:
            session: Сессия БД
            data_type_id: ID типа данных
            sync_time: Новое время синхронизации
            show_logs: Отображение подробного логирования (Debug уровень)
        """
        if show_logs:
            db_logger.info(f"🔄 [update_sync_time] Updating sync time for type {data_type_id}: {sync_time}")

        stmt = (
            update(AvanpostSysUpdateModel).where(AvanpostSysUpdateModel.FK_Type == data_type_id).values(FDate=sync_time)
        )

        if show_logs:
            db_logger.debug(f"📝 SQL: {stmt.compile(compile_kwargs={'literal_binds': True})}")

        await session.execute(stmt)

        if show_logs:
            db_logger.info(f"✅ [update_sync_time] Updated sync time for type {data_type_id}")

    @staticmethod
    @log_exceptions(db_logger)
    async def update_sync_times_bulk(
        session: AsyncSession,
        sync_times: dict[int, datetime],
        show_logs: bool = True,
    ) -> None:
        """
        Массовое обновление времени синхронизации для системных типов данных.

        Args:
            session: Сессия БД
            sync_times: Словарь {data_type_id: sync_time}
            show_logs: Отображение подробного логирования (Debug уровень)
        """
        if not sync_times:
            db_logger.debug("ℹ️ [update_sync_times_bulk] No sync times to update")
            return

        if show_logs:
            db_logger.info(f"🔄 [update_sync_times_bulk] Updating {len(sync_times)} sync times")

        for data_type_id, sync_time in sync_times.items():
            await SystemRepository.update_sync_time(session, data_type_id, sync_time, show_logs)

        if show_logs:
            db_logger.info(f"✅ [update_sync_times_bulk] Updated {len(sync_times)} sync times")

    # ==================== ПОЛЬЗОВАТЕЛЬСКИЕ НАСТРОЙКИ СИНХРОНИЗАЦИИ ====================

    @staticmethod
    @log_exceptions(db_logger)
    async def get_user_sync_times(
        session: AsyncSession,
        user_id: int,
        data_types: list[int],
        show_logs: bool = True,
    ) -> dict[int, datetime]:
        """
        Получение времени синхронизации пользователя для списка типов данных.
        """
        if show_logs:
            db_logger.debug(f"📋 [get_user_sync_times] Getting user sync times for user {user_id}")

        result: dict[int, datetime] = {}
        default_time = datetime(1900, 1, 1)

        if not data_types:
            return result

        stmt = select(AvanpostSysUserUpdateModel).where(
            AvanpostSysUserUpdateModel.FK_User == user_id,
            AvanpostSysUserUpdateModel.FK_Type.in_(data_types),
        )

        if show_logs:
            db_logger.debug(f"📝 SQL: {stmt.compile(compile_kwargs={'literal_binds': True})}")

        result_query = await session.execute(stmt)
        records = result_query.scalars().all()

        existing = {record.FK_Type: record.FDate for record in records}

        created_count = 0
        for dt_id in data_types:
            if dt_id in existing:
                result[dt_id] = existing[dt_id]
            else:
                result[dt_id] = default_time
                new_record = AvanpostSysUserUpdateModel(
                    FK_User=user_id,
                    FK_Type=dt_id,
                    FDate=default_time,
                )
                session.add(new_record)
                created_count += 1

        if created_count > 0:
            await session.flush()

        if show_logs:
            db_logger.info(
                f"✅ [get_user_sync_times] Found {len(existing)} existing records, created {created_count} new"
            )

        return result

    @staticmethod
    @log_exceptions(db_logger)
    async def create_user_sync_records_bulk_with_stats(
        session: AsyncSession,
        user_ids: list[int],
        data_type_ids: list[int],
        sync_time: datetime | None = None,
        data_type_names: dict[int, str] | None = None,
    ) -> dict[str, Any]:
        """
        Массовое создание записей синхронизации для множества пользователей
        с возвратом агрегированной статистики по типам данных.

        Args:
            session: Сессия БД
            user_ids: Список ID пользователей
            data_type_ids: Список ID типов данных
            sync_time: Время синхронизации (по умолчанию - 1900-01-01)
            data_type_names: Словарь {data_type_id: table_name} для отображения

        Returns:
            dict: Статистика по типам данных
        """
        db_logger.info(
            f"📋 [create_user_sync_records_bulk_with_stats] Creating user sync records for {len(user_ids)} users"
        )

        if not user_ids or not data_type_ids:
            return {
                "total_users": len(user_ids),
                "users_with_records": 0,
                "total_records_created": 0,
                "by_data_type": {},
            }

        if sync_time is None:
            sync_time = datetime(1900, 1, 1)

        # Получение имен типов данных, если не переданы
        if data_type_names is None:
            data_type_names = {}
            stmt = select(AvanpostDirSysDataTypeModel.FID, AvanpostDirSysDataTypeModel.FTableName).where(
                AvanpostDirSysDataTypeModel.FID.in_(data_type_ids)
            )

            db_logger.debug(f"📝 SQL (get names): {stmt.compile(compile_kwargs={'literal_binds': True})}")

            result = await session.execute(stmt)
            for row in result.all():
                data_type_names[row.FID] = row.FTableName or f"Type_{row.FID}"

        # Счетчики по типам данных
        stats_by_type: dict[int, int] = dict.fromkeys(data_type_ids, 0)
        total_created = 0
        users_with_records = 0

        # Обработка пользователей пакетами
        batch_size = 50
        for i in range(0, len(user_ids), batch_size):
            batch_user_ids = user_ids[i : i + batch_size]

            for user_id in batch_user_ids:
                # Получение существующих записей для пользователя
                existing_times = await SystemRepository.get_user_sync_times(session, user_id, data_type_ids)

                user_created = 0
                for dt_id in data_type_ids:
                    if dt_id not in existing_times:
                        record = AvanpostSysUserUpdateModel(
                            FK_User=user_id,
                            FK_Type=dt_id,
                            FDate=sync_time,
                        )
                        session.add(record)
                        stats_by_type[dt_id] = stats_by_type.get(dt_id, 0) + 1
                        user_created += 1
                        total_created += 1

                if user_created > 0:
                    users_with_records += 1

                # Периодический flush для освобождения памяти
                if total_created % 1000 == 0:
                    await session.flush()

            # Коммит пакета
            await session.flush()

        # Финальный коммит
        await session.commit()

        # Формирование результата с человекочитаемыми названиями таблиц
        by_data_type_readable = {}
        for dt_id, count in stats_by_type.items():
            if count > 0:
                table_name = data_type_names.get(dt_id, f"Type_{dt_id}")
                by_data_type_readable[f"{dt_id} ({table_name})"] = count

        result = {
            "total_users": len(user_ids),
            "users_with_records": users_with_records,
            "total_records_created": total_created,
            "by_data_type": by_data_type_readable,
        }

        db_logger.info(
            f"✅ [create_user_sync_records_bulk_with_stats] Created {total_created} records for {users_with_records} users"
        )
        return result  # type: ignore[no-any-return]

    # ==================== ОБНОВЛЕНИЕ ПОЛЬЗОВАТЕЛЬСКИХ НАСТРОЕК ====================

    @staticmethod
    @log_exceptions(db_logger)
    async def update_user_sync_time(
        session: AsyncSession,
        user_id: int,
        data_type_id: int,
        sync_time: datetime,
        show_logs: bool = True,
    ) -> None:
        """
        Обновление времени синхронизации пользователя для типа данных.

        Args:
            session: Сессия БД
            user_id: ID пользователя
            data_type_id: ID типа данных
            sync_time: Новое время синхронизации
            show_logs: Отображение подробного логирования (Debug уровень)
        """
        if show_logs:
            db_logger.info(
                f"🔄 [update_user_sync_time] Updating user sync time for user {user_id}, type {data_type_id}: {sync_time}"
            )

        result = await session.execute(
            select(AvanpostSysUserUpdateModel).where(
                AvanpostSysUserUpdateModel.FK_User == user_id,
                AvanpostSysUserUpdateModel.FK_Type == data_type_id,
            )
        )
        record = result.scalar_one_or_none()

        if record:
            record.FDate = sync_time
        else:
            new_record = AvanpostSysUserUpdateModel(
                FK_User=user_id,
                FK_Type=data_type_id,
                FDate=sync_time,
            )
            session.add(new_record)

        if show_logs:
            db_logger.info(f"✅ [update_user_sync_time] Updated user sync time for user {user_id}, type {data_type_id}")

    @staticmethod
    @log_exceptions(db_logger)
    async def update_user_sync_times_bulk(
        session: AsyncSession,
        user_id: int,
        sync_times: dict[int, datetime],
        show_logs: bool = True,
    ) -> None:
        """
        Массовое обновление времени синхронизации для пользователя.

        Args:
            session: Сессия БД
            user_id: ID пользователя
            sync_times: Словарь {data_type_id: sync_time}
            show_logs: Отображение подробного логирования (Debug уровень)
        """
        if not sync_times:
            db_logger.debug("ℹ️ [update_user_sync_times_bulk] No sync times to update")
            return

        if show_logs:
            db_logger.info(
                f"🔄 [update_user_sync_times_bulk] Updating {len(sync_times)} user sync times for user {user_id}"
            )

        for data_type_id, sync_time in sync_times.items():
            await SystemRepository.update_user_sync_time(session, user_id, data_type_id, sync_time, show_logs)

        if show_logs:
            db_logger.info(f"✅ [update_user_sync_times_bulk] Updated {len(sync_times)} user sync times")

    # ==================== ДОПОЛНИТЕЛЬНЫЕ МЕТОДЫ ====================

    @staticmethod
    @log_exceptions(db_logger)
    async def delete_sync_record(
        session: AsyncSession,
        data_type_id: int,
    ) -> bool:
        """
        Удаление записи синхронизации для типа данных.

        Args:
            session: Сессия БД
            data_type_id: ID типа данных

        Returns:
            bool: Успешно ли удалено
        """
        db_logger.info(f"🗑️ [delete_sync_record] Deleting sync record for type {data_type_id}")

        stmt = select(AvanpostSysUpdateModel).where(AvanpostSysUpdateModel.FK_Type == data_type_id)

        db_logger.debug(f"📝 SQL: {stmt.compile(compile_kwargs={'literal_binds': True})}")

        result = await session.execute(stmt)
        record = result.scalar_one_or_none()

        if not record:
            db_logger.warning(f"⚠️ [delete_sync_record] Sync record for type {data_type_id} not found")
            return False

        await session.delete(record)
        await session.flush()

        db_logger.info(f"✅ [delete_sync_record] Deleted sync record for type {data_type_id}")
        return True

    @staticmethod
    @log_exceptions(db_logger)
    async def delete_user_sync_record(
        session: AsyncSession,
        user_id: int,
        data_type_id: int,
    ) -> bool:
        """
        Удаление записи синхронизации пользователя.

        Args:
            session: Сессия БД
            user_id: ID пользователя
            data_type_id: ID типа данных

        Returns:
            bool: Успешно ли удалено
        """
        db_logger.info(f"🗑️ [delete_user_sync_record] Deleting user sync record for user {user_id}, type {data_type_id}")

        stmt = select(AvanpostSysUserUpdateModel).where(
            AvanpostSysUserUpdateModel.FK_User == user_id,
            AvanpostSysUserUpdateModel.FK_Type == data_type_id,
        )

        db_logger.debug(f"📝 SQL: {stmt.compile(compile_kwargs={'literal_binds': True})}")

        result = await session.execute(stmt)
        record = result.scalar_one_or_none()

        if not record:
            db_logger.warning(
                f"⚠️ [delete_user_sync_record] User sync record for user {user_id}, type {data_type_id} not found"
            )
            return False

        await session.delete(record)
        await session.flush()

        db_logger.info(f"✅ [delete_user_sync_record] Deleted user sync record for user {user_id}, type {data_type_id}")
        return True


__all__ = ["SystemRepository"]
