import json
import logging
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, TypeVar

from sqlalchemy.ext.asyncio import AsyncSession

from ..config import settings
from ..db import db_manager
from ..db.repositories import AvanpostRepository, GenericRepository, SystemRepository, UserRepository
from ..logger import app_logger
from ..models import datetime_now
from ..models.avanpost import get_avanpost_model, get_avanpost_table_name

ModelType = TypeVar("ModelType")


# ==================== СТАТИСТИКА СИНХРОНИЗАЦИИ ====================


@dataclass
class SyncStatistics:
    """
    Статистика синхронизации.

    Поля отчета:
        - Recv:         Общее количество записей, полученных от Avanpost
        - DelRecv:      Количество записей, помеченных на удаление
        - Ins:          Количество реально вставленных записей
        - Upd:          Количество реально обновленных записей
        - Del:          Количество реально удаленных записей
        - Err:          Количество записей с ошибками
        - ErrTbl:       Количество таблиц с ошибками
        - UncUpd:       Количество пропущенных при UPSERT
        - UncDel:       Количество пропущенных при DELETE
        - UserOk:       Пользователей успешно
        - UserErr:      Пользователей с ошибками
        - Status:       Общий статус
    """

    # Общие счетчики
    total_data_types: int = 0
    processed_data_types: int = 0
    failed_data_types: int = 0

    # Счетчики по операциям
    tables_with_inserts: set[str] = field(default_factory=set)
    tables_with_updates: set[str] = field(default_factory=set)
    tables_with_deletes: set[str] = field(default_factory=set)
    tables_with_errors: set[str] = field(default_factory=set)
    tables_with_unchanged_upserts: set[str] = field(default_factory=set)
    tables_with_unchanged_deletes: set[str] = field(default_factory=set)

    # Количество записей
    total_inserted: int = 0
    total_updated: int = 0
    total_deleted: int = 0
    total_unchanged_upsert: int = 0
    total_unchanged_delete: int = 0
    total_error_records: int = 0

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
                "error_records": 0,
                "unchanged_upsert": 0,
                "unchanged_delete": 0,
                "received": 0,
                "received_upsert": 0,
                "received_delete": 0,
                "users_ok": 0,
                "users_err": 0,
            }
        )
    )

    # Флаги для отслеживания изменений
    _current_table_has_changes: set[str] = field(default_factory=set)
    _current_table_has_error: set[str] = field(default_factory=set)

    # Ошибки
    error_messages: list[str] = field(default_factory=list)

    # Статистика по пользователям
    total_users_processed: int = 0
    failed_user_ids: list[int] = field(default_factory=list)

    # Время
    start_time: datetime | None = None
    end_time: datetime | None = None

    # Флаг - нужно ли выводить отчет
    _suppress_report: bool = False

    # Текущий пользователь
    _current_user_id: int | None = None

    # ==================== УПРАВЛЕНИЕ ВРЕМЕНЕМ ====================

    def start(self) -> None:
        """Запуск таймера"""
        self.start_time = datetime_now()

    def finish(self) -> None:
        """Остановка таймера"""
        self.end_time = datetime_now()

    def suppress_report(self, value: bool = True) -> None:
        """Управление выводом отчета"""
        self._suppress_report = value

    # ==================== УПРАВЛЕНИЕ ПОЛЬЗОВАТЕЛЯМИ ====================

    def set_current_user(self, user_id: int) -> None:
        """Установка текущего пользователя"""
        self._current_user_id = user_id
        self._current_table_has_changes.clear()
        self._current_table_has_error.clear()

    def finalize_user(self) -> None:
        """Завершение обработки пользователя"""
        if self._current_user_id is None:
            return

        for table_name in self._current_table_has_changes:
            self.table_stats[table_name]["users_ok"] += 1

        for table_name in self._current_table_has_error:
            self.table_stats[table_name]["users_err"] += 1

        self._current_table_has_changes.clear()
        self._current_table_has_error.clear()

    def add_processed_user(self) -> None:
        """Увеличение счетчика обработанных пользователей"""
        self.total_users_processed += 1

    def add_failed_user(self, user_id: int) -> None:
        """Добавление ID пользователя с ошибкой"""
        if user_id not in self.failed_user_ids:
            self.failed_user_ids.append(user_id)

    def _mark_table_change(self, table_name: str) -> None:
        """Отметка изменений в таблице для текущего пользователя"""
        if self._current_user_id:
            self._current_table_has_changes.add(table_name)

    def _mark_table_error(self, table_name: str) -> None:
        """Отметка ошибки в таблице для текущего пользователя"""
        if self._current_user_id:
            self._current_table_has_error.add(table_name)

    # ==================== ДОБАВЛЕНИЕ СТАТИСТИКИ ====================

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
        """Добавление вставленных записей"""
        if count > 0:
            self.tables_with_inserts.add(table_name)
            self.total_inserted += count
            self.table_stats[table_name]["inserted"] += count
            self._mark_table_change(table_name)

    def add_update(self, table_name: str, count: int = 1) -> None:
        """Добавление обновленных записей"""
        if count > 0:
            self.tables_with_updates.add(table_name)
            self.total_updated += count
            self.table_stats[table_name]["updated"] += count
            self._mark_table_change(table_name)

    def add_delete(self, table_name: str, count: int = 1) -> None:
        """Добавление удаленных записей"""
        if count > 0:
            self.tables_with_deletes.add(table_name)
            self.total_deleted += count
            self.table_stats[table_name]["deleted"] += count
            self._mark_table_change(table_name)

    def add_unchanged_upsert(self, table_name: str, count: int = 1) -> None:
        """Записи UPSERT без изменений"""
        if count > 0:
            self.tables_with_unchanged_upserts.add(table_name)
            self.total_unchanged_upsert += count
            self.table_stats[table_name]["unchanged_upsert"] += count

    def add_unchanged_delete(self, table_name: str, count: int = 1) -> None:
        """Записи DELETE без изменений"""
        if count > 0:
            self.tables_with_unchanged_deletes.add(table_name)
            self.total_unchanged_delete += count
            self.table_stats[table_name]["unchanged_delete"] += count

    def add_error(self, table_name: str, error: str, error_count: int = 1) -> None:
        """Добавление ошибки для таблицы"""
        self.tables_with_errors.add(table_name)
        self.failed_data_types += 1
        self.table_stats[table_name]["errors"] += 1
        self.total_error_records += error_count
        self.table_stats[table_name]["error_records"] = (
            self.table_stats[table_name].get("error_records", 0) + error_count
        )
        self._mark_table_error(table_name)
        self.error_messages.append(f"[{table_name}] {error[:200]}")

    def add_error_records(self, table_name: str, count: int = 1) -> None:
        """Добавление количества записей с ошибками"""
        if count > 0:
            self.total_error_records += count
            self.table_stats[table_name]["error_records"] = self.table_stats[table_name].get("error_records", 0) + count
            self.tables_with_errors.add(table_name)
            self.failed_data_types += 1
            self._mark_table_error(table_name)

    def merge(self, other: "SyncStatistics") -> None:
        """Объединение статистики"""
        self.total_data_types += other.total_data_types
        self.processed_data_types += other.processed_data_types
        self.failed_data_types += other.failed_data_types

        self.total_inserted += other.total_inserted
        self.total_updated += other.total_updated
        self.total_deleted += other.total_deleted
        self.total_unchanged_upsert += other.total_unchanged_upsert
        self.total_unchanged_delete += other.total_unchanged_delete
        self.total_error_records += other.total_error_records

        self.total_received += other.total_received
        self.total_received_upsert += other.total_received_upsert
        self.total_received_delete += other.total_received_delete

        self.tables_with_inserts.update(other.tables_with_inserts)
        self.tables_with_updates.update(other.tables_with_updates)
        self.tables_with_deletes.update(other.tables_with_deletes)
        self.tables_with_errors.update(other.tables_with_errors)
        self.tables_with_unchanged_upserts.update(other.tables_with_unchanged_upserts)
        self.tables_with_unchanged_deletes.update(other.tables_with_unchanged_deletes)

        for table_name, stats in other.table_stats.items():
            if table_name not in self.table_stats:
                self.table_stats[table_name] = defaultdict(int)
            for key, value in stats.items():
                self.table_stats[table_name][key] += value

        self.error_messages.extend(other.error_messages)

    # ==================== ПРЕОБРАЗОВАНИЕ В СЛОВАРЬ ====================

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
            "tables_with_unchanged_upserts": sorted(self.tables_with_unchanged_upserts),
            "tables_with_unchanged_deletes": sorted(self.tables_with_unchanged_deletes),
            "total_inserted": int(self.total_inserted),
            "total_updated": int(self.total_updated),
            "total_deleted": int(self.total_deleted),
            "total_unchanged_upsert": int(self.total_unchanged_upsert),
            "total_unchanged_delete": int(self.total_unchanged_delete),
            "total_error_records": int(self.total_error_records),
            "total_received": int(self.total_received),
            "total_received_upsert": int(self.total_received_upsert),
            "total_received_delete": int(self.total_received_delete),
            "table_stats": dict(self.table_stats),
            "error_count": len(self.error_messages),
            "error_messages": self.error_messages[:10],
            "total_users_processed": int(self.total_users_processed),
            "failed_user_ids": self.failed_user_ids,
            "duration_seconds": duration,
            "start_time": self.start_time.isoformat() + "Z" if self.start_time else None,
            "end_time": self.end_time.isoformat() + "Z" if self.end_time else None,
        }

    # ==================== ВЫВОД ОТЧЕТА ====================

    def print_report(self, title: str = "Sync Report", force: bool = False) -> None:
        """Вывод отчета в консоль"""
        if self._suppress_report:
            return

        has_changes = (
            self.total_inserted > 0
            or self.total_updated > 0
            or self.total_deleted > 0
            or self.total_unchanged_upsert > 0
            or self.total_unchanged_delete > 0
            or self.total_error_records > 0
        )
        has_errors = len(self.error_messages) > 0 or len(self.tables_with_errors) > 0
        has_received_data = self.total_received > 0
        has_user_errors = len(self.failed_user_ids) > 0

        if not has_changes and not has_errors and not has_user_errors and not force:
            if has_received_data:
                app_logger.warning(
                    f"⚠️ {title}: Received {self.total_received} records from Avanpost, "
                    f"but no changes detected (all data is up to date)"
                )
            else:
                app_logger.info(f"✅ {title}: No changes detected (all data is up to date)")
            return

        duration = None
        if self.start_time and self.end_time:
            duration = (self.end_time - self.start_time).total_seconds()

        all_tables = sorted(
            set(self.table_stats.keys())
            | set(self.tables_with_inserts)
            | set(self.tables_with_updates)
            | set(self.tables_with_deletes)
            | set(self.tables_with_errors)
            | set(self.tables_with_unchanged_upserts)
            | set(self.tables_with_unchanged_deletes)
        )

        filtered_tables = []
        for table in all_tables:
            stats = self.table_stats.get(table, {})
            if (
                stats.get("inserted", 0) > 0
                or stats.get("updated", 0) > 0
                or stats.get("deleted", 0) > 0
                or stats.get("errors", 0) > 0
                or stats.get("error_records", 0) > 0
                or stats.get("unchanged_upsert", 0) > 0
                or stats.get("unchanged_delete", 0) > 0
            ):
                filtered_tables.append(table)

        if not filtered_tables:
            if has_received_data:
                app_logger.info(f"✅ {title}: Received {self.total_received} records but no changes detected")
            else:
                app_logger.info(f"✅ {title}: No changes detected")
            return

        max_table_len = max(40, min(max(len(t) for t in filtered_tables), 80))

        separator_len = max_table_len + 8 + 8 + 8 + 8 + 8 + 8 + 8 + 8 + 8 + 8 + 8 + 10 + 18

        print("\n📋 SYNC STATISTICS:")
        print("-" * separator_len)

        header = (
            f"{'Table':<{max_table_len}} "
            f"{'Recv':>8} "
            f"{'DelRecv':>8} "
            f"{'Ins':>8} "
            f"{'Upd':>8} "
            f"{'Del':>8} "
            f"{'Err':>8} "
            f"{'ErrTbl':>8} "
            f"{'UncUpd':>8} "
            f"{'UncDel':>8} "
            f"{'UserOk':>8} "
            f"{'UserErr':>8} "
            f"{'  Status':<10}"
        )
        print(header)
        print("-" * separator_len)

        total_received_upsert = 0
        total_received_delete = 0
        total_inserted = 0
        total_updated = 0
        total_deleted = 0
        total_errors = 0
        total_error_records = 0
        total_unchanged_upsert = 0
        total_unchanged_delete = 0

        for table in filtered_tables:
            stats = self.table_stats.get(table, {})
            received_upsert = stats.get("received_upsert", 0)
            received_delete = stats.get("received_delete", 0)
            inserted = stats.get("inserted", 0)
            updated = stats.get("updated", 0)
            deleted = stats.get("deleted", 0)
            errors = stats.get("errors", 0)
            error_records = stats.get("error_records", 0)
            unchanged_upsert = stats.get("unchanged_upsert", 0)
            unchanged_delete = stats.get("unchanged_delete", 0)
            users_ok = stats.get("users_ok", 0)
            users_err = stats.get("users_err", 0)

            received = received_upsert

            total_received_upsert += received_upsert
            total_received_delete += received_delete
            total_inserted += inserted
            total_updated += updated
            total_deleted += deleted
            total_errors += errors
            total_error_records += error_records
            total_unchanged_upsert += unchanged_upsert
            total_unchanged_delete += unchanged_delete

            if errors > 0 or error_records > 0:
                status = "  ❌ ERROR"
            elif inserted > 0 or updated > 0 or deleted > 0:
                status = "  ✅ OK"
            elif unchanged_upsert > 0 or unchanged_delete > 0:
                status = "  ⏭️  NONE"
            else:
                continue

            print(
                f"{table:<{max_table_len}} "
                f"{received:>8} "
                f"{received_delete:>8} "
                f"{inserted:>8} "
                f"{updated:>8} "
                f"{deleted:>8} "
                f"{error_records:>8} "
                f"{errors:>8} "
                f"{unchanged_upsert:>8} "
                f"{unchanged_delete:>8} "
                f"{users_ok:>8} "
                f"{users_err:>8} "
                f"{status:<10}"
            )

        print("-" * separator_len)
        status_text = " ⚠️ ERRORS" if total_errors > 0 or len(self.failed_user_ids) > 0 else "  ✅ DONE"
        duration_str = f"{duration:.2f}s" if duration else "N/A"
        total_received = total_received_upsert

        users_ok = self.total_users_processed - len(self.failed_user_ids)
        users_err = len(self.failed_user_ids)

        summary_label = f"📊 SUMMARY (Tables: {len(filtered_tables)}, Duration: {duration_str})"

        print(
            f"{summary_label:<{max_table_len - 1}} "
            f"{total_received:>8} "
            f"{total_received_delete:>8} "
            f"{total_inserted:>8} "
            f"{total_updated:>8} "
            f"{total_deleted:>8} "
            f"{total_error_records:>8} "
            f"{total_errors:>8} "
            f"{total_unchanged_upsert:>8} "
            f"{total_unchanged_delete:>8} "
            f"{users_ok:>8} "
            f"{users_err:>8} "
            f"{status_text:<10}"
        )
        print("-" * separator_len)

        if self.failed_user_ids:
            print(f"\n❌ USERS WITH ERRORS ({len(self.failed_user_ids)}):")
            failed_ids_str = ", ".join(map(str, self.failed_user_ids))
            print(f"   {failed_ids_str}")

        if self.tables_with_errors:
            print(f"\n❌ TABLES WITH ERRORS ({len(self.tables_with_errors)}):")
            for table in sorted(self.tables_with_errors):
                print(f"   - {table}")
            if self.error_messages:
                print("\n📝 Error details:")
                for err in self.error_messages[:10]:
                    print(f"   - {err}")
                if len(self.error_messages) > 10:
                    print(f"   - ... и еще {len(self.error_messages) - 10} ошибок")


# ==================== ОСНОВНОЙ СЕРВИС ====================


class AvanpostSyncService:
    """Сервис синхронизации данных Avanpost."""

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
        self._fk_cache: dict[str, set[Any]] = {}
        self._model_columns_cache: dict[tuple[Any, bool], set[str]] = {}

        from ..models.avanpost import AVANPOST_BASE_DATA_TYPES, AVANPOST_USER_DATA_TYPES

        self.base_data_types = AVANPOST_BASE_DATA_TYPES
        self.user_data_types = AVANPOST_USER_DATA_TYPES

    @property
    def is_initialized(self) -> bool:
        return self._initialized

    @property
    def is_syncing(self) -> bool:
        return self._sync_in_progress

    # ==================== ИНИЦИАЛИЗАЦИЯ ====================

    async def initialize(self, session: AsyncSession | None = None) -> None:
        """Инициализация сервиса"""
        if self._initialized:
            return

        if session is None:
            async with db_manager.get_session() as sess:
                self._data_type_cache = await SystemRepository.get_data_types_dict(sess)
        else:
            self._data_type_cache = await SystemRepository.get_data_types_dict(session)

        self._initialized = True
        app_logger.info(f"✅ AvanpostSyncService initialized with {len(self._data_type_cache)} data types")

    # ==================== ВСПОМОГАТЕЛЬНЫЕ МЕТОДЫ ====================

    @staticmethod
    def _get_model_by_data_type(data_type_id: int) -> Any:
        """Получение модели по типу данных."""

        return get_avanpost_model(data_type_id)

    @staticmethod
    def _get_table_name(data_type_id: int) -> str | None:
        """Получение имени таблицы по типу данных."""

        return get_avanpost_table_name(data_type_id)

    def _get_model_columns(self, model: Any, include_all: bool = True) -> set[str]:
        """Получение списка колонок модели с кешированием."""
        cache_key = (model, include_all)
        if cache_key in self._model_columns_cache:
            return self._model_columns_cache[cache_key]

        all_columns = {column.name for column in model.__table__.columns}

        if include_all:
            result = all_columns
        else:
            pk_columns = {col.name for col in model.__table__.primary_key.columns}
            result = pk_columns

        self._model_columns_cache[cache_key] = result
        return result

    @staticmethod
    def _get_pk_columns(model: Any) -> list[str]:
        """Получение списка колонок первичного ключа."""
        return [col.name for col in model.__table__.primary_key.columns]

    @staticmethod
    def _get_required_columns(model: Any) -> list[str]:
        """Получение списка NOT NULL колонок."""
        return [col.name for col in model.__table__.columns if not col.nullable]

    @staticmethod
    async def _get_sync_times_for_types(
        data_types: list[int],
        user_id: int | None = None,
    ) -> dict[int, datetime]:
        """Получение времени синхронизации для списка типов данных."""
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
        """Обновление времени синхронизации для типов данных."""
        if not sync_times:
            return

        async with db_manager.get_session() as session:
            if user_id is None:
                await SystemRepository.update_sync_times_bulk(session, sync_times)
            else:
                await SystemRepository.update_user_sync_times_bulk(session, user_id, sync_times)

    # ==================== СИНХРОНИЗАЦИЯ БАЗОВЫХ ДАННЫХ ====================

    async def sync_base_data(self, force: bool = False) -> SyncStatistics:
        """Синхронизация базовых данных с детальной статистикой"""
        stats = SyncStatistics()
        stats.start()
        stats.total_data_types = len(self.base_data_types)

        app_logger.info("🔄 Starting base data synchronization...")

        try:
            last_sync_by_type = await self._get_sync_times_for_types(self.base_data_types)

            min_last_sync = min(last_sync_by_type.values()) if last_sync_by_type else None

            if min_last_sync:
                app_logger.info(f"📅 Min last sync time: {min_last_sync.isoformat()}")
            else:
                app_logger.info("📅 No previous sync time found, using default")

            # Разбивка на чанки для вызова процедуры
            chunk_size = getattr(settings, "AVANPOST_SYNC_CHUNK_SIZE", 10)
            chunks = [self.base_data_types[i : i + chunk_size] for i in range(0, len(self.base_data_types), chunk_size)]

            app_logger.debug(f"📊 Split {len(self.base_data_types)} types into {len(chunks)} chunks")

            all_data_items: list[dict[str, Any]] = []
            all_requested_types: set[int] = set()

            for idx, chunk in enumerate(chunks):
                app_logger.info(f"📦 Processing chunk {idx + 1}/{len(chunks)} with {len(chunk)} types...")

                all_requested_types.update(chunk)

                chunk_min_time = None
                for dt_id in chunk:
                    if dt_id in last_sync_by_type:
                        sync_time = last_sync_by_type[dt_id]
                        if chunk_min_time is None or sync_time < chunk_min_time:
                            chunk_min_time = sync_time

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

            current_time = datetime_now()
            sync_times: dict[int, datetime] = {}

            for dt_id in all_requested_types:
                sync_times[dt_id] = current_time

            if all_data_items:
                # Разделение записей на DELETE и UPSERT
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

                    if not isinstance(data_type_raw, int):
                        app_logger.warning(f"⚠️ DataTypeId is not int: {type(data_type_raw)}")
                        continue

                    current_dt_id: int = data_type_raw

                    if current_dt_id not in self.base_data_types:
                        app_logger.warning(f"⚠️ Skipping {current_dt_id} (not in base_data_types)")
                        continue

                    records = data_item.get("Data")
                    if not records:
                        continue

                    table_name = self._get_table_name(current_dt_id) or "UNKNOWN"
                    if table_name == "UNKNOWN":
                        app_logger.warning(f"⚠️ No table mapping for DataTypeId {current_dt_id}")
                        continue

                    flag_expire = data_item.get("FlagExpire", False)
                    data_type_for_table[table_name] = current_dt_id

                    if flag_expire == 1 or flag_expire is True:
                        if table_name not in delete_records_by_table:
                            delete_records_by_table[table_name] = []
                            delete_order.append(table_name)

                        if isinstance(records, list):
                            delete_records_by_table[table_name].extend(records)
                        else:
                            delete_records_by_table[table_name].append(records)
                    else:
                        if table_name not in upsert_records_by_table:
                            upsert_records_by_table[table_name] = []
                            upsert_order.append(table_name)

                        if isinstance(records, list):
                            upsert_records_by_table[table_name].extend(records)
                        else:
                            upsert_records_by_table[table_name].append(records)

                # Подсчёт полученных записей для статистики
                for table_name in set(delete_order) | set(upsert_order):
                    upsert_count = len(upsert_records_by_table.get(table_name, []))
                    delete_count = len(delete_records_by_table.get(table_name, []))
                    stats.add_received(table_name, upsert_count, delete_count)

                # 1. DELETE (в порядке из JSON)
                async with db_manager.get_session() as session:
                    for table_name in delete_order:
                        records = delete_records_by_table[table_name]
                        dt_id_value = data_type_for_table.get(table_name)
                        if dt_id_value is None or not records:
                            continue

                        delete_dt_id: int = dt_id_value

                        model = self._get_model_by_data_type(delete_dt_id)
                        if not model:
                            app_logger.warning(f"⚠️ No model found for DataTypeId {delete_dt_id}")
                            continue

                        # Оставление только первичного ключа для DELETE
                        pk_columns = self._get_pk_columns(model)
                        clean_records: list[dict[str, Any]] = []
                        for rec in records:
                            if not isinstance(rec, dict):
                                continue
                            clean_rec = {}
                            for pk in pk_columns:
                                if pk in rec:
                                    clean_rec[pk] = rec[pk]
                            if clean_rec:
                                clean_records.append(clean_rec)

                        if not clean_records:
                            continue

                        try:
                            # ИСПОЛЬЗУЕМ GenericRepository ДЛЯ УДАЛЕНИЯ
                            deleted, unchanged, errors = await GenericRepository.delete_records_bulk(
                                session=session,
                                model=model,
                                records=clean_records,
                                primary_keys=pk_columns,
                                chunk_size=1000,
                                raise_on_error=False,
                            )

                            if deleted > 0:
                                stats.add_delete(table_name, deleted)
                            if unchanged > 0:
                                stats.add_unchanged_delete(table_name, unchanged)
                            if errors > 0:
                                stats.add_error_records(table_name, errors)
                                stats.add_error(table_name, f"DELETE errors: {errors} records")

                            app_logger.debug(
                                f"🗑️ DELETE result for {table_name}: "
                                f"deleted={deleted}, unchanged={unchanged}, errors={errors}"
                            )

                        except Exception as e:
                            stats.add_error(table_name, str(e))
                            app_logger.error(f"❌ Failed to DELETE from {table_name}: {e}")
                            await session.rollback()

                # 2. UPSERT (В порядке из JSON)
                async with db_manager.get_session() as session:
                    for table_name in upsert_order:
                        records = upsert_records_by_table[table_name]
                        dt_id_value = data_type_for_table.get(table_name)
                        if dt_id_value is None or not records:
                            continue

                        upsert_dt_id: int = dt_id_value

                        model = self._get_model_by_data_type(upsert_dt_id)
                        if not model:
                            app_logger.warning(f"⚠️ No model found for DataTypeId {upsert_dt_id}")
                            continue

                        # Фильтрация записей с NULL в NOT NULL колонках
                        required_fields = self._get_required_columns(model)

                        filtered_records: list[dict[str, Any]] = []
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
                            stats.add_unchanged_upsert(table_name, len(records) - len(filtered_records))
                            app_logger.warning(
                                f"⚠️ Filtered out {len(records) - len(filtered_records)} records with NULL in required fields "
                                f"from {table_name}"
                            )

                        if not filtered_records:
                            continue

                        model_columns = self._get_model_columns(model, include_all=True)

                        # Разбивка на чанки для UPSERT
                        chunk_size_upsert = 1000
                        total_chunks = (len(filtered_records) + chunk_size_upsert - 1) // chunk_size_upsert

                        for chunk_idx in range(0, len(filtered_records), chunk_size_upsert):
                            upsert_chunk: list[dict[str, Any]] = filtered_records[
                                chunk_idx : chunk_idx + chunk_size_upsert
                            ]

                            try:
                                # ИСПОЛЬЗУЕМ GenericRepository ДЛЯ UPSERT
                                result = await GenericRepository.save_data_bulk(
                                    session=session,
                                    model=model,
                                    records=upsert_chunk,
                                    model_columns=model_columns,
                                    raise_on_error=False,
                                    commit_chunks=True,
                                )
                                stats.processed_data_types += 1

                                if result.get("inserted", 0) > 0:
                                    stats.add_insert(table_name, result["inserted"])
                                if result.get("updated", 0) > 0:
                                    stats.add_update(table_name, result["updated"])
                                if result.get("deleted", 0) > 0:
                                    stats.add_delete(table_name, result["deleted"])
                                if result.get("unchanged_upsert", 0) > 0:
                                    stats.add_unchanged_upsert(table_name, result["unchanged_upsert"])
                                if result.get("unchanged_delete", 0) > 0:
                                    stats.add_unchanged_delete(table_name, result["unchanged_delete"])
                                if result.get("error_records", 0) > 0:
                                    stats.add_error_records(table_name, result["error_records"])

                                app_logger.debug(
                                    f"✅ UPSERT chunk {chunk_idx // chunk_size_upsert + 1}/{total_chunks} for {table_name}: "
                                    f"inserted={result.get('inserted', 0)}, "
                                    f"updated={result.get('updated', 0)}, "
                                    f"deleted={result.get('deleted', 0)}, "
                                    f"unchanged_upsert={result.get('unchanged_upsert', 0)}, "
                                    f"unchanged_delete={result.get('unchanged_delete', 0)}, "
                                    f"error_records={result.get('error_records', 0)}"
                                )

                            except Exception as e:
                                stats.add_error(table_name, str(e))
                                stats.add_error_records(table_name, len(upsert_chunk))
                                app_logger.error(
                                    f"❌ Failed to UPSERT {table_name} (chunk {chunk_idx // chunk_size_upsert + 1}/{total_chunks}): {e}"
                                )
                                await session.rollback()
                                # Пропуск оставшихся чанков при ошибке
                                break

                app_logger.info("✅ Base data synchronization completed")
            else:
                app_logger.debug("ℹ️ No data received from procedure")

            if sync_times:
                await self._update_sync_times(sync_times)
                app_logger.info(f"✅ Updated sync times for {len(sync_times)} data types")

            stats.finish()
            stats.print_report("Base Data Sync Report")
            return stats

        except Exception as e:
            stats.add_error("__global__", str(e))
            stats.finish()
            stats.print_report("Base Data Sync Report")
            app_logger.error(f"❌ Failed to sync base data: {e}")
            import traceback

            app_logger.error(f"📄 Traceback: {traceback.format_exc()}")
            raise

    # ==================== СИНХРОНИЗАЦИЯ ДАННЫХ ПОЛЬЗОВАТЕЛЯ ====================

    async def sync_user_data(
        self,
        user_id: int,
        force: bool = False,
        suppress_report: bool = True,
    ) -> SyncStatistics:
        """
        Синхронизация данных пользователя с детальной статистикой.
        """
        stats = SyncStatistics()
        stats.start()
        stats.total_data_types = len(self.user_data_types)
        stats.suppress_report(suppress_report)
        stats.set_current_user(user_id)

        app_logger.debug(f"🔄 Starting user data synchronization for user {user_id}...")

        processed_data_types: set[int] = set()
        all_requested_types: set[int] = set()

        try:
            last_sync_by_type = await self._get_sync_times_for_types(self.user_data_types, user_id)

            chunk_size = 10
            chunks = [self.user_data_types[i : i + chunk_size] for i in range(0, len(self.user_data_types), chunk_size)]

            all_data_items: list[dict[str, Any]] = []

            for _idx, chunk in enumerate(chunks):
                all_requested_types.update(chunk)

                chunk_min_time = None
                for dt_id_chunk in chunk:
                    if dt_id_chunk in last_sync_by_type:
                        sync_time = last_sync_by_type[dt_id_chunk]
                        if chunk_min_time is None or sync_time < chunk_min_time:
                            chunk_min_time = sync_time

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

                        if valid_items:
                            all_data_items.extend(valid_items)

            if all_data_items:
                # Разделение записей на DELETE и UPSERT
                delete_records_by_table: dict[str, list[dict[str, Any]]] = {}
                upsert_records_by_table: dict[str, list[dict[str, Any]]] = {}
                delete_order: list[str] = []
                upsert_order: list[str] = []
                data_type_for_table: dict[str, int] = {}

                for data_item in all_data_items:
                    if not isinstance(data_item, dict):
                        continue

                    data_type_raw = data_item.get("DataTypeId")
                    if data_type_raw is None:
                        continue

                    if not isinstance(data_type_raw, int):
                        continue

                    current_dt_id: int = data_type_raw

                    if current_dt_id not in self.user_data_types:
                        continue

                    records = data_item.get("Data")
                    if not records:
                        continue

                    table_name = self._get_table_name(current_dt_id) or "UNKNOWN"
                    if table_name == "UNKNOWN":
                        continue

                    flag_expire = data_item.get("FlagExpire", False)
                    data_type_for_table[table_name] = current_dt_id

                    if flag_expire == 1 or flag_expire is True:
                        if table_name not in delete_records_by_table:
                            delete_records_by_table[table_name] = []
                            delete_order.append(table_name)

                        if isinstance(records, list):
                            delete_records_by_table[table_name].extend(records)
                        else:
                            delete_records_by_table[table_name].append(records)
                    else:
                        if table_name not in upsert_records_by_table:
                            upsert_records_by_table[table_name] = []
                            upsert_order.append(table_name)

                        if isinstance(records, list):
                            upsert_records_by_table[table_name].extend(records)
                        else:
                            upsert_records_by_table[table_name].append(records)

                # Подсчёт полученных записей для статистики
                for table_name in set(delete_order) | set(upsert_order):
                    upsert_count = len(upsert_records_by_table.get(table_name, []))
                    delete_count = len(delete_records_by_table.get(table_name, []))
                    stats.add_received(table_name, upsert_count, delete_count)

                # 1. DELETE (в порядке из JSON)
                async with db_manager.get_session() as session:
                    for table_name in delete_order:
                        records = delete_records_by_table[table_name]
                        dt_id = data_type_for_table.get(table_name)

                        if dt_id is None or not records:
                            continue

                        processed_data_types.add(dt_id)

                        model = self._get_model_by_data_type(dt_id)
                        if not model:
                            continue

                        pk_columns = self._get_pk_columns(model)
                        clean_records: list[dict[str, Any]] = []
                        for rec in records:
                            if not isinstance(rec, dict):
                                continue
                            clean_rec = {}
                            for pk in pk_columns:
                                if pk in rec:
                                    clean_rec[pk] = rec[pk]
                            if clean_rec:
                                clean_records.append(clean_rec)

                        if not clean_records:
                            continue

                        try:
                            # ИСПОЛЬЗУЕМ GenericRepository ДЛЯ УДАЛЕНИЯ
                            deleted, unchanged, errors = await GenericRepository.delete_records_bulk(
                                session=session,
                                model=model,
                                records=clean_records,
                                primary_keys=pk_columns,
                                chunk_size=1000,
                                raise_on_error=False,
                            )

                            if deleted > 0:
                                stats.add_delete(table_name, deleted)
                            if unchanged > 0:
                                stats.add_unchanged_delete(table_name, unchanged)
                            if errors > 0:
                                stats.add_error_records(table_name, errors)
                                stats.add_error(table_name, f"DELETE errors: {errors} records")

                            app_logger.debug(
                                f"🗑️ DELETE result for {table_name}: "
                                f"deleted={deleted}, unchanged={unchanged}, errors={errors}"
                            )

                        except Exception as e:
                            stats.add_error(table_name, str(e))
                            app_logger.error(f"❌ Failed to DELETE from {table_name}: {e}")
                            await session.rollback()

                # 2. UPSERT (В порядке из JSON)
                async with db_manager.get_session() as session:
                    for table_name in upsert_order:
                        records = upsert_records_by_table[table_name]
                        dt_id = data_type_for_table.get(table_name)

                        if dt_id is None or not records:
                            continue

                        processed_data_types.add(dt_id)

                        model = self._get_model_by_data_type(dt_id)
                        if not model:
                            continue

                        # Фильтрация записей с NULL в NOT NULL колонках
                        required_fields = self._get_required_columns(model)

                        filtered_records: list[dict[str, Any]] = []
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
                            stats.add_unchanged_upsert(table_name, len(records) - len(filtered_records))

                        if not filtered_records:
                            continue

                        model_columns = self._get_model_columns(model, include_all=True)

                        try:
                            # ИСПОЛЬЗУЕМ GenericRepository ДЛЯ UPSERT
                            result = await GenericRepository.save_data_bulk(
                                session=session,
                                model=model,
                                records=filtered_records,
                                model_columns=model_columns,
                                raise_on_error=False,
                                commit_chunks=True,
                            )
                            stats.processed_data_types += 1

                            if result.get("inserted", 0) > 0:
                                stats.add_insert(table_name, result["inserted"])
                            if result.get("updated", 0) > 0:
                                stats.add_update(table_name, result["updated"])
                            if result.get("deleted", 0) > 0:
                                stats.add_delete(table_name, result["deleted"])
                            if result.get("unchanged_upsert", 0) > 0:
                                stats.add_unchanged_upsert(table_name, result["unchanged_upsert"])
                            if result.get("unchanged_delete", 0) > 0:
                                stats.add_unchanged_delete(table_name, result["unchanged_delete"])
                            if result.get("error_records", 0) > 0:
                                stats.add_error_records(table_name, result["error_records"])

                            app_logger.debug(
                                f"✅ UPSERT result for {table_name}: "
                                f"inserted={result.get('inserted', 0)}, "
                                f"updated={result.get('updated', 0)}, "
                                f"deleted={result.get('deleted', 0)}, "
                                f"unchanged_upsert={result.get('unchanged_upsert', 0)}, "
                                f"unchanged_delete={result.get('unchanged_delete', 0)}, "
                                f"error_records={result.get('error_records', 0)}"
                            )

                        except Exception as e:
                            stats.add_error(table_name, str(e))
                            stats.add_error_records(table_name, len(filtered_records))
                            app_logger.error(f"❌ Failed to UPSERT {table_name}: {e}")
                            app_logger.error(
                                f"   Problematic records (first 3): {json.dumps(filtered_records[:3], ensure_ascii=False, default=str, indent=2)}"
                            )
                            await session.rollback()

            # ============================================================
            # ОБНОВЛЕНИЕ ВРЕМЕНИ СИНХРОНИЗАЦИИ
            # ============================================================

            # Собираем все успешно обработанные типы
            successfully_processed_types = set()

            # 1. Типы с данными, которые успешно обработаны
            for dt_id in processed_data_types:
                # Проверяем ошибки для этого типа
                error_for_type = any(
                    f"DataTypeId {dt_id}" in error or f"table_{dt_id}" in error for error in stats.error_messages
                )

                if not error_for_type:
                    successfully_processed_types.add(dt_id)
                    app_logger.debug(f"✅ Type {dt_id} processed with data successfully")

            # 2. Типы без данных (считаем успешными)
            for dt_id in all_requested_types:
                if dt_id not in processed_data_types:
                    successfully_processed_types.add(dt_id)
                    app_logger.debug(f"ℹ️ No data for type {dt_id}, marking as successful")

            # 3. Обновляем время для всех успешных типов
            if successfully_processed_types:
                current_time = datetime_now()
                sync_times = dict.fromkeys(successfully_processed_types, current_time)

                await self._update_sync_times(sync_times, user_id)
                app_logger.info(f"✅ Updated sync times for {len(sync_times)} data types for user {user_id}")

                # Детальный лог
                if logging.getLogger().isEnabledFor(logging.DEBUG):
                    with_data = sorted(
                        [dt_id for dt_id in processed_data_types if dt_id in successfully_processed_types]
                    )
                    no_data = sorted([dt_id for dt_id in all_requested_types if dt_id not in processed_data_types])
                    if with_data:
                        app_logger.debug(f"   With data: {with_data}")
                    if no_data:
                        app_logger.debug(f"   No data: {no_data}")

            # 4. Логируем пропущенные типы
            failed_types = set(all_requested_types) - successfully_processed_types
            if failed_types:
                app_logger.warning(
                    f"⚠️ Sync times NOT updated for failed data types: {sorted(failed_types)} for user {user_id}"
                )
                # Добавляем причины
                for dt_id in failed_types:
                    if dt_id in processed_data_types:
                        app_logger.debug(f"   Type {dt_id}: had data but errors occurred")
                    else:
                        app_logger.debug(f"   Type {dt_id}: unknown reason")

            stats.finish()
            stats.finalize_user()

            return stats

        except Exception as e:
            stats.add_error("__global__", str(e))
            stats.finish()
            app_logger.error(f"❌ Failed to sync user data for user {user_id}: {e}")
            import traceback

            app_logger.error(f"📄 Traceback: {traceback.format_exc()}")
            raise

    # ==================== СИНХРОНИЗАЦИЯ ВСЕХ ПОЛЬЗОВАТЕЛЕЙ ====================

    async def sync_all_users(self, force: bool = False) -> dict[str, Any]:
        """Синхронизация всех пользователей с агрегированной статистикой"""
        app_logger.info("🔄 Starting all users synchronization...")

        all_stats = SyncStatistics()
        all_stats.start()

        async with db_manager.get_session() as session:
            # ИСПОЛЬЗУЕМ UserRepository ДЛЯ ПОЛУЧЕНИЯ ПОЛЬЗОВАТЕЛЕЙ
            users = await UserRepository.get_all_avanpost_users(session)
            total_users = len(users)
            all_stats.total_data_types = total_users

            app_logger.info(f"👥 Found {total_users} users to sync")

            errors_list: list[str] = []

            for idx, user in enumerate(users, 1):
                app_logger.info(f"📦 Processing user {idx}/{total_users} (ID: {user.FID})...")
                try:
                    user_stats = await self.sync_user_data(user.FID, force, suppress_report=True)
                    all_stats.add_processed_user()
                    all_stats.merge(user_stats)

                    app_logger.info(
                        f"✅ User {user.FID} completed: "
                        f"inserted={user_stats.total_inserted}, "
                        f"updated={user_stats.total_updated}, "
                        f"deleted={user_stats.total_deleted}"
                    )

                except Exception as e:
                    all_stats.add_failed_user(user.FID)
                    errors_list.append(f"User {user.FID}: {str(e)}")
                    all_stats.add_error(f"User_{user.FID}", str(e))
                    app_logger.error(f"❌ Failed to sync user {user.FID}: {e}")

            all_stats.finish()

            result_stats = {
                "total_users": total_users,
                "successful": all_stats.total_users_processed - len(all_stats.failed_user_ids),
                "failed": len(all_stats.failed_user_ids),
                "failed_user_ids": all_stats.failed_user_ids,
                "total_inserted": all_stats.total_inserted,
                "total_updated": all_stats.total_updated,
                "total_deleted": all_stats.total_deleted,
                "total_unchanged_upsert": all_stats.total_unchanged_upsert,
                "total_unchanged_delete": all_stats.total_unchanged_delete,
                "total_received": all_stats.total_received,
                "total_received_upsert": all_stats.total_received_upsert,
                "total_received_delete": all_stats.total_received_delete,
                "errors": errors_list,
            }

            all_stats.print_report("All Users Sync Report", force=True)

            return result_stats

    # ==================== ПОЛНАЯ СИНХРОНИЗАЦИЯ ====================

    async def sync_all(self, force: bool = False) -> dict[str, Any]:
        """Полная синхронизация всех данных"""
        app_logger.info("🔄 Starting full synchronization...")

        base_stats = await self.sync_base_data(force)
        user_stats = await self.sync_all_users(force)

        base_dict = base_stats.to_dict() if hasattr(base_stats, "to_dict") else {}

        base_inserted = int(base_dict.get("total_inserted") or 0)
        base_updated = int(base_dict.get("total_updated") or 0)
        base_deleted = int(base_dict.get("total_deleted") or 0)
        base_unchanged = int(base_dict.get("total_unchanged") or 0)

        if isinstance(user_stats, dict):
            user_inserted = int(user_stats.get("total_inserted") or 0)
            user_updated = int(user_stats.get("total_updated") or 0)
            user_deleted = int(user_stats.get("total_deleted") or 0)
            user_unchanged = int(user_stats.get("total_unchanged") or 0)
        else:
            user_inserted = int(getattr(user_stats, "total_inserted", 0) or 0)
            user_updated = int(getattr(user_stats, "total_updated", 0) or 0)
            user_deleted = int(getattr(user_stats, "total_deleted", 0) or 0)
            user_unchanged = int(getattr(user_stats, "total_unchanged", 0) or 0)

        result = {
            "base_data": base_dict,
            "users": user_stats,
            "total_inserted": base_inserted + user_inserted,
            "total_updated": base_updated + user_updated,
            "total_deleted": base_deleted + user_deleted,
            "total_unchanged": base_unchanged + user_unchanged,
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

__all__ = [
    "AvanpostSyncService",
    "avanpost_sync_service",
    "SyncStatistics",
]
