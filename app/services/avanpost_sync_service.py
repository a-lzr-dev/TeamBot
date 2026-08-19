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

ModelType = TypeVar("ModelType")


# ==================== СТАТИСТИКА СИНХРОНИЗАЦИИ ====================


@dataclass
class SyncStatistics:
    """
    Статистика синхронизации.

    Поля отчета (для понимания вывода в консоль):
        - Recv:         Общее количество записей, полученных от Avanpost для таблицы.
        - DelRecv:      Количество записей, помеченных на удаление (FlagExpire=1).
        - Ins:          Количество записей, реально вставленных в БД (INSERT).
        - Upd:          Количество записей, реально обновленных в БД (UPDATE).
        - Del:          Количество записей, реально удаленных из БД (DELETE).
        - Err:          Количество ЗАПИСЕЙ, с которыми произошла ошибка при обработке.
        - ErrTbl:       Количество ТАБЛИЦ, в которых произошла хотя бы одна ошибка.
        - UncUpd:       Количество записей, пропущенных при UPSERT (которые не были добавлены или изменены физически, т.к. не найдены).
        - UncDel:       Количество записей, пропущенных при DELETE (которые не были удалены физически, т.к. не найдены).
        - UserOk:       Количество пользователей, для которых таблица обработана успешно.
        - UserErr:      Количество пользователей, для которых в таблице была ошибка.
        - Status:       Общий статус обработки таблицы (OK, ERROR, SKIP, NONE).

    ВАЖНОЕ РАЗЛИЧИЕ:
        - Err (error_records)  - счетчик ЗАПИСЕЙ с ошибками.
        - ErrTbl (errors)      - счетчик ТАБЛИЦ, в которых были ошибки.
    """

    # Общие счетчики
    total_data_types: int = 0
    processed_data_types: int = 0
    failed_data_types: int = 0

    # Счетчики по операциям
    tables_with_inserts: set[str] = field(default_factory=set)
    tables_with_updates: set[str] = field(default_factory=set)
    tables_with_deletes: set[str] = field(default_factory=set)
    tables_with_errors: set[str] = field(default_factory=set)  # ErrTbl
    tables_with_unchanged: set[str] = field(default_factory=set)
    tables_with_skipped: set[str] = field(default_factory=set)

    # Количество записей
    total_inserted: int = 0  # Ins
    total_updated: int = 0  # Upd
    total_deleted: int = 0  # Del
    total_unchanged: int = 0  # (не отображается в отчете)
    total_skipped_upsert: int = 0  # UncUpd
    total_skipped_delete: int = 0  # UncDel
    total_error_records: int = 0  # Err

    # Количество полученных записей
    total_received: int = 0  # Recv
    total_received_upsert: int = 0
    total_received_delete: int = 0  # DelRecv

    # Детальная статистика по таблицам
    table_stats: dict[str, dict[str, int]] = field(
        default_factory=lambda: defaultdict(
            lambda: {
                "inserted": 0,
                "updated": 0,
                "deleted": 0,
                "errors": 0,  # ErrTbl - количество таблиц с ошибками
                "error_records": 0,  # Err - количество записей с ошибками
                "unchanged": 0,
                "skipped_upsert": 0,
                "skipped_delete": 0,
                "received": 0,
                "received_upsert": 0,
                "received_delete": 0,
                "users_ok": 0,
                "users_err": 0,
            }
        )
    )

    # Флаг для отслеживания изменений в текущей таблице для текущего пользователя
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

    # Флаг - нужно ли выводить отчет (для отключения вывода в sync_user_data)
    _suppress_report: bool = False

    # Текущий пользователь для отслеживания
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
        """Установка текущего пользователя для отслеживания"""
        self._current_user_id = user_id
        self._current_table_has_changes.clear()
        self._current_table_has_error.clear()

    def finalize_user(self) -> None:
        """Завершение обработки пользователя - обновляем счетчики"""
        if self._current_user_id is None:
            return

        # Для каждой таблицы, где были изменения, увеличиваем users_ok
        for table_name in self._current_table_has_changes:
            self.table_stats[table_name]["users_ok"] += 1

        # Для каждой таблицы, где были ошибки, увеличиваем users_err
        for table_name in self._current_table_has_error:
            self.table_stats[table_name]["users_err"] += 1

        # Сбрасываем флаги
        self._current_table_has_changes.clear()
        self._current_table_has_error.clear()

    def add_processed_user(self) -> None:
        """Увеличивает счетчик обработанных пользователей."""
        self.total_users_processed += 1

    def add_failed_user(self, user_id: int) -> None:
        """Добавляет ID пользователя, синхронизация которого завершилась ошибкой."""
        if user_id not in self.failed_user_ids:
            self.failed_user_ids.append(user_id)

    def _mark_table_change(self, table_name: str) -> None:
        """Отметить, что в таблице были изменения для текущего пользователя"""
        if self._current_user_id:
            self._current_table_has_changes.add(table_name)

    def _mark_table_error(self, table_name: str) -> None:
        """Отметить, что в таблице была ошибка для текущего пользователя"""
        if self._current_user_id:
            self._current_table_has_error.add(table_name)

    # ==================== ДОБАВЛЕНИЕ СТАТИСТИКИ ====================

    def add_received(self, table_name: str, upsert_count: int = 0, delete_count: int = 0) -> None:
        """Добавление полученных записей (Recv, DelRecv)"""
        if upsert_count > 0 or delete_count > 0:
            total = upsert_count + delete_count
            self.total_received += total
            self.total_received_upsert += upsert_count
            self.total_received_delete += delete_count
            self.table_stats[table_name]["received"] += total
            self.table_stats[table_name]["received_upsert"] += upsert_count
            self.table_stats[table_name]["received_delete"] += delete_count

    def add_insert(self, table_name: str, count: int = 1) -> None:
        """Добавление реально ВСТАВЛЕННЫХ записей (INSERT) -> Ins"""
        if count > 0:
            self.tables_with_inserts.add(table_name)
            self.total_inserted += count
            self.table_stats[table_name]["inserted"] += count
            self._mark_table_change(table_name)

    def add_update(self, table_name: str, count: int = 1) -> None:
        """Добавление реально ОБНОВЛЕННЫХ записей (UPDATE) -> Upd"""
        if count > 0:
            self.tables_with_updates.add(table_name)
            self.total_updated += count
            self.table_stats[table_name]["updated"] += count
            self._mark_table_change(table_name)

    def add_delete(self, table_name: str, count: int = 1) -> None:
        """Добавление реально УДАЛЕННЫХ записей (DELETE) -> Del"""
        if count > 0:
            self.tables_with_deletes.add(table_name)
            self.total_deleted += count
            self.table_stats[table_name]["deleted"] += count
            self._mark_table_change(table_name)

    def add_unchanged(self, table_name: str, count: int = 1) -> None:
        """Записи без изменений (пропущены)"""
        if count > 0:
            self.tables_with_unchanged.add(table_name)
            self.total_unchanged += count
            self.table_stats[table_name]["unchanged"] += count

    def add_skip_upsert(self, table_name: str, count: int = 1) -> None:
        """Пропущено из UPSERT (не вставлены/не обновлены из-за ошибок) -> UncUpd"""
        if count > 0:
            self.tables_with_skipped.add(table_name)
            self.total_skipped_upsert += count
            self.table_stats[table_name]["skipped_upsert"] += count

    def add_skip_delete(self, table_name: str, count: int = 1) -> None:
        """Пропущено из DELETE (не найдены для удаления) -> UncDel"""
        if count > 0:
            self.tables_with_skipped.add(table_name)
            self.total_skipped_delete += count
            self.table_stats[table_name]["skipped_delete"] += count

    def add_error(self, table_name: str, error: str) -> None:
        """
        Добавление ошибки для таблицы.
        Увеличивает счетчик таблиц с ошибками (ErrTbl).
        """
        self.tables_with_errors.add(table_name)
        self.failed_data_types += 1
        self.table_stats[table_name]["errors"] += 1
        self._mark_table_error(table_name)
        self.error_messages.append(f"[{table_name}] {error[:200]}")

    def add_error_records(self, table_name: str, count: int = 1) -> None:
        """
        Добавление количества записей с ошибками.
        Увеличивает счетчик записей с ошибками (Err).
        """
        if count > 0:
            self.total_error_records += count
            self.table_stats[table_name]["error_records"] = self.table_stats[table_name].get("error_records", 0) + count
            self.tables_with_errors.add(table_name)
            self.failed_data_types += 1
            self._mark_table_error(table_name)

    # ==================== ОБЪЕДИНЕНИЕ СТАТИСТИКИ ====================

    def merge(self, other: "SyncStatistics") -> None:
        """Объединение статистики из другого объекта"""
        # Объединение счетчиков
        self.total_data_types += other.total_data_types
        self.processed_data_types += other.processed_data_types
        self.failed_data_types += other.failed_data_types

        self.total_inserted += other.total_inserted
        self.total_updated += other.total_updated
        self.total_deleted += other.total_deleted
        self.total_unchanged += other.total_unchanged
        self.total_skipped_upsert += other.total_skipped_upsert
        self.total_skipped_delete += other.total_skipped_delete
        self.total_error_records += other.total_error_records

        self.total_received += other.total_received
        self.total_received_upsert += other.total_received_upsert
        self.total_received_delete += other.total_received_delete

        # Объединение множеств
        self.tables_with_inserts.update(other.tables_with_inserts)
        self.tables_with_updates.update(other.tables_with_updates)
        self.tables_with_deletes.update(other.tables_with_deletes)
        self.tables_with_errors.update(other.tables_with_errors)
        self.tables_with_unchanged.update(other.tables_with_unchanged)
        self.tables_with_skipped.update(other.tables_with_skipped)

        # Объединение детальной статистики по таблицам
        for table_name, stats in other.table_stats.items():
            if table_name not in self.table_stats:
                self.table_stats[table_name] = defaultdict(int)
            for key, value in stats.items():
                self.table_stats[table_name][key] += value

        # Объединение ошибок
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
            "tables_with_unchanged": sorted(self.tables_with_unchanged),
            "tables_with_skipped": sorted(self.tables_with_skipped),
            "total_inserted": int(self.total_inserted),
            "total_updated": int(self.total_updated),
            "total_deleted": int(self.total_deleted),
            "total_unchanged": int(self.total_unchanged),
            "total_skipped_upsert": int(self.total_skipped_upsert),
            "total_skipped_delete": int(self.total_skipped_delete),
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
        """
        Вывод отчета в консоль.

        Поля отчета:
            - Recv:    Получено записей
            - DelRecv: Получено записей на удаление
            - Ins:     Вставлено
            - Upd:     Обновлено
            - Del:     Удалено
            - Err:     Записей с ошибками
            - ErrTbl:  Таблиц с ошибками
            - UncUpd:  Пропущено при UPSERT
            - UncDel:  Пропущено при DELETE
            - UserOk:  Пользователей успешно
            - UserErr: Пользователей с ошибками
            - Status:  Статус
        """
        if self._suppress_report:
            return

        has_changes = (
            self.total_inserted > 0
            or self.total_updated > 0
            or self.total_deleted > 0
            or self.total_unchanged > 0
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

        all_tables = sorted(
            set(self.table_stats.keys())
            | set(self.tables_with_inserts)
            | set(self.tables_with_updates)
            | set(self.tables_with_deletes)
            | set(self.tables_with_errors)
            | set(self.tables_with_unchanged)
            | set(self.tables_with_skipped)
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
                or stats.get("skipped_upsert", 0) > 0
                or stats.get("skipped_delete", 0) > 0
                or stats.get("unchanged", 0) > 0
            ):
                filtered_tables.append(table)

        if not filtered_tables:
            if has_received_data:
                app_logger.info(f"✅ {title}: Received {self.total_received} records but no changes detected")
            else:
                app_logger.info(f"✅ {title}: No changes detected")
            return

        max_table_len = 45
        for table in filtered_tables:
            if len(table) > max_table_len:
                max_table_len = len(table)
        if max_table_len > 80:
            max_table_len = 80

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
        total_errors = 0  # ErrTbl
        total_error_records = 0  # Err
        total_skipped_upsert = 0
        total_skipped_delete = 0
        total_unchanged = 0

        for table in filtered_tables:
            stats = self.table_stats.get(table, {})
            received_upsert = stats.get("received_upsert", 0)
            received_delete = stats.get("received_delete", 0)
            inserted = stats.get("inserted", 0)
            updated = stats.get("updated", 0)
            deleted = stats.get("deleted", 0)
            errors = stats.get("errors", 0)  # ErrTbl
            error_records = stats.get("error_records", 0)  # Err
            skipped_upsert = stats.get("skipped_upsert", 0)
            skipped_delete = stats.get("skipped_delete", 0)
            unchanged = stats.get("unchanged", 0)
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
            total_skipped_upsert += skipped_upsert
            total_skipped_delete += skipped_delete
            total_unchanged += unchanged

            if errors > 0 or error_records > 0:
                status = "  ❌ ERROR"
            elif inserted > 0 or updated > 0 or deleted > 0:
                status = "  ✅ OK"
            elif skipped_upsert > 0 or skipped_delete > 0:
                status = "  ⚠️ SKIP"
            elif unchanged > 0:
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
                f"{skipped_upsert:>8} "
                f"{skipped_delete:>8} "
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
            f"{total_skipped_upsert:>8} "
            f"{total_skipped_delete:>8} "
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
        self._model_columns_cache: dict[Any, set[str]] = {}

        from ..models.avanpost import AVANPOST_BASE_DATA_TYPES, AVANPOST_USER_DATA_TYPES

        self.base_data_types = AVANPOST_BASE_DATA_TYPES
        self.user_data_types = AVANPOST_USER_DATA_TYPES

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
                self._data_type_cache = await SystemRepository.get_data_types_dict(sess)
        else:
            self._data_type_cache = await SystemRepository.get_data_types_dict(session)

        self._initialized = True
        app_logger.info(f"✅ AvanpostSyncService initialized with {len(self._data_type_cache)} data types")

    @staticmethod
    def _get_model_by_data_type(data_type_id: int) -> Any:
        """Получение модели по типу данных."""
        from ..models.avanpost import get_avanpost_model

        return get_avanpost_model(data_type_id)

    @staticmethod
    def _get_table_name(data_type_id: int) -> str | None:
        """Получение имени таблицы по типу данных."""
        from ..models.avanpost import get_avanpost_table_name

        return get_avanpost_table_name(data_type_id)

    def _get_model_columns(self, model: Any, include_all: bool = True) -> set[str]:
        """
        Получение списка колонок модели.

        Args:
            model: Модель SQLAlchemy
            include_all: Если True - все колонки, если False - только первичный ключ
        """
        cache_key = (model, include_all)
        if cache_key in self._model_columns_cache:
            return self._model_columns_cache[cache_key]

        all_columns = {column.name for column in model.__table__.columns}

        if include_all:
            result = all_columns
        else:
            # Возвращение только колонок первичного ключа
            pk_columns = {col.name for col in model.__table__.primary_key.columns}
            result = pk_columns

        self._model_columns_cache[cache_key] = result
        return result

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

            chunk_size = 10
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

            current_time = datetime_now()
            sync_times: dict[int, datetime] = {}

            for dt_id in all_requested_types:
                sync_times[dt_id] = current_time

            if all_data_items:
                if settings.is_development:
                    app_logger.debug("=" * 80)
                    app_logger.debug("📋 ORDER FROM JSON (as received from Avanpost)")
                    app_logger.debug("=" * 80)

                    for idx, data_item in enumerate(all_data_items, 1):
                        data_type_raw = data_item.get("DataTypeId")
                        flag_expire = data_item.get("FlagExpire")
                        records = data_item.get("Data", [])

                        if data_type_raw is not None:
                            data_type_id_val = data_type_raw
                            model = self._get_model_by_data_type(data_type_id_val)
                            model_name = (model.__name__ if model else "UNKNOWN") or "UNKNOWN"
                            table_name = self._get_table_name(data_type_id_val) or "UNKNOWN"
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

                    flag_expire = data_item.get("FlagExpire")
                    data_type_for_table[table_name] = current_dt_id

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

                for table_name in set(delete_order) | set(upsert_order):
                    upsert_count = len(upsert_records_by_table.get(table_name, []))
                    delete_count = len(delete_records_by_table.get(table_name, []))
                    stats.add_received(table_name, upsert_count, delete_count)

                # DELETE
                async with db_manager.get_session() as session:
                    for table_name in delete_order:
                        records = delete_records_by_table[table_name]
                        dt_id_raw = data_type_for_table.get(table_name)

                        if dt_id_raw is None or not records:
                            continue

                        dt_id_val_delete: int = dt_id_raw
                        model = self._get_model_by_data_type(dt_id_val_delete)
                        if not model:
                            app_logger.warning(f"⚠️ No model found for DataTypeId {dt_id_val_delete}")
                            continue

                        # Получаем имена колонок первичного ключа
                        pk_columns = [col.name for col in model.__table__.primary_key.columns]

                        # Оставляем только колонки первичного ключа
                        clean_records = []
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
                            # Используем GenericRepository.delete_records_bulk для удаления
                            deleted, skipped, errors = await GenericRepository.delete_records_bulk(
                                session=session,
                                model=model,
                                records=clean_records,
                                primary_keys=pk_columns,
                                chunk_size=1000,
                                raise_on_error=False,
                            )

                            # Обновляем статистику
                            if deleted > 0:
                                stats.add_delete(table_name, deleted)
                            if skipped > 0:
                                stats.add_skip_delete(table_name, skipped)
                            if errors > 0:
                                stats.add_error_records(table_name, errors)
                                stats.add_error(table_name, f"DELETE errors: {errors} records")

                            app_logger.debug(
                                f"🗑️ DELETE result for {table_name}: "
                                f"deleted={deleted}, skipped={skipped}, errors={errors}"
                            )

                        except Exception as e:
                            stats.add_error(table_name, str(e))
                            app_logger.error(f"❌ Failed to DELETE from {table_name}: {e}")
                            await session.rollback()

                # UPSERT
                async with db_manager.get_session() as session:
                    for table_name in upsert_order:
                        records = upsert_records_by_table[table_name]
                        dt_id_raw = data_type_for_table.get(table_name)

                        if dt_id_raw is None:
                            app_logger.warning(f"⚠️ No data type ID found for table {table_name}, skipping")
                            continue

                        if not records:
                            continue

                        dt_id_val_upsert: int = dt_id_raw
                        model = self._get_model_by_data_type(dt_id_val_upsert)
                        if not model:
                            app_logger.warning(f"⚠️ No model found for DataTypeId {dt_id_val_upsert}")
                            continue

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

                        model_columns_for_upsert = self._get_model_columns(model, include_all=True)

                        try:
                            result = await GenericRepository.save_data_bulk(
                                session=session,
                                model=model,
                                records=filtered_records,
                                model_columns=model_columns_for_upsert,
                                raise_on_error=False,
                                commit_chunks=True,
                            )
                            stats.processed_data_types += 1

                            # ============================================================
                            # ИСПРАВЛЕНО: корректная обработка статистики UPSERT
                            # ============================================================
                            if result.get("inserted", 0) > 0:
                                stats.add_insert(table_name, result["inserted"])
                            if result.get("updated", 0) > 0:
                                stats.add_update(table_name, result["updated"])
                            if result.get("deleted", 0) > 0:
                                stats.add_delete(table_name, result["deleted"])
                            if result.get("unchanged", 0) > 0:
                                stats.add_unchanged(table_name, result["unchanged"])
                            if result.get("skipped_upsert", 0) > 0:
                                stats.add_skip_upsert(table_name, result["skipped_upsert"])
                            if result.get("skipped_delete", 0) > 0:
                                stats.add_skip_delete(table_name, result["skipped_delete"])
                            if result.get("error_records", 0) > 0:
                                stats.add_error_records(table_name, result["error_records"])

                            app_logger.debug(
                                f"✅ UPSERT result for {table_name}: "
                                f"inserted={result.get('inserted', 0)}, "
                                f"updated={result.get('updated', 0)}, "
                                f"deleted={result.get('deleted', 0)}, "
                                f"unchanged={result.get('unchanged', 0)}, "
                                f"skipped_upsert={result.get('skipped_upsert', 0)}, "
                                f"skipped_delete={result.get('skipped_delete', 0)}, "
                                f"error_records={result.get('error_records', 0)}"
                            )
                        except Exception as e:
                            stats.add_error(table_name, str(e))
                            app_logger.error(f"❌ Failed to UPSERT {table_name}: {e}")
                            await session.rollback()

                app_logger.info("✅ Base data synchronization completed")
            else:
                app_logger.debug("ℹ️ No data received from procedure")

            if sync_times:
                await self._update_sync_times(sync_times)
                app_logger.info(f"✅ Updated sync times for {len(sync_times)} data types (all requested)")

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

    async def sync_user_data(self, user_id: int, force: bool = False, suppress_report: bool = True) -> SyncStatistics:
        """
        Синхронизация данных пользователя с детальной статистикой.
        """
        import json

        stats = SyncStatistics()
        stats.start()
        stats.total_data_types = len(self.user_data_types)
        stats.suppress_report(suppress_report)
        stats.set_current_user(user_id)

        app_logger.debug(f"🔄 Starting user data synchronization for user {user_id}...")

        try:
            last_sync_by_type = await self._get_sync_times_for_types(self.user_data_types, user_id)

            chunk_size = 10
            chunks = [self.user_data_types[i : i + chunk_size] for i in range(0, len(self.user_data_types), chunk_size)]

            all_data_items: list[dict[str, Any]] = []
            all_requested_types: set[int] = set()

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

                for table_name in set(delete_order) | set(upsert_order):
                    upsert_count = len(upsert_records_by_table.get(table_name, []))
                    delete_count = len(delete_records_by_table.get(table_name, []))
                    stats.add_received(table_name, upsert_count, delete_count)

                # ============ DELETE (ИСПРАВЛЕНО) ============
                async with db_manager.get_session() as session:
                    for table_name in delete_order:
                        records = delete_records_by_table[table_name]
                        dt_id_raw = data_type_for_table.get(table_name)

                        if dt_id_raw is None or not records:
                            continue

                        dt_id_val_user_delete: int = dt_id_raw
                        model = self._get_model_by_data_type(dt_id_val_user_delete)
                        if not model:
                            continue

                        # Получаем колонки первичного ключа
                        pk_columns = [col.name for col in model.__table__.primary_key.columns]

                        # Оставляем только первичные ключи
                        clean_records = []
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
                            # Используем delete_records_bulk для удаления
                            deleted, skipped, errors = await GenericRepository.delete_records_bulk(
                                session=session,
                                model=model,
                                records=clean_records,
                                primary_keys=pk_columns,
                                chunk_size=1000,
                                raise_on_error=False,
                            )

                            if deleted > 0:
                                stats.add_delete(table_name, deleted)
                            if skipped > 0:
                                stats.add_skip_delete(table_name, skipped)
                            if errors > 0:
                                stats.add_error_records(table_name, errors)
                                stats.add_error(table_name, f"DELETE errors: {errors} records")

                            app_logger.debug(
                                f"🗑️ DELETE result for {table_name}: "
                                f"deleted={deleted}, skipped={skipped}, errors={errors}"
                            )

                        except Exception as e:
                            stats.add_error(table_name, str(e))
                            app_logger.error(f"❌ Failed to DELETE from {table_name}: {e}")
                            app_logger.error(
                                f"   Problematic records (first 3): {json.dumps(clean_records[:3], ensure_ascii=False, default=str, indent=2)}"
                            )
                            await session.rollback()

                # ============ UPSERT ============
                async with db_manager.get_session() as session:
                    for table_name in upsert_order:
                        records = upsert_records_by_table[table_name]
                        dt_id_raw = data_type_for_table.get(table_name)

                        if dt_id_raw is None or not records:
                            continue

                        dt_id_val_user_upsert: int = dt_id_raw
                        model = self._get_model_by_data_type(dt_id_val_user_upsert)
                        if not model:
                            continue

                        model_columns = self._get_model_columns(model)

                        # Разбиваем на чанки
                        chunk_size = 1000
                        total_chunks = (len(records) + chunk_size - 1) // chunk_size

                        table_inserted = 0
                        table_updated = 0
                        table_deleted = 0
                        table_skipped = 0
                        table_unchanged = 0
                        table_errors = 0
                        table_error_records = 0

                        for chunk_idx in range(0, len(records), chunk_size):
                            chunk_records = records[chunk_idx : chunk_idx + chunk_size]

                            # Фильтруем записи с NULL в обязательных полях
                            required_fields = [col.name for col in model.__table__.columns if not col.nullable]

                            filtered_records = []
                            skipped_records = []

                            for rec in chunk_records:
                                if not isinstance(rec, dict):
                                    continue
                                has_null = False
                                for req_field in required_fields:
                                    if req_field in rec and rec[req_field] is None:
                                        has_null = True
                                        break
                                if has_null:
                                    skipped_records.append(rec)
                                else:
                                    filtered_records.append(rec)

                            if skipped_records:
                                stats.add_skip_upsert(table_name, len(skipped_records))
                                table_skipped += len(skipped_records)

                            if not filtered_records:
                                continue

                            try:
                                result = await GenericRepository.save_data_bulk(
                                    session=session,
                                    model=model,
                                    records=filtered_records,
                                    model_columns=model_columns,
                                    raise_on_error=True,
                                    commit_chunks=True,
                                )

                                # Коммитим успешный чанк
                                await session.commit()

                                # Обновляем статистику
                                inserted = result.get("inserted", 0)
                                updated = result.get("updated", 0)
                                deleted = result.get("deleted", 0)
                                unchanged = result.get("unchanged", 0)
                                skipped_upsert = result.get("skipped_upsert", 0)
                                skipped_delete = result.get("skipped_delete", 0)
                                error_records = result.get("error_records", 0)

                                table_inserted += inserted
                                table_updated += updated
                                table_skipped += skipped_upsert
                                table_unchanged += unchanged
                                table_error_records += error_records

                                stats.processed_data_types += 1

                                if inserted > 0:
                                    stats.add_insert(table_name, inserted)
                                if updated > 0:
                                    stats.add_update(table_name, updated)
                                if deleted > 0:
                                    stats.add_delete(table_name, deleted)
                                if unchanged > 0:
                                    stats.add_unchanged(table_name, unchanged)
                                if skipped_upsert > 0:
                                    stats.add_skip_upsert(table_name, skipped_upsert)
                                if skipped_delete > 0:
                                    stats.add_skip_delete(table_name, skipped_delete)
                                if error_records > 0:
                                    stats.add_error_records(table_name, error_records)

                                if chunk_size == 0:
                                    app_logger.debug(
                                        f"✅ Chunk {chunk_idx // chunk_size + 1}/{total_chunks} for {table_name}: "
                                        f"inserted={inserted}, updated={updated}, deleted={deleted}, unchanged={unchanged}"
                                    )

                            except Exception as e:
                                table_errors += 1
                                table_error_records += len(filtered_records)
                                await session.rollback()

                                error_msg = f"Chunk {chunk_idx // chunk_size + 1}/{total_chunks} failed: {str(e)[:200]}"
                                stats.add_error(table_name, error_msg)

                                app_logger.error(
                                    f"❌ Failed to UPSERT {table_name} (chunk {chunk_idx // chunk_size + 1}/{total_chunks}): {e}"
                                )
                                app_logger.error(
                                    f"   Problematic records (first 3): {json.dumps(filtered_records[:3], ensure_ascii=False, default=str, indent=2)}"
                                )

                                # Пропускаем оставшиеся чанки при ошибке
                                break

                        # Логируем итоги по таблице
                        if table_inserted > 0 or table_updated > 0 or table_deleted > 0 or table_skipped > 0:
                            app_logger.info(
                                f"✅ Table {table_name} completed: "
                                f"inserted={table_inserted}, "
                                f"updated={table_updated}, "
                                f"deleted={table_deleted}, "
                                f"skipped={table_skipped}, "
                                f"unchanged={table_unchanged}, "
                                f"errors={table_errors}, "
                                f"error_records={table_error_records}"
                            )
                        elif table_errors > 0:
                            app_logger.warning(
                                f"⚠️ Table {table_name} failed: {table_errors} chunks with errors, {table_skipped} skipped records"
                            )

                current_time = datetime_now()
                sync_times: dict[int, datetime] = {}

                for dt_id in all_requested_types:
                    sync_times[dt_id] = current_time

                if sync_times:
                    await self._update_sync_times(sync_times, user_id)

            # ============ ВАЖНО: возвращаем stats ВСЕГДА ============
            stats.finish()
            stats.finalize_user()

            # Если не было данных, но статистика пустая - все равно возвращаем stats
            return stats

        except Exception as e:
            stats.add_error("__global__", str(e))
            stats.finish()
            app_logger.error(f"❌ Failed to sync user data for user {user_id}: {e}")
            app_logger.error(f"   Context: user_id={user_id}, force={force}, data_types={self.user_data_types[:10]}...")
            import traceback

            app_logger.error(f"📄 Traceback: {traceback.format_exc()}")
            raise

    # ==================== СИНХРОНИЗАЦИЯ ВСЕХ ПОЛЬЗОВАТЕЛЕЙ ====================

    async def sync_all_users(self, force: bool = False) -> dict[str, Any]:
        """Синхронизация всех пользователей с агрегированной статистикой."""
        app_logger.info("🔄 Starting all users synchronization...")

        all_stats = SyncStatistics()
        all_stats.start()

        async with db_manager.get_session() as session:
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
                "total_unchanged": all_stats.total_unchanged,
                "total_skipped_upsert": all_stats.total_skipped_upsert,
                "total_skipped_delete": all_stats.total_skipped_delete,
                "total_received": all_stats.total_received,
                "total_received_upsert": all_stats.total_received_upsert,
                "total_received_delete": all_stats.total_received_delete,
                "errors": errors_list,
            }

            all_stats.print_report("All Users Sync Report", force=True)

            return result_stats

    # ==================== ПОЛНАЯ СИНХРОНИЗАЦИЯ ====================

    async def sync_all(self, force: bool = False) -> dict[str, Any]:
        """Полная синхронизация всех данных."""
        app_logger.info("🔄 Starting full synchronization...")

        base_stats = await self.sync_base_data(force)
        user_stats = await self.sync_all_users(force)

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
