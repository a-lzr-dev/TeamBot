from datetime import datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..db import db_manager
from ..logger import app_logger as logger
from ..models import (
    AvanpostContactLangModel,
    AvanpostContactLinkModel,
    AvanpostContactModel,
    AvanpostContactMsgModel,
    AvanpostContactMsgProcessModel,
    AvanpostDirContactGroupModel,
    AvanpostDirContactLinkTypeModel,
    AvanpostDirContactMsgDirectionTypeModel,
    AvanpostDirContactMsgProcessTypeModel,
    AvanpostDirContactMsgTypeModel,
    AvanpostDirFileTypeModel,
    AvanpostDirLanguageModel,
    AvanpostDirOperatorModel,
    AvanpostDirOwnerModel,
    AvanpostDirOwnerMotorCadeModel,
    AvanpostDirScenarioActionLangModel,
    AvanpostDirScenarioActionModel,
    AvanpostDirScenarioActionTypeModel,
    AvanpostDirScenarioActionValueModel,
    AvanpostDirScenarioActionValueTypeModel,
    AvanpostDirScenarioCustomModel,
    AvanpostDirScenarioGroupItemLangModel,
    AvanpostDirScenarioGroupItemLinkScenarioGroupModel,
    AvanpostDirScenarioGroupItemLinkScenarioInstructionModel,
    AvanpostDirScenarioGroupItemLinkScenarioModel,
    AvanpostDirScenarioGroupItemModel,
    AvanpostDirScenarioGroupItemTypeModel,
    AvanpostDirScenarioGroupModel,
    AvanpostDirScenarioInstructionFileModel,
    AvanpostDirScenarioInstructionLangModel,
    AvanpostDirScenarioInstructionModel,
    AvanpostDirScenarioModel,
    AvanpostDirScenarioTypeModel,
    AvanpostDirSysDataTypeModel,
    AvanpostDirUserContactRoleTypeModel,
    AvanpostDirUserLinkContactMsgControlProcessTypeModel,
    AvanpostDirUserStatusTypeModel,
    AvanpostFileModel,
    AvanpostLinkContactMsgFileModel,
    AvanpostLinkMsgFileModel,
    AvanpostMsgModel,
    AvanpostSysUpdateModel,
    AvanpostSysUserUpdateModel,
    AvanpostUserChatLangModel,
    AvanpostUserChatModel,
    AvanpostUserLinkChatContactMsgModel,
    AvanpostUserLinkContactModel,
    AvanpostUserLinkContactMsgControlModel,
    AvanpostUserMissionItemLangModel,
    AvanpostUserMissionItemModel,
    AvanpostUserMissionLangModel,
    AvanpostUserMissionModel,
    AvanpostUserModel,
    AvanpostUserOrderLangModel,
    AvanpostUserOrderLinkMissionModel,
    AvanpostUserOrderModel,
    AvanpostUserStatusModel,
    AvanpostUserVehicleModel,
    BaseModel,
)

# Дата 1900-01-01 означает, что данные никогда не синхронизировались
DEFAULT_SYNC_DATE = datetime(1900, 1, 1)

# Маппинг типа данных -> (модель, имя таблицы, флаг пользовательских данных, флаг отложенной синхронизации)
DATA_TYPE_MAPPING: dict[int, tuple[type[BaseModel], str, bool, bool]] = {
    # Базовые справочники (без зависимостей) - ID 1-20
    1: (AvanpostDirLanguageModel, "TAvanpostDirLanguages", False, False),
    2: (AvanpostDirContactGroupModel, "TAvanpostDirContactsGroups", False, False),
    3: (AvanpostDirContactLinkTypeModel, "TAvanpostDirContactsLinksTypes", False, False),
    4: (AvanpostDirOperatorModel, "TAvanpostDirOperators", False, False),
    5: (AvanpostDirOwnerModel, "TAvanpostDirOwners", False, False),
    6: (AvanpostDirOwnerMotorCadeModel, "TAvanpostDirOwnersMotorCades", False, False),
    7: (AvanpostDirFileTypeModel, "TAvanpostDirFilesTypes", False, False),
    8: (AvanpostDirContactMsgDirectionTypeModel, "TAvanpostDirContactsMsgsDirectionsTypes", False, False),
    9: (AvanpostDirContactMsgTypeModel, "TAvanpostDirContactsMsgsTypes", False, False),
    10: (AvanpostDirContactMsgProcessTypeModel, "TAvanpostDirContactsMsgsProcessTypes", False, False),
    # Справочники, от которых зависят другие - ID 11-12
    11: (AvanpostDirScenarioTypeModel, "TAvanpostDirScenariosTypes", False, False),
    12: (AvanpostDirScenarioGroupItemTypeModel, "TAvanpostDirScenariosGroupsItemsTypes", False, False),
    # Основные справочники - ID 13-20
    13: (AvanpostDirUserStatusTypeModel, "TAvanpostDirUsersStatusTypes", False, False),
    14: (AvanpostDirUserContactRoleTypeModel, "TAvanpostDirUsersContactsRolesTypes", False, False),
    15: (
        AvanpostDirUserLinkContactMsgControlProcessTypeModel,
        "TAvanpostDirUsersLinksContactsMsgsControlsProcessTypes",
        False,
        False,
    ),
    16: (AvanpostDirScenarioActionTypeModel, "TAvanpostDirScenariosActionsTypes", False, False),
    17: (AvanpostDirScenarioActionValueTypeModel, "TAvanpostDirScenariosActionsValuesTypes", False, False),
    # Сценарии действий (зависят от справочников выше) - ID 101-108
    101: (AvanpostDirScenarioModel, "TAvanpostDirScenarios", False, False),
    102: (AvanpostDirScenarioActionModel, "TAvanpostDirScenariosActions", False, False),
    103: (AvanpostDirScenarioActionLangModel, "TAvanpostDirScenariosActionsLangs", False, False),
    104: (AvanpostDirScenarioActionValueModel, "TAvanpostDirScenariosActionsValues", False, False),
    105: (AvanpostDirScenarioInstructionModel, "TAvanpostDirScenariosInstructions", False, False),
    106: (AvanpostDirScenarioInstructionLangModel, "TAvanpostDirScenariosInstructionsLangs", False, False),
    107: (AvanpostDirScenarioCustomModel, "TAvanpostDirScenariosCustom", False, False),
    108: (AvanpostDirScenarioGroupModel, "TAvanpostDirScenariosGroups", False, False),
    # Меню действий (зависят от сценариев) - ID 201-206
    201: (AvanpostDirScenarioGroupItemModel, "TAvanpostDirScenariosGroupsItems", False, False),
    202: (AvanpostDirScenarioGroupItemLangModel, "TAvanpostDirScenariosGroupsItemsLangs", False, False),
    203: (
        AvanpostDirScenarioGroupItemLinkScenarioModel,
        "TAvanpostDirScenariosGroupsItemsLinksScenarios",
        False,
        False,
    ),
    204: (
        AvanpostDirScenarioGroupItemLinkScenarioGroupModel,
        "TAvanpostDirScenariosGroupsItemsLinksScenariosGroups",
        False,
        False,
    ),
    205: (
        AvanpostDirScenarioGroupItemLinkScenarioInstructionModel,
        "TAvanpostDirScenariosGroupsItemsLinksScenariosInstructions",
        False,
        False,
    ),
    # Контакты (независимые) - ID 301-302
    301: (AvanpostContactModel, "TAvanpostContacts", False, False),
    302: (AvanpostContactLangModel, "TAvanpostContactsLangs", False, False),
    # Контакты (зависят от AvanpostContactModel) - ID 303
    303: (AvanpostContactLinkModel, "TAvanpostContactsLinks", False, False),
    # Данные с пользователями - ID 401-403
    401: (AvanpostUserModel, "TAvanpostUsers", True, False),
    402: (AvanpostUserChatModel, "TAvanpostUsersChats", True, False),
    403: (AvanpostUserChatLangModel, "TAvanpostUsersChatsLangs", True, False),
    # Оперативная синхронизация - ID 501-515
    501: (AvanpostMsgModel, "TAvanpostMsgs", True, False),
    502: (AvanpostContactMsgModel, "TAvanpostContactsMsgs", True, False),
    503: (AvanpostContactMsgProcessModel, "TAvanpostContactsMsgsProcess", True, False),
    504: (AvanpostUserStatusModel, "TAvanpostUsersStatus", True, False),
    505: (AvanpostUserLinkContactModel, "TAvanpostUsersLinksContacts", True, False),
    506: (AvanpostUserMissionModel, "TAvanpostUsersMissions", True, False),
    507: (AvanpostUserMissionLangModel, "TAvanpostUsersMissionsLangs", True, False),
    508: (AvanpostUserMissionItemModel, "TAvanpostUsersMissionsItems", True, False),
    509: (AvanpostUserMissionItemLangModel, "TAvanpostUsersMissionsItemsLangs", True, False),
    510: (AvanpostUserOrderModel, "TAvanpostUsersOrders", True, False),
    511: (AvanpostUserOrderLangModel, "TAvanpostUsersOrdersLangs", True, False),
    512: (AvanpostUserOrderLinkMissionModel, "TAvanpostUsersLinksContactsMissions", True, False),
    513: (AvanpostUserVehicleModel, "TAvanpostUsersVehicles", True, False),
    514: (AvanpostUserLinkChatContactMsgModel, "TAvanpostUsersLinksChatsContactsMsgs", True, False),
    515: (AvanpostUserLinkContactMsgControlModel, "TAvanpostUsersLinksContactsMsgsControls", True, False),
    # Отложенная синхронизация - ID 601-603
    601: (AvanpostFileModel, "TAvanpostFiles", False, True),
    602: (AvanpostLinkMsgFileModel, "TAvanpostLinksMsgsFiles", True, True),
    603: (AvanpostLinkContactMsgFileModel, "TAvanpostLinksContactsMsgsFiles", True, True),
    604: (AvanpostDirScenarioInstructionFileModel, "TAvanpostDirScenariosInstructionsFiles", False, False),
}


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
            # ============================================================
            # ШАГ 1: Заполнение TAvanpostDirSysDataTypes
            # ============================================================
            result = await session.execute(select(AvanpostDirSysDataTypeModel))
            existing_ids = {r.FID for r in result.scalars().all()}

            new_records = []
            for data_type_id, (model, table_name, user_related, deferred_sync) in DATA_TYPE_MAPPING.items():
                if data_type_id not in existing_ids:
                    new_records.append(
                        AvanpostDirSysDataTypeModel(
                            FID=data_type_id,
                            FName=model.__name__,
                            FUserRelated=user_related,
                            FDeferredSync=deferred_sync,
                            FTableName=table_name,
                        )
                    )
                    logger.info(f"➕ New type: {data_type_id} -> {model.__name__}")

            if new_records:
                session.add_all(new_records)
                await session.flush()
                logger.info(f"✅ Inserted {len(new_records)} new records into TAvanpostDirSysDataTypes")

            # ============================================================
            # ШАГ 2: Заполнение TAvanpostSysUpdates для всех типов данных
            # ============================================================
            all_types = list(DATA_TYPE_MAPPING.keys())
            existing_sync = await session.execute(select(AvanpostSysUpdateModel))
            existing_sync_ids = {r.FK_Type for r in existing_sync.scalars().all()}

            sync_records = []
            for data_type_id in all_types:
                if data_type_id not in existing_sync_ids:
                    sync_records.append(
                        AvanpostSysUpdateModel(
                            FK_Type=data_type_id,
                            FDate=DEFAULT_SYNC_DATE,
                        )
                    )
                    logger.debug(f"➕ New sync record for type: {data_type_id}")

            if sync_records:
                session.add_all(sync_records)
                await session.flush()
                logger.info(f"✅ Inserted {len(sync_records)} records into TAvanpostSysUpdates")

            # ============================================================
            # ШАГ 3: Заполнение TAvanpostSysUsersUpdates для существующих пользователей
            # ============================================================
            users_result = await session.execute(select(AvanpostUserModel))
            users = users_result.scalars().all()

            if users:
                logger.info(f"👥 Found {len(users)} users in TAvanpostUsers")

                user_data_types = [
                    dt_id for dt_id, (_, _, user_related, _) in DATA_TYPE_MAPPING.items() if user_related
                ]

                if user_data_types:
                    logger.info(f"📊 User-related data types: {user_data_types}")

                    existing_user_sync = await session.execute(select(AvanpostSysUserUpdateModel))
                    existing_user_sync_set = {(r.FK_User, r.FK_Type) for r in existing_user_sync.scalars().all()}

                    user_sync_records = []
                    for user in users:
                        for data_type_id in user_data_types:
                            if (user.FID, data_type_id) not in existing_user_sync_set:
                                user_sync_records.append(
                                    AvanpostSysUserUpdateModel(
                                        FK_User=user.FID,
                                        FK_Type=data_type_id,
                                        FDate=DEFAULT_SYNC_DATE,
                                    )
                                )
                                logger.debug(f"➕ New user sync: user={user.FID}, type={data_type_id}")

                    if user_sync_records:
                        session.add_all(user_sync_records)
                        await session.flush()
                        logger.info(f"✅ Inserted {len(user_sync_records)} records into TAvanpostSysUsersUpdates")
                    else:
                        logger.info("ℹ️ No new user sync records needed")
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
