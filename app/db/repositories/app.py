"""Репозиторий для работы с мобильными клиентами"""

from __future__ import annotations

from datetime import timedelta
from typing import Any, cast

from sqlalchemy import delete, func, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from ...logger import db_logger
from ...models import AppLogModel, AppLogRequestModel, AppModel, datetime_now
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
    их диагностическими логами (TAppLogs) и запросами логов (TAppLogsRequests)."""

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
    async def get_or_create_app(
        session: AsyncSession,
        fid: str,
        user_id: str | None = None,
    ) -> AppModel:
        """Найти или создать TApps по FFid, опционально проставив FUserID (usrXXX)."""
        existing = await AppRepository.get_app_by_fid(session, fid)
        if existing is not None:
            if user_id and existing.FUserID != user_id:
                existing.FUserID = user_id
            return existing

        # SQLAlchemy 2.0-конструктор принимает **kwargs, но Pyright
        # не выводит это из DeclarativeBase. Кастуем класс к Any
        # и типизируем результат через cast уже после вызова
        # (тот же приём, что и для AppLogRequestModel выше).
        model_cls: Any = cast("Any", AppModel)
        app = cast(
            "AppModel",
            model_cls(FFid=fid, FIsActive=True, FUserID=user_id),
        )
        session.add(app)
        await session.flush()
        await session.refresh(app)
        return app

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

        # SQLAlchemy 2.0-конструктор принимает **kwargs, но Pyright
        # не выводит это из DeclarativeBase. Кастуем сам класс к Any
        # и типизируем результат через cast уже после вызова.
        model_cls: Any = cast("Any", AppLogRequestModel)
        model = cast(
            "AppLogRequestModel",
            model_cls(
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
            ),
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

        Args:
            session: Асинхронная сессия SQLAlchemy.
            info_days: Срок хранения логов уровня < ERROR (INFO/DEBUG/...).
            error_days: Срок хранения логов уровня >= ERROR.
            requests_retention_days: Срок хранения записей TAppLogsRequests.

        Returns:
            dict[str, int]: Статистика удаления:
                - logs_deleted:       количество удалённых записей TAppLogs;
                - requests_deleted:   количество удалённых TAppLogsRequests;
                - requests_expired:   количество записей с истёкшим TTL
                                      (FExpiresAt < now) — на текущий момент
                                      не вычисляется отдельно, возвращается 0
                                      для совместимости с вызывающим кодом.
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
