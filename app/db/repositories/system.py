from datetime import datetime

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from ...logger import db_logger
from ...models import AvanpostSysUpdateModel, AvanpostSysUserUpdateModel


class SystemRepository:
    """Репозиторий для работы с системными таблицами синхронизации"""

    @staticmethod
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

        # Явное приведение к datetime | None
        if sync_time is not None and not isinstance(sync_time, datetime):
            sync_time = None

        db_logger.debug(f"📖 GET sys sync time for type {data_type_id}: {sync_time}")
        return sync_time  # type: ignore

    @staticmethod
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

    # ==================== ПОЛЬЗОВАТЕЛЬСКИЕ НАСТРОЙКИ ====================

    @staticmethod
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

        # Явное приведение к datetime | None
        if sync_time is not None and not isinstance(sync_time, datetime):
            sync_time = None

        db_logger.debug(f"📖 GET user sync time for user {user_id}, type {data_type_id}: {sync_time}")
        return sync_time  # type: ignore

    @staticmethod
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


__all__ = ["SystemRepository"]
