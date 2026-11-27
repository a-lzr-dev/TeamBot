"""Репозиторий для работы с мобильными клиентами"""

from __future__ import annotations

from datetime import timedelta
from typing import Any

from sqlalchemy import delete, func, select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from ...logger import db_logger
from ...models import (
    AppLogModel,
    AppLogRequestModel,
    AppModel,
    AppUploadModel,
    datetime_now,
)
from ...utils.decorators import log_exceptions


def _rowcount(result: Any) -> int:
    """Безопасно извлекает rowcount из результата SQLAlchemy.

    У базового ``sqlalchemy.engine.Result`` нет типизированного ``rowcount``;
    он присутствует только у ``CursorResult`` (DML). В рантайме ``execute``
    для INSERT/UPDATE/DELETE всегда возвращает ``CursorResult``, поэтому
    атрибут есть, но статический анализатор этого не знает.

    Возвращает 0, если атрибут отсутствует или равен None.
    """
    value: Any = getattr(result, "rowcount", None)
    if value is None:
        return 0
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0


class AppRepository:
    """Репозиторий для работы с мобильными клиентами (TApps),
    их диагностическими логами (TAppLogs), запросами логов
    (TAppLogsRequests) и загрузками файлов (TAppUploads)."""

    # ============================================================
    # TApps (справочник мобильных клиентов)
    # ============================================================

    @staticmethod
    @log_exceptions(db_logger)
    async def get_app_by_fid(session: AsyncSession, fid: str) -> AppModel | None:
        """Найти мобильный клиент по FFid."""
        stmt = select(AppModel).where(AppModel.FFid == fid)
        result = await session.execute(stmt)
        return result.scalar_one_or_none()

    @staticmethod
    @log_exceptions(db_logger)
    async def get_by_key(session: AsyncSession, key: str) -> AppModel | None:
        """Найти активное устройство по X-API-Key (TApps.FKey).

        Возвращает только активные записи (FIsActive=True) с непустым FKey.
        Используется AuthMiddleware для эндпоинтов группы 3.
        """
        if not key:
            return None
        stmt = select(AppModel).where(
            AppModel.FKey == key,
            AppModel.FIsActive.is_(True),
        )
        result = await session.execute(stmt)
        return result.scalar_one_or_none()

    @staticmethod
    @log_exceptions(db_logger)
    async def register_app(
        session: AsyncSession,
        *,
        fid: str,
        user_id: str | None,
        key: str,
        app_version_code: int | None,
    ) -> AppModel:
        """Создать или обновить TApps при POST /register.

        Единственная точка создания записи устройства. FKey обязателен
        (значение tkn из тела запроса). При повторной регистрации
        обновляет FUserID/FKey/FLastSeenAt.
        """
        existing = await AppRepository.get_app_by_fid(session, fid)
        if existing is not None:
            existing.FUserID = user_id
            existing.FKey = key[:512]
            existing.FLastSeenAt = datetime_now()
            await session.flush()
            await session.refresh(existing)
            return existing

        # PyCharm не видит SQLAlchemy-конструктор — приводим класс к Any.
        model_any: Any = AppModel
        app = model_any(
            FFid=fid,
            FIsActive=True,
            FUserID=user_id,
            FKey=key[:512],
            FAppVersion=app_version_code.__str__(),
            FLastSeenAt=datetime_now(),
        )
        session.add(app)
        await session.flush()
        await session.refresh(app)
        return app

    # ============================================================
    # TAppUploads (загрузки файлов, PostgreSQL)
    # ============================================================

    @staticmethod
    @log_exceptions(db_logger)
    async def upload_create(
        session: AsyncSession,
        *,
        fk_app: int,
        fid: str,
        user_id: str | None,
        upload_id: str,
        file_name: str,
        file_ext: str | None,
        file_size: int,
        chunk_size: int,
        storage_key: str,
        sha256: str | None = None,
        retention_days: int = 7,
        content_type: str | None = None,
    ) -> AppUploadModel:
        """Создать запись о resumable-загрузке.

        ``upload_id`` должен быть уникальным — при дубликате будет
        IntegrityError, вызывающий код обрабатывает как «уже существует».
        """
        now = datetime_now()
        model = AppUploadModel(
            FK_App=fk_app,
            FFid=fid,
            FUserID=user_id,
            FUploadID=upload_id,
            FFileName=file_name[:255],
            FFileExt=(file_ext or "")[:16],
            FFileSize=file_size,
            FUploadedBytes=0,
            FChunkSize=chunk_size,
            FContentType=content_type,
            FSHA256=sha256,
            FStatus="active",
            FStorageKey=storage_key,
            FVersion=0,
            FCreatedAt=now,
            FUpdatedAt=now,
            FExpiresAt=now + timedelta(days=retention_days),
        )

        session.add(model)
        await session.flush()
        await session.refresh(model)
        return model

    @staticmethod
    @log_exceptions(db_logger)
    async def upload_get_by_upload_id(session: AsyncSession, upload_id: str) -> AppUploadModel | None:
        stmt = select(AppUploadModel).where(AppUploadModel.FUploadID == upload_id)
        result = await session.execute(stmt)
        return result.scalar_one_or_none()

    @staticmethod
    @log_exceptions(db_logger)
    async def upload_get_many_by_upload_ids(
        session: AsyncSession,
        upload_ids: list[str],
    ) -> dict[str, AppUploadModel]:
        """Вернуть {FUploadID: model} для набора upload_id."""
        if not upload_ids:
            return {}
        stmt = select(AppUploadModel).where(AppUploadModel.FUploadID.in_(upload_ids))
        result = await session.execute(stmt)
        return {m.FUploadID: m for m in result.scalars().all()}

    @staticmethod
    @log_exceptions(db_logger)
    async def upload_get_by_pk(session: AsyncSession, upload_pk: int) -> AppUploadModel | None:
        stmt = select(AppUploadModel).where(AppUploadModel.FID == upload_pk)
        result = await session.execute(stmt)
        return result.scalar_one_or_none()

    @staticmethod
    @log_exceptions(db_logger)
    async def upload_list_active_by_app(session: AsyncSession, fk_app: int) -> list[AppUploadModel]:
        stmt = (
            select(AppUploadModel)
            .where(AppUploadModel.FK_App == fk_app, AppUploadModel.FStatus == "active")
            .order_by(AppUploadModel.FCreatedAt.desc())
        )
        result = await session.execute(stmt)
        return list(result.scalars().all())

    @staticmethod
    @log_exceptions(db_logger)
    async def upload_list_active_by_user(session: AsyncSession, user_id: str) -> list[AppUploadModel]:
        stmt = (
            select(AppUploadModel)
            .where(AppUploadModel.FUserID == user_id, AppUploadModel.FStatus == "active")
            .order_by(AppUploadModel.FCreatedAt.desc())
        )
        result = await session.execute(stmt)
        return list(result.scalars().all())

    # ---------- OFFSET / APPEND (атомарно) ----------

    @staticmethod
    @log_exceptions(db_logger)
    async def upload_advance_offset(
        session: AsyncSession,
        *,
        upload_id: str,
        expected_offset: int,
        chunk_len: int,
        actual_sha256: str | None = None,
    ) -> tuple[bool, int, str | None]:
        """Атомарно продвинуть ``FUploadedBytes`` с проверкой offset.

        Реализовано через условный ``UPDATE ... WHERE FUploadedBytes = :expected``
        (оптимистичная блокировка), без ``SELECT FOR UPDATE``.

        Returns:
            ``(ok, actual_offset, err)``:
              - ``(True, new_offset, None)``
              - ``(False, actual_offset, "offset_mismatch" | "not_found" | "expired" | status)``
        """
        now = datetime_now()
        stmt = (
            update(AppUploadModel)
            .where(
                AppUploadModel.FUploadID == upload_id,
                AppUploadModel.FStatus == "active",
                AppUploadModel.FUploadedBytes == expected_offset,
                AppUploadModel.FExpiresAt > now,
            )
            .values(
                FUploadedBytes=AppUploadModel.FUploadedBytes + chunk_len,
                FVersion=AppUploadModel.FVersion + 1,
                FActualSHA256=actual_sha256,
                FUpdatedAt=now,
            )
        )
        result = await session.execute(stmt)
        if _rowcount(result) == 1:
            await session.commit()
            return True, expected_offset + chunk_len, None

        # Не обновились — выясняем причину.
        current = await AppRepository.upload_get_by_upload_id(session, upload_id)
        if current is None:
            return False, 0, "not_found"
        if current.FStatus != "active":
            return False, current.FUploadedBytes, current.FStatus
        if current.FExpiresAt <= now:
            return False, current.FUploadedBytes, "expired"
        return False, current.FUploadedBytes, "offset_mismatch"

    @staticmethod
    @log_exceptions(db_logger)
    async def upload_set_actual_sha256(
        session: AsyncSession,
        *,
        upload_id: str,
        actual_sha256: str,
    ) -> None:
        stmt = (
            update(AppUploadModel)
            .where(AppUploadModel.FUploadID == upload_id)
            .values(FActualSHA256=actual_sha256, FUpdatedAt=datetime_now())
        )
        await session.execute(stmt)
        await session.commit()

    # ---------- COMPLETE / CANCEL / EXPIRE ----------

    @staticmethod
    @log_exceptions(db_logger)
    async def upload_mark_completed(
        session: AsyncSession,
        *,
        upload_id: str,
        remote_file_id: str,
    ) -> bool:
        """Пометить загрузку завершённой и сохранить ID файла из SQL Server.

        Returns:
            True, если загрузка была ``active`` и все байты загружены;
            False — повторный complete или incomplete.
        """
        now = datetime_now()
        stmt = (
            update(AppUploadModel)
            .where(
                AppUploadModel.FUploadID == upload_id,
                AppUploadModel.FStatus == "active",
                AppUploadModel.FUploadedBytes == AppUploadModel.FFileSize,
            )
            .values(
                FStatus="completed",
                FRemoteFileID=remote_file_id,
                FCompletedAt=now,
                FUpdatedAt=now,
                FVersion=AppUploadModel.FVersion + 1,
            )
        )
        result = await session.execute(stmt)
        ok = _rowcount(result) == 1
        await session.commit()
        return ok

    @staticmethod
    @log_exceptions(db_logger)
    async def upload_mark_cancelled(session: AsyncSession, *, upload_id: str) -> bool:
        """Пометить загрузку отменённой (по явной команде пользователя)."""
        stmt = (
            update(AppUploadModel)
            .where(
                AppUploadModel.FUploadID == upload_id,
                AppUploadModel.FStatus == "active",
            )
            .values(
                FStatus="cancelled",
                FUpdatedAt=datetime_now(),
                FVersion=AppUploadModel.FVersion + 1,
            )
        )
        result = await session.execute(stmt)
        ok = _rowcount(result) == 1
        await session.commit()
        return ok

    @staticmethod
    @log_exceptions(db_logger)
    async def upload_mark_expired(session: AsyncSession, *, upload_id: str) -> bool:
        stmt = (
            update(AppUploadModel)
            .where(
                AppUploadModel.FUploadID == upload_id,
                AppUploadModel.FStatus == "active",
            )
            .values(
                FStatus="expired",
                FUpdatedAt=datetime_now(),
                FVersion=AppUploadModel.FVersion + 1,
            )
        )
        result = await session.execute(stmt)
        await session.commit()
        return _rowcount(result) == 1

    # ---------- CLEANUP ----------

    @staticmethod
    @log_exceptions(db_logger)
    async def upload_find_expired_active(
        session: AsyncSession,
        *,
        limit: int = 500,
    ) -> list[AppUploadModel]:
        """Вернуть активные загрузки с истёкшим ``FExpiresAt`` (для воркера)."""
        now = datetime_now()
        stmt = (
            select(AppUploadModel)
            .where(
                AppUploadModel.FStatus == "active",
                AppUploadModel.FExpiresAt <= now,
            )
            .order_by(AppUploadModel.FExpiresAt.asc())
            .limit(limit)
        )
        result = await session.execute(stmt)
        return list(result.scalars().all())

    @staticmethod
    @log_exceptions(db_logger)
    async def upload_cleanup_expired(
        session: AsyncSession,
        *,
        limit: int = 500,
    ) -> list[str]:
        """Пометить истёкшие активные загрузки как ``expired``.

        Returns:
            список ``FStorageKey`` — вызывающий код (воркер) должен удалить
            соответствующие файлы из storage и затем строки через
            ``upload_delete_by_upload_id``.
        """
        expired = await AppRepository.upload_find_expired_active(session, limit=limit)
        keys: list[str] = []
        for model in expired:
            if await AppRepository.upload_mark_expired(session, upload_id=model.FUploadID):
                keys.append(model.FStorageKey)
        if keys:
            db_logger.info("🧹 [upload_cleanup_expired] marked=%d", len(keys))
        return keys

    @staticmethod
    @log_exceptions(db_logger)
    async def upload_cleanup_finalized(
        session: AsyncSession,
        *,
        retention_days: int,
        limit: int = 500,
    ) -> list[str]:
        """Вернуть storage-ключи ``completed``/``cancelled`` старше N дней.

        Строки не удаляются — вызывающий код удаляет файлы, затем
        строки через ``upload_delete_by_upload_id``.
        """
        threshold = datetime_now() - timedelta(days=retention_days)
        stmt = (
            select(AppUploadModel)
            .where(
                AppUploadModel.FStatus.in_(("completed", "cancelled")),
                AppUploadModel.FUpdatedAt < threshold,
            )
            .order_by(AppUploadModel.FUpdatedAt.asc())
            .limit(limit)
        )
        result = await session.execute(stmt)
        return [m.FStorageKey for m in result.scalars().all()]

    @staticmethod
    @log_exceptions(db_logger)
    async def upload_delete_by_upload_id(session: AsyncSession, *, upload_id: str) -> int:
        """Физически удалить запись (после удаления файла из storage)."""
        stmt = delete(AppUploadModel).where(AppUploadModel.FUploadID == upload_id)
        result = await session.execute(stmt)
        await session.commit()
        return _rowcount(result)

    @staticmethod
    @log_exceptions(db_logger)
    async def upload_delete_by_pk(session: AsyncSession, *, upload_pk: int) -> int:
        stmt = delete(AppUploadModel).where(AppUploadModel.FID == upload_pk)
        result = await session.execute(stmt)
        await session.commit()
        return _rowcount(result)

    # ---------- СТАТИСТИКА ----------

    @staticmethod
    @log_exceptions(db_logger)
    async def upload_stats_snapshot(session: AsyncSession) -> dict[str, int]:
        """Счётчики загрузок по статусам (для /sync-stats или health)."""
        stmt = select(AppUploadModel.FStatus, func.count(AppUploadModel.FID)).group_by(AppUploadModel.FStatus)
        result = await session.execute(stmt)
        return {str(status or "unknown"): int(count or 0) for status, count in result.all()}

    @staticmethod
    @log_exceptions(db_logger)
    async def upload_total_bytes(session: AsyncSession) -> int:
        stmt = select(func.coalesce(func.sum(AppUploadModel.FFileSize), 0)).where(AppUploadModel.FStatus == "active")
        result = await session.execute(stmt)
        return int(result.scalar() or 0)

    # ============================================================
    # ЛОГИ (TAppLogs)
    # ============================================================

    @staticmethod
    @log_exceptions(db_logger)
    async def insert_batch(
        session: AsyncSession,
        *,
        fk_app: int,
        batch_id: str,
        request_id: str | None,
        fid: str,
        user_id: str | None,
        trigger: str,
        filter_applied: str,
        truncated: bool,
        truncated_reason: str | None,
        records: list[dict[str, Any]],
    ) -> tuple[int, bool]:
        """Вставить записи батча. Возвращает (inserted, duplicate_batch).

        duplicate_batch=True, если ни одна строка не вставилась
        из-за UNIQUE(FBatchID, FIdx) — батч уже был обработан.
        """
        if not records:
            return 0, False

        values = [
            {
                "FK_App": fk_app,
                "FBatchID": batch_id,
                "FIdx": rec["idx"],
                "FRequestID": request_id,
                "FFid": fid,
                "FUserID": user_id,
                "FTrigger": trigger,
                "FFilterApplied": filter_applied,
                "FTruncated": truncated,
                "FTruncatedReason": truncated_reason,
                "FTs": rec["ts"],
                "FSessionID": rec["session_id"],
                "FLevel": rec["level"],
                "FCritical": rec.get("critical", False),
                "FTag": rec.get("tag"),
                "FMsg": rec["msg"],
                "FTrace": rec.get("trace"),
                "FThread": rec.get("thread"),
                "FFields": rec.get("fields"),
            }
            for rec in records
        ]

        # Pyright не выводит типы из pg_insert для нестандартной модели;
        # кастуем к Any, чтобы не ловить ложные "Unexpected argument".
        stmt: Any = pg_insert(AppLogModel).values(values).on_conflict_do_nothing(index_elements=["FBatchID", "FIdx"])
        result = await session.execute(stmt)
        inserted = _rowcount(result)
        duplicate = inserted == 0 and len(values) > 0
        await session.commit()
        return inserted, duplicate

    @staticmethod
    @log_exceptions(db_logger)
    async def get_logs(
        session: AsyncSession,
        *,
        since_ts: int | None = None,
        level: int | None = None,
        critical: bool | None = None,
        request_id: str | None = None,
        fid: str | None = None,
        limit: int = 500,
        offset: int = 0,
    ) -> list[AppLogModel]:
        stmt = select(AppLogModel)
        if since_ts is not None:
            stmt = stmt.where(AppLogModel.FTs >= since_ts)
        if level is not None:
            stmt = stmt.where(AppLogModel.FLevel == level)
        if critical is not None:
            stmt = stmt.where(AppLogModel.FCritical.is_(critical))
        if request_id is not None:
            stmt = stmt.where(AppLogModel.FRequestID == request_id)
        if fid is not None:
            stmt = stmt.where(AppLogModel.FFid == fid)
        stmt = stmt.order_by(AppLogModel.FReceivedAt.desc()).limit(limit).offset(offset)
        result = await session.execute(stmt)
        return list(result.scalars().all())

    @staticmethod
    @log_exceptions(db_logger)
    async def count_daily_bytes(session: AsyncSession, fid: str) -> int:
        """Сумма (msg+trace+fields) за текущие сутки для rate-limit."""
        day_start = datetime_now().replace(hour=0, minute=0, second=0, microsecond=0)
        stmt = select(
            func.coalesce(
                func.sum(
                    func.length(AppLogModel.FMsg)
                    + func.coalesce(func.length(AppLogModel.FTrace), 0)
                    + func.coalesce(func.length(AppLogModel.FFields), 0)
                ),
                0,
            )
        ).where(
            AppLogModel.FFid == fid,
            AppLogModel.FReceivedAt >= day_start,
        )
        result = await session.execute(stmt)
        return int(result.scalar() or 0)

    @staticmethod
    @log_exceptions(db_logger)
    async def cleanup_logs(
        session: AsyncSession,
        *,
        info_days: int,
        error_days: int,
    ) -> int:
        now = datetime_now()
        # Удаляем INFO/DEBUG/... (level < 4) старше info_days
        stmt_low = delete(AppLogModel).where(
            AppLogModel.FLevel < 4,
            AppLogModel.FReceivedAt < now - timedelta(days=info_days),
        )
        # Удаляем ERROR/CRITICAL (level >= 4) старше error_days
        stmt_high = delete(AppLogModel).where(
            AppLogModel.FLevel >= 4,
            AppLogModel.FReceivedAt < now - timedelta(days=error_days),
        )
        r1 = await session.execute(stmt_low)
        r2 = await session.execute(stmt_high)
        await session.commit()
        return _rowcount(r1) + _rowcount(r2)

    # ============================================================
    # ЗАПРОСЫ ЛОГОВ (TAppLogsRequests)
    # ============================================================

    @staticmethod
    @log_exceptions(db_logger)
    async def create_request(
        session: AsyncSession,
        *,
        request_id: str,
        app_id: int,
        fid: str,
        user_id: str | None,
        max_bytes: int,
        since_ts: int,
        levels: list[int] | None,
        force_all: bool,
        ttl_sec: int,
        created_by: str,
    ) -> AppLogRequestModel:
        expires_at = datetime_now() + timedelta(seconds=ttl_sec)

        model = AppLogRequestModel(
            FID=request_id,
            FK_App=app_id,
            FFid=fid,
            FUserID=user_id,
            FMaxBytes=max_bytes,
            FSinceTs=since_ts,
            FLevels=",".join(str(x) for x in levels) if levels else None,
            FForceAll=force_all,
            FTtlSec=ttl_sec,
            FExpiresAt=expires_at,
            FCreatedBy=created_by,
        )

        session.add(model)
        await session.flush()
        await session.refresh(model)
        return model

    @staticmethod
    @log_exceptions(db_logger)
    async def get_request_by_id(session: AsyncSession, request_id: str) -> AppLogRequestModel | None:
        stmt = select(AppLogRequestModel).where(AppLogRequestModel.FID == request_id)
        result = await session.execute(stmt)
        return result.scalar_one_or_none()

    @staticmethod
    @log_exceptions(db_logger)
    async def mark_request_fulfilled(
        session: AsyncSession,
        request_id: str,
        *,
        truncated: bool,
        truncated_reason: str | None,
    ) -> None:
        model = await AppRepository.get_request_by_id(session, request_id)
        if model is None:
            return
        model.FFulfilledAt = datetime_now()
        model.FTruncated = truncated
        model.FTruncatedReason = truncated_reason
        await session.flush()

    @staticmethod
    @log_exceptions(db_logger)
    async def mark_request_declined(
        session: AsyncSession,
        request_id: str,
        reason: str,
    ) -> bool:
        model = await AppRepository.get_request_by_id(session, request_id)
        if model is None or model.FDeclineReason is not None:
            return False
        model.FDeclineReason = reason
        await session.flush()
        return True

    @staticmethod
    @log_exceptions(db_logger)
    async def count_requests_today(
        session: AsyncSession,
        fid: str,
        *,
        force_all_only: bool = False,
    ) -> int:
        day_start = datetime_now().replace(hour=0, minute=0, second=0, microsecond=0)
        stmt = select(AppLogRequestModel).where(
            AppLogRequestModel.FFid == fid,
            AppLogRequestModel.FCreatedAt >= day_start,
        )
        if force_all_only:
            stmt = stmt.where(AppLogRequestModel.FForceAll.is_(True))
        result = await session.execute(stmt)
        return len(list(result.scalars().all()))

    @staticmethod
    @log_exceptions(db_logger)
    async def list_requests(
        session: AsyncSession,
        *,
        fid: str | None = None,
        limit: int = 200,
        offset: int = 0,
    ) -> list[AppLogRequestModel]:
        stmt = select(AppLogRequestModel)
        if fid is not None:
            stmt = stmt.where(AppLogRequestModel.FFid == fid)
        stmt = stmt.order_by(AppLogRequestModel.FCreatedAt.desc()).limit(limit).offset(offset)
        result = await session.execute(stmt)
        return list(result.scalars().all())

    @staticmethod
    @log_exceptions(db_logger)
    async def cleanup_requests(session: AsyncSession, *, retention_days: int) -> int:
        threshold = datetime_now() - timedelta(days=retention_days)
        stmt = delete(AppLogRequestModel).where(AppLogRequestModel.FCreatedAt < threshold)
        result = await session.execute(stmt)
        await session.commit()
        return _rowcount(result)

    @staticmethod
    @log_exceptions(db_logger)
    async def run_retention(
        session: AsyncSession,
        *,
        info_days: int,
        error_days: int,
        requests_retention_days: int,
    ) -> dict[str, int]:
        """Комплексная очистка устаревших диагностических логов и запросов.

        Объединяет операции cleanup_logs и cleanup_requests в один вызов,
        чтобы фоновая задача retention в ApplicationManager работала
        с единой точкой входа.
        """
        logs_deleted = await AppRepository.cleanup_logs(
            session,
            info_days=info_days,
            error_days=error_days,
        )

        requests_deleted = await AppRepository.cleanup_requests(
            session,
            retention_days=requests_retention_days,
        )

        db_logger.info(
            "🧹 [run_retention] logs_deleted=%d requests_deleted=%d "
            "(info_days=%d, error_days=%d, requests_retention_days=%d)",
            logs_deleted,
            requests_deleted,
            info_days,
            error_days,
            requests_retention_days,
        )

        return {
            "logs_deleted": logs_deleted,
            "requests_deleted": requests_deleted,
            "requests_expired": 0,
        }


__all__ = ["AppRepository"]
