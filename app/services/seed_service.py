from datetime import datetime

from sqlalchemy.ext.asyncio import AsyncSession

from ..config import settings
from ..db import db_manager
from ..db.repositories import DirLanguageRepository, SystemRepository, UserRepository
from ..logger import app_logger as logger
from ..models.avanpost import (
    AVANPOST_MODEL_MAPPING,
    AVANPOST_USER_DATA_TYPES,
    get_avanpost_table_name,
)

# Дата 1900-01-01 означает, что данные никогда не синхронизировались
DEFAULT_SYNC_DATE = datetime(1900, 1, 1)


class AvanpostSeedService:
    """Сервис для заполнения системных данных Avanpost"""

    @staticmethod
    async def seed_system_tables(session: AsyncSession) -> bool:
        """
        Заполнение системных таблиц Avanpost.

        Args:
            session: Сессия БД

        Returns:
            bool: True если успешно, False если ошибка
        """
        try:
            # 1. Проверка существующих типов данных
            existing_types = await SystemRepository.get_data_types_dict(session)
            existing_ids = set(existing_types.keys())

            # 2. Создание недостающих типов данных через SystemRepository
            data_types_to_create = []
            for data_type_id, model in AVANPOST_MODEL_MAPPING.items():
                if data_type_id not in existing_ids:
                    # Определяем флаги на основе ID
                    user_related = data_type_id in AVANPOST_USER_DATA_TYPES
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
                    logger.info(f"➕ New type: {data_type_id} -> {model.__name__}")

            if data_types_to_create:
                created_count = await SystemRepository.create_data_types_bulk(
                    session=session,
                    data_types=data_types_to_create,
                )
                logger.info(f"✅ Inserted {created_count} new records into TAvanpostDirSysDataTypes")
            else:
                logger.info("ℹ️ No new data types to create")

            # 3. Добавление пользователей из настроек
            try:
                user_ids = getattr(settings, "AVANPOST_AUTO_ADD_USERS_ON_START", [])
                if user_ids:
                    logger.info(f"👤 Adding Avanpost users from settings: {user_ids}")
                    result = await AvanpostSeedService.seed_avanpost_users(session)
                    added = [uid for uid, was_added in result.items() if was_added]
                    if added:
                        logger.info(f"✅ Successfully added Avanpost users: {added}")
                    else:
                        logger.warning("⚠️ No Avanpost users were added successfully")
            except Exception as e:
                logger.error(f"❌ Failed to add Avanpost users: {e}", exc_info=True)

            # 4. Заполнение TAvanpostSysUpdates для всех типов данных
            all_types = list(AVANPOST_MODEL_MAPPING.keys())

            created_count = await SystemRepository.create_sync_records_bulk(
                session=session,
                data_type_ids=all_types,
                sync_time=DEFAULT_SYNC_DATE,
            )
            logger.info(f"✅ Inserted {created_count} records into TAvanpostSysUpdates")

            # 5. Заполнение TAvanpostSysUsersUpdates для существующих пользователей
            users = await UserRepository.get_all_avanpost_users(session)

            if users:
                logger.info(f"👥 Found {len(users)} users in TAvanpostUsers")

                if AVANPOST_USER_DATA_TYPES:
                    logger.info(f"📊 User-related data types: {AVANPOST_USER_DATA_TYPES}")

                    total_created = 0
                    for user in users:
                        created_count = await SystemRepository.create_user_sync_records_bulk(
                            session=session,
                            user_id=user.FID,
                            data_type_ids=AVANPOST_USER_DATA_TYPES,
                            sync_time=DEFAULT_SYNC_DATE,
                        )
                        total_created += created_count

                    logger.info(f"✅ Inserted {total_created} records into TAvanpostSysUsersUpdates")
                else:
                    logger.info("ℹ️ No user-related data types found")
            else:
                logger.info("ℹ️ No users found in TAvanpostUsers, skipping TAvanpostSysUsersUpdates")

            await session.commit()
            logger.info("✅ All seeds completed successfully")
            return True

        except Exception as e:
            logger.error(f"❌ Failed to seed: {e}")
            await session.rollback()
            return False

    @staticmethod
    async def seed_avanpost_users(session: AsyncSession) -> dict[int, bool]:
        """
        Добавление пользователей Avanpost из настроек.
        Использует DirLanguageRepository для работы с языками.

        Args:
            session: Сессия БД

        Returns:
            dict[int, bool]: Словарь {user_id: was_added}
        """
        user_ids = getattr(settings, "AVANPOST_AUTO_ADD_USERS_ON_START", [])

        if not user_ids:
            logger.debug("ℹ️ No Avanpost users to add from settings")
            return {}

        logger.info(f"👤 Adding Avanpost users from settings: {user_ids}")

        # 1. Проверка и создание языка 'RU'
        try:
            lang_ru = await DirLanguageRepository.ensure_language(
                session=session,
                language_id="RU",
                is_default=True,
            )
            logger.debug(f"✅ Language 'RU' ready (default={lang_ru.FFlagDefault})")
        except Exception as e:
            logger.error(f"❌ Failed to ensure language 'RU': {e}")

        # 2. Добавление пользователей
        result = {}
        for user_id in user_ids:
            try:
                success, user = await UserRepository.create_or_update_avanpost_user_upsert(
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
                    logger.info(f"✅ Added/updated Avanpost user {user_id}")
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

    @classmethod
    async def seed_all(cls) -> bool:
        """
        Заполнение всех системных таблиц Avanpost.

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


avanpost_seed_service = AvanpostSeedService()

__all__ = [
    "AvanpostSeedService",
    "avanpost_seed_service",
]
