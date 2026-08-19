from datetime import datetime
from typing import Any

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from ...exceptions import log_exceptions
from ...logger import db_logger
from ...models import AvanpostDirSysDataTypeModel, AvanpostSysUpdateModel, AvanpostSysUserUpdateModel


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
        stmt = select(AvanpostDirSysDataTypeModel).order_by(AvanpostDirSysDataTypeModel.FID)
        result = await session.execute(stmt)
        return list(result.scalars().all())

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
        stmt = select(
            AvanpostDirSysDataTypeModel.FID,
            AvanpostDirSysDataTypeModel.FName,
            AvanpostDirSysDataTypeModel.FTableName,
            AvanpostDirSysDataTypeModel.FUserRelated,
            AvanpostDirSysDataTypeModel.FDeferredSync,
        )
        result = await session.execute(stmt)
        rows = result.all()

        return {
            row.FID: {
                "name": row.FName,
                "table": row.FTableName,
                "user_related": row.FUserRelated,
                "deferred_sync": row.FDeferredSync,
            }
            for row in rows
        }

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
        stmt = select(AvanpostDirSysDataTypeModel).where(AvanpostDirSysDataTypeModel.FID == data_type_id)
        result = await session.execute(stmt)
        scalar: AvanpostDirSysDataTypeModel | None = result.scalar_one_or_none()
        return scalar

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
        stmt = select(AvanpostDirSysDataTypeModel.FID).order_by(AvanpostDirSysDataTypeModel.FID)
        result = await session.execute(stmt)
        return [row[0] for row in result.all()]

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
            return 0

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
                db_logger.warning(f"⚠️ Failed to create data type {data.get('FID')}: {e}")

        if created > 0:
            db_logger.info(f"✅ Created {created} new data types")
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
        stmt = select(AvanpostSysUpdateModel.FDate).where(AvanpostSysUpdateModel.FK_Type == data_type_id)
        result = await session.execute(stmt)
        sync_time = result.scalar_one_or_none()

        if sync_time is None:
            return None
        if not isinstance(sync_time, datetime):
            return None

        db_logger.debug(f"📖 GET sys sync time for type {data_type_id}: {sync_time}")
        return sync_time

    @staticmethod
    @log_exceptions(db_logger)
    async def get_sync_times(
        session: AsyncSession,
        data_types: list[int],
    ) -> dict[int, datetime]:
        """
        Получение времени синхронизации для списка типов данных.
        Оптимизировано: один запрос вместо N.

        Args:
            session: Сессия БД
            data_types: Список ID типов данных

        Returns:
            dict[int, datetime]: Словарь {data_type_id: last_sync_time}
        """
        db_logger.debug(f"📖 GET system sync times for {len(data_types)} types (optimized, single query)")

        result: dict[int, datetime] = {}
        default_time = datetime(1900, 1, 1)

        if not data_types:
            return result

        stmt = select(AvanpostSysUpdateModel).where(AvanpostSysUpdateModel.FK_Type.in_(data_types))
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
                db_logger.info(f"📅 Created sync record for system type {dt_id} with default time")

        await session.flush()

        db_logger.debug(f"📖 GET system sync times result: {len(result)} types (found {len(existing)} existing)")
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
        if sync_time is None:
            sync_time = datetime(1900, 1, 1)

        # Проверяем существование
        existing = await SystemRepository.get_sync_time(session, data_type_id)
        if existing is not None:
            db_logger.debug(f"ℹ️ Sync record for type {data_type_id} already exists")
            return None

        record = AvanpostSysUpdateModel(
            FK_Type=data_type_id,
            FDate=sync_time,
        )
        session.add(record)
        await session.flush()
        await session.refresh(record)

        db_logger.info(f"📅 Created sync record for type {data_type_id}")
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

        Args:
            session: Сессия БД
            data_type_ids: Список ID типов данных
            sync_time: Время синхронизации (по умолчанию - 1900-01-01)

        Returns:
            int: Количество созданных записей
        """
        if not data_type_ids:
            return 0

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
            db_logger.info(f"📅 Created {created} sync records")

        return created

    @staticmethod
    @log_exceptions(db_logger)
    async def update_sync_time(
        session: AsyncSession,
        data_type_id: int,
        sync_time: datetime,
    ) -> None:
        """
        Обновление времени синхронизации для типа данных.

        Args:
            session: Сессия БД
            data_type_id: ID типа данных
            sync_time: Новое время синхронизации
        """
        db_logger.debug(f"📝 UPDATE system sync time for type {data_type_id}: {sync_time}")

        await session.execute(
            update(AvanpostSysUpdateModel).where(AvanpostSysUpdateModel.FK_Type == data_type_id).values(FDate=sync_time)
        )

    @staticmethod
    @log_exceptions(db_logger)
    async def update_sync_times_bulk(
        session: AsyncSession,
        sync_times: dict[int, datetime],
    ) -> None:
        """
        Массовое обновление времени синхронизации.
        Оптимизировано: использует bulk_update.

        Args:
            session: Сессия БД
            sync_times: Словарь {data_type_id: sync_time}
        """
        if not sync_times:
            return

        db_logger.debug(f"📝 UPDATE system sync times bulk: {len(sync_times)} types (optimized)")

        for data_type_id, sync_time in sync_times.items():
            await session.execute(
                update(AvanpostSysUpdateModel)
                .where(AvanpostSysUpdateModel.FK_Type == data_type_id)
                .values(FDate=sync_time)
            )

    # ==================== ПОЛЬЗОВАТЕЛЬСКИЕ НАСТРОЙКИ СИНХРОНИЗАЦИИ ====================

    @staticmethod
    @log_exceptions(db_logger)
    async def get_user_sync_time(
        session: AsyncSession,
        user_id: int,
        data_type_id: int,
    ) -> datetime | None:
        """
        Получение времени последней синхронизации пользователя для типа данных.

        Args:
            session: Сессия БД
            user_id: ID пользователя
            data_type_id: ID типа данных

        Returns:
            datetime | None: Время синхронизации или None
        """
        stmt = select(AvanpostSysUserUpdateModel.FDate).where(
            AvanpostSysUserUpdateModel.FK_User == user_id,
            AvanpostSysUserUpdateModel.FK_Type == data_type_id,
        )
        result = await session.execute(stmt)
        sync_time = result.scalar_one_or_none()

        if sync_time is None:
            return None
        if not isinstance(sync_time, datetime):
            return None

        db_logger.debug(f"📖 GET user sync time for user {user_id}, type {data_type_id}: {sync_time}")
        return sync_time

    @staticmethod
    @log_exceptions(db_logger)
    async def get_user_sync_times(
        session: AsyncSession,
        user_id: int,
        data_types: list[int],
    ) -> dict[int, datetime]:
        """
        Получение времени синхронизации пользователя для списка типов данных.
        Оптимизировано: один запрос вместо N.

        Args:
            session: Сессия БД
            user_id: ID пользователя
            data_types: Список ID типов данных

        Returns:
            dict[int, datetime]: Словарь {data_type_id: last_sync_time}
        """
        db_logger.debug(f"📖 GET user sync times for user {user_id}, {len(data_types)} types (optimized, single query)")

        result: dict[int, datetime] = {}
        default_time = datetime(1900, 1, 1)

        if not data_types:
            return result

        stmt = select(AvanpostSysUserUpdateModel).where(
            AvanpostSysUserUpdateModel.FK_User == user_id,
            AvanpostSysUserUpdateModel.FK_Type.in_(data_types),
        )
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
                new_record = AvanpostSysUserUpdateModel(
                    FK_User=user_id,
                    FK_Type=dt_id,
                    FDate=default_time,
                )
                session.add(new_record)
                db_logger.info(f"📅 Created user sync record for user {user_id}, type {dt_id}")

        await session.flush()

        db_logger.debug(f"📖 GET user sync times result: {len(result)} types (found {len(existing)} existing)")
        return result

    @staticmethod
    @log_exceptions(db_logger)
    async def create_user_sync_record(
        session: AsyncSession,
        user_id: int,
        data_type_id: int,
        sync_time: datetime | None = None,
    ) -> AvanpostSysUserUpdateModel | None:
        """
        Создание записи синхронизации пользователя для типа данных.

        Args:
            session: Сессия БД
            user_id: ID пользователя
            data_type_id: ID типа данных
            sync_time: Время синхронизации (по умолчанию - 1900-01-01)

        Returns:
            AvanpostSysUserUpdateModel | None: Созданная запись или None
        """
        if sync_time is None:
            sync_time = datetime(1900, 1, 1)

        # Проверяем существование
        existing = await SystemRepository.get_user_sync_time(session, user_id, data_type_id)
        if existing is not None:
            db_logger.debug(f"ℹ️ User sync record for user {user_id}, type {data_type_id} already exists")
            return None

        record = AvanpostSysUserUpdateModel(
            FK_User=user_id,
            FK_Type=data_type_id,
            FDate=sync_time,
        )
        session.add(record)
        await session.flush()
        await session.refresh(record)

        db_logger.info(f"📅 Created user sync record for user {user_id}, type {data_type_id}")
        return record

    @staticmethod
    @log_exceptions(db_logger)
    async def create_user_sync_records_bulk(
        session: AsyncSession,
        user_id: int,
        data_type_ids: list[int],
        sync_time: datetime | None = None,
    ) -> int:
        """
        Массовое создание записей синхронизации пользователя.

        Args:
            session: Сессия БД
            user_id: ID пользователя
            data_type_ids: Список ID типов данных
            sync_time: Время синхронизации (по умолчанию - 1900-01-01)

        Returns:
            int: Количество созданных записей
        """
        if not data_type_ids:
            return 0

        if sync_time is None:
            sync_time = datetime(1900, 1, 1)

        created = 0
        existing_times = await SystemRepository.get_user_sync_times(session, user_id, data_type_ids)

        for dt_id in data_type_ids:
            if dt_id not in existing_times:
                record = AvanpostSysUserUpdateModel(
                    FK_User=user_id,
                    FK_Type=dt_id,
                    FDate=sync_time,
                )
                session.add(record)
                created += 1

        if created > 0:
            await session.flush()
            db_logger.info(f"📅 Created {created} user sync records for user {user_id}")

        return created

    @staticmethod
    @log_exceptions(db_logger)
    async def update_user_sync_time(
        session: AsyncSession,
        user_id: int,
        data_type_id: int,
        sync_time: datetime,
    ) -> None:
        """
        Обновление времени синхронизации пользователя для типа данных.

        Args:
            session: Сессия БД
            user_id: ID пользователя
            data_type_id: ID типа данных
            sync_time: Новое время синхронизации
        """
        db_logger.debug(f"📝 UPDATE user sync time for user {user_id}, type {data_type_id}: {sync_time}")

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

    @staticmethod
    @log_exceptions(db_logger)
    async def update_user_sync_times_bulk(
        session: AsyncSession,
        user_id: int,
        sync_times: dict[int, datetime],
    ) -> None:
        """
        Массовое обновление времени синхронизации пользователя.

        Args:
            session: Сессия БД
            user_id: ID пользователя
            sync_times: Словарь {data_type_id: sync_time}
        """
        if not sync_times:
            return

        db_logger.debug(f"📝 UPDATE user sync times bulk for user {user_id}: {len(sync_times)} types")

        for data_type_id, sync_time in sync_times.items():
            await SystemRepository.update_user_sync_time(session, user_id, data_type_id, sync_time)

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
        stmt = select(AvanpostSysUpdateModel).where(AvanpostSysUpdateModel.FK_Type == data_type_id)
        result = await session.execute(stmt)
        record = result.scalar_one_or_none()

        if not record:
            return False

        await session.delete(record)
        await session.flush()
        db_logger.info(f"🗑️ Deleted sync record for type {data_type_id}")
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
        stmt = select(AvanpostSysUserUpdateModel).where(
            AvanpostSysUserUpdateModel.FK_User == user_id,
            AvanpostSysUserUpdateModel.FK_Type == data_type_id,
        )
        result = await session.execute(stmt)
        record = result.scalar_one_or_none()

        if not record:
            return False

        await session.delete(record)
        await session.flush()
        db_logger.info(f"🗑️ Deleted user sync record for user {user_id}, type {data_type_id}")
        return True


__all__ = ["SystemRepository"]
