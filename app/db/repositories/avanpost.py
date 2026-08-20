import json
from datetime import datetime
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from ...exceptions import log_exceptions
from ...logger import db_logger

# ==================== Перечень ВНЕШНИХ ХРАНИМЫХ ПРОЦЕДУР ====================
#
# ext.PA_avp_RSAppUsersObjectsContacts_Check
#   - Проверка пользователя по номеру телефона
#   - Возвращает: user_id, menu_group_id, contact_id
#
# ext.PA_avp_RSAppScenariosGroups_Load
#   - Получение списка групп действий
#   - Возвращает: ID, Name
#
# ext.PA_avp_RSAppScenariosGroupsItems_Load
#   - Получение пунктов меню для группы
#   - Параметры: @GroupID, @ParentItemID
#   - Возвращает: ID, Name, FlagHasSubItems, ParentItemID
#
# ext.PA_avp_RSAppBaseData_Load
#   - Синхронизация базовых данных (справочники)
#   - Параметр: @Params (JSON с DataTypes, LastSync, Force)
#   - Возвращает: JSON с Data
#
# ext.PA_avp_RSAppUserData_Load
#   - Синхронизация данных пользователя
#   - Параметры: @Params (JSON с UserId, DataTypes, LastSync, Force)
#   - Возвращает: JSON с Data
#
# ext.PA_avp_RSAppUsersVehicles_Load
#   - Получение списка ID пользователей из системы
#   - Возвращает: список user_id
#
# ======================================================================


class AvanpostRepository:
    """Репозиторий для работы с Avanpost (MSSQL)"""

    # ==================== ПОЛЬЗОВАТЕЛИ ====================

    @staticmethod
    @log_exceptions(db_logger)
    async def check_user_by_phone(
        session: AsyncSession,
        phone_number: str,
    ) -> tuple[int | None, int | None, int | None]:
        """
        Проверка пользователя по номеру телефона через хранимую процедуру.

        Returns:
            Tuple[int | None, int | None, int | None]: (user_id, menu_group_id, contact_id) или (None, None, None)
        """
        try:
            sql = """
                    EXEC ext.PA_avp_RSAppUsersObjectsContacts_Check
                        @Contact = :phone
                """

            result = await session.execute(text(sql), {"phone": phone_number})
            row = result.fetchone()

            if row:
                # Проверка сколько колонок вернула процедура
                if len(row) >= 3:
                    user_id = row[0] if row[0] is not None else None
                    menu_group_id = row[1] if row[1] is not None else None
                    contact_id = row[2] if row[2] is not None else None
                    return user_id, menu_group_id, contact_id
                elif len(row) >= 2:
                    user_id = row[0] if row[0] is not None else None
                    menu_group_id = row[1] if row[1] is not None else None
                    return user_id, menu_group_id, None
                else:
                    user_id = row[0] if row[0] is not None else None
                    return user_id, None, None

            return None, None, None

        except Exception as e:
            db_logger.error(f"❌ Failed to check user in Avanpost: {e}", exc_info=True)
            return None, None, None

    @staticmethod
    @log_exceptions(db_logger)
    async def get_user_ids_by_vehicles(
        session: AsyncSession,
    ) -> list[int]:
        """
        Получение списка ID пользователей из Avanpost через хранимую процедуру
        ext.PA_avp_RSAppUsersVehicles_Load.

        Args:
            session: Сессия БД (avanpost)

        Returns:
            list[int]: Список ID пользователей (user_id)
        """
        db_logger.info("📥 Calling ext.PA_avp_RSAppUsersVehicles_Load to get user IDs...")
        try:
            sql = """
                EXEC ext.PA_avp_RSAppUsersVehicles_Load
            """

            result = await session.execute(text(sql))
            rows = result.scalars().all()

            if not rows:
                db_logger.info("ℹ️ No user IDs returned from the procedure.")
                return []

            user_ids = [int(row) for row in rows if row is not None]

            db_logger.info(f"✅ Retrieved {len(user_ids)} user IDs from the procedure.")
            return user_ids

        except Exception as e:
            db_logger.error(f"❌ Failed to get user IDs from vehicles: {e}", exc_info=True)
            return []

    # ==================== ГРУППЫ ДЕЙСТВИЙ ====================

    @staticmethod
    @log_exceptions(db_logger)
    async def get_groups(
        session: AsyncSession,
    ) -> list[dict]:
        """
        Получение списка групп действий из Avanpost.

        Args:
            session: Сессия БД (avanpost)

        Returns:
            List[Dict]: Список групп
        """
        try:
            sql = """
                EXEC ext.PA_avp_RSAppScenariosGroups_Load
            """

            result = await session.execute(text(sql))
            rows = result.fetchall()

            if not rows:
                return []

            columns = result.keys()
            groups = []

            for row in rows:
                item = dict(zip(columns, row, strict=False))
                groups.append(
                    {
                        "id": item.get("ID"),
                        "name": item.get("Name"),
                    }
                )

            return groups

        except Exception as e:
            db_logger.error(f"❌ Failed to get groups: {e}", exc_info=True)
            return []

    # ==================== ДЕЙСТВИЯ ====================

    @staticmethod
    @log_exceptions(db_logger)
    async def get_menu_items(
        session: AsyncSession,
        group_id: int,
        parent_item_id: int | None = None,
    ) -> list[dict]:
        """
        Получение действий из Avanpost.

        Args:
            session: Сессия БД (avanpost)
            group_id: ID группы
            parent_item_id: ID родительского элемента

        Returns:
            List[Dict]: Список пунктов меню
        """
        try:
            sql = """
                EXEC ext.PA_avp_RSAppScenariosGroupsItems_Load
                    @GroupID = :group_id,
                    @ParentItemID = :parent_item_id
            """

            result = await session.execute(text(sql), {"group_id": group_id, "parent_item_id": parent_item_id})
            rows = result.fetchall()

            if not rows:
                return []

            columns = result.keys()
            items = []

            for row in rows:
                item = dict(zip(columns, row, strict=False))
                items.append(
                    {
                        "id": item.get("ID"),
                        "name": item.get("Name"),
                        "has_subitems": bool(item.get("FlagHasSubItems") or False),
                        "parent_id": item.get("ParentItemID"),
                    }
                )

            return items

        except Exception as e:
            db_logger.error(f"❌ Failed to get menu items: {e}", exc_info=True)
            return []

    @staticmethod
    @log_exceptions(db_logger)
    async def has_subitems(
        session: AsyncSession,
        group_id: int,
        item_id: int,
    ) -> bool:
        """
        Проверка, есть ли у действия дочерние элементы.

        Args:
            session: Сессия БД (avanpost)
            group_id: ID группы
            item_id: ID пункта меню

        Returns:
            bool: True, если есть дочерние элементы
        """
        try:
            items = await AvanpostRepository.get_menu_items(
                session=session,
                group_id=group_id,
                parent_item_id=item_id,
            )

            return len(items) > 0

        except Exception as e:
            db_logger.error(f"❌ Failed to check subitems for item {item_id} in group {group_id}: {e}", exc_info=True)
            return False

    # ==================== ОШИБКИ ====================

    @staticmethod
    @log_exceptions(db_logger)
    async def check_error_exists_by_procedure(
        session: AsyncSession,
        error_code: str,
        check_procedure: str,
    ) -> bool:
        """
        Проверка существования ошибки через хранимую процедуру.

        Args:
            session: Сессия БД (avanpost)
            error_code: Код ошибки
            check_procedure: Имя хранимой процедуры для проверки

        Returns:
            bool: True, если ошибка все еще существует в системе
        """
        try:
            sql = f"EXEC {check_procedure} @ErrorCode = :error_code"
            result = await session.execute(text(sql), {"error_code": error_code})
            rows = result.fetchall()

            return len(rows) > 0

        except Exception as e:
            db_logger.error(f"❌ Failed to check error via procedure {check_procedure}: {e}", exc_info=True)
            return True

    # ==================== ХРАНИМЫЕ ПРОЦЕДУРЫ СИНХРОНИЗАЦИИ ====================

    @staticmethod
    @log_exceptions(db_logger)
    async def call_base_data_procedure(
        session: AsyncSession,
        data_types: list[int],
        last_sync: datetime | None = None,
        force: bool = False,
    ) -> dict[str, Any]:
        """
        Вызов хранимой процедуры ext.PA_avp_RSAppBaseData_Load.

        Args:
            session: Сессия MSSQL (avanpost)
            data_types: Список типов данных для синхронизации
            last_sync: Время последней синхронизации
            force: Принудительная синхронизация

        Returns:
            dict: Данные из процедуры
        """
        params = {
            "DataTypes": data_types,
            "LastSync": last_sync.isoformat() if last_sync else "1900-01-01T00:00:00",
            "Force": force,
        }
        params_json = json.dumps(params, ensure_ascii=False)

        db_logger.debug(f"📤 CALL ext.PA_avp_RSAppBaseData_Load Params: {params_json}")

        sql = text("EXEC ext.PA_avp_RSAppBaseData_Load @Params = :params")

        try:
            result = await session.execute(sql, {"params": params_json})
        except Exception as e:
            db_logger.error(f"❌ SQL Execution failed: {e}")
            db_logger.error(f"❌ Failed with JSON: {params_json}")
            raise

        rows = result.fetchall()

        db_logger.info(f"📊 Procedure returned {len(rows)} rows")

        if not rows:
            db_logger.info("ℹ️ No rows returned from procedure")
            return {"Data": []}

        try:
            first_row = rows[0]

            db_logger.debug(f"🔍 First row type: {type(first_row)}")
            db_logger.debug(f"🔍 First row length: {len(first_row)}")

            if len(first_row) >= 1:
                json_data = first_row[0]
                db_logger.debug(f"🔍 Response type: {type(json_data)}")

                if isinstance(json_data, str):
                    trimmed = json_data.strip()
                    if trimmed.startswith("{") or trimmed.startswith("["):
                        try:
                            parsed_data = json.loads(trimmed)
                            db_logger.debug("✅ JSON parsed successfully")
                            db_logger.debug(f"🔍 parsed_data type: {type(parsed_data)}")

                            if isinstance(parsed_data, list):
                                db_logger.debug(f"🔍 parsed_data is a list, length: {len(parsed_data)}")

                                if parsed_data and isinstance(parsed_data[0], dict):
                                    if "Data" in parsed_data[0]:
                                        data_items = parsed_data[0].get("Data", [])
                                        db_logger.debug(
                                            f"🔍 Found Data field in first item, length: {len(data_items) if isinstance(data_items, list) else 'not a list'}"
                                        )
                                        if isinstance(data_items, list) and data_items:
                                            if isinstance(data_items[0], dict) and "DataTypeId" in data_items[0]:
                                                db_logger.debug(
                                                    f"📊 Extracted {len(data_items)} data items from Data field"
                                                )
                                                return {"Data": data_items}
                                            else:
                                                db_logger.warning("⚠️ Data field does not contain DataTypeId objects")
                                                return {"Data": []}
                                        else:
                                            return {"Data": []}
                                    else:
                                        db_logger.warning("⚠️ First item does not contain 'Data' field")
                                        return {"Data": []}
                                else:
                                    db_logger.warning("⚠️ parsed_data is list but first item is not a dict")
                                    return {"Data": []}

                            elif isinstance(parsed_data, dict):
                                db_logger.debug(f"🔍 parsed_data is dict, keys: {list(parsed_data.keys())}")

                                if "Data" in parsed_data:
                                    data_items = parsed_data.get("Data", [])
                                    if isinstance(data_items, list) and data_items:
                                        if isinstance(data_items[0], dict) and "DataTypeId" in data_items[0]:
                                            db_logger.debug(
                                                f"📊 Extracted {len(data_items)} data items from Data field"
                                            )
                                            return {"Data": data_items}
                                        else:
                                            db_logger.warning("⚠️ Data field does not contain DataTypeId objects")
                                            return {"Data": []}
                                    else:
                                        return {"Data": []}
                                else:
                                    db_logger.warning(f"⚠️ No 'Data' field in response: {list(parsed_data.keys())}")
                                    return {"Data": []}

                            else:
                                db_logger.warning(f"⚠️ Unexpected parsed_data type: {type(parsed_data)}")
                                return {"Data": []}

                        except json.JSONDecodeError as e:
                            db_logger.error(f"❌ Failed to parse JSON: {e}")
                            return {"Data": []}
                    else:
                        db_logger.warning(f"⚠️ Response doesn't start with JSON: {trimmed[:100]}...")
                        return {"Data": []}
                else:
                    db_logger.warning(f"⚠️ Unexpected response type: {type(json_data)}")
                    return {"Data": []}
            else:
                db_logger.warning(f"⚠️ Unexpected row structure, expected at least 1 column, got {len(first_row)}")
                return {"Data": []}

        except Exception as e:
            db_logger.error(f"❌ Error processing response: {e}")
            import traceback

            db_logger.error(f"📄 Traceback: {traceback.format_exc()}")
            return {"Data": []}

    @staticmethod
    @log_exceptions(db_logger)
    async def call_user_data_procedure(
        session: AsyncSession,
        user_id: int,
        data_types: list[int],
        last_sync: datetime | None = None,
        force: bool = False,
    ) -> dict[str, Any]:
        """Вызов хранимой процедуры ext.PA_avp_RSAppUserData_Load"""
        import json

        params = {
            "UserId": user_id,
            "DataTypes": data_types,
            "LastSync": last_sync.isoformat() if last_sync else "1900-01-01T00:00:00",
            "Force": force,
        }
        params_json = json.dumps(params, ensure_ascii=False)

        db_logger.debug(f"📤 CALL ext.PA_avp_RSAppUserData_Load Params: {params_json}")

        sql = text("EXEC ext.PA_avp_RSAppUserData_Load @Params = :params")
        try:
            result = await session.execute(sql, {"params": params_json})
        except Exception as e:
            db_logger.error(f"❌ SQL Execution failed: {e}")
            db_logger.error(f"❌ Failed with JSON: {params_json}")
            raise

        rows = result.fetchall()

        if not rows:
            db_logger.info("ℹ️ No rows returned from user procedure")
            return {"Data": []}

        try:
            db_logger.debug(f"🔍 User response rows count: {len(rows)}")

            if hasattr(rows[0], "__getitem__") and not isinstance(rows[0], str):
                first_col = rows[0][0]

                if isinstance(first_col, str):
                    trimmed = first_col.strip()
                    if trimmed.startswith("{") or trimmed.startswith("["):
                        try:
                            data = json.loads(trimmed)
                            db_logger.debug(f"🔍 Parsed JSON type: {type(data)}")

                            if isinstance(data, list) and len(data) > 0:
                                data = data[0]
                                db_logger.debug(
                                    f"🔍 Extracted first item from list, keys: {list(data.keys()) if isinstance(data, dict) else 'not dict'}"
                                )

                            if not isinstance(data, dict):
                                db_logger.warning(f"⚠️ Expected dict, got {type(data)}")
                                return {"Data": []}

                            db_logger.debug(f"🔍 Parsed JSON keys: {list(data.keys())}")

                            if "Data" not in data:
                                db_logger.warning(f"⚠️ No 'Data' field in response: {list(data.keys())}")
                                return {"Data": []}

                            raw_data = data.get("Data", [])

                            if not raw_data:
                                db_logger.info("ℹ️ No data in response")
                                return {"Data": []}

                            db_logger.debug(f"🔍 Raw data length: {len(raw_data)}")

                            result_data = []

                            for item in raw_data:
                                if not isinstance(item, dict):
                                    db_logger.warning(f"⚠️ Item is not dict: {type(item)}")
                                    continue

                                data_type_id = item.get("DataTypeId")
                                if data_type_id is None:
                                    db_logger.warning(f"⚠️ DataTypeId is None for item: {list(item.keys())}")
                                    continue

                                records = item.get("Data")
                                if records is None:
                                    db_logger.debug(f"ℹ️ No records for DataTypeId {data_type_id}")
                                    continue

                                flag_expire = item.get("FlagExpire", False)

                                if not isinstance(records, list | dict):
                                    db_logger.warning(f"⚠️ Unexpected records type: {type(records)}")
                                    continue

                                result_data.append(
                                    {
                                        "DataTypeId": data_type_id,
                                        "FlagExpire": flag_expire,
                                        "Data": records,
                                    }
                                )

                                records_count = len(records) if isinstance(records, list) else 1
                                db_logger.debug(
                                    f"  └─ DataTypeId {data_type_id}: {records_count} records, FlagExpire={flag_expire}"
                                )

                            if "Stats" in data:
                                stats = data["Stats"]
                                db_logger.debug(f"📊 Stats from response: {stats}")

                            db_logger.debug(f"📊 Total data blocks: {len(result_data)}")

                            return {"Data": result_data}

                        except json.JSONDecodeError as e:
                            db_logger.error(f"❌ Failed to parse JSON: {e}")
                            db_logger.error(f"❌ JSON preview: {trimmed[:500]}...")
                            return {"Data": []}

                    elif isinstance(first_col, int | float):
                        if first_col == 0:
                            db_logger.info("ℹ️ User procedure returned 0 (no data)")
                        else:
                            db_logger.warning(f"⚠️ User procedure returned code: {first_col}")
                        return {"Data": []}

            return {"Data": []}

        except Exception as e:
            db_logger.error(f"❌ Error processing user response: {e}")
            import traceback

            db_logger.debug(f"📄 Traceback: {traceback.format_exc()}")
            return {"Data": []}


__all__ = ["AvanpostRepository"]
