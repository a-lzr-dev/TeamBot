import json
from datetime import datetime
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from ...logger import db_logger
from ...utils.decorators import log_exceptions

# ==================== ПЕРЕЧЕНЬ ВНЕШНИХ ХРАНИМЫХ ПРОЦЕДУР ====================
#
# 1. ext.PA_avp_RSAppUsersObjectsContacts_Check
#    - Проверка пользователя по номеру телефона
#    - Параметр: @Contact (номер телефона)
#    - Возвращает: user_id, menu_group_id, contact_id
#    - Используется в: Авторизация пользователей
#
# 2. ext.PA_avp_RSAppBaseData_Load
#    - Синхронизация базовых данных (справочники)
#    - Параметр: @Params (JSON с полями DataTypes, LastSync, Force)
#    - Возвращает: JSON с полем Data (список объектов)
#    - Формат ответа: [{"SyncType":"System","SyncTime":"...","Data":[...],"Stats":{...}}]
#    - Используется в: Синхронизация справочников (AVANPOST_BASE_DATA_TYPES)
#
# 3. ext.PA_avp_RSAppUserData_Load
#    - Синхронизация данных конкретного пользователя
#    - Параметр: @Params (JSON с полями UserId, DataTypes, LastSync, Force)
#    - Возвращает: JSON с полем Data (список объектов)
#    - Формат ответа: [{"Data": [...]}] или {"Data": [...]}
#    - Используется в: Синхронизация пользовательских данных
#
# 4. ext.PA_avp_RSAppUsers_DefaultAdding_Load
#    - Получение списка ID пользователей для добавления по умолчанию
#    - Параметры: отсутствуют
#    - Возвращает: список user_id
#    - Используется в: Загрузка пользователей из Avanpost (seed)
#
# ======================================================================


class AvanpostRepository:
    """
    Репозиторий для работы с Avanpost (MSSQL).

    Предоставляет методы для:
    - Проверки пользователей по номеру телефона
    - Получения списка пользователей
    - Вызова хранимых процедур синхронизации
    - Проверки существования ошибок
    """

    # ==================== ПОЛЬЗОВАТЕЛИ ====================

    @staticmethod
    @log_exceptions(db_logger)
    async def check_user_by_phone(
        session: AsyncSession,
        phone_number: str,
    ) -> tuple[int | None, int | None, int | None]:
        """
        Проверка пользователя по номеру телефона через хранимую процедуру.

        Вызывает ext.PA_avp_RSAppUsersObjectsContacts_Check для проверки
        существования пользователя в системе Avanpost.

        Args:
            session: Сессия БД (avanpost)
            phone_number: Номер телефона для проверки

        Returns:
            tuple[int | None, int | None, int | None]:
                (user_id, menu_group_id, contact_id) или (None, None, None)
        """
        try:
            sql = """
                    EXEC ext.PA_avp_RSAppUsersObjectsContacts_Check
                        @Contact = :phone
                """

            result = await session.execute(text(sql), {"phone": phone_number})
            row = result.fetchone()

            if row:
                # Проверка количества колонок, возвращенных процедурой
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
    async def get_user_ids_default_adding(
        session: AsyncSession,
    ) -> list[int]:
        """
        Получение списка ID пользователей для добавления по умолчанию.

        Вызывает ext.PA_avp_RSAppUsers_DefaultAdding_Load для получения
        списка пользователей, которые должны быть добавлены в систему.

        Args:
            session: Сессия БД (avanpost)

        Returns:
            list[int]: Список ID пользователей (user_id)
        """
        db_logger.info("📥 Calling ext.PA_avp_RSAppUsers_DefaultAdding_Load to get user IDs...")
        try:
            sql = """
                EXEC ext.PA_avp_RSAppUsers_DefaultAdding_Load
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

        Используется для проверки, устранена ли ошибка во внешней системе
        перед ее автоматическим решением.

        Args:
            session: Сессия БД (avanpost)
            error_code: Код ошибки
            check_procedure: Имя хранимой процедуры для проверки

        Returns:
            bool: True если ошибка все еще существует в системе
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

        Синхронизирует базовые справочные данные из Avanpost.

        СТРУКТУРА ОТВЕТА ПРОЦЕДУРЫ:
        [
            {
                "SyncType": "System",           -- Тип синхронизации
                "SyncTime": "2026-08-21T19:03:29", -- Время синхронизации
                "Data": [                        -- Массив блоков данных
                    {
                        "DataTypeId": 1,        -- ID типа данных
                        "FlagExpire": null,     -- Флаг удаления
                        "Data": [               -- Реальные данные (массив записей)
                            {"FID": "RU", "FFlagDefault": true},
                            {"FID": "EN", "FFlagDefault": false}
                        ]
                    },
                    ...
                ],
                "Stats": {                       -- Статистика
                    "Total": 10,
                    "TablesUpdated": 3
                }
            }
        ]

        Args:
            session: Сессия MSSQL (avanpost)
            data_types: Список типов данных для синхронизации
            last_sync: Время последней синхронизации
            force: Принудительная синхронизация

        Returns:
            dict[str, Any]: Словарь с ключом "Data", содержащим список блоков данных
        """
        # Подготовка параметров для JSON
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

                    # Проверка, что ответ является JSON
                    if trimmed.startswith("{") or trimmed.startswith("["):
                        try:
                            parsed_data = json.loads(trimmed)
                            db_logger.debug("✅ JSON parsed successfully")
                            db_logger.debug(f"🔍 parsed_data type: {type(parsed_data)}")

                            # ============================================================
                            # УНИВЕРСАЛЬНАЯ ОБРАБОТКА JSON
                            # ============================================================
                            #
                            # Процедура возвращает JSON в формате массива с одним объектом:
                            # [{"SyncType":"System","SyncTime":"...","Data":[...],"Stats":{...}}]
                            #
                            # Нужно извлечь поле Data и вернуть его содержимое.
                            # ============================================================

                            # Шаг 1: Извлечение основного объекта данных
                            if isinstance(parsed_data, list):
                                if not parsed_data:
                                    db_logger.warning("⚠️ Empty list received")
                                    return {"Data": []}

                                # Берем первый элемент массива как основной объект данных
                                data_obj = parsed_data[0]
                                db_logger.debug("🔍 Extracted first item from list array")
                            else:
                                # Если вдруг пришел не массив, а объект
                                data_obj = parsed_data

                            # Шаг 2: Проверка, что data_obj является словарем
                            if not isinstance(data_obj, dict):
                                db_logger.warning(f"⚠️ Expected dict, got {type(data_obj)}")
                                return {"Data": []}

                            db_logger.debug(f"🔍 data_obj keys: {list(data_obj.keys())}")

                            # Шаг 3: Извлечение данных из поля "Data"
                            if "Data" not in data_obj:
                                db_logger.debug(
                                    f"⚠️ No 'Data' field in response. Available keys: {list(data_obj.keys())}"
                                )
                                return {"Data": []}

                            raw_data = data_obj.get("Data")

                            if not raw_data:
                                db_logger.info("ℹ️ 'Data' field is empty")
                                return {"Data": []}

                            # Шаг 4: Проверка, что raw_data - это список
                            if not isinstance(raw_data, list):
                                db_logger.warning(f"⚠️ Expected list, got {type(raw_data)}")
                                return {"Data": []}

                            db_logger.info(f"✅ Extracted {len(raw_data)} data blocks from 'Data' field")

                            # Шаг 5: Обработка каждого блока данных
                            # Каждый блок содержит: DataTypeId, FlagExpire, Data (список записей)
                            result_data = []

                            for block in raw_data:
                                if not isinstance(block, dict):
                                    db_logger.warning(f"⚠️ Block is not dict: {type(block)}")
                                    continue

                                data_type_id = block.get("DataTypeId")
                                if data_type_id is None:
                                    db_logger.warning(f"⚠️ DataTypeId is None for block: {list(block.keys())}")
                                    continue

                                records = block.get("Data")
                                if not records:
                                    db_logger.debug(f"ℹ️ No records for DataTypeId {data_type_id}")
                                    continue

                                flag_expire = block.get("FlagExpire", False)

                                # Проверка, что records - это список
                                if isinstance(records, list):
                                    db_logger.debug(
                                        f"  └─ DataTypeId {data_type_id}: {len(records)} records, "
                                        f"FlagExpire={flag_expire}"
                                    )
                                else:
                                    db_logger.debug(
                                        f"  └─ DataTypeId {data_type_id}: single record, FlagExpire={flag_expire}"
                                    )
                                    # Если records - не список (одиночный объект), превращаем в список
                                    records = [records]

                                result_data.append(
                                    {
                                        "DataTypeId": data_type_id,
                                        "FlagExpire": flag_expire,
                                        "Data": records,
                                    }
                                )

                            # Шаг 6: Логируем статистику, если она есть
                            if "Stats" in data_obj:
                                stats = data_obj.get("Stats", {})
                                db_logger.debug(f"📊 Stats from response: {stats}")

                            db_logger.info(f"📊 Total data blocks extracted: {len(result_data)}")

                            return {"Data": result_data}

                        except json.JSONDecodeError as e:
                            db_logger.error(f"❌ Failed to parse JSON: {e}")
                            db_logger.error(f"❌ JSON preview: {trimmed[:500]}...")
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
        show_logs: bool = True,
    ) -> dict[str, Any]:
        """
        Вызов хранимой процедуры ext.PA_avp_RSAppUserData_Load.

        Синхронизирует данные конкретного пользователя из Avanpost.
        Использует ту же универсальную логику обработки JSON,
        что и call_base_data_procedure.

        Args:
            session: Сессия MSSQL (avanpost)
            user_id: ID пользователя в Avanpost
            data_types: Список типов данных для синхронизации
            last_sync: Время последней синхронизации
            force: Принудительная синхронизация
            show_logs: Отображение подробного логирования (Debug уровень)

        Returns:
            dict[str, Any]: Словарь с ключом "Data", содержащим список записей
        """
        # Подготовка параметров для JSON
        params = {
            "UserId": user_id,
            "DataTypes": data_types,
            "LastSync": last_sync.isoformat() if last_sync else "1900-01-01T00:00:00",
            "Force": force,
        }
        params_json = json.dumps(params, ensure_ascii=False)

        if show_logs:
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
            if show_logs:
                db_logger.info("ℹ️ No rows returned from user procedure")
            return {"Data": []}

        try:
            if show_logs:
                db_logger.debug(f"🔍 User response rows count: {len(rows)}")

            if hasattr(rows[0], "__getitem__") and not isinstance(rows[0], str):
                first_col = rows[0][0]

                if isinstance(first_col, str):
                    trimmed = first_col.strip()
                    if trimmed.startswith("{") or trimmed.startswith("["):
                        try:
                            data = json.loads(trimmed)
                            db_logger.debug(f"🔍 Parsed JSON type: {type(data)}")

                            # ============================================================
                            # УНИВЕРСАЛЬНАЯ ОБРАБОТКА JSON (аналогично base_data_procedure)
                            # ============================================================

                            # Шаг 1: Извлечение основного объекта данных
                            if isinstance(data, list):
                                if not data:
                                    if show_logs:
                                        db_logger.info("ℹ️ Empty list received")
                                    return {"Data": []}
                                data_obj = data[0]
                                if show_logs:
                                    db_logger.debug(
                                        f"🔍 Extracted first item from list, keys: "
                                        f"{list(data_obj.keys()) if isinstance(data_obj, dict) else 'not dict'}"
                                    )
                            else:
                                data_obj = data

                            # Шаг 2: Проверка, что data_obj является словарем
                            if not isinstance(data_obj, dict):
                                db_logger.warning(f"⚠️ Expected dict, got {type(data_obj)}")
                                return {"Data": []}

                            if show_logs:
                                db_logger.debug(f"🔍 data_obj keys: {list(data_obj.keys())}")

                            # Шаг 3: Извлечение данных из поля "Data"
                            if "Data" not in data_obj:
                                db_logger.debug(f"⚠️ No 'Data' field in response: {list(data_obj.keys())}")
                                return {"Data": []}

                            raw_data = data_obj.get("Data", [])

                            if not raw_data:
                                if show_logs:
                                    db_logger.info("ℹ️ No data in response")
                                return {"Data": []}

                            if show_logs:
                                db_logger.debug(f"🔍 Raw data length: {len(raw_data)}")

                            # Шаг 4: Обработка и структурирование данных
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
                                    if show_logs:
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
                                if show_logs:
                                    db_logger.debug(
                                        f"  └─ DataTypeId {data_type_id}: {records_count} records, "
                                        f"FlagExpire={flag_expire}"
                                    )

                            if "Stats" in data_obj:
                                stats = data_obj["Stats"]
                                if show_logs:
                                    db_logger.debug(f"📊 Stats from response: {stats}")

                            if show_logs:
                                db_logger.debug(f"📊 Total data blocks: {len(result_data)}")

                            return {"Data": result_data}

                        except json.JSONDecodeError as e:
                            db_logger.error(f"❌ Failed to parse JSON: {e}")
                            db_logger.error(f"❌ JSON preview: {trimmed[:500]}...")
                            return {"Data": []}

                    elif isinstance(first_col, int | float):
                        if first_col == 0:
                            if show_logs:
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
