"""
Сервис заполнения системных данных Avanpost.

Отвечает за:
1. Создание типов данных в TAvanpostDirSysDataTypes
2. Добавление пользователей из настроек (AVANPOST_AUTO_ADD_USERS_IDS_ON_START)
3. Загрузку пользователей из транспорта Avanpost (опционально)
4. Создание записей глобальной синхронизации (TAvanpostSysUpdates)
5. Создание записей пользовательской синхронизации (TAvanpostSysUsersUpdates)
6. Обработку ошибок и откат транзакций при сбоях
7. Вывод детальной статистики выполнения
"""

from datetime import datetime
from typing import Any

from sqlalchemy import inspect
from sqlalchemy.ext.asyncio import AsyncSession

from ..config import settings
from ..db import db_manager
from ..db.repositories import (
    AvanpostRepository,
    DirContactGroupRepository,
    DirLanguageRepository,
    SystemRepository,
    UserRepository,
)
from ..db.repositories.generic import GenericRepository
from ..logger import app_logger as logger
from ..models.avanpost import (
    AVANPOST_BASE_DATA_TYPES,
    AVANPOST_MODEL_MAPPING,
    AVANPOST_USER_DATA_ALL_TYPES,
    AvanpostUserModel,
    get_avanpost_table_name,
)

# ==================== РЕПОЗИТОРИИ (СИНГЛТОНЫ) ====================
# Инициализация репозиториев на уровне модуля для повторного использования
_user_repo = UserRepository()  # Работа с пользователями
_system_repo = SystemRepository()  # Системные данные и синхронизация
_dir_lang_repo = DirLanguageRepository()  # Справочник языков
_dir_contact_group_repo = DirContactGroupRepository()  # Группы контактов
_avanpost_repo = AvanpostRepository()  # Прямой доступ к Avanpost

# ==================== КОНСТАНТЫ ====================
# Дата 1900-01-01 означает, что данные никогда не синхронизировались
DEFAULT_SYNC_DATE = datetime(1900, 1, 1)


class AvanpostSeedService:
    """
    Сервис для заполнения системных данных Avanpost.

    Выполняет инициализацию всех системных таблиц, необходимых для работы
    с данными Avanpost: типы данных, пользователи, записи синхронизации.

    Порядок инициализации:
    1. Типы данных (TAvanpostDirSysDataTypes)
    2. Пользователи (TAvanpostUsers)
    3. Глобальная синхронизация (TAvanpostSysUpdates)
    4. Пользовательская синхронизация (TAvanpostSysUsersUpdates)
    """

    # ==================== ПУБЛИЧНЫЕ МЕТОДЫ ====================

    @classmethod
    async def seed_all(cls) -> bool:
        """
        Точка входа для заполнения всех системных таблиц Avanpost.

        Управляет жизненным циклом соединений с БД и делегирует
        выполнение основному методу seed_system_tables.

        Returns:
            bool: True если успешно, False если ошибка
        """
        logger.info("🔄 Starting seed for Avanpost system tables...")

        try:
            await db_manager.initialize_all()
            async with db_manager.get_session("main") as session:
                success = await cls.seed_system_tables(session)
                if success:
                    logger.info("✅ Avanpost system data seeded successfully")
                else:
                    logger.warning("⚠️ Avanpost seeding completed with errors")
                return success
        except Exception as e:
            logger.error(f"❌ Failed to seed: {e}")
            return False
        finally:
            await db_manager.close_all()

    # ==================== ОСНОВНОЙ МЕТОД SEED ====================

    @staticmethod
    async def seed_system_tables(session: AsyncSession) -> bool:
        """
        Основной метод заполнения системных таблиц Avanpost.

        Выполняет полную инициализацию в правильном порядке с учётом
        зависимостей между таблицами. Обрабатывает ошибки и откатывает
        транзакцию при необходимости.

        Этапы:
        1. Создание недостающих типов данных
        2. Добавление пользователей из конфигурации
        3. (Опционально) Загрузка пользователей из транспорта
        4. Создание записей глобальной синхронизации
        5. Создание записей пользовательской синхронизации

        Args:
            session: Сессия БД

        Returns:
            bool: True при успешном выполнении, False при ошибке
        """
        try:
            # ---------- ШАГ 1: ТИПЫ ДАННЫХ ----------
            await AvanpostSeedService._create_data_types(session)

            # ---------- ШАГ 2: ПОЛЬЗОВАТЕЛИ ----------
            # 2.1 Пользователи из настроек
            await AvanpostSeedService.seed_avanpost_users(session)

            # 2.2 Пользователи из транспорта (опционально)
            await AvanpostSeedService._seed_vehicles_if_enabled(session)

            # ---------- ШАГ 3: ГЛОБАЛЬНАЯ СИНХРОНИЗАЦИЯ ----------
            await AvanpostSeedService._create_global_sync_records(session)

            # ---------- ШАГ 4: ПОЛЬЗОВАТЕЛЬСКАЯ СИНХРОНИЗАЦИЯ ----------
            await AvanpostSeedService._create_user_sync_records(session)

            await session.commit()
            logger.info("✅ All seeds completed successfully")
            return True

        except Exception as e:
            logger.error(f"❌ Failed to seed: {e}")
            await session.rollback()
            return False

    # ==================== ПРИВАТНЫЕ МЕТОДЫ SEED ====================

    @staticmethod
    async def _create_data_types(session: AsyncSession) -> None:
        """
        Создание недостающих типов данных в TAvanpostDirSysDataTypes.

        Проверяет существующие типы и добавляет только отсутствующие.
        Для каждого типа определяет флаги:
        - FUserRelated: привязан ли тип к пользователю
        - FDeferredSync: нужна ли отложенная синхронизация (ID >= 700)

        Args:
            session: Сессия БД
        """
        existing_types = await _system_repo.get_data_types_dict(session)
        existing_ids = set(existing_types.keys())

        data_types_to_create = []
        for data_type_id, model in AVANPOST_MODEL_MAPPING.items():
            if data_type_id not in existing_ids:
                user_related = data_type_id in AVANPOST_USER_DATA_ALL_TYPES
                deferred_sync = data_type_id >= 700  # ID 701-704 - отложенная синхронизация

                data_types_to_create.append(
                    {
                        "FID": data_type_id,
                        "FName": model.__name__,
                        "FTableName": get_avanpost_table_name(data_type_id),
                        "FUserRelated": user_related,
                        "FDeferredSync": deferred_sync,
                    }
                )

        if data_types_to_create:
            created_count = await _system_repo.create_data_types_bulk(
                session=session,
                data_types=data_types_to_create,
            )
            logger.info(f"✅ Inserted {created_count} new records into TAvanpostDirSysDataTypes")
        else:
            logger.info("ℹ️ No new data types to create")

    @staticmethod
    async def _seed_vehicles_if_enabled(session: AsyncSession) -> None:
        """
        Загрузка пользователей из транспорта, если включено в настройках.

        Проверяет флаг AVANPOST_AUTO_ADD_USERS_ALL_ON_START и при необходимости
        загружает всех пользователей из таблицы транспорта Avanpost.

        Args:
            session: Сессия БД
        """
        if not getattr(settings, "AVANPOST_AUTO_ADD_USERS_ALL_ON_START", False):
            return

        logger.info("🚗 Loading additional users from Avanpost Vehicles...")
        try:
            vehicles_result = await AvanpostSeedService.seed_avanpost_users_all(
                session=session,
                create_sync_records=False,
            )

            if vehicles_result.get("errors", 0) > 0:
                logger.warning(f"⚠️ User seed completed with errors: {vehicles_result.get('errors', 0)}")
                error_messages = vehicles_result.get("error_messages", [])
                if error_messages:
                    for err in error_messages[:3]:
                        logger.warning(f"   - {err}")
            else:
                logger.info(
                    f"✅ User seed completed: loaded={vehicles_result.get('total_loaded', 0)}, "
                    f"added={vehicles_result.get('total_added', 0)}"
                )
        except Exception as e:
            logger.error(f"❌ Failed to seed users from vehicles: {e}", exc_info=True)

    @staticmethod
    async def _create_global_sync_records(session: AsyncSession) -> None:
        """
        Создание записей глобальной синхронизации в TAvanpostSysUpdates.

        Для всех базовых типов данных создаются записи с датой DEFAULT_SYNC_DATE,
        означающей, что данные никогда не синхронизировались.

        Args:
            session: Сессия БД
        """
        all_types = list(AVANPOST_BASE_DATA_TYPES)
        created_count = await _system_repo.create_sync_records_bulk(
            session=session,
            data_type_ids=all_types,
            sync_time=DEFAULT_SYNC_DATE,
        )
        logger.info(f"✅ Inserted {created_count} records into TAvanpostSysUpdates")

    @staticmethod
    async def _create_user_sync_records(session: AsyncSession) -> None:
        """
        Создание записей пользовательской синхронизации в TAvanpostSysUsersUpdates.

        Для всех существующих пользователей и всех типов данных, связанных
        с пользователями, создаются записи с датой DEFAULT_SYNC_DATE.

        Выводит детальную статистику по типам данных.

        Args:
            session: Сессия БД
        """
        users = await _user_repo.get_all_avanpost_users(session)

        if not users:
            logger.info("ℹ️ No users found in TAvanpostUsers, skipping TAvanpostSysUsersUpdates")
            return

        if not AVANPOST_USER_DATA_ALL_TYPES:
            logger.info(f"👥 Found {len(users)} users in TAvanpostUsers")
            logger.info("ℹ️ No user-related data types found, skipping TAvanpostSysUsersUpdates")
            return

        # Подготовка данных
        user_ids = [user.FID for user in users]
        data_type_names = {
            dt_id: get_avanpost_table_name(dt_id) or f"Type_{dt_id}" for dt_id in AVANPOST_USER_DATA_ALL_TYPES
        }

        # Создание записей со статистикой
        stats = await _system_repo.create_user_sync_records_bulk_with_stats(
            session=session,
            user_ids=user_ids,
            data_type_ids=AVANPOST_USER_DATA_ALL_TYPES,
            sync_time=DEFAULT_SYNC_DATE,
            data_type_names=data_type_names,
        )

        # Вывод статистики
        AvanpostSeedService._log_user_sync_stats(stats)

    @staticmethod
    def _log_user_sync_stats(stats: dict[str, Any]) -> None:
        """
        Вывод статистики созданных записей пользовательской синхронизации.

        Форматирует вывод в виде таблицы для наглядного отображения
        количества записей по каждому типу данных.

        Args:
            stats: Словарь со статистикой от create_user_sync_records_bulk_with_stats
        """
        logger.info("=" * 60)
        logger.info("📊 USER SYNC RECORDS CREATED")
        logger.info("=" * 60)
        logger.info(f"👥 Total users processed: {stats['total_users']:,}")
        logger.info(f"✅ Users with new records: {stats['users_with_records']:,}")
        logger.info(f"📝 Total records created: {stats['total_records_created']:,}")
        logger.info("")
        logger.info("📋 By data type:")
        logger.info("-" * 50)

        if stats["by_data_type"]:
            for type_label, count in stats["by_data_type"].items():
                logger.info(f"  {type_label:<40} {count:>10,}")
        else:
            logger.info("  ℹ️ No new records created (all already exist)")

        logger.info("=" * 60)

    # ==================== МЕТОДЫ ЗАГРУЗКИ ПОЛЬЗОВАТЕЛЕЙ ====================

    @staticmethod
    async def seed_avanpost_users(session: AsyncSession) -> dict[int, bool]:
        """
        Добавление пользователей Avanpost из настроек.

        Использует список ID из конфигурации (AVANPOST_AUTO_ADD_USERS_IDS_ON_START)
        и добавляет их в TAvanpostUsers, если они ещё не существуют.

        Args:
            session: Сессия БД

        Returns:
            dict[int, bool]: Словарь {user_id: was_added} - был ли добавлен пользователь
        """
        user_ids = getattr(settings, "AVANPOST_AUTO_ADD_USERS_IDS_ON_START", [])

        if not user_ids:
            logger.debug("ℹ️ No Avanpost users to add from settings")
            return {}

        logger.info(f"👤 Adding Avanpost users from settings: {user_ids}")

        # Проверка и создание языка 'RU'
        try:
            await _dir_lang_repo.ensure_language(
                session=session,
                language_id="RU",
                is_default=True,
            )
        except Exception as e:
            logger.error(f"❌ Failed to ensure language 'RU': {e}")

        # Добавление пользователей в TAvanpostUsers (только новых)
        result: dict[int, bool] = {}
        for user_id in user_ids:
            try:
                existing_user = await _user_repo.get_avanpost_user_data(session, user_id)
                if existing_user:
                    continue

                success, _ = await _user_repo.create_or_update_avanpost_user_upsert(
                    session=session,
                    telegram_user_id=None,
                    avanpost_user_id=user_id,
                    telegram_user_required=False,
                    fk_contact=None,
                    fk_language="RU",
                    fk_menugroup=None,
                    fk_owner=None,
                    fk_motorcade=None,
                    fname=f"User_{user_id}",
                    fphone=None,
                )

                if success:
                    result[user_id] = True
                    logger.info(f"✅ Added Avanpost user {user_id}")
                else:
                    result[user_id] = False
                    logger.warning(f"⚠️ Failed to add Avanpost user {user_id}")

            except Exception as e:
                logger.error(f"❌ Error adding Avanpost user {user_id}: {e}")
                result[user_id] = False
                await session.rollback()

        await session.flush()

        added = [uid for uid, was_added in result.items() if was_added]
        if added:
            logger.info(f"✅ Successfully added Avanpost users: {added}")
        else:
            logger.warning("⚠️ No Avanpost users were added successfully")

        return result

    @staticmethod
    async def seed_avanpost_users_all(
        session: AsyncSession,
        create_sync_records: bool = False,
    ) -> dict[str, Any]:
        """
        Загрузка всех пользователей из Avanpost.

        Загружает пользователей из внешней системы Avanpost
        и добавляет их в локальную БД. Поддерживает массовую вставку для
        оптимизации производительности.

        Args:
            session: Сессия БД
            create_sync_records: Создавать ли записи синхронизации для новых пользователей

        Returns:
            dict[str, Any]: Статистика выполнения операции
                - total_loaded: всего загружено из Avanpost
                - total_added: успешно добавлено в БД
                - total_skipped: пропущено (уже существовали)
                - sync_records_created: создано записей синхронизации
                - errors: количество ошибок
                - error_messages: список сообщений об ошибках
        """
        logger.info("🔄 Starting user seed all from Avanpost ...")

        result: dict[str, Any] = {
            "total_loaded": 0,
            "total_added": 0,
            "total_skipped": 0,
            "sync_records_created": 0,
            "errors": 0,
            "error_messages": [],
        }

        # 1. Получение списка пользователей из Avanpost
        try:
            async with db_manager.get_session("avanpost") as avanpost_session:
                user_ids = await _avanpost_repo.get_user_ids_default_adding(avanpost_session)

            if not user_ids:
                logger.warning("⚠️ No users to seed.")
                return result

            result["total_loaded"] = len(user_ids)
            logger.info(f"📊 Loaded {len(user_ids):,} user IDs from Avanpost")

        except Exception as e:
            result["errors"] += 1
            error_msg = f"Failed to load user IDs from vehicles: {str(e)}"
            result["error_messages"].append(error_msg)
            logger.error(f"❌ {error_msg}", exc_info=True)
            return result

        # 2. Проверка существующих пользователей в TAvanpostUsers
        try:
            existing_users = await _user_repo.get_all_avanpost_users(session)
            existing_ids = {user.FID for user in existing_users}
            logger.debug(f"📊 Found {len(existing_ids):,} existing users in TAvanpostUsers")
        except Exception as e:
            result["errors"] += 1
            error_msg = f"Failed to get existing users: {str(e)}"
            result["error_messages"].append(error_msg)
            logger.error(f"❌ {error_msg}", exc_info=True)
            return result

        # 3. Фильтрация новых пользователей
        new_user_ids = [uid for uid in user_ids if uid not in existing_ids]
        result["total_skipped"] = len(user_ids) - len(new_user_ids)

        if new_user_ids:
            logger.info(f"🆕 Found {len(new_user_ids):,} new users to add (out of {len(user_ids):,} loaded)")
            logger.debug(f"   Sample new user IDs: {new_user_ids[:10]}...")
        else:
            logger.info(f"ℹ️ All {len(user_ids):,} users all already exist in TAvanpostUsers")
            return result

        if result["total_skipped"] > 0:
            logger.info(f"⏭️ Skipping {result['total_skipped']:,} already existing users")

        # 4. Проверка и создание языка 'RU'
        try:
            await _dir_lang_repo.ensure_language(
                session=session,
                language_id="RU",
                is_default=True,
            )
            logger.debug("✅ Language 'RU' ensured")
        except Exception as e:
            logger.error(f"❌ Failed to ensure language 'RU': {e}")
            result["errors"] += 1
            result["error_messages"].append(f"Failed to ensure language 'RU': {str(e)}")
            return result

        # 5. Подготовка данных для массовой вставки
        records_to_insert = []
        for user_id in new_user_ids:
            records_to_insert.append(
                {
                    "FID": user_id,
                    "FK_Language": "RU",
                    "FName": f"User_{user_id}",
                }
            )

        # 6. Массовая вставка через GenericRepository
        try:
            model_columns = {column.name for column in inspect(AvanpostUserModel).columns}

            result_stats = await GenericRepository.save_data_bulk(
                session=session,
                model=AvanpostUserModel,
                records=records_to_insert,
                model_columns=model_columns,
                chunk_size=1000,
                raise_on_error=False,
                commit_chunks=True,
            )

            inserted_count = result_stats.get("inserted", 0)
            result["total_added"] = inserted_count

            if inserted_count == 0:
                logger.warning("⚠️ No users were inserted (all conflicted)")

        except Exception as e:
            result["errors"] += len(new_user_ids)
            error_msg = f"Bulk insert failed: {str(e)}"
            result["error_messages"].append(error_msg)
            logger.error(f"❌ {error_msg}", exc_info=True)
            await session.rollback()
            return result

        # 7. Создание записей синхронизации для новых пользователей (опционально)
        if create_sync_records and result["total_added"] > 0:
            try:
                added_user_ids = new_user_ids[: result["total_added"]]

                data_type_names = {}
                for dt_id in AVANPOST_USER_DATA_ALL_TYPES:
                    data_type_names[dt_id] = get_avanpost_table_name(dt_id) or f"Type_{dt_id}"

                stats = await _system_repo.create_user_sync_records_bulk_with_stats(
                    session=session,
                    user_ids=added_user_ids,
                    data_type_ids=AVANPOST_USER_DATA_ALL_TYPES,
                    sync_time=DEFAULT_SYNC_DATE,
                    data_type_names=data_type_names,
                )

                result["sync_records_created"] = stats["total_records_created"]

                logger.info(
                    f"✅ Created {stats['total_records_created']:,} sync records "
                    f"for {stats['users_with_records']:,} new users"
                )

                if stats["by_data_type"]:
                    logger.debug("📋 By data type:")
                    for type_label, count in list(stats["by_data_type"].items())[:5]:
                        logger.debug(f"    {type_label}: {count:,}")
                    if len(stats["by_data_type"]) > 5:
                        logger.debug(f"    ... and {len(stats['by_data_type']) - 5} more types")

            except Exception as e:
                logger.warning(f"⚠️ Failed to create sync records: {e}")
                result["error_messages"].append(f"Sync records creation error: {str(e)}")
                result["errors"] += 1

        await session.commit()

        # 8. Итоговая статистика
        logger.info("=" * 60)
        logger.info("📊 USERS SEED SUMMARY")
        logger.info("=" * 60)
        logger.info(f"📥 Loaded from Avanpost:       {result['total_loaded']:,}")
        logger.info(f"👥 Already existing in DB:     {result['total_skipped']:,}")
        logger.info(f"✅ New users added:            {result['total_added']:,}")
        if create_sync_records:
            logger.info(f"📝 Sync records created:      {result['sync_records_created']:,}")
        if result["errors"] > 0:
            logger.info(f"❌ Errors:                     {result['errors']}")
        logger.info("=" * 60)

        if result["errors"] > 0:
            logger.warning(f"⚠️ User seed completed with {result['errors']} errors")
            if result["error_messages"]:
                for err in result["error_messages"][:3]:
                    logger.warning(f"   - {err}")

        return result


avanpost_seed_service = AvanpostSeedService()

__all__ = [
    "AvanpostSeedService",
    "avanpost_seed_service",
]
