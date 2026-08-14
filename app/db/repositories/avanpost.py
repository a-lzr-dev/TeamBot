import json
from datetime import datetime
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from ...logger import db_logger


class AvanpostRepository:
    """Репозиторий для работы с Avanpost (MSSQL)"""

    # ==================== ПОЛЬЗОВАТЕЛИ ====================

    @staticmethod
    async def check_user_by_phone(
        session: AsyncSession,
        phone_number: str,
    ) -> tuple[int | None, int | None]:
        """
        Проверка пользователя по номеру телефона через хранимую процедуру.

        Args:
            session: Сессия БД (avanpost)
            phone_number: Номер телефона

        Returns:
            Tuple[int | None, int | None]: (user_id, group_id) или (None, None)
        """
        try:
            sql = """
                EXEC ext.PA_avp_RSAppUsersObjectsContacts_Check
                    @Contact = :phone
            """

            result = await session.execute(text(sql), {"phone": phone_number})
            row = result.fetchone()

            if row:
                user_id = row[0] if len(row) > 0 else None
                group_id = row[1] if len(row) > 1 else None
                return user_id, group_id

            return None, None

        except Exception as e:
            db_logger.error(f"❌ Failed to check user in Avanpost: {e}", exc_info=True)
            return None, None

    # ==================== ГРУППЫ ДЕЙСТВИЙ ====================

    @staticmethod
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
    async def has_subitems(
        session: AsyncSession,
        group_id: int,
        item_id: int,
    ) -> bool:
        """
        Проверка, есть ли у действия дочерние элементы.
        Использует get_menu_items для получения данных.

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

            # Если есть элементы, значит есть дочерние
            return len(items) > 0

        except Exception as e:
            db_logger.error(f"❌ Failed to check subitems for item {item_id} in group {group_id}: {e}", exc_info=True)
            return False

    # ==================== ОШИБКИ ====================

    @staticmethod
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

            # Если есть строки - ошибка все еще существует
            return len(rows) > 0

        except Exception as e:
            db_logger.error(f"❌ Failed to check error via procedure {check_procedure}: {e}", exc_info=True)
            return True

    # ==================== ХРАНИМЫЕ ПРОЦЕДУРЫ СИНХРОНИЗАЦИИ ====================

    @staticmethod
    async def call_base_data_procedure(
        session: AsyncSession,
        data_types: list[int],
        last_sync: datetime | None = None,
        force: bool = False,
    ) -> dict[str, Any]:
        """
        Вызов хранимой процедуры ext.PA_avp_RSAppBaseData_Load.
        """
        params = {
            "DataTypes": data_types,
            "LastSync": last_sync.isoformat() if last_sync else "1900-01-01T00:00:00",
            "Force": force,
        }
        params_json = json.dumps(params, ensure_ascii=False)

        # ================================================================
        # ВЫВОД ПАРАМЕТРОВ В DEBUG (краткий формат)
        # ================================================================
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

            # Процедура возвращает одну колонку с JSON
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

                            # Случай 1: parsed_data - это список
                            if isinstance(parsed_data, list):
                                db_logger.debug(f"🔍 parsed_data is a list, length: {len(parsed_data)}")

                                # Если список не пустой и первый элемент - словарь с Data
                                if parsed_data and isinstance(parsed_data[0], dict):
                                    # Проверка, есть ли поле Data в первом элементе
                                    if "Data" in parsed_data[0]:
                                        data_items = parsed_data[0].get("Data", [])
                                        db_logger.debug(
                                            f"🔍 Found Data field in first item, length: {len(data_items) if isinstance(data_items, list) else 'not a list'}"
                                        )
                                        if isinstance(data_items, list) and data_items:
                                            # Проверка, что это массив объектов с DataTypeId
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

                            # Случай 2: parsed_data - это словарь (старый формат)
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
    async def call_user_data_procedure(
        session: AsyncSession,
        user_id: int,
        data_types: list[int],
        last_sync: datetime | None = None,
        force: bool = False,
    ) -> dict[str, Any]:
        """
        Вызов хранимой процедуры ext.PA_avp_RSAppUserData_Load.

        Args:
            session: Сессия MSSQL (avanpost)
            user_id: ID пользователя
            data_types: Список типов данных для синхронизации
            last_sync: Время последней синхронизации
            force: Принудительная синхронизация

        Returns:
            dict: Данные из процедуры
        """
        params = {
            "UserId": user_id,
            "DataTypes": data_types,
            "LastSync": last_sync.isoformat() if last_sync else "1900-01-01T00:00:00",
            "Force": force,
        }
        params_json = json.dumps(params, ensure_ascii=False)

        # ================================================================
        # ВЫВОД ПАРАМЕТРОВ В DEBUG (краткий формат)
        # ================================================================
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

                            if isinstance(data, dict) and "Data" in data:
                                return data
                            elif isinstance(data, list):
                                return {"Data": data}
                        except json.JSONDecodeError as e:
                            db_logger.error(f"❌ Failed to parse JSON: {e}")
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
