from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, TypeVar

from sqlalchemy import and_, delete, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from ..config import settings
from ..db import db_manager
from ..db.repositories import AvanpostRepository, SystemRepository
from ..logger import app_logger
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
    datetime_now,
)

ModelType = TypeVar("ModelType")


# ==================== СТАТИСТИКА СИНХРОНИЗАЦИИ ====================


@dataclass
class SyncStatistics:
    """Статистика синхронизации"""

    # Общие счетчики
    total_data_types: int = 0
    processed_data_types: int = 0
    failed_data_types: int = 0

    # Счетчики по операциям
    tables_with_inserts: set[str] = field(default_factory=set)
    tables_with_updates: set[str] = field(default_factory=set)
    tables_with_deletes: set[str] = field(default_factory=set)
    tables_with_errors: set[str] = field(default_factory=set)
    tables_with_unchanged: set[str] = field(default_factory=set)

    # Количество записей
    total_inserted: int = 0
    total_updated: int = 0
    total_deleted: int = 0
    total_unchanged: int = 0
    total_skipped_upsert: int = 0
    total_skipped_delete: int = 0

    # Количество полученных записей
    total_received: int = 0
    total_received_upsert: int = 0
    total_received_delete: int = 0

    # Детальная статистика по таблицам
    table_stats: dict[str, dict[str, int]] = field(
        default_factory=lambda: defaultdict(
            lambda: {
                "inserted": 0,
                "updated": 0,
                "deleted": 0,
                "errors": 0,
                "unchanged": 0,
                "skipped_upsert": 0,
                "skipped_delete": 0,
                "received": 0,
                "received_upsert": 0,
                "received_delete": 0,
            }
        )
    )

    # Ошибки
    error_messages: list[str] = field(default_factory=list)

    # Время
    start_time: datetime | None = None
    end_time: datetime | None = None

    def start(self) -> None:
        """Запуск таймера"""
        self.start_time = datetime_now()

    def finish(self) -> None:
        """Остановка таймера"""
        self.end_time = datetime_now()

    def add_received(self, table_name: str, upsert_count: int = 0, delete_count: int = 0) -> None:
        """Добавление полученных записей"""
        if upsert_count > 0 or delete_count > 0:
            total = upsert_count + delete_count
            self.total_received += total
            self.total_received_upsert += upsert_count
            self.total_received_delete += delete_count
            self.table_stats[table_name]["received"] += total
            self.table_stats[table_name]["received_upsert"] += upsert_count
            self.table_stats[table_name]["received_delete"] += delete_count

    def add_insert(self, table_name: str, count: int = 1) -> None:
        """Добавление реально ВСТАВЛЕННЫХ записей (INSERT)"""
        if count > 0:
            self.tables_with_inserts.add(table_name)
            self.total_inserted += count
            self.table_stats[table_name]["inserted"] += count

    def add_update(self, table_name: str, count: int = 1) -> None:
        """Добавление реально ОБНОВЛЕННЫХ записей (UPDATE)"""
        if count > 0:
            self.tables_with_updates.add(table_name)
            self.total_updated += count
            self.table_stats[table_name]["updated"] += count

    def add_delete(self, table_name: str, count: int = 1) -> None:
        """Добавление реально УДАЛЕННЫХ записей (DELETE)"""
        if count > 0:
            self.tables_with_deletes.add(table_name)
            self.total_deleted += count
            self.table_stats[table_name]["deleted"] += count

    def add_unchanged(self, table_name: str, count: int = 1) -> None:
        """Записи без изменений (пропущены)"""
        if count > 0:
            self.tables_with_unchanged.add(table_name)
            self.total_unchanged += count
            self.table_stats[table_name]["unchanged"] += count

    def add_skip_upsert(self, table_name: str, count: int = 1) -> None:
        """Пропущено из UPSERT (не вставлены/не обновлены из-за ошибок)"""
        if count > 0:
            self.total_skipped_upsert += count
            self.table_stats[table_name]["skipped_upsert"] += count

    def add_skip_delete(self, table_name: str, count: int = 1) -> None:
        """Пропущено из DELETE (не найдены для удаления)"""
        if count > 0:
            self.total_skipped_delete += count
            self.table_stats[table_name]["skipped_delete"] += count

    def add_error(self, table_name: str, error: str) -> None:
        """Добавление ошибки"""
        self.tables_with_errors.add(table_name)
        self.failed_data_types += 1
        self.table_stats[table_name]["errors"] += 1
        self.error_messages.append(f"[{table_name}] {error[:200]}")

    def to_dict(self) -> dict[str, Any]:
        """Преобразование в словарь"""
        duration = None
        if self.start_time and self.end_time:
            duration = (self.end_time - self.start_time).total_seconds()

        return {
            "total_data_types": int(self.total_data_types),
            "processed_data_types": int(self.processed_data_types),
            "failed_data_types": int(self.failed_data_types),
            "tables_with_inserts": sorted(self.tables_with_inserts),
            "tables_with_updates": sorted(self.tables_with_updates),
            "tables_with_deletes": sorted(self.tables_with_deletes),
            "tables_with_errors": sorted(self.tables_with_errors),
            "tables_with_unchanged": sorted(self.tables_with_unchanged),
            "total_inserted": int(self.total_inserted),
            "total_updated": int(self.total_updated),
            "total_deleted": int(self.total_deleted),
            "total_unchanged": int(self.total_unchanged),
            "total_skipped_upsert": int(self.total_skipped_upsert),
            "total_skipped_delete": int(self.total_skipped_delete),
            "total_received": int(self.total_received),
            "total_received_upsert": int(self.total_received_upsert),
            "total_received_delete": int(self.total_received_delete),
            "table_stats": dict(self.table_stats),
            "error_count": len(self.error_messages),
            "error_messages": self.error_messages[:10],
            "duration_seconds": duration,
            "start_time": self.start_time.isoformat() + "Z" if self.start_time else None,
            "end_time": self.end_time.isoformat() + "Z" if self.end_time else None,
        }

    def print_report(self, title: str = "Sync Report", force: bool = False) -> None:
        """
        Вывод отчета в консоль только если есть изменения или ошибки.

        Args:
            title: Заголовок отчета
            force: Принудительный вывод отчета (для отладки)
        """
        # Проверки
        has_changes = self.total_inserted > 0 or self.total_updated > 0 or self.total_deleted > 0
        has_errors = len(self.error_messages) > 0 or len(self.tables_with_errors) > 0
        has_received_data = self.total_received > 0

        if not has_changes and not has_errors and not force:
            # Если данные были получены, но изменений нет
            if has_received_data:
                app_logger.warning(
                    f"⚠️ {title}: Received {self.total_received} records from Avanpost, "
                    f"but no changes detected (all data is up to date)"
                )
                # Вывод деталей по таблично
                if self.table_stats:
                    app_logger.debug("📊 Received data by table:")
                    for table_name, stats in self.table_stats.items():
                        received = stats.get("received", 0)
                        if received > 0:
                            app_logger.debug(f"   └─ {table_name}: {received} records received, 0 changes")
            else:
                app_logger.info(f"✅ {title}: No changes detected (all data is up to date)")
            return
        duration = None
        if self.start_time and self.end_time:
            duration = (self.end_time - self.start_time).total_seconds()

        # Определение множества всех таблиц
        all_tables = sorted(
            set(self.table_stats.keys())
            | set(self.tables_with_inserts)
            | set(self.tables_with_updates)
            | set(self.tables_with_deletes)
            | set(self.tables_with_errors)
            | set(self.tables_with_unchanged)
        )

        # Вычисление максимальной длины имени таблицы для динамического выравнивания
        max_table_len = 45
        for table in all_tables:
            if len(table) > max_table_len:
                max_table_len = len(table)
        # Ограничение разумным пределом
        if max_table_len > 80:
            max_table_len = 80

        # Ширина колонок с цифрами - 8 символов
        # Колонки: Recv(8) + DelRecv(8) + Ins(8) + Upd(8) + Del(8) + Err(8) + UncUps(8) + SkipDel(8) + Status(10)
        separator_len = max_table_len + 8 + 8 + 8 + 8 + 8 + 8 + 8 + 8 + 10 + 18

        print("\n📋 SYNC STATISTICS:")
        print("-" * separator_len)

        # Заголовок
        header = f"{'Table':<{max_table_len}} {'Recv':>8} {'DelRecv':>8} {'Ins':>8} {'Upd':>8} {'Del':>8} {'Err':>8} {'UncUps':>8} {'SkipDel':>8} {'  Status':<10}"
        print(header)
        print("-" * separator_len)

        # Сбор итоговых сумм для SUMMARY строки
        total_received_upsert = 0
        total_received_delete = 0
        total_inserted = 0
        total_updated = 0
        total_deleted = 0
        total_errors = 0
        total_unchanged = 0
        total_skipped_upsert = 0
        total_skipped_delete = 0
        has_any_data = False

        for table in all_tables:
            stats = self.table_stats.get(table, {})
            received_upsert = stats.get("received_upsert", 0)
            received_delete = stats.get("received_delete", 0)
            inserted = stats.get("inserted", 0)
            updated = stats.get("updated", 0)
            deleted = stats.get("deleted", 0)
            errors = stats.get("errors", 0)
            unchanged = stats.get("unchanged", 0)
            skipped_upsert = stats.get("skipped_upsert", 0)
            skipped_delete = stats.get("skipped_delete", 0)

            # Recv = только UPSERT (не включает DELETE)
            received = received_upsert

            # Суммирование для итогов
            total_received_upsert += received_upsert
            total_received_delete += received_delete
            total_inserted += inserted
            total_updated += updated
            total_deleted += deleted
            total_errors += errors
            total_unchanged += unchanged
            total_skipped_upsert += skipped_upsert
            total_skipped_delete += skipped_delete

            # Отображение только таблиц с изменениями или ошибками
            if (
                inserted == 0
                and updated == 0
                and deleted == 0
                and errors == 0
                and unchanged == 0
                and skipped_upsert == 0
                and skipped_delete == 0
                and received == 0
                and received_delete == 0
            ):
                continue

            has_any_data = True

            # Статусы с иконками (выравнивание по ЛЕВОМУ краю)
            if errors > 0:
                status = "  ❌ ERROR"
            elif inserted > 0 or updated > 0 or deleted > 0:
                status = "  ✅ OK"
            elif unchanged > 0 or skipped_upsert > 0 or skipped_delete > 0:
                status = "  ⏭️ SKIP"
            else:
                status = "    -"

            # Строка таблицы - UncUps = unchanged + skipped_upsert
            unc_ups = unchanged + skipped_upsert

            print(
                f"{table:<{max_table_len}} {received:>8} {received_delete:>8} {inserted:>8} {updated:>8} {deleted:>8} {errors:>8} {unc_ups:>8} {skipped_delete:>8} {status:<10}"
            )

        # Итоговая строка SUMMARY
        if has_any_data:
            print("-" * separator_len)
            status_text = " ⚠️ ERRORS" if total_errors > 0 else "  ✅ DONE"
            duration_str = f"{duration:.2f}s" if duration else "N/A"
            summary_label = f"📊 SUMMARY (Tables: {len(all_tables)}, Duration: {duration_str})"
            total_received = total_received_upsert
            total_unc_ups = total_unchanged + total_skipped_upsert

            print(
                f"{summary_label:<{max_table_len - 1}} {total_received:>8} {total_received_delete:>8} {total_inserted:>8} {total_updated:>8} {total_deleted:>8} {total_errors:>8} {total_unc_ups:>8} {total_skipped_delete:>8} {status_text:<10}"
            )
            print("-" * separator_len)

        # Вывод ошибок
        if self.tables_with_errors:
            print(f"\n❌ TABLES WITH ERRORS ({len(self.tables_with_errors)}):")
            for table in sorted(self.tables_with_errors):
                print(f"   - {table}")
            print("\n📝 Error details:")
            for err in self.error_messages:
                print(f"   - {err}")


class AvanpostSyncService:
    """Сервис синхронизации данных Avanpost."""

    # Маппинг типа данных -> модель SQLAlchemy
    MODEL_MAPPING: dict[int, Any] = {
        # Базовые справочники (ID 1-20)
        1: AvanpostDirLanguageModel,
        2: AvanpostDirContactGroupModel,
        3: AvanpostDirContactLinkTypeModel,
        4: AvanpostDirOperatorModel,
        5: AvanpostDirOwnerModel,
        6: AvanpostDirOwnerMotorCadeModel,
        7: AvanpostDirFileTypeModel,
        8: AvanpostDirContactMsgDirectionTypeModel,
        9: AvanpostDirContactMsgTypeModel,
        10: AvanpostDirContactMsgProcessTypeModel,
        11: AvanpostDirScenarioTypeModel,
        12: AvanpostDirScenarioGroupItemTypeModel,
        13: AvanpostDirUserStatusTypeModel,
        14: AvanpostDirUserContactRoleTypeModel,
        15: AvanpostDirUserLinkContactMsgControlProcessTypeModel,
        16: AvanpostDirScenarioActionTypeModel,
        17: AvanpostDirScenarioActionValueTypeModel,
        # Сценарии действий (ID 101-120)
        101: AvanpostDirScenarioModel,
        102: AvanpostDirScenarioActionModel,
        103: AvanpostDirScenarioActionLangModel,
        104: AvanpostDirScenarioActionValueModel,
        105: AvanpostDirScenarioInstructionModel,
        106: AvanpostDirScenarioInstructionLangModel,
        107: AvanpostDirScenarioCustomModel,
        108: AvanpostDirScenarioGroupModel,
        # Меню действий (ID 201-220)
        201: AvanpostDirScenarioGroupItemModel,
        202: AvanpostDirScenarioGroupItemLangModel,
        203: AvanpostDirScenarioGroupItemLinkScenarioModel,
        204: AvanpostDirScenarioGroupItemLinkScenarioGroupModel,
        205: AvanpostDirScenarioGroupItemLinkScenarioInstructionModel,
        # Данные (ID 301-320)
        301: AvanpostContactModel,
        302: AvanpostContactLangModel,
        303: AvanpostContactLinkModel,
        # Данные с пользователями (ID 401-420)
        401: AvanpostUserModel,
        402: AvanpostUserChatModel,
        403: AvanpostUserChatLangModel,
        # Оперативная синхронизация (ID 501-520)
        501: AvanpostMsgModel,
        502: AvanpostContactMsgModel,
        503: AvanpostContactMsgProcessModel,
        504: AvanpostUserStatusModel,
        505: AvanpostUserLinkContactModel,
        506: AvanpostUserMissionModel,
        507: AvanpostUserMissionLangModel,
        508: AvanpostUserMissionItemModel,
        509: AvanpostUserMissionItemLangModel,
        510: AvanpostUserOrderModel,
        511: AvanpostUserOrderLangModel,
        512: AvanpostUserOrderLinkMissionModel,
        513: AvanpostUserVehicleModel,
        514: AvanpostUserLinkChatContactMsgModel,
        515: AvanpostUserLinkContactMsgControlModel,
        # Отложенная синхронизация (ID 601-620)
        601: AvanpostFileModel,
        602: AvanpostLinkMsgFileModel,
        603: AvanpostLinkContactMsgFileModel,
        604: AvanpostDirScenarioInstructionFileModel,
    }

    # Маппинг типа данных -> имя таблицы в main
    DATA_TYPE_MAPPING: dict[int, str] = {
        data_type_id: model.__tablename__ for data_type_id, model in MODEL_MAPPING.items()
    }

    def __init__(self) -> None:
        self._initialized: bool = False
        self._sync_in_progress: bool = False
        self._last_sync_time: datetime | None = None
        self._data_type_cache: dict[int, dict[str, Any]] = {}
        self._stats: dict[str, Any] = {
            "total_syncs": 0,
            "successful_syncs": 0,
            "failed_syncs": 0,
            "last_sync_duration": 0.0,
            "total_records_synced": 0,
        }
        # Кеш для проверки внешних ключей
        self._fk_cache: dict[str, set[Any]] = {}
        self._model_columns_cache: dict[Any, set[str]] = {}

        # Типы данных для синхронизации
        self.base_data_types: list[int] = (
            list(range(1, 18)) + list(range(101, 109)) + list(range(201, 206)) + list(range(301, 304))
        )

        self.user_data_types: list[int] = [
            401,  # Пользователи
            402,  # Чаты
            403,  # Переводы чатов
            504,  # Статусы пользователей
            505,  # Связи пользователей с контактами
            506,  # Задания
            507,  # Переводы заданий
            508,  # Пункты заданий
            509,  # Переводы пунктов
            510,  # Заказы
            511,  # Переводы заказов
            512,  # Cвязи заказов с заданиями
            513,  # Транспорт
        ]

    @property
    def is_initialized(self) -> bool:
        return self._initialized

    @property
    def is_syncing(self) -> bool:
        return self._sync_in_progress

    async def initialize(self, session: AsyncSession | None = None) -> None:
        """Инициализация сервиса"""
        if self._initialized:
            return

        if session is None:
            async with db_manager.get_session() as sess:
                await self._load_data_types(sess)
        else:
            await self._load_data_types(session)

        self._initialized = True
        app_logger.info(f"✅ AvanpostSyncService initialized with {len(self._data_type_cache)} data types")

    async def _load_data_types(self, session: AsyncSession) -> None:
        """Загрузка типов данных в кеш"""
        try:
            stmt = select(AvanpostDirSysDataTypeModel)
            result = await session.execute(stmt)
            records = result.scalars().all()

            for record in records:
                self._data_type_cache[record.FID] = {
                    "name": record.FName,
                    "table": record.FTableName,
                    "user_related": record.FUserRelated,
                    "deferred_sync": record.FDeferredSync,
                }

            app_logger.debug(f"📊 Loaded {len(records)} data types into cache")

        except Exception as e:
            app_logger.error(f"❌ Failed to load data types: {e}")
            raise

    def _get_model_by_data_type(self, data_type_id: int) -> Any:
        """Получение модели по типу данных"""
        return self.MODEL_MAPPING.get(data_type_id)

    def _get_model_columns(self, model: Any) -> set[str]:
        """Получение списка колонок модели"""
        if model not in self._model_columns_cache:
            all_columns = {column.name for column in model.__table__.columns}
            self._model_columns_cache[model] = all_columns
        return self._model_columns_cache[model]

    @staticmethod
    async def _get_sync_times_for_types(
        data_types: list[int],
        user_id: int | None = None,
    ) -> dict[int, datetime]:
        """
        Получение времени синхронизации для списка типов данных.

        Args:
            data_types: Список ID типов данных
            user_id: ID пользователя (если None - используются системные настройки)

        Returns:
            dict[int, datetime]: Словарь {data_type_id: last_sync_time}
        """
        async with db_manager.get_session() as session:
            if user_id is None:
                return await SystemRepository.get_sync_times(session, data_types)
            else:
                return await SystemRepository.get_user_sync_times(session, user_id, data_types)

    @staticmethod
    async def _update_sync_times(
        sync_times: dict[int, datetime],
        user_id: int | None = None,
    ) -> None:
        """
        Обновление времени синхронизации для типов данных.

        Args:
            sync_times: Словарь {data_type_id: sync_time}
            user_id: ID пользователя (если None - системные настройки)
        """
        if not sync_times:
            return

        async with db_manager.get_session() as session:
            if user_id is None:
                await SystemRepository.update_sync_times_bulk(session, sync_times)
            else:
                await SystemRepository.update_user_sync_times_bulk(session, user_id, sync_times)

    @staticmethod
    async def delete_records_bulk(
        session: AsyncSession,
        model: Any,
        records: list[dict[str, Any]] | dict[str, Any],
        primary_keys: list[str],
    ) -> int:
        """Массовое удаление записей по первичному ключу."""
        if not records:
            return 0

        if isinstance(records, dict):
            records_list: list[dict[str, Any]] = [records]
        elif isinstance(records, list):
            records_list = records
        else:
            return 0

        delete_conditions: list[Any] = []
        for record in records_list:
            if not isinstance(record, dict):
                continue
            if all(pk in record for pk in primary_keys):
                if len(primary_keys) == 1:
                    delete_conditions.append(record[primary_keys[0]])
                else:
                    delete_conditions.append(tuple(record[pk] for pk in primary_keys))
            else:
                app_logger.warning(f"⚠️ Record missing primary key fields: {record}")

        if not delete_conditions:
            return 0

        stmt = delete(model)
        if len(primary_keys) == 1:
            pk_col = getattr(model, primary_keys[0])
            stmt = stmt.where(pk_col.in_(delete_conditions))
        else:
            from sqlalchemy import or_

            conditions = []
            for pk_tuple in delete_conditions:
                cond = and_(*[getattr(model, pk) == value for pk, value in zip(primary_keys, pk_tuple, strict=False)])
                conditions.append(cond)
            stmt = stmt.where(or_(*conditions))

        result = await session.execute(stmt)
        rowcount_raw = result.rowcount if hasattr(result, "rowcount") else 0
        rowcount: int = int(rowcount_raw) if rowcount_raw is not None else 0
        return rowcount

    async def save_data_bulk(
        self,
        session: AsyncSession,
        model: Any,
        records: list[dict[str, Any]] | dict[str, Any],
        model_columns: set[str],
        force_delete: bool = False,
    ) -> tuple[int, int, int, int, int]:
        """
        Массовое сохранение данных с использованием UPSERT.

        Returns:
            tuple[int, int, int, int, int]: (inserted, updated, unchanged, skipped_upsert, skipped_delete)
            - inserted: реально вставлены (новые записи)
            - updated: реально обновлены (данные изменились)
            - unchanged: получены, но данные не изменились (пропущены)
            - skipped_upsert: не вставлены/не обновлены из-за ошибок
            - skipped_delete: не найдены для удаления
        """
        if not records:
            return 0, 0, 0, 0, 0

        if isinstance(records, dict):
            records_list = [records]
        elif isinstance(records, list):
            records_list = records
        else:
            app_logger.warning(f"⚠️ Unexpected records type: {type(records)}")
            return 0, 0, 0, 0, 0

        # Удаление всех записей, если force_delete = True
        if force_delete:
            app_logger.debug(f"🗑️ Force delete all {len(records_list)} records from {model.__tablename__}")
            primary_keys = [col.name for col in model.__table__.primary_key.columns]
            if primary_keys:
                delete_records = []
                for rec in records_list:
                    if isinstance(rec, dict) and "FID" in rec:
                        delete_records.append({"FID": rec["FID"]})

                if delete_records:
                    deleted = await self.delete_records_bulk(session, model, delete_records, primary_keys)
                    skipped_delete = len(delete_records) - deleted
                    app_logger.debug(
                        f"🗑️ Deleted {deleted} records from {model.__tablename__} (skipped_delete: {skipped_delete})"
                    )
                    return 0, 0, 0, 0, skipped_delete
            return 0, 0, 0, 0, len(records_list)

        # Разделение на DELETE и UPSERT
        delete_records = []
        upsert_records = []

        for rec in records_list:
            if not isinstance(rec, dict):
                continue

            flag_expire = rec.get("FlagExpire")
            rec_keys = set(rec.keys())
            data_keys = rec_keys - {"FlagExpire", "SyncTime"}
            is_delete_signal = data_keys == {"FID"}

            if flag_expire == 1 or flag_expire is True or is_delete_signal:
                delete_records.append(rec)
            else:
                clean_record = {}
                for col in model_columns:
                    clean_record[col] = rec.get(col)
                if clean_record:
                    upsert_records.append(clean_record)

        app_logger.debug(f"📊 {model.__tablename__}: DELETE={len(delete_records)}, UPSERT={len(upsert_records)}")

        total_skipped_delete = 0
        total_inserted = 0
        total_updated = 0
        total_unchanged = 0
        total_skipped_upsert = 0

        # Обработка DELETE
        if delete_records:
            primary_keys = [col.name for col in model.__table__.primary_key.columns]
            if primary_keys:
                deleted = await self.delete_records_bulk(session, model, delete_records, primary_keys)
                skipped_delete = len(delete_records) - deleted
                total_skipped_delete = skipped_delete
                app_logger.debug(
                    f"🗑️ Deleted {deleted} records from {model.__tablename__} (skipped_delete: {skipped_delete})"
                )
            else:
                app_logger.warning(f"⚠️ No primary key for {model.__tablename__}, cannot delete")
                total_skipped_delete = len(delete_records)

        # Обработка UPSERT
        if upsert_records:
            app_logger.debug(f"💾 Processing {len(upsert_records)} records to {model.__tablename__}")

            table_name = model.__tablename__
            if table_name == "TAvanpostContactsLinks":
                for rec in upsert_records:
                    if "FK_Operator" in rec:
                        if hasattr(rec["FK_Operator"], "value"):
                            rec["FK_Operator"] = rec["FK_Operator"].value
                        elif hasattr(rec["FK_Operator"], "__int__"):
                            try:
                                rec["FK_Operator"] = int(rec["FK_Operator"])
                            except (ValueError, TypeError):
                                rec["FK_Operator"] = None

            primary_keys = [col.name for col in model.__table__.primary_key.columns]
            if not primary_keys:
                app_logger.warning(f"⚠️ No primary key found for {model.__tablename__}, using all columns")
                primary_keys = list(upsert_records[0].keys())

            # Получение существующих записей для сравнения
            existing_records = {}
            existing_ids = set()
            if len(primary_keys) == 1:
                # Для простого ключа
                pk_col = getattr(model, primary_keys[0])
                pk_values = [rec.get(primary_keys[0]) for rec in upsert_records if rec.get(primary_keys[0]) is not None]

                if pk_values:
                    stmt = select(model).where(pk_col.in_(pk_values))
                    result = await session.execute(stmt)
                    db_records = result.scalars().all()
                    for db_rec in db_records:
                        pk_val = getattr(db_rec, primary_keys[0])
                        existing_records[pk_val] = db_rec
                existing_ids = set(existing_records.keys())
            else:
                # Создание словара с составным ключом для составного ключа
                stmt = select(model)
                result = await session.execute(stmt)
                db_records = result.scalars().all()

                # Индексирование по составному ключу
                for db_rec in db_records:
                    key = tuple(getattr(db_rec, pk) for pk in primary_keys)
                    existing_records[key] = db_rec

            # Разделение на INSERT, UPDATE и UNCHANGED
            insert_records = []
            update_records = []
            unchanged_records = []

            for rec in upsert_records:
                if len(primary_keys) == 1:
                    # === ПРОСТОЙ КЛЮЧ ===
                    pk_val = rec.get(primary_keys[0])
                    if pk_val is not None and pk_val in existing_ids:
                        db_rec = existing_records.get(pk_val)
                        if db_rec:
                            has_changes = False

                            for col in model_columns:
                                if col in primary_keys:
                                    continue
                                new_val = rec.get(col)
                                old_val = getattr(db_rec, col, None)

                                # Нормализация для сравнения
                                if isinstance(new_val, str) and isinstance(old_val, str):
                                    new_val = new_val.strip()
                                    old_val = old_val.strip()
                                elif isinstance(new_val, int) and isinstance(old_val, int):
                                    pass
                                elif new_val is None and old_val is None:
                                    continue

                                if new_val != old_val:
                                    has_changes = True
                                    break

                            if has_changes:
                                update_records.append(rec)
                            else:
                                unchanged_records.append(rec)
                        else:
                            insert_records.append(rec)
                    else:
                        insert_records.append(rec)
                else:
                    # === СОСТАВНОЙ КЛЮЧ ===
                    # Создание ключа из всех полей primary key
                    pk_tuple = tuple(rec.get(pk) for pk in primary_keys)

                    # Проверка, есть ли запись в existing_records
                    db_rec = existing_records.get(pk_tuple)

                    if db_rec:
                        has_changes = False

                        for col in model_columns:
                            if col in primary_keys:
                                continue
                            new_val = rec.get(col)
                            old_val = getattr(db_rec, col, None)

                            # Нормализация для сравнения
                            if isinstance(new_val, str) and isinstance(old_val, str):
                                new_val = new_val.strip()
                                old_val = old_val.strip()
                            elif isinstance(new_val, int) and isinstance(old_val, int):
                                pass
                            elif new_val is None and old_val is None:
                                continue

                            if new_val != old_val:
                                has_changes = True
                                break

                        if has_changes:
                            update_records.append(rec)
                        else:
                            unchanged_records.append(rec)
                    else:
                        insert_records.append(rec)

            app_logger.debug(
                f"📊 {table_name}: INSERT={len(insert_records)}, UPDATE={len(update_records)}, UNCHANGED={len(unchanged_records)}"
            )

            # Выполнение INSERT для новых записей
            if insert_records:
                batch_size = 1000
                for i in range(0, len(insert_records), batch_size):
                    batch = insert_records[i : i + batch_size]
                    try:
                        stmt = insert(model).values(batch)
                        if len(primary_keys) == 1:
                            stmt = stmt.on_conflict_do_nothing(index_elements=primary_keys)
                        await session.execute(stmt)
                        total_inserted += len(batch)
                    except Exception as e:
                        app_logger.warning(f"⚠️ INSERT failed for batch: {e}")
                        total_skipped_upsert += len(batch)
                app_logger.debug(f"✅ INSERT {len(insert_records)} new records to {table_name}")

            # Выполнение UPDATE для изменившихся записей
            if update_records:
                batch_size = 1000
                for i in range(0, len(update_records), batch_size):
                    batch = update_records[i : i + batch_size]

                    stmt = insert(model).values(batch)
                    update_fields = [col for col in batch[0] if col not in primary_keys]

                    if update_fields:
                        stmt = stmt.on_conflict_do_update(
                            index_elements=primary_keys,
                            set_={col: getattr(stmt.excluded, col) for col in update_fields},
                        )
                    else:
                        stmt = stmt.on_conflict_do_nothing()

                    try:
                        await session.execute(stmt)
                        total_updated += len(batch)
                    except Exception as e:
                        app_logger.warning(f"⚠️ UPDATE failed for batch: {e}")
                        total_skipped_upsert += len(batch)
                app_logger.debug(f"🔄 UPDATE {len(update_records)} existing records in {table_name}")

            # Записи без изменений - считаем пропущенными
            if unchanged_records:
                total_unchanged = len(unchanged_records)
                app_logger.debug(f"⏭️ UNCHANGED {len(unchanged_records)} records in {table_name} (no data changes)")

        return total_inserted, total_updated, total_unchanged, total_skipped_upsert, total_skipped_delete

    # ==================== СИНХРОНИЗАЦИЯ БАЗОВЫХ ДАННЫХ ====================

    async def sync_base_data(self, force: bool = False) -> SyncStatistics:
        """Синхронизация базовых данных с детальной статистикой"""
        stats = SyncStatistics()
        stats.start()
        stats.total_data_types = len(self.base_data_types)

        app_logger.info("🔄 Starting base data synchronization...")

        try:
            # Получение времени синхронизация для каждого типа данных
            last_sync_by_type = await self._get_sync_times_for_types(self.base_data_types)

            # Минимальное время для обратной совместимости
            min_last_sync = min(last_sync_by_type.values()) if last_sync_by_type else None

            if min_last_sync:
                app_logger.info(f"📅 Min last sync time: {min_last_sync.isoformat()}")
            else:
                app_logger.info("📅 No previous sync time found, using default")

            # Разбитие типов на группы по 10 для обхода ограничений
            chunk_size = 10
            chunks = [self.base_data_types[i : i + chunk_size] for i in range(0, len(self.base_data_types), chunk_size)]

            app_logger.debug(f"📊 Split {len(self.base_data_types)} types into {len(chunks)} chunks")

            all_data_items: list[dict[str, Any]] = []
            all_requested_types: set[int] = set()

            for idx, chunk in enumerate(chunks):
                app_logger.info(f"📦 Processing chunk {idx + 1}/{len(chunks)} with {len(chunk)} types...")

                # Запоминание типов из этого чанка
                all_requested_types.update(chunk)

                chunk_min_time = None
                for dt_id in chunk:
                    if dt_id in last_sync_by_type:
                        sync_time = last_sync_by_type[dt_id]
                        if chunk_min_time is None or sync_time < chunk_min_time:
                            chunk_min_time = sync_time

                app_logger.debug(
                    f"📅 Chunk {idx + 1} min sync time: {chunk_min_time.isoformat() if chunk_min_time else 'None'}"
                )

                async with db_manager.get_session("avanpost") as session:
                    result = await AvanpostRepository.call_base_data_procedure(
                        session=session,
                        data_types=chunk,
                        last_sync=chunk_min_time,
                        force=force,
                    )

                if result and "Data" in result:
                    data_items = result["Data"]
                    if isinstance(data_items, list):
                        all_data_items.extend(data_items)
                        app_logger.info(f"✅ Chunk {idx + 1}: got {len(data_items)} items")
                    else:
                        app_logger.warning(f"⚠️ Chunk {idx + 1}: unexpected data type: {type(data_items)}")
                else:
                    app_logger.warning(f"⚠️ Chunk {idx + 1}: no data")

            app_logger.debug(f"📊 Total collected: {len(all_data_items)} items")

            # Обновление времени для всех запрошенных типов

            current_time = datetime_now()
            sync_times: dict[int, datetime] = {}

            for dt_id in all_requested_types:
                sync_times[dt_id] = current_time

            if all_data_items:
                # Отображение порядка из JSON
                if settings.is_development:
                    app_logger.debug("=" * 80)
                    app_logger.debug("📋 ORDER FROM JSON (as received from Avanpost)")
                    app_logger.debug("=" * 80)

                    for idx, data_item in enumerate(all_data_items, 1):
                        data_type_raw = data_item.get("DataTypeId")
                        flag_expire = data_item.get("FlagExpire")
                        records = data_item.get("Data", [])

                        if data_type_raw is not None:
                            data_type_id = data_type_raw
                            model = self._get_model_by_data_type(data_type_id)
                            model_name = (model.__name__ if model else "UNKNOWN") or "UNKNOWN"
                            table_name = self.DATA_TYPE_MAPPING.get(data_type_id, "UNKNOWN")
                        else:
                            model_name = "UNKNOWN"
                            table_name = "UNKNOWN"

                        records_count = len(records) if isinstance(records, list) else 1 if records else 0

                        app_logger.debug(
                            f"  {idx:3d}. DataTypeId: {str(data_type_raw) if data_type_raw is not None else 'None':>3} | "
                            f"FlagExpire: {flag_expire} | "
                            f"Model: {model_name:35s} | "
                            f"Table: {table_name:40s} | "
                            f"Records: {records_count:4d}"
                        )

                    app_logger.debug("=" * 80)

                # Деление на DELETE И UPSERT
                delete_records_by_table: dict[str, list[dict[str, Any]]] = {}
                upsert_records_by_table: dict[str, list[dict[str, Any]]] = {}
                delete_order: list[str] = []
                upsert_order: list[str] = []
                data_type_for_table: dict[str, int] = {}

                for data_item in all_data_items:
                    if not isinstance(data_item, dict):
                        app_logger.warning(f"⚠️ data_item is not dict: {type(data_item)}")
                        continue

                    data_type_raw = data_item.get("DataTypeId")
                    if data_type_raw is None:
                        app_logger.warning("⚠️ DataTypeId is None")
                        continue

                    data_type_id = data_type_raw
                    if data_type_id not in self.base_data_types:
                        app_logger.warning(f"⚠️ Skipping {data_type_id} (not in base_data_types)")
                        continue

                    records = data_item.get("Data")
                    if not records:
                        continue

                    table_name = self.DATA_TYPE_MAPPING.get(data_type_id) or "UNKNOWN"
                    if table_name == "UNKNOWN":
                        app_logger.warning(f"⚠️ No table mapping for DataTypeId {data_type_id}")
                        continue

                    flag_expire = data_item.get("FlagExpire")
                    data_type_for_table[table_name] = data_type_id

                    if flag_expire == 1 or flag_expire is True:
                        if table_name not in delete_records_by_table:
                            delete_records_by_table[table_name] = []
                            delete_order.append(table_name)

                        if isinstance(records, list):
                            delete_records_by_table[table_name].extend(records)
                        else:
                            delete_records_by_table[table_name].append(records)

                        app_logger.debug(
                            f"📊 {table_name}: added {len(records) if isinstance(records, list) else 1} DELETE records"
                        )
                    else:
                        if table_name not in upsert_records_by_table:
                            upsert_records_by_table[table_name] = []
                            upsert_order.append(table_name)

                        if isinstance(records, list):
                            upsert_records_by_table[table_name].extend(records)
                        else:
                            upsert_records_by_table[table_name].append(records)

                        app_logger.debug(
                            f"📊 {table_name}: added {len(records) if isinstance(records, list) else 1} UPSERT records"
                        )

                # Добавление информации о полученных записях
                for table_name in set(delete_order) | set(upsert_order):
                    upsert_count = len(upsert_records_by_table.get(table_name, []))
                    delete_count = len(delete_records_by_table.get(table_name, []))
                    stats.add_received(table_name, upsert_count, delete_count)

                # Удаление (DELETE)
                async with db_manager.get_session() as session:
                    for table_name in delete_order:
                        records = delete_records_by_table[table_name]
                        data_type_id = data_type_for_table.get(table_name)

                        if data_type_id is None:
                            app_logger.warning(f"⚠️ No data type ID found for table {table_name}, skipping")
                            continue

                        if not records:
                            continue

                        model = self._get_model_by_data_type(data_type_id)
                        if not model:
                            app_logger.warning(f"⚠️ No model found for DataTypeId {data_type_id}")
                            continue

                        model_columns = self._get_model_columns(model)

                        try:
                            inserted, updated, unchanged, skipped_upsert, skipped_delete = await self.save_data_bulk(
                                session,
                                model,
                                records,
                                model_columns,
                                force_delete=True,
                            )
                            stats.processed_data_types += 1
                            if inserted > 0:
                                stats.add_insert(table_name, inserted)
                            if updated > 0:
                                stats.add_update(table_name, updated)
                            if unchanged > 0:
                                stats.add_unchanged(table_name, unchanged)
                            if skipped_upsert > 0:
                                stats.add_skip_upsert(table_name, skipped_upsert)
                            if skipped_delete > 0:
                                stats.add_skip_delete(table_name, skipped_delete)
                            app_logger.debug(
                                f"🗑️ DELETE result for {table_name}: inserted={inserted}, updated={updated}, unchanged={unchanged}, skipped_upsert={skipped_upsert}, skipped_delete={skipped_delete}"
                            )
                        except Exception as e:
                            stats.add_error(table_name, str(e))
                            app_logger.error(f"❌ Failed to DELETE from {table_name}: {e}")
                            await session.rollback()

                # Вставка/обновление (UPSERT)
                async with db_manager.get_session() as session:
                    for table_name in upsert_order:
                        records = upsert_records_by_table[table_name]
                        data_type_id = data_type_for_table.get(table_name)

                        if data_type_id is None:
                            app_logger.warning(f"⚠️ No data type ID found for table {table_name}, skipping")
                            continue

                        if not records:
                            continue

                        model = self._get_model_by_data_type(data_type_id)
                        if not model:
                            app_logger.warning(f"⚠️ No model found for DataTypeId {data_type_id}")
                            continue

                        # Фильтр записей с NULL в обязательных полях
                        required_fields = [col.name for col in model.__table__.columns if not col.nullable]

                        filtered_records = []
                        for rec in records:
                            has_null = False
                            for req_field in required_fields:
                                if rec.get(req_field) is None and req_field in rec and rec[req_field] is None:
                                    has_null = True
                                    break
                            if not has_null:
                                filtered_records.append(rec)

                        if len(filtered_records) < len(records):
                            stats.add_skip_upsert(table_name, len(records) - len(filtered_records))
                            app_logger.warning(
                                f"⚠️ Filtered out {len(records) - len(filtered_records)} records with NULL in required fields "
                                f"from {table_name}"
                            )

                        if not filtered_records:
                            continue

                        model_columns = self._get_model_columns(model)

                        # Вызов save_data_bulk
                        try:
                            inserted, updated, unchanged, skipped_upsert, skipped_delete = await self.save_data_bulk(
                                session,
                                model,
                                filtered_records,
                                model_columns,
                                force_delete=False,
                            )
                            stats.processed_data_types += 1
                            if inserted > 0:
                                stats.add_insert(table_name, inserted)
                            if updated > 0:
                                stats.add_update(table_name, updated)
                            if unchanged > 0:
                                stats.add_unchanged(table_name, unchanged)
                            if skipped_upsert > 0:
                                stats.add_skip_upsert(table_name, skipped_upsert)
                            if skipped_delete > 0:
                                stats.add_skip_delete(table_name, skipped_delete)

                            app_logger.debug(
                                f"✅ UPSERT result for {table_name}: inserted={inserted}, updated={updated}, unchanged={unchanged}, skipped_upsert={skipped_upsert}, skipped_delete={skipped_delete}"
                            )
                        except Exception as e:
                            stats.add_error(table_name, str(e))
                            app_logger.error(f"❌ Failed to UPSERT {table_name}: {e}")
                            await session.rollback()

                app_logger.info("✅ Base data synchronization completed")
            else:
                app_logger.debug("ℹ️ No data received from procedure")

            # Обновление времени для всех запрошенных типов

            if sync_times:
                await self._update_sync_times(sync_times)
                app_logger.info(f"✅ Updated sync times for {len(sync_times)} data types (all requested)")

                # Вывод предупреждения, если какие-то типы не получили данные
                received_types = set()
                for data_item in all_data_items:
                    data_type_raw = data_item.get("DataTypeId")
                    if data_type_raw is not None:
                        received_types.add(data_type_raw)

                missing_types = all_requested_types - received_types
                if missing_types:
                    app_logger.warning(
                        f"⚠️ No data received for types: {sorted(missing_types)}, "
                        f"but sync times were updated to {current_time}"
                    )
            else:
                app_logger.debug("ℹ️ No types requested, skipping sync time update")

            stats.finish()

            # Вывод отчета только если есть изменения или ошибки
            stats.print_report("Base Data Sync Report")
            return stats

        except Exception as e:
            stats.add_error("__global__", str(e))
            stats.finish()
            # Вывод ошибки
            stats.print_report("Base Data Sync Report")
            app_logger.error(f"❌ Failed to sync base data: {e}")
            import traceback

            app_logger.error(f"📄 Traceback: {traceback.format_exc()}")
            raise

    # ==================== СИНХРОНИЗАЦИЯ ДАННЫХ ПОЛЬЗОВАТЕЛЯ ====================

    async def sync_user_data(self, user_id: int, force: bool = False) -> SyncStatistics:
        """Синхронизация данных пользователя с детальной статистикой"""
        stats = SyncStatistics()
        stats.start()
        stats.total_data_types = len(self.user_data_types)

        app_logger.info(f"🔄 Starting user data synchronization for user {user_id}...")
        app_logger.debug(f"📊 Will sync {len(self.user_data_types)} data types: {self.user_data_types}")

        try:
            # Получение времени синхронизация для каждого типа данных
            last_sync_by_type = await self._get_sync_times_for_types(self.user_data_types, user_id)

            min_last_sync = min(last_sync_by_type.values()) if last_sync_by_type else None

            if min_last_sync:
                app_logger.info(f"📅 Min user sync time: {min_last_sync.isoformat()}")
            else:
                app_logger.info("📅 No previous user sync time found, using default")

            chunk_size = 10
            chunks = [self.user_data_types[i : i + chunk_size] for i in range(0, len(self.user_data_types), chunk_size)]

            app_logger.debug(f"📊 Split {len(self.user_data_types)} user types into {len(chunks)} chunks")

            all_data_items: list[dict[str, Any]] = []
            all_requested_types: set[int] = set()

            for idx, chunk in enumerate(chunks):
                app_logger.info(f"📦 Processing user chunk {idx + 1}/{len(chunks)} with {len(chunk)} types...")

                all_requested_types.update(chunk)

                chunk_min_time = None
                for dt_id in chunk:
                    if dt_id in last_sync_by_type:
                        sync_time = last_sync_by_type[dt_id]
                        if chunk_min_time is None or sync_time < chunk_min_time:
                            chunk_min_time = sync_time

                app_logger.debug(
                    f"📅 User chunk {idx + 1} min sync time: {chunk_min_time.isoformat() if chunk_min_time else 'None'}"
                )

                async with db_manager.get_session("avanpost") as session:
                    result = await AvanpostRepository.call_user_data_procedure(
                        session=session,
                        user_id=user_id,
                        data_types=chunk,
                        last_sync=chunk_min_time,
                        force=force,
                    )

                if result and "Data" in result:
                    data_items = result["Data"]
                    if isinstance(data_items, list):
                        valid_items = []
                        for item in data_items:
                            if isinstance(item, dict) and item.get("DataTypeId") is not None:
                                valid_items.append(item)
                            else:
                                app_logger.warning(f"⚠️ Skipping invalid item: {item}")

                        if valid_items:
                            app_logger.debug(f"📊 Chunk {idx + 1}: received {len(valid_items)} valid data type groups")
                            for item in valid_items:
                                dt_id = item.get("DataTypeId")
                                records = item.get("Data", [])
                                records_count = len(records) if isinstance(records, list) else 1 if records else 0
                                app_logger.debug(f"  └─ DataTypeId {dt_id}: {records_count} records")

                            all_data_items.extend(valid_items)
                            app_logger.info(f"✅ User chunk {idx + 1}: got {len(valid_items)} items")
                        else:
                            app_logger.warning(f"⚠️ User chunk {idx + 1}: no valid items")
                    else:
                        app_logger.warning(f"⚠️ User chunk {idx + 1}: unexpected data type: {type(data_items)}")
                else:
                    app_logger.warning(f"⚠️ User chunk {idx + 1}: no data")

            app_logger.debug(f"📊 Total user data collected: {len(all_data_items)} items")

            current_time = datetime_now()
            sync_times: dict[int, datetime] = {}

            for dt_id in all_requested_types:
                sync_times[dt_id] = current_time

            if all_data_items:
                # Отображение порядка из JSON
                if settings.is_development:
                    app_logger.debug("=" * 80)
                    app_logger.debug("📋 ORDER FROM JSON (as received from Avanpost) - USER")
                    app_logger.debug("=" * 80)

                    for idx, data_item in enumerate(all_data_items, 1):
                        data_type_raw = data_item.get("DataTypeId")
                        flag_expire = data_item.get("FlagExpire")
                        records = data_item.get("Data", [])

                        if data_type_raw is not None:
                            data_type_id = data_type_raw
                            model = self._get_model_by_data_type(data_type_id)
                            model_name = (model.__name__ if model else "UNKNOWN") or "UNKNOWN"
                            table_name = self.DATA_TYPE_MAPPING.get(data_type_id, "UNKNOWN")
                        else:
                            model_name = "UNKNOWN"
                            table_name = "UNKNOWN"

                        records_count = len(records) if isinstance(records, list) else 1 if records else 0

                        app_logger.debug(
                            f"  {idx:3d}. DataTypeId: {str(data_type_raw) if data_type_raw is not None else 'None':>3} | "
                            f"FlagExpire: {flag_expire} | "
                            f"Model: {model_name:35s} | "
                            f"Table: {table_name:40s} | "
                            f"Records: {records_count:4d}"
                        )

                    app_logger.debug("=" * 80)

                # Деление на DELETE и UPSERT
                # FlagExpire на уровне DataTypeId - ЕДИНСТВЕННЫЙ сигнал на удаление
                delete_records_by_table: dict[str, list[dict[str, Any]]] = {}
                upsert_records_by_table: dict[str, list[dict[str, Any]]] = {}
                delete_order: list[str] = []
                upsert_order: list[str] = []
                data_type_for_table: dict[str, int] = {}

                for data_item in all_data_items:
                    if not isinstance(data_item, dict):
                        app_logger.warning(f"⚠️ data_item is not dict: {type(data_item)}")
                        continue

                    data_type_raw = data_item.get("DataTypeId")
                    if data_type_raw is None:
                        app_logger.warning("⚠️ DataTypeId is None")
                        continue

                    data_type_id = data_type_raw
                    if data_type_id not in self.user_data_types:
                        app_logger.warning(f"⚠️ Skipping {data_type_id} (not in user_data_types)")
                        continue

                    records = data_item.get("Data")
                    if not records:
                        continue

                    table_name = self.DATA_TYPE_MAPPING.get(data_type_id) or "UNKNOWN"
                    if table_name == "UNKNOWN":
                        app_logger.warning(f"⚠️ No table mapping for DataTypeId {data_type_id}")
                        continue

                    # ЕДИНСТВЕННЫЙ сигнал на удаление - FlagExpire на уровне DataTypeId
                    flag_expire = data_item.get("FlagExpire", False)
                    data_type_for_table[table_name] = data_type_id

                    if flag_expire == 1 or flag_expire is True:
                        # ВСЕ записи этого типа идут на УДАЛЕНИЕ
                        if table_name not in delete_records_by_table:
                            delete_records_by_table[table_name] = []
                            delete_order.append(table_name)

                        if isinstance(records, list):
                            delete_records_by_table[table_name].extend(records)
                        else:
                            delete_records_by_table[table_name].append(records)

                        app_logger.debug(
                            f"📊 {table_name}: added {len(records) if isinstance(records, list) else 1} DELETE records (FlagExpire={flag_expire})"
                        )
                    else:
                        # ВСЕ записи этого типа идут на ВСТАВКУ/ОБНОВЛЕНИЕ
                        if table_name not in upsert_records_by_table:
                            upsert_records_by_table[table_name] = []
                            upsert_order.append(table_name)

                        if isinstance(records, list):
                            upsert_records_by_table[table_name].extend(records)
                        else:
                            upsert_records_by_table[table_name].append(records)

                        app_logger.debug(
                            f"📊 {table_name}: added {len(records) if isinstance(records, list) else 1} UPSERT records"
                        )

                # Добавление информации о полученных записях
                for table_name in set(delete_order) | set(upsert_order):
                    upsert_count = len(upsert_records_by_table.get(table_name, []))
                    delete_count = len(delete_records_by_table.get(table_name, []))
                    stats.add_received(table_name, upsert_count, delete_count)

                # Удаление (DELETE)
                for table_name in delete_order:
                    records = delete_records_by_table[table_name]
                    data_type_id = data_type_for_table.get(table_name)

                    if data_type_id is None or not records:
                        continue

                    model = self._get_model_by_data_type(data_type_id)
                    if not model:
                        continue

                    model_columns = self._get_model_columns(model)

                    async with db_manager.get_session() as session:
                        try:
                            inserted, updated, unchanged, skipped_upsert, skipped_delete = await self.save_data_bulk(
                                session,
                                model,
                                records,
                                model_columns,
                                force_delete=True,
                            )
                            stats.processed_data_types += 1
                            if inserted > 0:
                                stats.add_insert(table_name, inserted)
                            if updated > 0:
                                stats.add_update(table_name, updated)
                            if unchanged > 0:
                                stats.add_unchanged(table_name, unchanged)
                            if skipped_upsert > 0:
                                stats.add_skip_upsert(table_name, skipped_upsert)
                            if skipped_delete > 0:
                                stats.add_skip_delete(table_name, skipped_delete)
                            app_logger.debug(
                                f"🗑️ DELETE result for {table_name}: inserted={inserted}, updated={updated}, unchanged={unchanged}, skipped_upsert={skipped_upsert}, skipped_delete={skipped_delete}"
                            )
                            await session.commit()
                        except Exception as e:
                            stats.add_error(table_name, str(e))
                            app_logger.error(f"❌ Failed to DELETE from {table_name}: {e}")
                            await session.rollback()

                # Вставка/обновление (UPSERT)
                for table_name in upsert_order:
                    records = upsert_records_by_table[table_name]
                    data_type_id = data_type_for_table.get(table_name)

                    if data_type_id is None or not records:
                        continue

                    model = self._get_model_by_data_type(data_type_id)
                    if not model:
                        continue

                    model_columns = self._get_model_columns(model)

                    async with db_manager.get_session() as session:
                        try:
                            required_fields = [col.name for col in model.__table__.columns if not col.nullable]

                            filtered_records = []
                            for rec in records:
                                if not isinstance(rec, dict):
                                    continue
                                has_null = False
                                for req_field in required_fields:
                                    if req_field in rec and rec[req_field] is None:
                                        has_null = True
                                        break
                                if not has_null:
                                    filtered_records.append(rec)

                            if len(filtered_records) < len(records):
                                stats.add_skip_upsert(table_name, len(records) - len(filtered_records))
                                app_logger.warning(
                                    f"⚠️ Filtered out {len(records) - len(filtered_records)} records with NULL in required fields "
                                    f"from {table_name} (user {user_id})"
                                )

                            if not filtered_records:
                                continue

                            inserted, updated, unchanged, skipped_upsert, skipped_delete = await self.save_data_bulk(
                                session,
                                model,
                                filtered_records,
                                model_columns,
                                force_delete=False,
                            )
                            stats.processed_data_types += 1
                            if inserted > 0:
                                stats.add_insert(table_name, inserted)
                            if updated > 0:
                                stats.add_update(table_name, updated)
                            if unchanged > 0:
                                stats.add_unchanged(table_name, unchanged)
                            if skipped_upsert > 0:
                                stats.add_skip_upsert(table_name, skipped_upsert)
                            if skipped_delete > 0:
                                stats.add_skip_delete(table_name, skipped_delete)

                            app_logger.debug(
                                f"✅ UPSERT result for {table_name}: inserted={inserted}, updated={updated}, unchanged={unchanged}, skipped_upsert={skipped_upsert}, skipped_delete={skipped_delete}"
                            )
                            await session.commit()
                        except Exception as e:
                            stats.add_error(table_name, str(e))
                            app_logger.error(f"❌ Failed to UPSERT {table_name} for user {user_id}: {e}")
                            await session.rollback()

                app_logger.info(f"✅ User data synchronization completed for user {user_id}")
            else:
                app_logger.debug("ℹ️ No user data received from procedure")

            # Обновление времени для всех запрошенных типов
            if sync_times:
                await self._update_sync_times(sync_times, user_id)
                app_logger.info(f"✅ Updated user sync times for {len(sync_times)} data types (all requested)")

                received_types = set()
                for data_item in all_data_items:
                    data_type_raw = data_item.get("DataTypeId")
                    if data_type_raw is not None:
                        received_types.add(data_type_raw)

                missing_types = all_requested_types - received_types
                if missing_types:
                    app_logger.warning(
                        f"⚠️ No data received for user {user_id} types: {sorted(missing_types)}, "
                        f"but sync times were updated to {current_time}"
                    )
            else:
                app_logger.debug(f"ℹ️ No types requested for user {user_id}, skipping sync time update")

            stats.finish()
            stats.print_report(f"User Data Sync Report (User {user_id})", force=True)
            return stats

        except Exception as e:
            stats.add_error("__global__", str(e))
            stats.finish()
            stats.print_report(f"User Data Sync Report (User {user_id})", force=True)
            app_logger.error(f"❌ Failed to sync user data for user {user_id}: {e}")
            import traceback

            app_logger.error(f"📄 Traceback: {traceback.format_exc()}")
            raise

    # ==================== СИНХРОНИЗАЦИЯ ВСЕХ ПОЛЬЗОВАТЕЛЕЙ ====================

    async def sync_all_users(self, force: bool = False) -> dict[str, Any]:
        """Синхронизация всех пользователей с агрегированной статистикой."""
        app_logger.info("🔄 Starting all users synchronization...")

        async with db_manager.get_session() as session:
            result = await session.execute(select(AvanpostUserModel))
            users = result.scalars().all()

            app_logger.info(f"👥 Found {len(users)} users to sync")

            # Использование отдельных переменных вместо словаря
            total_users = len(users)
            successful = 0
            failed = 0
            total_inserted = 0
            total_updated = 0
            total_deleted = 0
            total_unchanged = 0
            total_skipped_upsert = 0
            total_skipped_delete = 0
            total_received = 0
            total_received_upsert = 0
            total_received_delete = 0
            errors_list: list[str] = []

            for idx, user in enumerate(users, 1):
                app_logger.info(f"📦 Processing user {idx}/{total_users} (ID: {user.FID})...")
                try:
                    stats = await self.sync_user_data(user.FID, force)
                    successful += 1

                    stats_dict = stats.to_dict() if hasattr(stats, "to_dict") else {}
                    total_inserted += int(stats_dict.get("total_inserted", 0))
                    total_updated += int(stats_dict.get("total_updated", 0))
                    total_deleted += int(stats_dict.get("total_deleted", 0))
                    total_unchanged += int(stats_dict.get("total_unchanged", 0))
                    total_skipped_upsert += int(stats_dict.get("total_skipped_upsert", 0))
                    total_skipped_delete += int(stats_dict.get("total_skipped_delete", 0))
                    total_received += int(stats_dict.get("total_received", 0))
                    total_received_upsert += int(stats_dict.get("total_received_upsert", 0))
                    total_received_delete += int(stats_dict.get("total_received_delete", 0))

                    app_logger.info(
                        f"✅ User {user.FID} completed: "
                        f"inserted={stats_dict.get('total_inserted', 0)}, "
                        f"updated={stats_dict.get('total_updated', 0)}, "
                        f"deleted={stats_dict.get('total_deleted', 0)}"
                    )

                except Exception as e:
                    failed += 1
                    errors_list.append(f"User {user.FID}: {str(e)}")
                    app_logger.error(f"❌ Failed to sync user {user.FID}: {e}")

            # Формирование результата
            result_stats = {
                "total_users": total_users,
                "successful": successful,
                "failed": failed,
                "total_inserted": total_inserted,
                "total_updated": total_updated,
                "total_deleted": total_deleted,
                "total_unchanged": total_unchanged,
                "total_skipped_upsert": total_skipped_upsert,
                "total_skipped_delete": total_skipped_delete,
                "total_received": total_received,
                "total_received_upsert": total_received_upsert,
                "total_received_delete": total_received_delete,
                "errors": errors_list,
            }

            # Вывод агрегированного отчета
            app_logger.info("=" * 80)
            app_logger.info("📊 ALL USERS SYNC REPORT")
            app_logger.info("=" * 80)
            app_logger.info(f"👥 Total users:        {total_users}")
            app_logger.info(f"✅ Successful:         {successful}")
            app_logger.info(f"❌ Failed:             {failed}")
            app_logger.info("-" * 40)
            app_logger.info(f"📥 Received:           {total_received}")
            app_logger.info(f"   └─ Upsert:          {total_received_upsert}")
            app_logger.info(f"   └─ Delete:          {total_received_delete}")
            app_logger.info(f"📝 Inserted:           {total_inserted}")
            app_logger.info(f"🔄 Updated:            {total_updated}")
            app_logger.info(f"🗑️ Deleted:            {total_deleted}")
            app_logger.info(f"⏭️ Unchanged:          {total_unchanged}")
            app_logger.info(f"⏭️ Skipped (Upsert):   {total_skipped_upsert}")
            app_logger.info(f"⏭️ Skipped (Delete):   {total_skipped_delete}")
            if errors_list:
                app_logger.info(f"❌ Errors:             {len(errors_list)}")
                app_logger.info("-" * 40)
                app_logger.info("📝 Error details:")
                for err in errors_list[:5]:
                    app_logger.info(f"   - {err}")
                if len(errors_list) > 5:
                    app_logger.info(f"   ... and {len(errors_list) - 5} more")
            app_logger.info("=" * 80)

            return result_stats

    # ==================== ПОЛНАЯ СИНХРОНИЗАЦИЯ ====================

    async def sync_all(self, force: bool = False) -> dict[str, Any]:
        """Полная синхронизация всех данных."""
        app_logger.info("🔄 Starting full synchronization...")

        # Синхронизация базовых данных
        base_stats = await self.sync_base_data(force)

        # Синхронизация всех пользователей
        user_stats = await self.sync_all_users(force)

        # Безопасное получение значений из base_stats (объект SyncStatistics)
        base_dict = base_stats.to_dict() if hasattr(base_stats, "to_dict") else {}

        base_inserted = int(base_dict.get("total_inserted", 0))
        base_updated = int(base_dict.get("total_updated", 0))
        base_deleted = int(base_dict.get("total_deleted", 0))
        base_unchanged = int(base_dict.get("total_unchanged", 0))
        base_skipped_upsert = int(base_dict.get("total_skipped_upsert", 0))
        base_skipped_delete = int(base_dict.get("total_skipped_delete", 0))

        if isinstance(user_stats, dict):
            user_inserted = int(user_stats.get("total_inserted", 0))
            user_updated = int(user_stats.get("total_updated", 0))
            user_deleted = int(user_stats.get("total_deleted", 0))
            user_unchanged = int(user_stats.get("total_unchanged", 0))
            user_skipped_upsert = int(user_stats.get("total_skipped_upsert", 0))
            user_skipped_delete = int(user_stats.get("total_skipped_delete", 0))
        else:
            # Если user_stats не словарь (например, объект) - получение атрибутов
            user_inserted = int(getattr(user_stats, "total_inserted", 0))
            user_updated = int(getattr(user_stats, "total_updated", 0))
            user_deleted = int(getattr(user_stats, "total_deleted", 0))
            user_unchanged = int(getattr(user_stats, "total_unchanged", 0))
            user_skipped_upsert = int(getattr(user_stats, "total_skipped_upsert", 0))
            user_skipped_delete = int(getattr(user_stats, "total_skipped_delete", 0))

        result = {
            "base_data": base_dict,
            "users": user_stats,
            "total_inserted": base_inserted + user_inserted,
            "total_updated": base_updated + user_updated,
            "total_deleted": base_deleted + user_deleted,
            "total_unchanged": base_unchanged + user_unchanged,
            "total_skipped_upsert": base_skipped_upsert + user_skipped_upsert,
            "total_skipped_delete": base_skipped_delete + user_skipped_delete,
        }

        app_logger.info("✅ Full synchronization completed")
        app_logger.info(
            f"📊 Total: inserted={result['total_inserted']}, "
            f"updated={result['total_updated']}, "
            f"deleted={result['total_deleted']}"
        )

        return result

    # ==================== ВСПОМОГАТЕЛЬНЫЕ МЕТОДЫ ====================

    def clear_fk_cache(self) -> None:
        """Очистка кеша внешних ключей"""
        self._fk_cache.clear()
        app_logger.debug("🧹 FK cache cleared")

    async def get_status(self) -> dict[str, Any]:
        """Получение статуса сервиса"""
        return {
            "initialized": self._initialized,
            "is_syncing": self._sync_in_progress,
            "data_types_cached": len(self._data_type_cache),
            "fk_cache_size": len(self._fk_cache),
            "last_sync": self._last_sync_time.isoformat() if self._last_sync_time else None,
            "stats": self._stats,
        }

    async def health_check(self) -> bool:
        """Проверка здоровья сервиса"""
        return self._initialized and not self._sync_in_progress


avanpost_sync_service = AvanpostSyncService()
