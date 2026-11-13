"""Публичный API мобильного клиента Teamdroid.

Эндпоинты client-sync канала (X-API-Key из APP_CLIENT_SYNC_INGEST_API_KEYS):

    POST   /api/v1/client/register       — регистрация FID + TokenVerify
    DELETE /api/v1/client/register       — снятие FID + logout (TokenFinish)
    POST   /api/v1/client/login          — логин (mid=1 логин+пароль, mid=2 req_id+код)
    POST   /api/v1/client/update-check   — проверка версии клиента
    POST   /api/v1/client/send-code      — AuthStart
    POST   /api/v1/client/note           — relay {note} в Tinode
    POST   /api/v1/client/sync-load      — запрос пакета базовых данных
    POST   /api/v1/client/sync-edit      — подтверждение пакета
    GET    /api/v1/client/sync-stats     — диагностика sync-механизма
    GET    /api/v1/client/health         — health-check client-sync канала

Контракт ответа /register и /login (единый):

    Успех:
        {"scs": 1, "usi": "<usrXXX>", "prm": "<json-строка>"}
        — prm отдаётся как есть из колонки prm процедуры
          (без разбора на upd/snc/prm-индекс);
        — psh (если есть pending-сигналы) добавляется отдельным полем;
        — timestamp отсутствует.

    Неуспех:
        {"scs": 0, "error": "<код>", "message": "...", "usi": "<usrXXX>"?}
        — prm присутствует только для force_update (сырая строка);
        — timestamp отсутствует.

Формат WS-токена для /login (7 полей, разделитель ``|``):

    fid|sch|prm1|prm2|yyMMdd|appVer|appCode

    - fid:     UUID Firebase, [A-Za-z0-9_\\-]{20,}
    - sch:     "1" | "2" (mid при вызове PA_mbl_AuthLogin_Exec)
    - prm1:    логин (sch=1) | request_id (sch=2), '|' → '_'
    - prm2:    пароль (sch=1) | код (sch=2), '|' → '_'
    - yyMMdd:  6 цифр, дата токена
    - appVer:  versionName, '|' → '_'
    - appCode: versionCode, десятичное число

Для /register сохраняется legacy-формат (5 полей):

    fid|usrXXXX|yyMMdd|ver|code
"""

from __future__ import annotations

import asyncio
import json
import re
from typing import Any

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field, field_validator

from ...config import settings
from ...db.repositories import TeamdroidProcedureRepository
from ...dtos.sync import (
    SyncEditRequest,
    SyncEditResponse,
)
from ...dtos.sync import (
    SyncLoadRequest as _BaseSyncLoadRequest,
)
from ...logger import api_logger
from ...models import datetime_now
from ...services.sync_session_registry import sync_session_registry
from ...utils.decorators import log_exceptions
from ...ws.push_notification_service import push_notification_service
from ...ws.token_crypto import decrypt_ws_token, decrypt_ws_token_legacy

router = APIRouter(prefix="/client", tags=["Client"])

# ---------------------------------------------------------------------------
# Общие константы
# ---------------------------------------------------------------------------

_USER_ID_RE = re.compile(r"^usr[A-Za-z0-9_\-]{10,}$")
_TOPIC_PREFIXES = ("usr", "grp", "p2p", "fnd", "me")
_NOTE_WHAT_ALLOWED = frozenset({"recv", "read", "kp"})

_FAILED_ITEMS_RE = re.compile(r"(?:^|,)\s*(\d+)\s*:")
_FAILED_MARKER = "PRC_mbl_SyncBaseDataEdit_NoData:"

_BAD_TS_MARKER = "PRC_mbl_SyncBaseDataEdit_BadTs:"
_BAD_TS_RE = re.compile(r"(?:^|,)\s*(\d+)(?:,|$)")


# ---------------------------------------------------------------------------
# Хелперы
# ---------------------------------------------------------------------------


def _extract_client_ip(request: Request) -> str:
    """IP клиента с учётом прокси."""
    xff = request.headers.get("x-forwarded-for")
    if xff:
        parts = [p.strip() for p in xff.split(",") if p.strip()]
        if parts:
            return parts[-1][:64]
    xri = request.headers.get("x-real-ip")
    if xri:
        return xri.strip()[:64]
    client = request.client
    if client is not None:
        return (client.host or "")[:64]
    return ""


def _error_response(status_code: int, error: str) -> JSONResponse:
    """Стандартный JSON-ответ об ошибке для sync-load / sync-edit / note /
    send-code (контракт {"scs":0, ...})."""
    return JSONResponse(
        status_code=status_code,
        content={
            "scs": 0,
            "status_code": status_code,
            "error": error,
        },
    )


def _fail(
    status_code: int,
    error: str,
    message: str | None = None,
    **extra: Any,
) -> JSONResponse:
    """Единый формат неуспеха /register и /login: scs=0 + инфо об ошибке."""
    body: dict[str, Any] = {"scs": 0, "error": error}
    if message is not None:
        body["message"] = message
    if extra:
        body.update(extra)
    return JSONResponse(status_code=status_code, content=body)


def _as_str(value: Any) -> str | None:
    """Приводит значение к ``str | None``."""
    if value is None:
        return None
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="replace") or None
    if isinstance(value, str):
        return value or None
    return str(value)


def _extract_prm_parts(prm_raw: str | None) -> tuple[str | None, str | None, int | None]:
    """Извлечь из prm_raw (сырой строки) sid, snc и предложенный vcd.

    Возвращает (sid, snc, vcd). Любой элемент может быть None.
    Парсинг best-effort: при любой ошибке возвращает (None, None, None).
    """
    if not prm_raw:
        return None, None, None

    try:
        items = json.loads(prm_raw)
    except (ValueError, TypeError):
        return None, None, None

    if not isinstance(items, list):
        return None, None, None

    sid_val: str | None = None
    snc_val: str | None = None
    vcd_val: int | None = None

    for item in items:
        if not isinstance(item, dict):
            continue

        if "fup" in item and vcd_val is None:
            raw_inner = item.get("prm")
            inner = None
            if isinstance(raw_inner, str):
                try:
                    inner = json.loads(raw_inner)
                except (ValueError, TypeError):
                    inner = None
            elif isinstance(raw_inner, dict):
                inner = raw_inner
            if isinstance(inner, dict):
                v = inner.get("vcd")
                if isinstance(v, int) and v > 0:
                    vcd_val = v

        if "sid" in item and sid_val is None:
            sid_val = _as_str(item.get("sid"))
            snc_val = _as_str(item.get("snc"))

    return sid_val, snc_val, vcd_val


def _extract_dtp_from_prm(prm_raw: str | None) -> list[int]:
    """Извлечь dtp из элемента {"sid":...} в prm_raw.

    Возвращает [] при любой ошибке или отсутствии элемента.
    """
    if not prm_raw:
        return []
    try:
        items = json.loads(prm_raw)
    except (ValueError, TypeError):
        return []
    if not isinstance(items, list):
        return []
    for item in items:
        if not isinstance(item, dict) or "sid" not in item:
            continue
        dtp_val = item.get("dtp")
        if isinstance(dtp_val, str):
            try:
                dtp_val = json.loads(dtp_val)
            except (ValueError, TypeError):
                return []
        if not isinstance(dtp_val, list):
            return []
        result: list[int] = []
        for x in dtp_val:
            try:
                result.append(int(x))
            except (ValueError, TypeError):
                continue
        return result
    return []


def _decrypt_and_get_ids(
    token: str,
) -> tuple[str, str, int] | JSONResponse | None:
    """Расшифровывает legacy WS-токен и возвращает (usi, dvc, api)."""
    data = decrypt_ws_token_legacy(token)
    if data is None:
        return None
    app_id = int(getattr(settings, "TEAMDROID_APP_ID", 0) or 0)
    if app_id <= 0:
        api_logger.error("client.sync: TEAMDROID_APP_ID=0 — sync невозможен")
        return JSONResponse(
            status_code=503,
            content={
                "scs": 0,
                "error": "server_misconfigured",
                "message": "TEAMDROID_APP_ID is not configured",
                "retry": None,
            },
        )
    return data.user_id, data.fcm_id, app_id


def _parse_failed_rows_from_sql_error(err_text: str) -> list[int]:
    if not err_text:
        return []
    idx = err_text.find(_FAILED_MARKER)
    if idx < 0:
        return []
    tail = err_text[idx + len(_FAILED_MARKER) :]
    try:
        return sorted({int(m) for m in _FAILED_ITEMS_RE.findall(tail)})
    except ValueError:
        return []


def _parse_bad_ts_rows_from_sql_error(err_text: str) -> list[int]:
    if not err_text:
        return []
    idx = err_text.find(_BAD_TS_MARKER)
    if idx < 0:
        return []
    tail = err_text[idx + len(_BAD_TS_MARKER) :]
    try:
        return sorted({int(m) for m in _BAD_TS_RE.findall(tail)})
    except ValueError:
        return []


def _bump_sync_stat(name: str, delta: int = 1) -> None:
    try:
        TeamdroidProcedureRepository.bump_sync_stat(name, delta)
    except (TypeError, ValueError) as bump_exc:
        api_logger.warning("bump_sync_stat(%r, %r) failed: %r", name, delta, bump_exc)


# ===========================================================================
# 1. FID REGISTRATION — POST /register
# ===========================================================================


class _TokenPayload(BaseModel):
    token: str = Field(..., min_length=1)

    @field_validator("token")
    @classmethod
    def _strip(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("empty token")
        return v


class SyncLoadRequest(_TokenPayload, _BaseSyncLoadRequest):
    pass


def _decrypt_or_error(token: str) -> tuple[object | None, JSONResponse | None]:
    """Расшифровать legacy-токен (5 полей) — для /register."""
    payload = decrypt_ws_token_legacy(token)
    if payload is None:
        return None, JSONResponse(
            status_code=400,
            content={
                "scs": 0,
                "error": "invalid_token",
                "message": "Token decryption or validation failed",
                "retry": None,
            },
        )
    return payload, None


@router.post(
    "/register",
    summary="Зарегистрировать FID (с проверкой токена)",
)
@log_exceptions(api_logger)
async def register_fid(payload: _TokenPayload, request: Request) -> JSONResponse:
    """Регистрация FID по legacy WS-токену (5 полей).

    Контракт ответа — см. docstring модуля.
    """
    from ...ws.token_crypto import WsTokenDataLegacy

    data, err = _decrypt_or_error(payload.token)
    if err is not None:
        return _fail(400, "invalid_token", "Token decryption or validation failed")
    if not isinstance(data, WsTokenDataLegacy):
        return _fail(400, "invalid_token", "Unexpected token payload format")

    user_id = data.user_id
    fid = data.fcm_id
    client_ip = _extract_client_ip(request)

    app_id = int(getattr(settings, "TEAMDROID_APP_ID", 0) or 0)
    if not app_id:
        api_logger.error("client.register: TEAMDROID_APP_ID=0 — TokenVerify невозможен")
        return _fail(503, "server_misconfigured", "TEAMDROID_APP_ID is not configured")

    # 1) TokenVerify.
    try:
        ok, verify_err, prm_raw = await asyncio.wait_for(
            asyncio.to_thread(
                TeamdroidProcedureRepository.verify_token,
                user_id=user_id,
                fcm_id=fid,
                app_id=app_id,
                token_date=data.date,
                client_ip=client_ip,
                app_version=data.app_version,
                app_version_code=data.app_version_code,
            ),
            timeout=30.0,
        )
    except TimeoutError:
        api_logger.warning("client.register: verify_token timeout user=%s", user_id)
        return _fail(504, "verify_timeout", "TokenVerify timeout", retry="register")

    # 2) Отказ / force-update.
    if not ok:
        api_logger.warning(
            "client.register: rejected user=%s fid_suffix=%s err=%s has_prm=%s",
            user_id,
            fid[-6:] if len(fid) >= 6 else "***",
            verify_err,
            prm_raw is not None,
        )

        if prm_raw:
            return _fail(
                401,
                "force_update",
                verify_err or "TokenVerify failed",
                prm=prm_raw,
            )

        return _fail(
            401,
            "token_rejected",
            verify_err or "TokenVerify failed",
        )

    # 3) scs=1 — регистрируем FID.
    await push_notification_service.update_fid(user_id, fid)
    api_logger.info(
        "client.register: OK user=%s fid_suffix=...%s prm_len=%d",
        user_id,
        fid[-8:] if len(fid) >= 8 else "***",
        len(prm_raw) if prm_raw else 0,
    )

    # 4) best-effort фиксация предложенного vcd.
    sid_val, snc_val, vcd_val = _extract_prm_parts(prm_raw)
    if isinstance(vcd_val, int) and vcd_val > 0:
        try:
            await asyncio.wait_for(
                asyncio.to_thread(
                    TeamdroidProcedureRepository.app_update_offered_batch,
                    [{"usi": user_id, "api": int(app_id), "dvc": fid, "vcd": int(vcd_val)}],
                ),
                timeout=10.0,
            )
            api_logger.info("client.register: offered vcd recorded user=%s vcd=%d", user_id, vcd_val)
        except Exception as vcd_exc:  # noqa: BLE001
            api_logger.warning(
                "client.register: failed to record offered vcd user=%s: %r",
                user_id,
                vcd_exc,
            )

    # 5) TApps sync (best-effort).
    try:
        from ...db import db_manager
        from ...db.repositories import AppRepository

        async with db_manager.get_session() as session:
            app = await AppRepository.get_or_create_app(session, fid, user_id=user_id)
            app.FLastSeenAt = datetime_now()
            await session.commit()
    except Exception as tapps_exc:  # noqa: BLE001
        api_logger.warning("client.register: TApps sync failed user=%s: %r", user_id, tapps_exc)

    # 6) Регистрируем sid в реестре (для последующего sync-edit).
    if sid_val:
        dtp_int = _extract_dtp_from_prm(prm_raw)
        try:
            await sync_session_registry.record_sid(
                user_id=user_id,
                sid=sid_val,
                snc=snc_val,
                dtp=dtp_int,
            )
            if snc_val and dtp_int:
                await sync_session_registry.record_load(
                    user_id=user_id,
                    sync_time=snc_val,
                    data_types=set(dtp_int),
                )
        except Exception as reg_exc:  # noqa: BLE001
            api_logger.warning(
                "client.register: failed to record sid user=%s sid=%s: %r",
                user_id,
                sid_val,
                reg_exc,
            )

    # 7) pending-сигналы из TPushPending → поле psh.
    psh: list[dict[str, Any]] = []
    try:
        from ...db import db_manager
        from ...db.repositories.app_push_pending import app_push_pending_repo

        async with db_manager.get_session() as session:
            psh = await app_push_pending_repo.take_for_user(session, user_id)
            await session.commit()
        if psh:
            api_logger.info(
                "client.register: delivered %d pending pushes user=%s",
                len(psh),
                user_id,
            )
    except Exception as pending_exc:  # noqa: BLE001
        api_logger.warning(
            "client.register: failed to take pending pushes user=%s: %r",
            user_id,
            pending_exc,
        )

    # 8) Сборка успешного ответа.
    body: dict[str, Any] = {"scs": 1}
    if prm_raw:
        body["prm"] = prm_raw
    if psh:
        body["psh"] = psh

    api_logger.info(
        "client.register: response user=%s scs=1 prm_len=%d psh=%d",
        user_id,
        len(prm_raw) if prm_raw else 0,
        len(psh),
    )

    return JSONResponse(status_code=200, content=body)


# ===========================================================================
# 1.1. LOGIN — POST /login (mid=1|2)
# ===========================================================================


@router.post(
    "/login",
    summary="Логин по WS-токену (расширенный формат)",
)
@log_exceptions(api_logger)
async def client_login(payload: _TokenPayload, request: Request) -> JSONResponse:
    """Логин по WS-токену нового формата (7 полей).

    Контракт токена (plaintext)::

        fid|sch|prm1|prm2|yyMMdd|appVer|appCode

    - ``sch``   — "1" (логин+пароль) | "2" (request_id + код);
    - ``prm1``  — логин (sch=1) | request_id (sch=2);
    - ``prm2``  — пароль (sch=1) | код (sch=2).

    Сервер:
      1) расшифровывает токен (без usi — его в plaintext нет);
      2) вызывает ext.PA_mbl_AuthLogin_Exec через
         TeamdroidProcedureRepository.login(mid=sch, pr1=prm1, pr2=prm2,
                                             dvc=fid, tkn=yyMMdd, cip=IP,
                                             ver=appVer, vcd=appCode,
                                             api=TEAMDROID_APP_ID);
         процедура сама проверяет учётные данные и делает TokenVerify,
         возвращает (Success, Usi, prm);
      3) best-effort пишет offered vcd;
      4) scs=0 при отказе / force-update;
      5) scs=1 + usi + update_fid + запись sid в реестр + pending-сигналы.
    """
    from ...ws.token_crypto import WsTokenData

    data = decrypt_ws_token(payload.token)
    if data is None:
        return _fail(
            400,
            "invalid_token",
            "Token decryption or validation failed",
        )
    assert isinstance(data, WsTokenData)

    fid = data.fcm_id
    client_ip = _extract_client_ip(request)

    app_id = int(getattr(settings, "TEAMDROID_APP_ID", 0) or 0)
    if not app_id:
        api_logger.error("client.login: TEAMDROID_APP_ID=0 — Login невозможен")
        return _fail(503, "server_misconfigured", "TEAMDROID_APP_ID is not configured")

    api_logger.info(
        "client.login: START mid=%s pr1_len=%d pr2_len=%d fid_suffix=...%s ver=%s vcd=%d",
        data.sch,
        len(data.prm1),
        len(data.prm2),
        fid[-8:] if len(fid) >= 8 else "***",
        data.app_version,
        data.app_version_code,
    )

    # ── Шаг 1: единый вызов ext.PA_mbl_AuthLogin_Exec (mid=1|2) ──
    try:
        ok, err, user_id, prm_raw = await asyncio.wait_for(
            asyncio.to_thread(
                TeamdroidProcedureRepository.login,
                mid=int(data.sch),
                pr1=data.prm1,
                pr2=data.prm2,
                fcm_id=fid,
                token_date=data.date,
                client_ip=client_ip,
                app_version=data.app_version,
                app_version_code=data.app_version_code,
                app_id=app_id,
            ),
            timeout=30.0,
        )
    except TimeoutError:
        api_logger.warning("client.login: timeout fid_suffix=...%s", fid[-6:])
        return _fail(504, "login_timeout", "Login timeout", retry="login")

    # ── Шаг 2: разбор prm_raw для offered vcd ──
    sid_val, snc_val, vcd_val = _extract_prm_parts(prm_raw)

    async def _record_offered_vcd(usi_for_vcd: str | None) -> None:
        if not usi_for_vcd or not isinstance(vcd_val, int) or vcd_val <= 0:
            return
        try:
            await asyncio.wait_for(
                asyncio.to_thread(
                    TeamdroidProcedureRepository.app_update_offered_batch,
                    [{"usi": usi_for_vcd, "api": int(app_id), "dvc": fid, "vcd": int(vcd_val)}],
                ),
                timeout=10.0,
            )
            api_logger.info("client.login: offered vcd recorded user=%s vcd=%d", usi_for_vcd, vcd_val)
        except Exception as vcd_exc:  # noqa: BLE001
            api_logger.warning("client.login: failed to record offered vcd: %r", vcd_exc)

    # ── Шаг 3: отказ / force-update ──
    if not ok:
        api_logger.warning(
            "client.login: REJECTED mid=%s fid_suffix=...%s err=%s has_prm=%s has_usi=%s",
            data.sch,
            fid[-6:] if len(fid) >= 6 else "***",
            err,
            prm_raw is not None,
            bool(user_id),
        )
        await _record_offered_vcd(user_id)

        if err == "invalid_credentials":
            return _fail(
                401,
                "auth_failed",
                "Invalid login/password or request_id/code",
                usi=user_id,
            )
        if err == "force_update":
            return _fail(
                401,
                "force_update",
                "Force update required",
                usi=user_id,
                prm=prm_raw or "[]",
            )
        if err == "PRC_mbl_AuthLogin_NoData":
            return _fail(
                409,
                "device_session_not_found",
                "Re-register via /client/register",
                retry="register",
                usi=user_id,
            )
        return _fail(
            401,
            "token_rejected",
            err or "Login failed",
            usi=user_id,
        )

    assert user_id is not None

    # ── Шаг 4: scs=1 — регистрируем FID ──
    await push_notification_service.update_fid(user_id, fid)
    api_logger.info(
        "client.login: OK user=%s prm_len=%d",
        user_id,
        len(prm_raw) if prm_raw else 0,
    )

    await _record_offered_vcd(user_id)

    # ── Шаг 5: TApps sync (best-effort) ──
    try:
        from ...db import db_manager
        from ...db.repositories import AppRepository

        async with db_manager.get_session() as session:
            app = await AppRepository.get_or_create_app(session, fid, user_id=user_id)
            app.FLastSeenAt = datetime_now()
            await session.commit()
    except Exception as tapps_exc:  # noqa: BLE001
        api_logger.warning("client.login: TApps sync failed user=%s: %r", user_id, tapps_exc)

    # ── Шаг 6: запись sid в реестр (для последующего sync-edit) ──
    if sid_val:
        dtp_int = _extract_dtp_from_prm(prm_raw)
        try:
            await sync_session_registry.record_sid(
                user_id=user_id,
                sid=sid_val,
                snc=snc_val,
                dtp=dtp_int,
            )
            if snc_val and dtp_int:
                await sync_session_registry.record_load(
                    user_id=user_id,
                    sync_time=snc_val,
                    data_types=set(dtp_int),
                )
        except Exception as reg_exc:  # noqa: BLE001
            api_logger.warning(
                "client.login: failed to record sid user=%s sid=%s: %r",
                user_id,
                sid_val,
                reg_exc,
            )

    # ── Шаг 7: pending-сигналы из TPushPending → поле psh ──
    psh: list[dict[str, Any]] = []
    try:
        from ...db import db_manager
        from ...db.repositories.app_push_pending import app_push_pending_repo

        async with db_manager.get_session() as session:
            psh = await app_push_pending_repo.take_for_user(session, user_id)
            await session.commit()
        if psh:
            api_logger.info(
                "client.login: delivered %d pending pushes user=%s",
                len(psh),
                user_id,
            )
    except Exception as pending_exc:  # noqa: BLE001
        api_logger.warning(
            "client.login: failed to take pending pushes user=%s: %r",
            user_id,
            pending_exc,
        )

    # ── Шаг 8: ответ ──
    body: dict[str, Any] = {"scs": 1, "usi": user_id}
    if prm_raw:
        body["prm"] = prm_raw
    if psh:
        body["psh"] = psh

    api_logger.info(
        "client.login: response user=%s scs=1 prm_len=%d psh=%d",
        user_id,
        len(prm_raw) if prm_raw else 0,
        len(psh),
    )

    return JSONResponse(status_code=200, content=body)


# ===========================================================================
# 2. FID UNREGISTRATION — DELETE /register (logout → TokenFinish)
# ===========================================================================


@router.delete(
    "/register",
    summary="Удалить FID (с завершением сессии токена)",
)
@log_exceptions(api_logger)
async def unregister_fid(payload: _TokenPayload) -> JSONResponse:
    """Удаление FID и завершение сессии токена.

    Вызывает ext.PA_mbl_TokenFinish_Exec через
    TeamdroidProcedureRepository.logout(usi, dvc, api).
    """
    from ...ws.token_crypto import WsTokenDataLegacy

    data, err = _decrypt_or_error(payload.token)
    if err is not None:
        return err
    assert isinstance(data, WsTokenDataLegacy)

    user_id = data.user_id
    fid = data.fcm_id

    app_id = int(getattr(settings, "TEAMDROID_APP_ID", 0) or 0)

    finish_ok = False
    if app_id:
        try:
            finish_ok, finish_err = await asyncio.wait_for(
                asyncio.to_thread(
                    TeamdroidProcedureRepository.logout,
                    usi=user_id,
                    fcm_id=fid,
                    app_id=app_id,
                ),
                timeout=30.0,
            )
            if not finish_ok:
                api_logger.warning(
                    "client.unregister: logout non-OK user=%s err=%s",
                    user_id,
                    finish_err,
                )
        except TimeoutError:
            api_logger.warning("client.unregister: logout timeout user=%s", user_id)
    else:
        api_logger.warning("client.unregister: TEAMDROID_APP_ID=0 — logout пропущен")

    await push_notification_service.remove_fid(user_id, fid)

    try:
        from ...db import db_manager
        from ...db.repositories import AppRepository

        async with db_manager.get_session() as session:
            app = await AppRepository.get_app_by_fid(session, fid)
            if app is not None and app.FUserID == user_id:
                app.FUserID = None
            await session.commit()
    except Exception as tapps_exc:  # noqa: BLE001
        api_logger.warning("client.unregister: TApps sync failed: %r", tapps_exc)

    api_logger.info(
        "client.unregister: OK user=%s fid_suffix=...%s logout_ok=%s",
        user_id,
        fid[-8:] if len(fid) >= 8 else "***",
        finish_ok,
    )

    return JSONResponse(
        status_code=200,
        content={
            "scs": 0,
            "user_id": user_id,
            "fid_registered": False,
            "token_finished": finish_ok,
        },
    )


# ===========================================================================
# 2.1. APP UPDATE CHECK — POST /update-check
# ===========================================================================


@router.post(
    "/update-check",
    summary="Проверить актуальность версии клиента",
)
@log_exceptions(api_logger)
async def app_update_check(payload: _TokenPayload) -> JSONResponse:
    from ...ws.token_crypto import WsTokenDataLegacy

    data, err = _decrypt_or_error(payload.token)
    if err is not None:
        return err
    assert isinstance(data, WsTokenDataLegacy)

    user_id = data.user_id
    fid = data.fcm_id

    app_id = int(getattr(settings, "TEAMDROID_APP_ID", 0) or 0)
    if not app_id:
        api_logger.error("client.app_update_check: TEAMDROID_APP_ID=0")
        return JSONResponse(
            status_code=503,
            content={
                "scs": 0,
                "error": "server_misconfigured",
                "message": "TEAMDROID_APP_ID is not configured",
                "retry": None,
            },
        )

    try:
        info = await asyncio.wait_for(
            asyncio.to_thread(
                TeamdroidProcedureRepository.app_update_check,
                user_id=user_id,
                fcm_id=fid,
                app_id=app_id,
            ),
            timeout=10.0,
        )
    except TimeoutError:
        api_logger.warning("client.app_update_check: timeout user=%s", user_id)
        return JSONResponse(
            status_code=504,
            content={
                "scs": 0,
                "error": "check_timeout",
                "retry": "sync-edit",
            },
        )

    if info is None:
        api_logger.warning(
            "client.app_update_check: NoData user=%s fid_suffix=%s",
            user_id,
            fid[-6:] if len(fid) >= 6 else "***",
        )
        return JSONResponse(
            status_code=404,
            content={
                "scs": 0,
                "error": "device_not_registered",
                "message": "Active device session not found",
                "retry": "register",
            },
        )

    api_logger.info(
        "client.app_update_check: user=%s result_len=%s",
        user_id,
        len(info) if info else 0,
    )

    try:
        from ...db import db_manager
        from ...db.repositories import AppRepository

        async with db_manager.get_session() as session:
            app = await AppRepository.get_app_by_fid(session, fid)
            if app is not None:
                app.FLastSeenAt = datetime_now()
                await session.commit()
    except Exception as ts_exc:  # noqa: BLE001
        api_logger.warning("client.app_update_check: FLastSeenAt update failed: %r", ts_exc)

    return JSONResponse(
        status_code=200,
        content={
            "scs": 1,
            "result": info,
        },
    )


# ===========================================================================
# 2.5. AUTH CODE — POST /send-code
# ===========================================================================


@router.post(
    "/send-code",
    summary="Запустить хранимую процедуру SQL Server для отправки кода",
)
@log_exceptions(api_logger)
async def send_code(params: dict[str, Any], request: Request) -> JSONResponse:
    phone = params.get("phone")
    if isinstance(phone, str):
        phone_str: str = phone.strip()
        digits = "".join(ch for ch in phone_str if ch.isdigit())
        if len(digits) < 8 or not phone_str.startswith("+"):
            return _error_response(400, "invalid_phone_format")
        params["phone"] = phone_str

    params["client_ip"] = _extract_client_ip(request)

    try:
        result = await asyncio.to_thread(
            TeamdroidProcedureRepository.auth_start,
            params,
        )
    except Exception as proc_exc:  # noqa: BLE001
        api_logger.error("❌ [client] send_code procedure failed: %r", proc_exc, exc_info=True)
        return _error_response(
            500,
            f"send_code_proc_failed: {type(proc_exc).__name__}: {proc_exc}",
        )

    api_logger.debug("✅ [client] send_code procedure executed: ip=%r", params.get("client_ip"))

    return JSONResponse(
        status_code=200,
        content={
            "scs": 1,
            "result": result.get("result"),
        },
    )


# ===========================================================================
# 3. NOTE RELAY — POST /note
# ===========================================================================


class NoteRelayRequest(BaseModel):
    topic: str = Field(..., min_length=1, max_length=64)
    what: str = Field(..., min_length=1, max_length=8)
    seq: int = Field(..., ge=0)
    user_id: str = Field(..., max_length=32)
    tinode_server: str | None = Field(None, max_length=255)

    @field_validator("topic")
    @classmethod
    def validate_topic(cls, v: str) -> str:
        v = v.strip()
        if not any(v.startswith(p) for p in _TOPIC_PREFIXES):
            raise ValueError(f"Topic must start with one of: {', '.join(_TOPIC_PREFIXES)}")
        if not re.fullmatch(r"[A-Za-z0-9_\-:.]+", v):
            raise ValueError("Topic contains invalid characters")
        return v

    @field_validator("what")
    @classmethod
    def validate_what(cls, v: str) -> str:
        v = v.strip().lower()
        if v not in _NOTE_WHAT_ALLOWED:
            raise ValueError(f"what must be one of: {', '.join(sorted(_NOTE_WHAT_ALLOWED))}, got {v!r}")
        return v

    @field_validator("user_id")
    @classmethod
    def validate_user_id(cls, v: str) -> str:
        v = v.strip()
        if not _USER_ID_RE.match(v):
            raise ValueError(f"user_id must match usr[A-Za-z0-9_-]+, got {v!r}")
        return v


class NoteRelayResponse(BaseModel):
    scs: int = Field(True)
    topic: str = Field(...)
    what: str = Field(...)
    seq: int = Field(...)
    user_id: str = Field(...)
    ctrl_code: int | None = Field(None)
    ctrl_text: str | None = Field(None)
    teamdroid_saved: bool = Field(False)


def _do_note(
    topic: str,
    what: str,
    seq: int,
    on_behalf_of: str,
    client_ip: str,
) -> tuple[dict[str, Any], bool]:
    from .teamdroid import _ctrl_to_dict, get_teamdroid_client

    client = get_teamdroid_client()

    ctrl = client.note(
        topic=topic,
        what=what,
        seq=seq,
        on_behalf_of=on_behalf_of,
    )
    ctrl_dict = _ctrl_to_dict(ctrl) if ctrl is not None else {}

    teamdroid_saved = False
    if what in ("recv", "read"):
        teamdroid_saved = TeamdroidProcedureRepository.edit_msg_status_delivery(
            topic=topic,
            what=what,
            seq=seq,
            user_id=on_behalf_of,
            client_ip=client_ip,
        )

    return ctrl_dict, teamdroid_saved


@router.post(
    "/note",
    summary="Переслать {note} (recv/read/kp) в Tinode",
)
@log_exceptions(api_logger)
async def relay_note(
    request: Request,
    payload: NoteRelayRequest,
) -> JSONResponse:
    from .teamdroid import _ensure_pb_available

    _ensure_pb_available()

    user_id = payload.user_id
    client_ip = _extract_client_ip(request)

    api_logger.info(
        "📨 [client/note] topic=%r what=%s seq=%s user=%r ip=%r",
        payload.topic,
        payload.what,
        payload.seq,
        user_id,
        client_ip,
    )

    try:
        ctrl_dict, teamdroid_saved = await asyncio.to_thread(
            _do_note,
            payload.topic,
            payload.what,
            payload.seq,
            user_id,
            client_ip,
        )
    except ValueError as val_exc:
        api_logger.warning("[client/note] validation error: %s", val_exc)
        return JSONResponse(
            status_code=400,
            content={
                "scs": 0,
                "error": f"validation_error: {val_exc}",
            },
        )
    except Exception as note_exc:  # noqa: BLE001
        api_logger.error("[client/note] failed: %r", note_exc, exc_info=True)
        return JSONResponse(
            status_code=500,
            content={
                "scs": 0,
                "error": f"{type(note_exc).__name__}: {note_exc}",
            },
        )

    ctrl_code = ctrl_dict.get("code")
    ctrl_text = ctrl_dict.get("text")

    response = NoteRelayResponse(
        scs=1,
        topic=payload.topic,
        what=payload.what,
        seq=payload.seq,
        user_id=user_id,
        ctrl_code=ctrl_code if isinstance(ctrl_code, int) else None,
        ctrl_text=ctrl_text if isinstance(ctrl_text, str) else None,
        teamdroid_saved=teamdroid_saved,
    )

    if isinstance(ctrl_code, int) and ctrl_code >= 400:
        api_logger.warning("⚠️ [client/note] Tinode returned CTRL code=%s text=%r", ctrl_code, ctrl_text)
        return JSONResponse(
            status_code=502,
            content={
                **response.model_dump(),
                "scs": 0,
                "error": f"tinode_ctrl_error: code={ctrl_code} text={ctrl_text!r}",
            },
        )

    return JSONResponse(status_code=200, content=response.model_dump())


# ===========================================================================
# 4. SYNC BASE DATA — POST /sync-load, POST /sync-edit
# ===========================================================================


@router.post(
    "/sync-load",
    summary="Загрузить пакет базовых данных для синхронизации",
)
@log_exceptions(api_logger)
async def sync_base_load(
    payload: SyncLoadRequest,
    request: Request,
) -> JSONResponse:
    ids = _decrypt_and_get_ids(payload.token)
    if ids is None:
        return _error_response(400, "invalid_token")
    if isinstance(ids, JSONResponse):
        return ids
    user_id, fcm_id, app_id = ids
    client_ip = _extract_client_ip(request)

    ok_iter, iters = await sync_session_registry.check_iterations(user_id)
    if not ok_iter:
        api_logger.warning("sync_base.load: too many iterations user=%s n=%d", user_id, iters)
        return JSONResponse(
            status_code=429,
            content={
                "scs": 0,
                "status_code": 429,
                "error": "too_many_iterations",
                "message": "Too many Load calls without a successful Edit",
                "retry": "sync-edit",
            },
        )

    requested_types: list[int] = list(payload.data_types or [])
    force_flag: bool = bool(payload.force)

    if not requested_types:
        api_logger.warning(
            "sync_base.load: user=%s dtp=null — рекомендую явный непустой dtp",
            user_id,
        )

    api_logger.info(
        "sync_base.load: user=%s dvc=%s... api=%d dtp=%r frc=%s ip=%r",
        user_id,
        fcm_id[-6:] if len(fcm_id) >= 6 else "***",
        app_id,
        requested_types,
        force_flag,
        client_ip,
    )

    load_timeout = int(getattr(settings, "APP_CLIENT_SYNC_BASE_LOAD_TIMEOUT_SEC", 30) or 30)
    try:
        bundle = await asyncio.wait_for(
            asyncio.to_thread(
                TeamdroidProcedureRepository.load_base_data,
                user_id=user_id,
                fcm_id=fcm_id,
                app_id=app_id,
                data_types=payload.data_types,
                limit=None,
                force=force_flag,
                client_ip=client_ip,
            ),
            timeout=load_timeout,
        )
    except TimeoutError:
        api_logger.warning("sync_base.load: timeout user=%s", user_id)
        return JSONResponse(
            status_code=504,
            content={
                "scs": 0,
                "status_code": 504,
                "error": "load_timeout",
                "retry": "sync-load",
            },
        )
    except RuntimeError as e:
        if "PRC_mbl_SyncBaseData_NoData" in str(e):
            api_logger.warning("sync_base.load: NoData user=%s", user_id)
            return JSONResponse(
                status_code=409,
                content={
                    "scs": 0,
                    "status_code": 409,
                    "error": "device_session_not_found",
                    "message": "Device session not found; re-register via /client/register",
                    "retry": "register",
                },
            )
        raise

    sid: str = str(bundle.get("sid") or "")
    snc: str | None = bundle.get("snc")
    dtp_from_sql: list[int] = list(bundle.get("dtp") or [])
    prm: list[dict[str, Any]] = list(bundle.get("prm") or [])

    if not sid and snc is None and not dtp_from_sql and not prm:
        api_logger.info(
            "sync_base.load: no changes user=%s dtp=%r frc=%s",
            user_id,
            requested_types,
            force_flag,
        )
        return JSONResponse(status_code=200, content={"scs": 1})

    if not sid:
        api_logger.error(
            "sync_base.load: SQL returned empty sid with non-empty payload user=%s snc=%r dtp=%r prm_rows=%d",
            user_id,
            snc,
            dtp_from_sql,
            len(prm),
        )
        return JSONResponse(
            status_code=502,
            content={
                "scs": 0,
                "status_code": 502,
                "error": "invalid_sql_payload",
                "message": "SQL returned empty sid",
                "retry": None,
            },
        )

    await sync_session_registry.bump_iteration(user_id)

    await sync_session_registry.record_sid(
        user_id=user_id,
        sid=sid,
        snc=snc,
        dtp=dtp_from_sql,
    )
    if snc is not None and dtp_from_sql:
        await sync_session_registry.record_load(
            user_id=user_id,
            sync_time=snc,
            data_types=set(dtp_from_sql),
        )

    api_logger.info(
        "sync_base.load: OK user=%s sid=%s snc=%r dtp=%s prm_rows=%d",
        user_id,
        sid,
        snc,
        dtp_from_sql,
        len(prm),
    )

    return JSONResponse(
        status_code=200,
        content={
            "scs": 1,
            "sid": sid,
            "prm": prm,
        },
    )


@router.post(
    "/sync-edit",
    summary="Подтвердить применение пакета базовых данных",
)
@log_exceptions(api_logger)
async def sync_base_edit(
    payload: SyncEditRequest,
    request: Request,
) -> JSONResponse:
    max_items = int(getattr(settings, "APP_CLIENT_SYNC_BASE_MAX_EDIT_ITEMS", 100) or 100)
    if len(payload.items) > max_items:
        return JSONResponse(
            status_code=400,
            content={
                "scs": 0,
                "status_code": 400,
                "error": f"too many items (max {max_items})",
            },
        )

    items: list[dict[str, Any]] = []
    issues: list[dict[str, Any]] = []

    for idx, item in enumerate(payload.items):
        ids = _decrypt_and_get_ids(item.token)
        if ids is None:
            return JSONResponse(
                status_code=400,
                content={
                    "scs": 0,
                    "status_code": 400,
                    "error": "invalid_token",
                    "message": f"items[{idx}]: invalid token",
                    "retry": None,
                },
            )
        if isinstance(ids, JSONResponse):
            return ids
        user_id, fcm_id, app_id = ids

        entry = await sync_session_registry.lookup_sid(item.sid)
        if entry is None:
            api_logger.warning(
                "sync_base.edit: items[%d] unknown sid user=%s sid=%s",
                idx,
                user_id,
                item.sid,
            )
            issues.append({"index": idx, "usi": user_id, "reason": "unknown_sid"})
            continue
        if entry["user_id"] != user_id:
            api_logger.warning(
                "sync_base.edit: items[%d] sid user mismatch sid=%s registry=%s token=%s",
                idx,
                item.sid,
                entry["user_id"],
                user_id,
            )
            issues.append({"index": idx, "usi": user_id, "reason": "sid_user_mismatch"})
            continue

        snc: str | None = entry.get("snc")
        dtp: list[int] = list(entry.get("dtp") or [])
        if not snc or not dtp:
            api_logger.warning(
                "sync_base.edit: items[%d] sid empty snc/dtp sid=%s snc=%r dtp=%r",
                idx,
                item.sid,
                snc,
                dtp,
            )
            issues.append({"index": idx, "usi": user_id, "reason": "sid_empty"})
            continue

        items.append(
            {
                "usi": user_id,
                "api": app_id,
                "dvc": fcm_id,
                "dtp": [int(t) for t in dtp],
                "ts": snc,
                "_sid": item.sid,
            }
        )

    if issues:
        _bump_sync_stat("edit_invalid", 1)
        return JSONResponse(
            status_code=400,
            content={
                "scs": 0,
                "status_code": 400,
                "error": "invalid_edit",
                "issues": issues,
                "retry": "sync-load",
            },
        )

    if not items:
        return JSONResponse(
            status_code=400,
            content={
                "scs": 0,
                "status_code": 400,
                "error": "nothing_to_commit",
                "message": "items is empty; nothing to commit",
                "retry": None,
            },
        )

    sql_items: list[dict[str, Any]] = [{k: v for k, v in it.items() if k != "_sid"} for it in items]

    payload_bytes = len(json.dumps(sql_items, ensure_ascii=False).encode("utf-8"))
    api_logger.info(
        "sync_base.edit: items=%d types=%d users=%s sids=%d payload_bytes=%d ip=%r",
        len(sql_items),
        sum(len(i["dtp"]) for i in sql_items),
        sorted({i["usi"] for i in sql_items}),
        len({it["_sid"] for it in items}),
        payload_bytes,
        _extract_client_ip(request),
    )

    edit_timeout = int(getattr(settings, "APP_CLIENT_SYNC_BASE_EDIT_TIMEOUT_SEC", 20) or 20)
    try:
        await asyncio.wait_for(
            asyncio.to_thread(
                TeamdroidProcedureRepository.edit_base_data,
                sql_items,
            ),
            timeout=edit_timeout,
        )
    except TimeoutError:
        _bump_sync_stat("edit_timeout", 1)
        api_logger.warning(
            "sync_base.edit: timeout after %ss, MERGE continues in background items=%d",
            edit_timeout,
            len(sql_items),
        )
        return JSONResponse(
            status_code=504,
            content={
                "scs": 0,
                "status_code": 504,
                "error": "edit_timeout",
                "message": (
                    "Edit timed out. MERGE may have committed or not. "
                    "Call sync-load to get a fresh sid/sync_time; "
                    "do NOT retry with the same sid."
                ),
                "merge_may_have_committed": True,
                "retry": "sync-load",
            },
        )
    except RuntimeError as e:
        err_text = str(e)

        if "PRC_mbl_SyncBaseDataEdit_BadTs" in err_text:
            _bump_sync_stat("edit_bad_ts", 1)
            failed_rows = _parse_bad_ts_rows_from_sql_error(err_text)
            failed_rows_0based = sorted({r - 1 for r in failed_rows if 1 <= r <= len(sql_items)})
            api_logger.warning(
                "sync_base.edit: BadTs (ts не парсится как DATETIME) failed_items=%s",
                failed_rows_0based,
            )
            return JSONResponse(
                status_code=502,
                content={
                    "scs": 0,
                    "status_code": 502,
                    "error": "bad_ts",
                    "message": (
                        "SQL Server could not parse 'ts' as DATETIME. "
                        "Request a fresh sync-load and retry with the new sid."
                    ),
                    "failed_items": failed_rows_0based,
                    "retry": "sync-load",
                },
            )

        if "PRC_mbl_SyncBaseDataEdit_NoData" in err_text:
            api_logger.warning("sync_base.edit: NoData (ничего не записано)")
            failed_rows = _parse_failed_rows_from_sql_error(str(e))
            failed_rows_0based = sorted({r - 1 for r in failed_rows if 1 <= r <= len(sql_items)})
            failed_set = set(failed_rows_0based)
            ok_indices = [i for i in range(len(sql_items)) if i not in failed_set]

            _bump_sync_stat("edit_partial", 1)

            return JSONResponse(
                status_code=207,
                content={
                    "scs": 0,
                    "status_code": 207,
                    "error": "device_session_not_found",
                    "message": "Some items failed: device session not found for those users",
                    "failed_items": failed_rows_0based,
                    "ok_indices": ok_indices,
                    "total_items": len(sql_items),
                    "retry": None,
                },
            )

        raise

    for it in items:
        usi = it["usi"]
        sid_val = it["_sid"]
        try:
            await sync_session_registry.drop_sid(sid_val)
        except Exception as exc:  # noqa: BLE001
            api_logger.warning(
                "sync_base.edit: drop_sid failed user=%s sid=%s: %r",
                usi,
                sid_val,
                exc,
            )
        try:
            await sync_session_registry.reset(usi, sync_time=it["ts"])
        except Exception as reset_exc:  # noqa: BLE001
            api_logger.warning(
                "sync_base.edit: registry reset failed user=%s ts=%s: %r",
                usi,
                it["ts"],
                reset_exc,
            )
        try:
            await sync_session_registry.reset_iterations(usi)
        except Exception as iter_exc:  # noqa: BLE001
            api_logger.warning("sync_base.edit: iterations reset failed user=%s: %r", usi, iter_exc)

    committed_types = sum(len(i["dtp"]) for i in sql_items)
    api_logger.info(
        "sync_base.edit: OK user(s)=%s sids=%d items=%d types=%d",
        sorted({i["usi"] for i in sql_items}),
        len({it["_sid"] for it in items}),
        len(sql_items),
        committed_types,
    )

    return JSONResponse(
        status_code=200,
        content=SyncEditResponse(
            scs=1,
            committed_items=len(sql_items),
            committed_types=committed_types,
            failed_items=[],
            error=None,
            retry=None,
        ).model_dump(),
    )


# ===========================================================================
# 5. SYNC STATS — GET /sync-stats
# ===========================================================================


@router.get(
    "/sync-stats",
    summary="Диагностика sync-механизма",
)
@log_exceptions(api_logger)
async def sync_stats() -> JSONResponse:
    metrics_from_registry = sync_session_registry.metrics_snapshot()
    stats_snapshot = TeamdroidProcedureRepository.sync_base_stats_snapshot()

    return JSONResponse(
        status_code=200,
        content={
            "scs": 1,
            "stats": stats_snapshot,
            "registry": sync_session_registry.snapshot(),
            "sids_pending": sync_session_registry.sids_snapshot(),
            "iterations": sync_session_registry.iterations_snapshot(),
            "activity": sync_session_registry.activity_snapshot(),
            "metrics": {
                "invalid_edit_total": metrics_from_registry.get("validate_edit_rejected", 0),
                "unknown_sid_total": metrics_from_registry.get("lookup_sid_miss", 0),
                "sid_user_mismatch_total": metrics_from_registry.get("lookup_sid_user_mismatch", 0),
                "oversized_dropped_total": stats_snapshot.get("load_oversized", 0),
                "missing_total": stats_snapshot.get("load_missing", 0),
                "edit_timeout_total": stats_snapshot.get("edit_timeout", 0),
                "edit_partial_total": stats_snapshot.get("edit_partial", 0),
                "edit_bad_ts_total": stats_snapshot.get("edit_bad_ts", 0),
                "registry_cleanup_runs": metrics_from_registry.get("cleanup_runs", 0),
            },
            "fail_open_after_restart": True,
            "settings": {
                "ttl_sec": int(getattr(settings, "APP_CLIENT_SYNC_BASE_REGISTRY_TTL_SEC", 3600)),
                "max_iterations": int(getattr(settings, "APP_CLIENT_SYNC_BASE_REGISTRY_MAX_ITERATIONS", 100)),
                "max_packets_per_user": int(
                    getattr(settings, "APP_CLIENT_SYNC_BASE_REGISTRY_MAX_PACKETS_PER_USER", 10)
                ),
                "require_latest": bool(getattr(settings, "APP_CLIENT_SYNC_BASE_REGISTRY_REQUIRE_LATEST", False)),
                "default_limit": int(getattr(settings, "APP_CLIENT_SYNC_BASE_DEFAULT_LIMIT", 1000)),
                "max_limit": int(getattr(settings, "APP_CLIENT_SYNC_BASE_MAX_LIMIT", 50_000)),
                "max_edit_items": int(getattr(settings, "APP_CLIENT_SYNC_BASE_MAX_EDIT_ITEMS", 100)),
                "max_record_bytes": int(getattr(settings, "APP_CLIENT_SYNC_BASE_MAX_RECORD_BYTES", 10 * 1024 * 1024)),
                "load_timeout_sec": int(getattr(settings, "APP_CLIENT_SYNC_BASE_LOAD_TIMEOUT_SEC", 30)),
                "edit_timeout_sec": int(getattr(settings, "APP_CLIENT_SYNC_BASE_EDIT_TIMEOUT_SEC", 20)),
            },
        },
    )


# ===========================================================================
# 6. HEALTH — GET /health
# ===========================================================================


@router.get(
    "/health",
    summary="Проверка готовности client-sync API",
)
@log_exceptions(api_logger)
async def client_health() -> JSONResponse:
    app_id = int(getattr(settings, "TEAMDROID_APP_ID", 0) or 0)
    sql_server = (getattr(settings, "TEAMDROID_SQL_SERVER", "") or "").strip()
    return JSONResponse(
        status_code=200,
        content={
            "ok": True,
            "teamdroid_sql_configured": bool(sql_server),
            "teamdroid_app_id_configured": app_id > 0,
            "registry_ttl_sec": int(getattr(settings, "APP_CLIENT_SYNC_BASE_REGISTRY_TTL_SEC", 3600)),
            "max_edit_items": int(getattr(settings, "APP_CLIENT_SYNC_BASE_MAX_EDIT_ITEMS", 100)),
            "max_record_bytes": int(getattr(settings, "APP_CLIENT_SYNC_BASE_MAX_RECORD_BYTES", 10 * 1024 * 1024)),
            "default_limit": int(getattr(settings, "APP_CLIENT_SYNC_BASE_DEFAULT_LIMIT", 1000)),
            "max_limit": int(getattr(settings, "APP_CLIENT_SYNC_BASE_MAX_LIMIT", 50_000)),
            "load_timeout_sec": int(getattr(settings, "APP_CLIENT_SYNC_BASE_LOAD_TIMEOUT_SEC", 30)),
            "edit_timeout_sec": int(getattr(settings, "APP_CLIENT_SYNC_BASE_EDIT_TIMEOUT_SEC", 20)),
        },
    )


__all__ = ["router"]