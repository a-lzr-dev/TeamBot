"""Роутер диагностических логов мобильных клиентов.

Эндпоинты:
- POST /api/v1/logs/batch                — приём батча (settings.API_KEY_HEADER из APP_CLIENT_SUPPORT_INGEST_API_KEYS)
- POST /api/v1/logs/request              — создать запрос логов (admin)
- POST /api/v1/logs/request/{id}/decline — клиент отказался (settings.API_KEY_HEADER)
- GET  /api/v1/logs                      — чтение логов (admin)
- GET  /api/v1/logs/requests             — чтение запросов (admin)

Важно (циклический импорт):
    Все импорты из ``app.*`` (config, db, ws, utils) выполняются ЛЕНИВО —
    внутри функций. На уровне модуля остаются только сторонние библиотеки.
    Это устраняет цикл:

        run.py → app.logger → app/__init__ → app.api.dependencies
              → app.api.manager → app.api.routers.__init__
              → app.api.routers.logs  ← здесь падало с ImportError

    Причина: ``push_notification_service`` тянет за собой ``app.config``
    и ``app.db.repositories``, которые в момент инициализации ``app.api``
    ещё не готовы.
"""

from __future__ import annotations

import gzip
import json
import re
import uuid
from typing import TYPE_CHECKING, Annotated, Any, Literal

from fastapi import APIRouter, Depends, Header, HTTPException, Query, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

router = APIRouter(prefix="/logs", tags=["Logs"])


# ---------------------------------------------------------------------------
# Pydantic-модели
# ---------------------------------------------------------------------------

_TRIGGERS = ("critical_wifi", "remote_request")
_FILTERS = ("details_on_error", "force_all")
_DECLINE_REASONS = ("disabled_by_user", "no_errors_pending", "first_record_too_large")


class LogRecordIn(BaseModel):
    ts: int
    session_id: str
    level: int
    critical: bool = False
    tag: str | None = None
    msg: str
    trace: str | None = None
    thread: str | None = None
    fields: str | None = None


class LogBatchIn(BaseModel):
    trigger: Literal["critical_wifi", "remote_request"]
    filter_applied: Literal["details_on_error", "force_all"]
    batch_id: str
    request_id: str | None = None
    truncated: bool = False
    truncated_reason: Literal["roaming", "max_bytes"] | None = None
    records: list[LogRecordIn]


class LogRequestIn(BaseModel):
    install_id: str = Field(..., min_length=8, max_length=255)
    max_bytes: int = Field(256 * 1024, ge=1024, le=4 * 1024 * 1024)
    since_ts: int = Field(0, ge=0)
    levels: list[int] | None = None
    force_all: bool = False
    ttl_sec: int = Field(3600, ge=60, le=86400)


class DeclineIn(BaseModel):
    reason: Literal[
        "disabled_by_user",
        "no_errors_pending",
        "first_record_too_large",
        "expired",
    ]


# ---------------------------------------------------------------------------
# Ленивые импорты из app.* — разрывают цикл
# ---------------------------------------------------------------------------


def _get_settings() -> Any:
    """Ленивый доступ к настройкам (без импорта на уровне модуля)."""
    from ...config import settings

    return settings


def _get_db_session_dep() -> Any:
    """Ленивый доступ к зависимости get_session."""
    from ..dependencies import get_session

    return get_session


def _get_ingest_key_dep() -> Any:
    """Ленивый доступ к зависимости _require_ingest_key."""
    return _require_ingest_key


def _get_timestamp() -> str:
    """Ленивый доступ к утилите get_timestamp."""
    from ...utils.datetime import get_timestamp

    return get_timestamp()


# ---------------------------------------------------------------------------
# Санитайзер (2-й эшелон, ограничения длины)
# ---------------------------------------------------------------------------

_BEARER_RE = re.compile(r"Bearer\s+[A-Za-z0-9._\-]{20,}")
_LONG_B64_RE = re.compile(r"[A-Za-z0-9+/=]{40,}")
_PHONE_RE = re.compile(r"(?<!\d)\d{11,19}(?!\d)")


def _sanitize(text: str | None, max_len: int) -> str | None:
    if text is None:
        return None
    if len(text) > max_len:
        text = text[:max_len]
    text = _BEARER_RE.sub("Bearer ***", text)
    text = _LONG_B64_RE.sub("***", text)
    text = _PHONE_RE.sub("***", text)
    return text


def _sanitize_records(records: list[LogRecordIn]) -> list[dict[str, Any]]:
    settings = _get_settings()
    max_msg = settings.APP_CLIENT_SUPPORT_LOGS_MAX_MSG_LEN
    max_trace = settings.APP_CLIENT_SUPPORT_LOGS_MAX_TRACE_LEN
    max_fields = settings.APP_CLIENT_SUPPORT_LOGS_MAX_FIELDS_LEN
    out: list[dict[str, Any]] = []
    for idx, r in enumerate(records):
        out.append(
            {
                "idx": idx,
                "ts": r.ts,
                "session_id": r.session_id[:128],
                "level": r.level,
                "critical": bool(r.critical),
                "tag": _sanitize(r.tag, 128),
                "msg": _sanitize(r.msg, max_msg) or "",
                "trace": _sanitize(r.trace, max_trace),
                "thread": _sanitize(r.thread, 256),
                "fields": _sanitize(r.fields, max_fields),
            }
        )
    return out


# ---------------------------------------------------------------------------
# Auth helpers
# ---------------------------------------------------------------------------


def _compare_key(provided: str, valid_keys: set[str]) -> bool:
    """Constant-time проверка ключа против набора (fail-closed)."""
    import hmac

    provided_b = provided.encode("utf-8")
    result = False
    for k in valid_keys:
        if hmac.compare_digest(provided_b, k.encode("utf-8")):
            result = True
    return result


def _ingest_keys() -> set[str]:
    """Ключи канала client-support (POST /api/v1/logs/batch, .../decline)."""
    settings = _get_settings()
    raw = getattr(settings, "APP_CLIENT_SUPPORT_INGEST_API_KEYS", []) or []
    return {str(k) for k in raw if str(k).strip()}


def _require_ingest_key(x_api_key: Annotated[str | None, Header()] = None) -> None:
    settings = _get_settings()
    if not getattr(settings, "APP_CLIENT_SUPPORT_LOGS_INGEST_ENABLED", True):
        raise HTTPException(status_code=404, detail="logs ingest disabled")
    keys = _ingest_keys()
    if not keys:
        raise HTTPException(status_code=503, detail="ingest keys not configured")
    if not x_api_key or not _compare_key(x_api_key, keys):
        raise HTTPException(status_code=401, detail="invalid ingest key")


# ---------------------------------------------------------------------------
# AppModel helpers (делегируются в AppRepository)
# ---------------------------------------------------------------------------


async def _bump_app_logs_count(session: AsyncSession, app_id: int, delta: int) -> None:
    from sqlalchemy import update

    from ...models import AppModel

    if delta <= 0:
        return
    stmt = update(AppModel).where(AppModel.FID == app_id).values(FLogsCount=AppModel.FLogsCount + delta)
    await session.execute(stmt)


async def _bump_app_requests_count(session: AsyncSession, app_id: int, delta: int = 1) -> None:
    from sqlalchemy import update

    from ...models import AppModel

    if delta <= 0:
        return
    stmt = update(AppModel).where(AppModel.FID == app_id).values(FLogRequestsCount=AppModel.FLogRequestsCount + delta)
    await session.execute(stmt)


# ---------------------------------------------------------------------------
# 1. POST /batch
# ---------------------------------------------------------------------------


async def _read_body(request: Request) -> bytes:
    raw = await request.body()
    enc = (request.headers.get("content-encoding") or "").lower()
    if enc == "gzip":
        raw = gzip.decompress(raw)
    return raw


@router.post("/batch", include_in_schema=False)
async def ingest_batch(
    request: Request,
    session: AsyncSession = Depends(_get_db_session_dep()),
    _: None = Depends(_get_ingest_key_dep()),
) -> JSONResponse:
    settings = _get_settings()
    if not getattr(settings, "APP_CLIENT_SUPPORT_LOGS_INGEST_ENABLED", True):
        raise HTTPException(status_code=404, detail="disabled")

    try:
        raw = await _read_body(request)
    except OSError as exc:
        raise HTTPException(status_code=400, detail=f"decompress failed: {exc}") from exc

    if len(raw) > settings.APP_CLIENT_SUPPORT_LOGS_MAX_BATCH_UNCOMPRESSED_BYTES:
        raise HTTPException(status_code=413, detail="batch too large after decompress")
    if len(raw) > settings.APP_CLIENT_SUPPORT_LOGS_MAX_BATCH_BYTES * 4:  # sanity
        raise HTTPException(status_code=413, detail="batch too large")

    try:
        payload = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise HTTPException(status_code=400, detail=f"invalid json: {exc}") from exc

    try:
        batch = LogBatchIn.model_validate(payload)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    if batch.trigger == "critical_wifi" and batch.filter_applied != "force_all":
        raise HTTPException(status_code=422, detail="critical_wifi must use filter_applied=force_all")

    if len(batch.records) > settings.APP_CLIENT_SUPPORT_LOGS_MAX_RECORDS_PER_BATCH:
        raise HTTPException(status_code=413, detail="too many records")

    records = _sanitize_records(batch.records)

    # FID клиента: X-Fid header (обязателен).
    fid = (request.headers.get("x-fid") or "").strip()
    if not fid:
        raise HTTPException(status_code=400, detail="missing X-Fid header")

    # Ленивый импорт репозитория + логгера
    from ...db.repositories import AppRepository
    from ...logger import api_logger

    app = await AppRepository.get_app_by_fid(session, fid)
    if app is None:
        raise HTTPException(status_code=404, detail="unknown fid; register device first")

    # rate limit по байтам/сутки (принятые логи)
    if getattr(settings, "APP_CLIENT_SUPPORT_LOGS_BYTES_PER_DAY", 0) > 0:
        current_bytes = await AppRepository.count_daily_bytes(session, fid)
        if current_bytes + len(raw) > settings.APP_CLIENT_SUPPORT_LOGS_BYTES_PER_DAY:
            api_logger.warning(
                "logs.batch: daily bytes limit exceeded fid=%s current=%d incoming=%d limit=%d",
                fid[-8:],
                current_bytes,
                len(raw),
                settings.APP_CLIENT_SUPPORT_LOGS_BYTES_PER_DAY,
            )
            raise HTTPException(status_code=429, detail="daily bytes limit reached")

    inserted, duplicate = await AppRepository.insert_batch(
        session=session,
        fk_app=app.FID,
        batch_id=batch.batch_id,
        request_id=batch.request_id,
        fid=fid,
        user_id=app.FUserID,
        trigger=batch.trigger,
        filter_applied=batch.filter_applied,
        truncated=batch.truncated,
        truncated_reason=batch.truncated_reason,
        records=records,
    )

    if inserted > 0:
        await _bump_app_logs_count(session, app.FID, inserted)

    if batch.request_id:
        await AppRepository.mark_request_fulfilled(
            session,
            batch.request_id,
            truncated=batch.truncated,
            truncated_reason=batch.truncated_reason,
        )

    await session.commit()

    api_logger.info(
        "logs.batch: fid=%s batch=%s trigger=%s inserted=%d duplicate=%s request=%s",
        fid[-8:],
        batch.batch_id,
        batch.trigger,
        inserted,
        duplicate,
        batch.request_id or "-",
    )

    return JSONResponse(
        status_code=200,
        content={
            "ok": True,
            "batch_id": batch.batch_id,
            "inserted": inserted,
            "duplicate": duplicate,
            "timestamp": _get_timestamp(),
        },
    )


# ---------------------------------------------------------------------------
# 2. POST /request
# ---------------------------------------------------------------------------


async def _send_logs_request_push(
    fids: list[str],
    *,
    request_id: str,
    max_bytes: int,
    since_ts: int,
    force_all: bool,
    levels: list[int] | None,
    ttl: int,
) -> bool:
    """Отправить push `logs_request` на указанные FID."""
    settings = _get_settings()
    from ...logger import api_logger

    # Ленивый импорт push-сервиса (он тянет много зависимостей).
    from ...ws.push_notification_service import push_notification_service

    if not getattr(settings, "FCM_ENABLED", False):
        api_logger.info("logs.request: FCM disabled, push skipped (request_id=%s)", request_id)
        return False

    if not fids:
        api_logger.warning("logs.request: no FIDs for user (request_id=%s)", request_id)
        return False

    ok = await push_notification_service.fcm.send(
        fids=fids,
        title="",
        body="",
        data={
            "type": settings.APP_CLIENT_SUPPORT_LOGS_PUSH_TYPE,
            "request_id": request_id,
            "max_bytes": str(max_bytes),
            "since_ts": str(since_ts),
            "force_all": "1" if force_all else "0",
            "levels": ",".join(str(x) for x in (levels or [])),
            "ttl_sec": str(ttl),
        },
        silent=True,
    )
    if ok:
        api_logger.info("logs.request: FCM push sent (request_id=%s, fids=%d)", request_id, len(fids))
    else:
        api_logger.warning("logs.request: FCM push failed (request_id=%s, fids=%d)", request_id, len(fids))
    return ok


@router.post("/request")
async def create_logs_request(
    payload: LogRequestIn,
    session: AsyncSession = Depends(_get_db_session_dep()),
) -> JSONResponse:
    settings = _get_settings()
    from ...db.repositories import AppRepository
    from ...logger import api_logger

    # admin-проверка уже сделана AuthMiddleware (settings.API_KEY_HEADER из API_KEYS)
    app = await AppRepository.get_app_by_fid(session, payload.install_id)
    if app is None:
        raise HTTPException(status_code=404, detail="install_id not found")

    force = bool(payload.force_all)
    if force and settings.APP_CLIENT_SUPPORT_LOGS_FORCE_ALL_PER_DAY > 0:
        cnt = await AppRepository.count_requests_today(session, payload.install_id, force_all_only=True)
        if cnt >= settings.APP_CLIENT_SUPPORT_LOGS_FORCE_ALL_PER_DAY:
            raise HTTPException(status_code=429, detail="force_all daily limit reached")

    if settings.APP_CLIENT_SUPPORT_LOGS_REQUESTS_PER_DAY > 0:
        cnt = await AppRepository.count_requests_today(session, payload.install_id, force_all_only=False)
        if cnt >= settings.APP_CLIENT_SUPPORT_LOGS_REQUESTS_PER_DAY:
            raise HTTPException(status_code=429, detail="daily request limit reached")

    max_bytes = payload.max_bytes
    if force:
        max_bytes = min(max_bytes, settings.APP_CLIENT_SUPPORT_LOGS_REQUEST_FORCE_ALL_MAX_BYTES)

    request_id = str(uuid.uuid4())
    ttl = min(payload.ttl_sec, settings.APP_CLIENT_SUPPORT_LOGS_REQUEST_TTL_SEC)

    await AppRepository.create_request(
        session=session,
        request_id=request_id,
        app_id=app.FID,
        fid=payload.install_id,
        user_id=app.FUserID,
        max_bytes=max_bytes,
        since_ts=payload.since_ts,
        levels=payload.levels,
        force_all=force,
        ttl_sec=ttl,
        created_by="admin",
    )
    await _bump_app_requests_count(session, app.FID)
    await session.commit()

    # Ленивый импорт push-сервиса
    from ...ws.push_notification_service import push_notification_service

    user_id = (app.FUserID or "").strip()
    if not user_id:
        api_logger.warning(
            "logs.request: app has no FUserID (app_id=%s), FCM push skipped",
            app.FID,
        )
        return JSONResponse(
            status_code=201,
            content={
                "ok": True,
                "request_id": request_id,
                "install_id": payload.install_id,
                "max_bytes": max_bytes,
                "force_all": force,
                "expires_in": ttl,
                "push_sent": False,
                "push_skipped_reason": "no_user_id",
                "timestamp": _get_timestamp(),
            },
        )

    fids = sorted(str(x) for x in push_notification_service.get_fcms_for_user(user_id))
    if not fids:
        api_logger.warning(
            "logs.request: no FIDs registered for user=%s (request_id=%s), FCM push skipped",
            user_id,
            request_id,
        )
        return JSONResponse(
            status_code=201,
            content={
                "ok": True,
                "request_id": request_id,
                "install_id": payload.install_id,
                "max_bytes": max_bytes,
                "force_all": force,
                "expires_in": ttl,
                "push_sent": False,
                "push_skipped_reason": "no_fcm_id",
                "timestamp": _get_timestamp(),
            },
        )

    push_ok = await _send_logs_request_push(
        fids,
        request_id=request_id,
        max_bytes=max_bytes,
        since_ts=payload.since_ts,
        force_all=force,
        levels=payload.levels,
        ttl=ttl,
    )

    return JSONResponse(
        status_code=201,
        content={
            "ok": True,
            "request_id": request_id,
            "install_id": payload.install_id,
            "max_bytes": max_bytes,
            "force_all": force,
            "expires_in": ttl,
            "push_sent": push_ok,
            "timestamp": _get_timestamp(),
        },
    )


# ---------------------------------------------------------------------------
# 3. POST /request/{id}/decline
# ---------------------------------------------------------------------------


@router.post("/request/{request_id}/decline", include_in_schema=False)
async def decline_request(
    request_id: str,
    payload: DeclineIn,
    session: AsyncSession = Depends(_get_db_session_dep()),
    _: None = Depends(_get_ingest_key_dep()),
) -> JSONResponse:
    from ...db.repositories import AppRepository

    ok = await AppRepository.mark_request_declined(session, request_id, payload.reason)
    await session.commit()
    if not ok:
        return JSONResponse(
            status_code=404,
            content={"ok": False, "reason": "not_found_or_already_closed", "request_id": request_id},
        )
    return JSONResponse(
        status_code=200,
        content={"ok": True, "request_id": request_id, "decline_reason": payload.reason},
    )


# ---------------------------------------------------------------------------
# 4. GET / (read)
# ---------------------------------------------------------------------------


@router.get("")
async def list_logs(
    session: AsyncSession = Depends(_get_db_session_dep()),
    since_ts: int | None = Query(None, ge=0),
    level: int | None = Query(None, ge=0, le=6),
    critical: bool | None = Query(None),
    request_id: str | None = Query(None),
    fid: str | None = Query(None),
    limit: int = Query(200, ge=1, le=2000),
    offset: int = Query(0, ge=0),
) -> JSONResponse:
    from ...db.repositories import AppRepository

    rows = await AppRepository.get_logs(
        session,
        since_ts=since_ts,
        level=level,
        critical=critical,
        request_id=request_id,
        fid=fid,
        limit=limit,
        offset=offset,
    )
    return JSONResponse(
        status_code=200,
        content={
            "ok": True,
            "total": len(rows),
            "logs": [
                {
                    "id": r.FID,
                    "received_at": r.FReceivedAt.isoformat() + "Z" if r.FReceivedAt else None,
                    "batch_id": r.FBatchID,
                    "idx": r.FIdx,
                    "request_id": r.FRequestID,
                    "fid": r.FFid,
                    "trigger": r.FTrigger,
                    "filter_applied": r.FFilterApplied,
                    "truncated": r.FTruncated,
                    "truncated_reason": r.FTruncatedReason,
                    "ts": r.FTs,
                    "level": r.FLevel,
                    "critical": r.FCritical,
                    "tag": r.FTag,
                    "msg": r.FMsg,
                    "trace": r.FTrace,
                    "thread": r.FThread,
                    "fields": r.FFields,
                }
                for r in rows
            ],
            "timestamp": _get_timestamp(),
        },
    )


# ---------------------------------------------------------------------------
# 5. GET /requests
# ---------------------------------------------------------------------------


@router.get("/requests")
async def list_requests(
    session: AsyncSession = Depends(_get_db_session_dep()),
    fid: str | None = Query(None),
    limit: int = Query(200, ge=1, le=1000),
    offset: int = Query(0, ge=0),
) -> JSONResponse:
    from ...db.repositories import AppRepository

    rows = await AppRepository.list_requests(session, fid=fid, limit=limit, offset=offset)
    return JSONResponse(
        status_code=200,
        content={
            "ok": True,
            "total": len(rows),
            "requests": [
                {
                    "request_id": r.FID,
                    "app_id": r.FK_App,
                    "fid": r.FFid,
                    "user_id": r.FUserID,
                    "created_at": r.FCreatedAt.isoformat() + "Z" if r.FCreatedAt else None,
                    "max_bytes": r.FMaxBytes,
                    "since_ts": r.FSinceTs,
                    "levels": r.FLevels,
                    "force_all": r.FForceAll,
                    "fulfilled_at": r.FFulfilledAt.isoformat() + "Z" if r.FFulfilledAt else None,
                    "truncated": r.FTruncated,
                    "truncated_reason": r.FTruncatedReason,
                    "decline_reason": r.FDeclineReason,
                    "ttl_sec": r.FTtlSec,
                    "expires_at": r.FExpiresAt.isoformat() + "Z" if r.FExpiresAt else None,
                    "created_by": r.FCreatedBy,
                }
                for r in rows
            ],
            "timestamp": _get_timestamp(),
        },
    )


__all__ = ["router"]
