import datetime
from typing import Any, TypeVar

from sqlalchemy import and_, delete, or_, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from ...logger import db_logger
from ...utils.log_helpers import LogHelper

ModelType = TypeVar("ModelType", bound=Any)


class GenericRepository:
    """Универсальный репозиторий для общих операций с БД."""

    # Лимит параметров PostgreSQL
    MAX_POSTGRES_PARAMS = 32767

    @staticmethod
    def _convert_str_to_datetime(value: Any) -> Any:
        """
        Конвертирование строки ISO в datetime.datetime.
        Поддержка форматов:
        - 2026-06-06T16:30:37.457
        - 2026-06-06T16:30:37.457Z
        - 2026-06-06 16:30:37.457
        - 2026-06-06T16:30:37
        """
        if isinstance(value, str):
            try:
                normalized = value.replace("Z", "+00:00")
                return datetime.datetime.fromisoformat(normalized)
            except (ValueError, TypeError):
                try:
                    return datetime.datetime.strptime(value, "%Y-%m-%d %H:%M:%S.%f")
                except (ValueError, TypeError):
                    try:
                        return datetime.datetime.strptime(value, "%Y-%m-%dT%H:%M:%S")
                    except (ValueError, TypeError):
                        return value
        return value

    @staticmethod
    def _convert_record_types(model: Any, record: dict[str, Any]) -> dict[str, Any]:
        """Конвертирование значений в соответствии с типами колонок модели"""
        converted = record.copy()

        datetime_columns = []
        date_columns = []

        for column in model.__table__.columns:
            col_type = column.type
            col_type_str = str(col_type).lower()

            if isinstance(col_type, datetime.datetime | datetime.date):
                if isinstance(col_type, datetime.datetime):
                    datetime_columns.append(column.name)
                elif isinstance(col_type, datetime.date):
                    date_columns.append(column.name)
            elif "datetime" in col_type_str or "timestamp" in col_type_str:
                datetime_columns.append(column.name)
            elif "date" in col_type_str and "datetime" not in col_type_str:
                date_columns.append(column.name)

        for col in datetime_columns:
            if col in converted and isinstance(converted[col], str):
                converted[col] = GenericRepository._convert_str_to_datetime(converted[col])

        for col in date_columns:
            if col in converted and isinstance(converted[col], str):
                dt = GenericRepository._convert_str_to_datetime(converted[col])
                if isinstance(dt, datetime.datetime):
                    converted[col] = dt.date()
                elif isinstance(dt, datetime.date):
                    converted[col] = dt

        return converted

    @staticmethod
    def _calculate_safe_chunk_size(
        chunk_size: int,
        num_columns: int,
        operation_type: str = "upsert",
    ) -> int:
        """Расчет безопасного размера чанка для обхода лимита PostgreSQL."""
        if num_columns <= 0:
            return chunk_size

        if operation_type == "upsert":
            estimated_params_per_record = num_columns * 2 + 10
        elif operation_type == "delete":
            estimated_params_per_record = 1
        else:
            estimated_params_per_record = num_columns

        max_records = GenericRepository.MAX_POSTGRES_PARAMS // max(1, estimated_params_per_record)
        safe_chunk_size = max(1, min(chunk_size, max_records))

        if safe_chunk_size < chunk_size:
            db_logger.warning(
                f"⚠️ Chunk size reduced from {chunk_size} to {safe_chunk_size} "
                f"due to PostgreSQL parameter limit ({num_columns} columns, "
                f"~{estimated_params_per_record} params/record, operation={operation_type})"
            )

        return safe_chunk_size

    @staticmethod
    async def delete_records_bulk(
        session: AsyncSession,
        model: Any,
        records: list[dict[str, Any]] | dict[str, Any],
        primary_keys: list[str],
        chunk_size: int = 1000,
        raise_on_error: bool = False,
    ) -> tuple[int, int, int]:
        """
        Массовое удаление записей по первичному ключу с разбивкой на чанки.

        Returns:
            tuple[int, int, int]: (удалено, без изменений (не найдены), ошибки)
        """
        if not records:
            return 0, 0, 0

        if isinstance(records, dict):
            records_list = [records]
        elif isinstance(records, list):
            records_list = records
        else:
            db_logger.warning(f"⚠️ Unexpected records type: {type(records)}")
            return 0, 0, 0

        delete_ids = []
        for record in records_list:
            if not isinstance(record, dict):
                continue
            # Извлекаем ТОЛЬКО первичные ключи
            if all(pk in record for pk in primary_keys):
                if len(primary_keys) == 1:
                    pk_value = record[primary_keys[0]]
                    if pk_value is not None:
                        delete_ids.append(pk_value)
                else:
                    pk_tuple = tuple(record[pk] for pk in primary_keys)
                    if all(v is not None for v in pk_tuple):
                        delete_ids.append(pk_tuple)

        if not delete_ids:
            return 0, 0, 0

        safe_chunk_size = GenericRepository._calculate_safe_chunk_size(
            chunk_size=chunk_size,
            num_columns=len(primary_keys),
            operation_type="delete",
        )

        total_deleted = 0
        total_unchanged = 0
        total_errors = 0

        for i in range(0, len(delete_ids), safe_chunk_size):
            chunk_ids = delete_ids[i : i + safe_chunk_size]

            if len(primary_keys) == 1:
                pk_col = getattr(model, primary_keys[0])
                delete_stmt = delete(model).where(pk_col.in_(chunk_ids))
                try:
                    result = await session.execute(delete_stmt)
                    rowcount = result.rowcount if hasattr(result, "rowcount") else 0
                    total_deleted += rowcount
                    total_unchanged += len(chunk_ids) - rowcount
                except Exception as e:
                    LogHelper.log_batch_error_fast(
                        logger=db_logger,
                        operation="DELETE",
                        table=model.__tablename__,
                        error=e,
                        batch_size=len(chunk_ids),
                    )
                    if raise_on_error:
                        raise
                    total_errors += len(chunk_ids)
            else:
                conditions = []
                for pk_tuple in chunk_ids:
                    if isinstance(pk_tuple, tuple):
                        cond = and_(
                            *[getattr(model, pk) == value for pk, value in zip(primary_keys, pk_tuple, strict=False)]
                        )
                        conditions.append(cond)

                if conditions:
                    delete_stmt = delete(model).where(or_(*conditions))
                    try:
                        result = await session.execute(delete_stmt)
                        rowcount = result.rowcount if hasattr(result, "rowcount") else 0
                        total_deleted += rowcount
                        total_unchanged += len(chunk_ids) - rowcount
                    except Exception as e:
                        LogHelper.log_batch_error_fast(
                            logger=db_logger,
                            operation="DELETE",
                            table=model.__tablename__,
                            error=e,
                            batch_size=len(chunk_ids),
                        )
                        if raise_on_error:
                            raise
                        total_errors += len(chunk_ids)

        return total_deleted, total_unchanged, total_errors

    @staticmethod
    async def upsert_records_bulk(
        session: AsyncSession,
        model: Any,
        records: list[dict[str, Any]],
        primary_keys: list[str],
        model_columns: set[str] | None = None,
        chunk_size: int = 1000,
        raise_on_error: bool = False,
    ) -> dict[str, int]:
        """
        Массовое обновление или вставка записей (UPSERT) с корректным подсчётом статистики.

        Returns:
            dict: {
                "inserted": количество ВСТАВЛЕННЫХ записей (новые записи),
                "updated": количество ОБНОВЛЕННЫХ записей (были изменения),
                "unchanged": количество записей БЕЗ ИЗМЕНЕНИЙ (уже существовали и не изменились),
                "error_records": количество записей с ошибками,
            }
        """
        if not records:
            return {"inserted": 0, "updated": 0, "unchanged": 0, "error_records": 0}

        if model_columns is None:
            model_columns = {column.name for column in model.__table__.columns}

        # 1. Нормализация записей
        normalized_records = []
        for rec in records:
            if not isinstance(rec, dict):
                continue
            # Конвертация типов данных
            normalized_records.append(GenericRepository._convert_record_types(model, rec))

        if not normalized_records:
            return {"inserted": 0, "updated": 0, "unchanged": 0, "error_records": 0}

        records = normalized_records

        # 2. Определение безопасного размера чанка
        num_columns = len(model_columns)
        safe_chunk_size = GenericRepository._calculate_safe_chunk_size(
            chunk_size=chunk_size,
            num_columns=num_columns,
            operation_type="upsert",
        )
        select_chunk_size = min(safe_chunk_size, 1000)

        # 3. Загрузка существующих записей из БД
        # Использование словаря с нормализованными ключами
        existing_records: dict[Any, Any] = {}

        if len(primary_keys) == 1:
            pk_col = getattr(model, primary_keys[0])
            # Сбор всех значений PK из записей
            pk_values = set()
            for rec in records:
                pk_val = rec.get(primary_keys[0])
                if pk_val is not None:
                    pk_values.add(pk_val)

            if pk_values:
                # Разбивка на чанки для SELECT
                pk_list = list(pk_values)
                for i in range(0, len(pk_list), select_chunk_size):
                    chunk = pk_list[i : i + select_chunk_size]
                    try:
                        select_stmt = select(model).where(pk_col.in_(chunk))
                        result = await session.execute(select_stmt)
                        db_records = result.scalars().all()
                        for db_rec in db_records:
                            db_pk_val = getattr(db_rec, primary_keys[0])
                            # Сохранение с нормализованным ключом (как в БД)
                            existing_records[db_pk_val] = db_rec
                    except Exception:
                        if raise_on_error:
                            raise
                        # При ошибке загрузки пропускаем чанк
                        continue
        else:
            # Составной первичный ключ
            all_keys: list[tuple[Any, ...]] = []
            for rec in records:
                key_values = tuple(rec.get(pk) for pk in primary_keys)
                if all(k is not None for k in key_values):
                    all_keys.append(key_values)

            if all_keys:
                for i in range(0, len(all_keys), select_chunk_size):
                    keys_chunk = all_keys[i : i + select_chunk_size]
                    conditions = []
                    for key_tuple in keys_chunk:
                        cond = and_(
                            *[getattr(model, pk) == value for pk, value in zip(primary_keys, key_tuple, strict=False)]
                        )
                        conditions.append(cond)
                    if conditions:
                        try:
                            select_stmt = select(model).where(or_(*conditions))
                            result = await session.execute(select_stmt)
                            db_records = result.scalars().all()
                            for db_rec in db_records:
                                # Формирование ключа как tuple
                                key = tuple(getattr(db_rec, pk) for pk in primary_keys)
                                existing_records[key] = db_rec
                        except Exception:
                            if raise_on_error:
                                raise
                            continue

        # 4. Классификация записей
        insert_records: list[dict[str, Any]] = []
        update_records: list[dict[str, Any]] = []
        unchanged_records: list[dict[str, Any]] = []
        error_records: list[dict[str, Any]] = []

        for rec in records:
            try:
                # Поиск существующей записи
                db_rec = None
                found = False

                if len(primary_keys) == 1:
                    pk_val = rec.get(primary_keys[0])
                    if pk_val is not None:
                        # Прямой поиск по точному значению
                        if pk_val in existing_records:
                            db_rec = existing_records[pk_val]
                            found = True
                        else:
                            # Поиск по строковому представлению (для разных типов)
                            pk_str = str(pk_val)
                            for existing_pk, existing_db_rec in existing_records.items():
                                if str(existing_pk) == pk_str:
                                    db_rec = existing_db_rec
                                    found = True
                                    break
                else:
                    # Составной ключ
                    key_tuple = tuple(rec.get(pk) for pk in primary_keys)
                    if all(k is not None for k in key_tuple):
                        if key_tuple in existing_records:
                            db_rec = existing_records[key_tuple]
                            found = True
                        else:
                            # Поиск по строковому представлению для составного ключа
                            key_str = tuple(str(k) for k in key_tuple)
                            for existing_key, existing_db_rec in existing_records.items():
                                if tuple(str(k) for k in existing_key) == key_str:
                                    db_rec = existing_db_rec
                                    found = True
                                    break

                if not found or db_rec is None:
                    # Запись не найдена → INSERT
                    insert_records.append(rec)
                    continue

                # 5. Проверка изменений
                has_changes = False
                for col in model_columns:
                    if col in primary_keys:
                        continue
                    new_val = rec.get(col)
                    old_val = getattr(db_rec, col, None)

                    # Сравнение с учётом None и типов
                    if new_val is None and old_val is None:
                        continue
                    if new_val is None or old_val is None:
                        has_changes = True
                        break

                    # Для строк — обрезаем пробелы
                    if isinstance(new_val, str) and isinstance(old_val, str):
                        new_val = new_val.strip()
                        old_val = old_val.strip()

                    if new_val != old_val:
                        has_changes = True
                        break

                if has_changes:
                    update_records.append(rec)
                else:
                    unchanged_records.append(rec)

            except Exception:
                # Ошибка при классификации записи
                error_records.append(rec)
                if raise_on_error:
                    raise

        # 6. Выполнение UPSERT
        inserted = 0
        updated = 0
        error_records_count = len(error_records)

        # 6.1. INSERT (новые записи)
        if insert_records:
            for i in range(0, len(insert_records), safe_chunk_size):
                batch = insert_records[i : i + safe_chunk_size]
                try:
                    insert_stmt = pg_insert(model).values(batch)
                    if len(primary_keys) == 1:
                        insert_stmt = insert_stmt.on_conflict_do_nothing(index_elements=primary_keys)
                    else:
                        insert_stmt = insert_stmt.on_conflict_do_nothing(index_elements=primary_keys)
                    await session.execute(insert_stmt)
                    inserted += len(batch)
                except Exception:
                    if raise_on_error:
                        raise
                    error_records_count += len(batch)

        # 6.2. UPDATE (записи с изменениями)
        if update_records:
            # Для UPDATE используем ON CONFLICT DO UPDATE
            update_fields = [col for col in model_columns if col not in primary_keys]
            for i in range(0, len(update_records), safe_chunk_size):
                batch = update_records[i : i + safe_chunk_size]
                try:
                    if update_fields:
                        upsert_stmt = pg_insert(model).values(batch)
                        upsert_stmt = upsert_stmt.on_conflict_do_update(
                            index_elements=primary_keys,
                            set_={col: getattr(upsert_stmt.excluded, col) for col in update_fields},
                        )
                    else:
                        upsert_stmt = pg_insert(model).values(batch).on_conflict_do_nothing()
                    await session.execute(upsert_stmt)
                    updated += len(batch)
                except Exception:
                    if raise_on_error:
                        raise
                    error_records_count += len(batch)

        # 7. Возврат статистики
        return {
            "inserted": inserted,
            "updated": updated,
            "unchanged": len(unchanged_records),
            "error_records": error_records_count,
        }

    @staticmethod
    async def save_data_bulk(
        session: AsyncSession,
        model: Any,
        records: list[dict[str, Any]] | dict[str, Any],
        model_columns: set[str],
        chunk_size: int = 1000,
        raise_on_error: bool = False,
        commit_chunks: bool = False,
    ) -> dict[str, int]:
        """
        Массовое сохранение данных с использованием UPSERT.

        Args:
            session: Асинхронная сессия SQLAlchemy
            model: Модель SQLAlchemy для работы с таблицей
            records: Список записей для сохранения (или одна запись)
            model_columns: Множество имен колонок модели для фильтрации данных
            chunk_size: Размер чанка для пакетной обработки
            raise_on_error: Поднимать исключение при ошибке или продолжать
            commit_chunks: Коммитить каждый чанк отдельно (для больших таблиц)

        Returns:
            dict: Статистика операций
                - inserted: количество вставленных записей
                - updated: количество обновленных записей
                - deleted: количество удаленных записей
                - unchanged_upsert: количество записей без изменений при UPSERT
                - unchanged_delete: количество записей без изменений при DELETE
                - error_records: количество записей с ошибками

        Note:
            Записи с FlagExpire=1 или True обрабатываются как DELETE.
            Остальные записи обрабатываются как UPSERT (INSERT или UPDATE).
        """
        if not records:
            return {
                "inserted": 0,
                "updated": 0,
                "deleted": 0,
                "unchanged_upsert": 0,
                "unchanged_delete": 0,
                "error_records": 0,
            }

        if isinstance(records, dict):
            records_list = [records]
        elif isinstance(records, list):
            records_list = records
        else:
            return {
                "inserted": 0,
                "updated": 0,
                "deleted": 0,
                "unchanged_upsert": 0,
                "unchanged_delete": 0,
                "error_records": 0,
            }

        # Конвертирование записей
        converted_records_list = []
        for rec in records_list:
            if isinstance(rec, dict):
                converted_records_list.append(GenericRepository._convert_record_types(model, rec))
            else:
                converted_records_list.append(rec)
        records_list = converted_records_list

        num_columns = len(model_columns)
        safe_chunk_size = GenericRepository._calculate_safe_chunk_size(
            chunk_size=chunk_size,
            num_columns=num_columns,
            operation_type="upsert",
        )

        # Получаем первичные ключи модели
        primary_keys = [col.name for col in model.__table__.primary_key.columns]

        delete_records = []
        upsert_records = []

        for rec in records_list:
            if not isinstance(rec, dict):
                continue

            flag_expire = rec.get("FlagExpire")

            if flag_expire == 1 or flag_expire is True:
                # Для удаления используем ТОЛЬКО первичные ключи
                if primary_keys:
                    clean_delete_record = {}
                    for pk in primary_keys:
                        if pk in rec:
                            clean_delete_record[pk] = rec[pk]
                    if clean_delete_record:
                        delete_records.append(clean_delete_record)
                else:
                    db_logger.warning(f"⚠️ No primary keys for {model.__tablename__}, skipping DELETE")
            else:
                clean_record = {}
                for col in model_columns:
                    clean_record[col] = rec.get(col)
                if clean_record:
                    upsert_records.append(clean_record)

        total_inserted = 0
        total_updated = 0
        total_deleted = 0
        total_unchanged_upsert = 0
        total_unchanged_delete = 0
        total_error_records = 0

        # DELETE
        if delete_records and primary_keys:
            if commit_chunks:
                delete_chunk_size = min(safe_chunk_size, 1000)
                for i in range(0, len(delete_records), delete_chunk_size):
                    chunk = delete_records[i : i + delete_chunk_size]
                    try:
                        deleted, unchanged, errors = await GenericRepository.delete_records_bulk(
                            session=session,
                            model=model,
                            records=chunk,
                            primary_keys=primary_keys,
                            chunk_size=delete_chunk_size,
                            raise_on_error=False,
                        )
                        total_deleted += deleted
                        total_unchanged_delete += unchanged
                        total_error_records += errors
                        if commit_chunks:
                            await session.commit()
                    except Exception as e:
                        db_logger.warning(f"⚠️ DELETE chunk failed for {model.__tablename__}: {e}")
                        await session.rollback()
                        if raise_on_error:
                            raise
            else:
                deleted, unchanged, errors = await GenericRepository.delete_records_bulk(
                    session=session,
                    model=model,
                    records=delete_records,
                    primary_keys=primary_keys,
                    chunk_size=safe_chunk_size,
                    raise_on_error=raise_on_error,
                )
                total_deleted += deleted
                total_unchanged_delete += unchanged
                total_error_records += errors

        # UPSERT
        if upsert_records:
            if not primary_keys:
                db_logger.warning(f"⚠️ No primary key for {model.__tablename__}, using all columns")
                primary_keys = list(upsert_records[0].keys())

            if commit_chunks:
                upsert_chunk_size = min(safe_chunk_size, 500)
                for i in range(0, len(upsert_records), upsert_chunk_size):
                    chunk = upsert_records[i : i + upsert_chunk_size]
                    try:
                        result = await GenericRepository.upsert_records_bulk(
                            session=session,
                            model=model,
                            records=chunk,
                            primary_keys=primary_keys,
                            model_columns=model_columns,
                            chunk_size=upsert_chunk_size,
                            raise_on_error=True,
                        )
                        total_inserted += result["inserted"]
                        total_updated += result["updated"]
                        total_unchanged_upsert += result["unchanged"]
                        total_error_records += result["error_records"]
                        if commit_chunks:
                            await session.commit()
                    except Exception as e:
                        db_logger.warning(f"⚠️ UPSERT chunk failed for {model.__tablename__}: {e}")
                        await session.rollback()
                        total_error_records += len(chunk)
                        if raise_on_error:
                            raise
            else:
                result = await GenericRepository.upsert_records_bulk(
                    session=session,
                    model=model,
                    records=upsert_records,
                    primary_keys=primary_keys,
                    model_columns=model_columns,
                    chunk_size=safe_chunk_size,
                    raise_on_error=raise_on_error,
                )
                total_inserted += result["inserted"]
                total_updated += result["updated"]
                total_unchanged_upsert += result["unchanged"]
                total_error_records += result["error_records"]

        return {
            "inserted": total_inserted,
            "updated": total_updated,
            "deleted": total_deleted,
            "unchanged_upsert": total_unchanged_upsert,
            "unchanged_delete": total_unchanged_delete,
            "error_records": total_error_records,
        }


__all__ = ["GenericRepository"]
