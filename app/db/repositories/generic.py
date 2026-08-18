from typing import Any

from sqlalchemy import and_, delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from ...logger import db_logger


class GenericRepository:
    """Универсальный репозиторий для общих операций с БД."""

    @staticmethod
    async def delete_records_bulk(
        session: AsyncSession,
        model: Any,
        records: list[dict[str, Any]] | dict[str, Any],
        primary_keys: list[str],
    ) -> int:
        """
        Массовое удаление записей по первичному ключу.

        Args:
            session: Сессия БД
            model: Модель SQLAlchemy
            records: Список записей для удаления
            primary_keys: Список полей первичного ключа

        Returns:
            int: Количество удаленных записей
        """
        if not records:
            return 0

        if isinstance(records, dict):
            records_list = [records]
        elif isinstance(records, list):
            records_list = records
        else:
            db_logger.warning(f"⚠️ Unexpected records type: {type(records)}")
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
                db_logger.warning(f"⚠️ Record missing primary key fields: {record}")

        if not delete_conditions:
            return 0

        delete_stmt = delete(model)
        if len(primary_keys) == 1:
            pk_col = getattr(model, primary_keys[0])
            delete_stmt = delete_stmt.where(pk_col.in_(delete_conditions))
        else:
            from sqlalchemy import or_

            conditions = []
            for pk_tuple in delete_conditions:
                cond = and_(*[getattr(model, pk) == value for pk, value in zip(primary_keys, pk_tuple, strict=False)])
                conditions.append(cond)
            delete_stmt = delete_stmt.where(or_(*conditions))

        result = await session.execute(delete_stmt)
        rowcount_raw = result.rowcount if hasattr(result, "rowcount") else 0
        rowcount: int = int(rowcount_raw) if rowcount_raw is not None else 0

        db_logger.debug(f"🗑️ Deleted {rowcount} records from {model.__tablename__}")
        return rowcount

    @staticmethod
    async def upsert_records_bulk(
        session: AsyncSession,
        model: Any,
        records: list[dict[str, Any]],
        primary_keys: list[str],
        model_columns: set[str] | None = None,
    ) -> dict[str, int]:
        """
        Массовое обновление или вставка записей (UPSERT).

        Args:
            session: Сессия БД
            model: Модель SQLAlchemy
            records: Список записей для UPSERT
            primary_keys: Список полей первичного ключа
            model_columns: Список колонок модели (опционально)

        Returns:
            dict: {inserted: int, updated: int, unchanged: int, skipped: int}
        """
        if not records:
            return {"inserted": 0, "updated": 0, "unchanged": 0, "skipped": 0}

        if model_columns is None:
            model_columns = {column.name for column in model.__table__.columns}

        # Получение существующих записей для сравнения
        existing_records = {}
        existing_ids = set()

        if len(primary_keys) == 1:
            pk_col = getattr(model, primary_keys[0])
            pk_values = [rec.get(primary_keys[0]) for rec in records if rec.get(primary_keys[0]) is not None]

            if pk_values:
                select_stmt = select(model).where(pk_col.in_(pk_values))
                result = await session.execute(select_stmt)
                db_records = result.scalars().all()
                for db_rec in db_records:
                    pk_val = getattr(db_rec, primary_keys[0])
                    existing_records[pk_val] = db_rec
            existing_ids = set(existing_records.keys())
        else:
            select_stmt = select(model)
            result = await session.execute(select_stmt)
            db_records = result.scalars().all()
            for db_rec in db_records:
                key = tuple(getattr(db_rec, pk) for pk in primary_keys)
                existing_records[key] = db_rec

        # Разделение на INSERT, UPDATE и UNCHANGED
        insert_records = []
        update_records = []
        unchanged_records = []

        for rec in records:
            if len(primary_keys) == 1:
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

                            if isinstance(new_val, str) and isinstance(old_val, str):
                                new_val = new_val.strip()
                                old_val = old_val.strip()
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
                pk_tuple = tuple(rec.get(pk) for pk in primary_keys)
                db_rec = existing_records.get(pk_tuple)

                if db_rec:
                    has_changes = False
                    for col in model_columns:
                        if col in primary_keys:
                            continue
                        new_val = rec.get(col)
                        old_val = getattr(db_rec, col, None)

                        if isinstance(new_val, str) and isinstance(old_val, str):
                            new_val = new_val.strip()
                            old_val = old_val.strip()
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

        inserted = 0
        updated = 0
        skipped = 0

        # INSERT
        if insert_records:
            batch_size = 1000
            for i in range(0, len(insert_records), batch_size):
                batch = insert_records[i : i + batch_size]
                try:
                    # Используем правильный импорт для PostgreSQL
                    from sqlalchemy.dialects.postgresql import insert as pg_insert

                    insert_stmt = pg_insert(model).values(batch)
                    if len(primary_keys) == 1:
                        insert_stmt = insert_stmt.on_conflict_do_nothing(index_elements=primary_keys)
                    await session.execute(insert_stmt)
                    inserted += len(batch)
                except Exception as e:
                    db_logger.warning(f"⚠️ INSERT failed for batch: {e}")
                    skipped += len(batch)

        # UPDATE
        if update_records:
            batch_size = 1000
            for i in range(0, len(update_records), batch_size):
                batch = update_records[i : i + batch_size]
                update_fields = [col for col in batch[0] if col not in primary_keys]

                try:
                    from sqlalchemy.dialects.postgresql import insert as pg_insert

                    if update_fields:
                        # Создаем INSERT с конфликтом и обновлением
                        upsert_stmt = pg_insert(model).values(batch)
                        upsert_stmt = upsert_stmt.on_conflict_do_update(
                            index_elements=primary_keys,
                            set_={col: getattr(upsert_stmt.excluded, col) for col in update_fields},
                        )
                        await session.execute(upsert_stmt)
                    else:
                        # Если нет полей для обновления - просто игнорируем конфликт
                        insert_stmt = pg_insert(model).values(batch)
                        insert_stmt = insert_stmt.on_conflict_do_nothing()
                        await session.execute(insert_stmt)
                    updated += len(batch)
                except Exception as e:
                    db_logger.warning(f"⚠️ UPDATE failed for batch: {e}")
                    skipped += len(batch)

        return {
            "inserted": inserted,
            "updated": updated,
            "unchanged": len(unchanged_records),
            "skipped": skipped,
        }

    @staticmethod
    async def save_data_bulk(
        session: AsyncSession,
        model: Any,
        records: list[dict[str, Any]] | dict[str, Any],
        model_columns: set[str],
        force_delete: bool = False,
    ) -> dict[str, int]:
        """
        Массовое сохранение данных с использованием UPSERT.

        Args:
            session: Сессия БД
            model: Модель SQLAlchemy
            records: Список записей для сохранения
            model_columns: Множество колонок модели
            force_delete: Принудительное удаление всех записей перед вставкой

        Returns:
            dict: {
                inserted: int,      # реально вставлены (новые записи)
                updated: int,       # реально обновлены (данные изменились)
                unchanged: int,     # получены, но данные не изменились
                skipped_upsert: int, # не вставлены/не обновлены из-за ошибок
                skipped_delete: int, # не найдены для удаления
            }
        """
        if not records:
            return {
                "inserted": 0,
                "updated": 0,
                "unchanged": 0,
                "skipped_upsert": 0,
                "skipped_delete": 0,
            }

        if isinstance(records, dict):
            records_list = [records]
        elif isinstance(records, list):
            records_list = records
        else:
            db_logger.warning(f"⚠️ Unexpected records type: {type(records)}")
            return {
                "inserted": 0,
                "updated": 0,
                "unchanged": 0,
                "skipped_upsert": len(records) if isinstance(records, list) else 1,
                "skipped_delete": 0,
            }

        # Удаление всех записей, если force_delete = True
        if force_delete:
            db_logger.debug(f"🗑️ Force delete all {len(records_list)} records from {model.__tablename__}")
            primary_keys = [col.name for col in model.__table__.primary_key.columns]
            if primary_keys:
                delete_records = []
                for rec in records_list:
                    if isinstance(rec, dict) and "FID" in rec:
                        delete_records.append({"FID": rec["FID"]})

                if delete_records:
                    deleted = await GenericRepository.delete_records_bulk(
                        session=session,
                        model=model,
                        records=delete_records,
                        primary_keys=primary_keys,
                    )
                    skipped_delete = len(delete_records) - deleted
                    db_logger.debug(
                        f"🗑️ Deleted {deleted} records from {model.__tablename__} (skipped_delete: {skipped_delete})"
                    )
                    return {
                        "inserted": 0,
                        "updated": 0,
                        "unchanged": 0,
                        "skipped_upsert": 0,
                        "skipped_delete": skipped_delete,
                    }
            return {
                "inserted": 0,
                "updated": 0,
                "unchanged": 0,
                "skipped_upsert": 0,
                "skipped_delete": len(records_list),
            }

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

        db_logger.debug(f"📊 {model.__tablename__}: DELETE={len(delete_records)}, UPSERT={len(upsert_records)}")

        total_skipped_delete = 0
        total_inserted = 0
        total_updated = 0
        total_unchanged = 0
        total_skipped_upsert = 0

        # Обработка DELETE
        if delete_records:
            primary_keys = [col.name for col in model.__table__.primary_key.columns]
            if primary_keys:
                deleted = await GenericRepository.delete_records_bulk(
                    session=session,
                    model=model,
                    records=delete_records,
                    primary_keys=primary_keys,
                )
                total_skipped_delete = len(delete_records) - deleted
                db_logger.debug(
                    f"🗑️ Deleted {deleted} records from {model.__tablename__} (skipped_delete: {total_skipped_delete})"
                )
            else:
                db_logger.warning(f"⚠️ No primary key for {model.__tablename__}, cannot delete")
                total_skipped_delete = len(delete_records)

        # Обработка UPSERT
        if upsert_records:
            # Специальная обработка для TAvanpostContactsLinks
            if model.__tablename__ == "TAvanpostContactsLinks":
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
                db_logger.warning(f"⚠️ No primary key found for {model.__tablename__}, using all columns")
                primary_keys = list(upsert_records[0].keys())

            # Получение существующих записей для сравнения
            existing_records = {}
            existing_ids = set()

            if len(primary_keys) == 1:
                pk_col = getattr(model, primary_keys[0])
                pk_values = [rec.get(primary_keys[0]) for rec in upsert_records if rec.get(primary_keys[0]) is not None]

                if pk_values:
                    select_stmt = select(model).where(pk_col.in_(pk_values))
                    result = await session.execute(select_stmt)
                    db_records = result.scalars().all()
                    for db_rec in db_records:
                        pk_val = getattr(db_rec, primary_keys[0])
                        existing_records[pk_val] = db_rec
                existing_ids = set(existing_records.keys())
            else:
                select_stmt = select(model)
                result = await session.execute(select_stmt)
                db_records = result.scalars().all()
                for db_rec in db_records:
                    key = tuple(getattr(db_rec, pk) for pk in primary_keys)
                    existing_records[key] = db_rec

            # Разделение на INSERT, UPDATE и UNCHANGED
            insert_records = []
            update_records = []
            unchanged_records = []

            for rec in upsert_records:
                if len(primary_keys) == 1:
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

                                if isinstance(new_val, str) and isinstance(old_val, str):
                                    new_val = new_val.strip()
                                    old_val = old_val.strip()
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
                    pk_tuple = tuple(rec.get(pk) for pk in primary_keys)
                    db_rec = existing_records.get(pk_tuple)

                    if db_rec:
                        has_changes = False
                        for col in model_columns:
                            if col in primary_keys:
                                continue
                            new_val = rec.get(col)
                            old_val = getattr(db_rec, col, None)

                            if isinstance(new_val, str) and isinstance(old_val, str):
                                new_val = new_val.strip()
                                old_val = old_val.strip()
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

            db_logger.debug(
                f"📊 {model.__tablename__}: "
                f"INSERT={len(insert_records)}, "
                f"UPDATE={len(update_records)}, "
                f"UNCHANGED={len(unchanged_records)}"
            )

            # Выполнение INSERT для новых записей
            if insert_records:
                batch_size = 1000
                for i in range(0, len(insert_records), batch_size):
                    batch = insert_records[i : i + batch_size]
                    try:
                        from sqlalchemy.dialects.postgresql import insert as pg_insert

                        insert_stmt = pg_insert(model).values(batch)
                        if len(primary_keys) == 1:
                            insert_stmt = insert_stmt.on_conflict_do_nothing(index_elements=primary_keys)
                        await session.execute(insert_stmt)
                        total_inserted += len(batch)
                    except Exception as e:
                        db_logger.warning(f"⚠️ INSERT failed for batch: {e}")
                        total_skipped_upsert += len(batch)
                db_logger.debug(f"✅ INSERT {len(insert_records)} new records to {model.__tablename__}")

            # Выполнение UPDATE для изменившихся записей
            if update_records:
                batch_size = 1000
                for i in range(0, len(update_records), batch_size):
                    batch = update_records[i : i + batch_size]
                    update_fields = [col for col in batch[0] if col not in primary_keys]

                    try:
                        from sqlalchemy.dialects.postgresql import insert as pg_insert

                        # Используем явный Insert для UPSERT
                        update_stmt = pg_insert(model).values(batch)
                        if update_fields:
                            update_stmt = update_stmt.on_conflict_do_update(
                                index_elements=primary_keys,
                                set_={col: getattr(update_stmt.excluded, col) for col in update_fields},
                            )
                        else:
                            update_stmt = update_stmt.on_conflict_do_nothing()
                        await session.execute(update_stmt)
                        total_updated += len(batch)
                    except Exception as e:
                        db_logger.warning(f"⚠️ UPDATE failed for batch: {e}")
                        total_skipped_upsert += len(batch)
                db_logger.debug(f"🔄 UPDATE {len(update_records)} existing records in {model.__tablename__}")

            # Записи без изменений
            if unchanged_records:
                total_unchanged = len(unchanged_records)
                db_logger.debug(
                    f"⏭️ UNCHANGED {len(unchanged_records)} records in {model.__tablename__} (no data changes)"
                )

        return {
            "inserted": total_inserted,
            "updated": total_updated,
            "unchanged": total_unchanged,
            "skipped_upsert": total_skipped_upsert,
            "skipped_delete": total_skipped_delete,
        }


__all__ = ["GenericRepository"]
