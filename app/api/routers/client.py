"""Публичный API мобильного клиента Teamdroid.

Эндпоинты client-sync канала

    1. With auth by APP_CLIENT_SYNC_INGEST_API_KEYS

    auth: API_KEY_HEADER -> APP_CLIENT_SYNC_INGEST_API_KEYS

    POST /api/v1/client/login                     — аутентификация по логину и паролю

    2. With registry dvs in TApps:

    auth: API_KEY_HEADER -> APP_CLIENT_SYNC_INGEST_API_KEYS
    complete: add/edit TApps

    POST /api/v1/client/register                  — регистрация устройства

    3. With unregistry dvs in TApps:

    auth: API_KEY_HEADER -> APP_CLIENT_SYNC_INGEST_API_KEYS
    complete: delete TApps

    DELETE /api/v1/client/register                — удаление регистрации устройства

    4. With auth by TApps:

    auth: API_KEY_HEADER -> TApps.FKey
    complete: edit TApps.FLastSeenAt

    POST   /api/v1/client/send-code               — запуск аутентификации по номеру телефона
    POST   /api/v1/client/sync-load               — проверка появления и загрузка обновлений данных
    POST   /api/v1/client/sync-edit               — подтверждение успешного получения обновлений
    POST   /api/v1/client/uploads                 — создать загрузку (upload_id)
    PATCH  /api/v1/client/uploads/{uid}           — передать chunk (offst в заголовке)
    HEAD   /api/v1/client/uploads/{uid}           — текущая позиция (offst/size)
    POST   /api/v1/client/uploads/{uid}/complete  — завершить → file_id
    DELETE /api/v1/client/uploads/{uid}           — отменить загрузку
    GET    /api/v1/client/files/{fid}             — скачать файл (Range)
    POST   /api/v1/client/msgs                    — отправить сообщение (текст + fls)

    5. With auth by APP_CLIENT_SUPPORT_INGEST_API_KEYS:

    auth: API_KEY_HEADER -> APP_CLIENT_SUPPORT_INGEST_API_KEYS

    POST   /api/v1/client/update-check            — проверка актуальности версии клиента

    6. Others:

    auth: API_KEY_HEADER -> APP_CLIENT_SYNC_INGEST_API_KEYS

    GET    /api/v1/client/sync-stats              — диагностика sync-механизма
    GET    /api/v1/client/health                  — health-check client-sync канала

    7. Deprecated:

    auth: API_KEY_HEADER -> APP_CLIENT_SYNC_INGEST_API_KEYS

    POST   /api/v1/client/note                    — relay {note} в Tinode

ЕДИНЫЙ формат WS-токена (7 полей, разделитель ``|``):

    fid|sch|prm1|prm2|yyMMdd|appVer|appCode

    sch="1" — login + password           (для POST /login)
    sch="2" — request_id + код           (для POST /login)
    sch="3" — post-login WS-токен        (для всех остальных эндпоинтов):
              prm1 = usi (usrXXX), prm2 = ""
"""

from __future__ import annotations

import asyncio
import base64
import hashlib
import hmac
import json
import re
import time
import uuid
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse, Response
from pydantic import BaseModel, Field, field_validator
from starlette.responses import StreamingResponse

from ...config import settings
from ...db.repositories import AppRepository, TeamdroidProcedureRepository
from ...db.repositories.teamdroid import TeamdroidFileProcedureRepository
from ...dtos.client import (
    MessageCreateRequest,
    TokenPayload,
    UploadCreateRequest,
)
from ...dtos.sync import (
    SyncEditHeaderRequest,
)
from ...dtos.sync import (
    SyncLoadRequest as _BaseSyncLoadRequest,
)
from ...logger import api_logger
from ...middlewares.api.auth import extract_request_client_ip, upsert_tapps, verify_token
from ...models import datetime_now
from ...models.base import is_expired
from ...services.sync_session_registry import sync_session_registry
from ...utils.decorators import log_exceptions
from ...ws.push_notification_service import push_notification_service
from ...ws.token_crypto import WsTokenData, decrypt_ws_token, encrypt_ws_token
from ._sync_response import record_and_build_response

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
# Загрузки: in-process локи (защита от одновременной записи в один файл)
# ---------------------------------------------------------------------------

_UPLOAD_LOCKS: dict[str, asyncio.Lock] = {}
_UPLOAD_LOCKS_GUARD = asyncio.Lock()


# ---------------------------------------------------------------------------
# Хелперы
# ---------------------------------------------------------------------------


def _error_response(status_code: int, error: str) -> JSONResponse:
    """Стандартный JSON-ответ об ошибке для sync-load / sync-edit / note /
    send-code (контракт {"scs":0, "err": ...})."""
    return JSONResponse(
        status_code=status_code,
        content={
            "scs": 0,
            "status_code": status_code,
            "err": error,
        },
    )


def _fail(
    status_code: int,
    error: str,
    message: str | None = None,
    **extra: Any,
) -> JSONResponse:
    """Единый формат неуспеха /register и /login: scs=0 + err + msg + доп. поля.

    Клиент ждёт поля `err` (код) и `msg` (описание). Подсказка retry
    передаётся через `rtr` в **extra.
    """
    body: dict[str, Any] = {"scs": 0, "err": error}
    if message is not None:
        body["msg"] = message
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


def _require_usi(data: WsTokenData | None) -> tuple[str, str, int] | JSONResponse:
    """Извлечь (usi, dvc, api) из расшифрованного токена или вернуть ошибку.

    Требует sch="3" (usi присутствует в plaintext). Для sch="1"|"2"
    возвращает JSONResponse scs=0 / err="login_required" / rtr="login".

    Returns:
        tuple (user_id, fcm_id, app_id) — успех;
        JSONResponse (scs=0)            — ошибка формата/конфигурации.
    """
    if data is None:
        return JSONResponse(
            status_code=400,
            content={
                "scs": 0,
                "status_code": 400,
                "err": "invalid_token",
                "msg": "Token decryption or validation failed",
                "rtr": None,
            },
        )

    app_id = int(getattr(settings, "TEAMDROID_APP_ID", 0) or 0)
    if app_id <= 0:
        api_logger.error("client: TEAMDROID_APP_ID=0 — операция невозможна")
        return JSONResponse(
            status_code=503,
            content={
                "scs": 0,
                "err": "server_misconfigured",
                "msg": "TEAMDROID_APP_ID is not configured",
                "rtr": None,
            },
        )

    if not data.has_usi:
        api_logger.warning(
            "client: token without usi (sch=%r) — требуется sch=3 после логина",
            data.sch,
        )
        return JSONResponse(
            status_code=409,
            content={
                "scs": 0,
                "err": "login_required",
                "msg": "Token does not contain usi; use sch=3 (post-login) token",
                "rtr": "login",
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
# ХЕЛПЕРЫ ЗАГРУЗОК
# ===========================================================================


async def _upload_lock(upload_id: str) -> asyncio.Lock:
    """Per-upload asyncio.Lock (защита от одновременной записи в один файл)."""
    async with _UPLOAD_LOCKS_GUARD:
        lock = _UPLOAD_LOCKS.get(upload_id)
        if lock is None:
            lock = asyncio.Lock()
            _UPLOAD_LOCKS[upload_id] = lock
        return lock


def _token_from_header(request: Request) -> str | None:
    """Токен из заголовка для PATCH/HEAD/DELETE (тело бинарное)."""
    raw = (
        request.headers.get(settings.API_KEY_HEADER)
        #            or request.headers.get("x-token")
        #            or request.headers.get("authorization")
    )
    if not raw:
        return None
    raw = raw.strip()
    if raw.lower().startswith("bearer "):
        raw = raw[7:].strip()
    return raw or None


def _auth_header(request: Request) -> tuple[tuple[str, str, int] | None, JSONResponse | None]:
    """Авторизация по заголовку. Возвращает (ids, error_response)."""
    token = _token_from_header(request)
    if not token:
        return None, _fail(401, "missing_token", "Header 'tkn' is required")
    data = decrypt_ws_token(token)
    ids = _require_usi(data)
    if isinstance(ids, JSONResponse):
        return None, ids
    assert isinstance(ids, tuple)
    return ids, None


def _upload_root() -> Path:
    """Общий корень локального хранилища."""
    return Path(getattr(settings, "UPLOAD_LOCAL_DIR", "./data/uploads"))


def _client_upload_root() -> Path:
    """Файлы, которые клиент загружает на сервер."""
    return _upload_root() / "in"


def _client_download_root() -> Path:
    """Файлы, которые сервер подготавливает для скачивания клиентом."""
    return _upload_root() / "out"


def _client_download_path(file_id: str) -> Path:
    """Безопасный путь к файлу, который скачивает клиент."""
    if not file_id or not re.fullmatch(r"[A-Za-z0-9_-]+", file_id):
        raise ValueError("invalid file_id")

    root = _client_download_root().resolve()
    path = (root / f"{file_id}.bin").resolve()

    if not path.is_relative_to(root):
        raise ValueError("invalid storage path")

    return path


def _file_link_secret() -> bytes:
    secret = getattr(settings, "APP_CLIENT_FILE_LINK_SECRET", "")
    if not secret:
        raise RuntimeError("APP_CLIENT_FILE_LINK_SECRET is not configured")
    return str(secret).encode("utf-8")


def _sign_file_link(file_id: str, expires: int) -> str:
    message = f"{file_id}:{expires}".encode()
    return hmac.new(
        _file_link_secret(),
        message,
        hashlib.sha256,
    ).hexdigest()


def _verify_file_link(file_id: str, expires_raw: str, signature: str) -> bool:
    try:
        expires = int(expires_raw)
    except (TypeError, ValueError):
        return False

    now = int(time.time())

    # Ссылка истекла или срок действия слишком большой.
    if expires < now or expires > now + 24 * 60 * 60:
        return False

    expected = _sign_file_link(file_id, expires)
    return hmac.compare_digest(expected, signature or "")


def _storage_path(storage_key: str) -> Path:
    """storage_key → абсолютный путь. Защита от path traversal."""
    key = (storage_key or "").strip().lstrip("/")
    if not key or ".." in key.split("/"):
        raise ValueError("invalid storage_key")
    root = _upload_root().resolve()
    path = (root / key).resolve()
    if not str(path).startswith(str(root)):
        raise ValueError("storage_key escapes root")
    return path


def _sha256_file(path: Path) -> str:
    """SHA-256 файла потоково, без загрузки в память."""
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


_UPLOAD_ERR_HTTP: dict[str, int] = {
    "not_found": 404,
    "forbidden": 403,
    "expired": 410,
    "offset_mismatch": 409,
    "device_mismatch": 409,
    "cancelled": 409,
    "already_final": 409,
    "incomplete": 409,
    "too_large": 413,
    "checksum_mismatch": 422,
    "files_forbidden": 403,
    "sql_error": 500,
    "no_rows": 500,
    "invalid_usi": 400,
    "bad_params": 400,
}


def _upload_error(err: str | None, **extra: Any) -> JSONResponse:
    """Единый конверт ошибки загрузки: scs=0 + err + доп. поля."""
    code = _UPLOAD_ERR_HTTP.get(err or "", 400)
    body: dict[str, Any] = {"scs": 0, "err": err or "error"}
    body.update(extra)
    return JSONResponse(status_code=code, content=body)


# ===========================================================================
# 1. FID REGISTRATION — POST /register
# ===========================================================================


class _TokenPayload(TokenPayload):
    """Алиас для обратной совместимости (tkn)."""


class SyncLoadRequest(TokenPayload, _BaseSyncLoadRequest):
    pass


@router.post(
    "/register",
    summary="Зарегистрировать FID (с проверкой токена)",
)
@log_exceptions(api_logger)
async def register_fid(payload: _TokenPayload, request: Request) -> JSONResponse:
    """Регистрация FID по WS-токену (sch=3, 7 полей).

    Контракт ответа — см. docstring модуля.
    """
    client_ip = extract_request_client_ip(request)

    # 1) Единая проверка: decrypt + TokenVerify + TApps upsert.
    try:
        verified = await asyncio.wait_for(
            verify_token(payload.tkn, client_ip=client_ip),
            timeout=30.0,
        )
    except TimeoutError:
        api_logger.warning("client.register: verify_token timeout")
        return _fail(504, "verify_timeout", "TokenVerify timeout", rtr="register")

    if verified.err == "server_misconfigured":
        api_logger.error("client.register: TEAMDROID_APP_ID=0 — регистрация невозможна")
        return _fail(503, "server_misconfigured", "TEAMDROID_APP_ID is not configured")

    if verified.err == "invalid_token":
        return _fail(400, "invalid_token", "Token decryption or validation failed")

    if verified.err == "sch_not_3":
        api_logger.warning(
            "client.register: token without usi — требуется sch=3 после логина",
        )
        return _fail(
            409,
            "login_required",
            "Token does not contain usi; use sch=3 (post-login) token",
            rtr="login",
        )

    if not verified.ok:
        prm_raw = verified.prm_raw
        fid_suffix = verified.fcm_id[-6:] if verified.fcm_id and len(verified.fcm_id) >= 6 else "***"
        api_logger.warning(
            "client.register: rejected user=%s fid_suffix=%s err=%s has_prm=%s",
            verified.user_id,
            fid_suffix,
            verified.err,
            prm_raw is not None,
        )
        if prm_raw:
            return _fail(
                401,
                "force_update",
                verified.err or "TokenVerify failed",
                prm=prm_raw,
            )
        return _fail(401, "token_rejected", verified.err or "TokenVerify failed")

    user_id = verified.user_id
    assert user_id is not None and isinstance(user_id, str)
    fid = verified.fcm_id
    assert fid is not None and isinstance(fid, str)
    app_id = verified.app_id
    bundle = verified.bundle

    # 2) Отказ TApps — сервер не сможет обслуживать запросы группы 3.
    if not verified.tapps_ok:
        if verified.tapps_reason == "key_already_bound":
            api_logger.warning(
                "client.register: FKey collision user=%s fid=%s",
                user_id,
                fid[-8:] if len(fid) >= 8 else "***",
            )
            return _fail(
                409,
                "key_already_bound",
                "Token already registered for another device",
            )
        return _fail(
            500,
            "tapps_sync_failed",
            "Device registration failed; retry /client/register",
        )

    # 3) scs=1 — регистрируем FID.
    await push_notification_service.update_fid(user_id, fid)
    api_logger.info(
        "client.register: OK user=%s fid_suffix=...%s",
        user_id,
        fid[-8:] if len(fid) >= 8 else "***",
    )

    # 4) best-effort фиксация предложенного vcd.
    _, _, vcd_val = _extract_prm_parts(_as_str(bundle.get("prm")))
    if isinstance(vcd_val, int) and vcd_val > 0:
        try:
            await asyncio.wait_for(
                asyncio.to_thread(
                    TeamdroidProcedureRepository.app_update_offered_batch,
                    [{"usi": user_id, "api": int(app_id), "dvc": fid, "vcd": int(vcd_val)}],
                ),
                timeout=10.0,
            )
            api_logger.info(
                "client.register: offered vcd recorded user=%s vcd=%d",
                user_id,
                vcd_val,
            )
        except Exception as vcd_exc:  # noqa: BLE001
            api_logger.warning(
                "client.register: failed to record offered vcd user=%s: %r",
                user_id,
                vcd_exc,
            )

    # 6) Регистрируем пакет (sid/snc/dtp/prm) в реестре и формируем тело ответа.
    body = await record_and_build_response(
        user_id=user_id,
        raw_sid=bundle.get("sid"),
        raw_snc=bundle.get("snc"),
        raw_dtp=bundle.get("dtp"),
        raw_prm=bundle.get("prm"),
        source="register",
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

    if psh:
        body["psh"] = psh

    api_logger.info(
        "client.register: response user=%s keys=%s",
        user_id,
        sorted(body.keys()),
    )
    return JSONResponse(status_code=200, content=body)


# ===========================================================================
# 1.1. LOGIN — POST /login (mid=1|2)
# ===========================================================================


@router.post(
    "/login",
    summary="Логин по WS-токену",
)
@log_exceptions(api_logger)
async def client_login(payload: _TokenPayload, request: Request) -> JSONResponse:
    """Логин по WS-токену (7 полей, sch="1"|"2").

    - ``sch="1"`` — prm1=логин, prm2=пароль;
    - ``sch="2"`` — prm1=request_id, prm2=код.

    Сервер:
      1) расшифровывает токен (usi в plaintext нет);
      2) вызывает ext.PA_mbl_AuthLogin_Exec (mid=1|2);
      3) возвращает пакет синхронизации (sid/prm) тем же контрактом,
         что и /sync-load, — клиент затем делает /sync-edit;
      4) при отказе — scs=0 + force_update/token_rejected/etc.
    """
    data = decrypt_ws_token(payload.tkn)
    if data is None:
        return _fail(400, "invalid_token", "Token decryption or validation failed")

    if data.sch not in ("1", "2"):
        api_logger.warning(
            "client.login: unsupported sch=%r (expected '1' or '2')",
            data.sch,
        )
        return _fail(
            400,
            "invalid_token",
            "Token scheme must be '1' or '2' for /login",
        )

    fid = data.fcm_id
    client_ip = extract_request_client_ip(request)

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
        ok, err, user_id, bundle = await asyncio.wait_for(
            asyncio.to_thread(
                TeamdroidProcedureRepository.login,
                mid=int(data.sch),
                pr1=data.prm1,
                pr2=data.prm2,
                app_id=app_id,
                fcm_id=fid,
                token_date=data.date,
                client_ip=client_ip,
                app_version=data.app_version,
                app_version_code=data.app_version_code,
            ),
            timeout=30.0,
        )
    except TimeoutError:
        api_logger.warning("client.login: timeout fid_suffix=...%s", fid[-6:])
        return _fail(504, "login_timeout", "Login timeout", rtr="login")

    # ── Шаг 2: разбор prm для offered vcd ──
    prm_raw = _as_str(bundle.get("prm"))
    _, _, vcd_val = _extract_prm_parts(prm_raw)

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
                rtr="register",
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
        "client.login: OK user=%s",
        user_id,
    )

    await _record_offered_vcd(user_id)

    # ── Шаг 4.1: собрать sch="3"-токен и записать TApps.FKey ──
    #     (чтобы клиент мог использовать его в X-API-Key для группы 3:
    #      send-code, sync-load, sync-edit, uploads*, files/{fid}, msgs)
    post_login_token: str
    try:
        post_login_token = encrypt_ws_token(
            WsTokenData(
                fcm_id=fid,
                user_id=user_id,
                sch="3",
                prm1=user_id,  # usi
                prm2="",
                date=data.date,
                app_version=data.app_version,
                app_version_code=data.app_version_code,
            )
        )
    except NotImplementedError:
        raise
    except Exception as enc_exc:
        api_logger.error(
            "client.login: encrypt_ws_token failed user=%s: %r",
            user_id,
            enc_exc,
            exc_info=True,
        )
        return _fail(
            500,
            "tapps_sync_failed",
            "Failed to build post-login token; retry /client/register",
        )

    tapps_ok, tapps_reason = await upsert_tapps(
        fid=fid,
        user_id=user_id,
        key=post_login_token,
        app_version_code=data.app_version_code,
    )
    if not tapps_ok:
        api_logger.warning(
            "client.login: TApps upsert failed user=%s reason=%s",
            user_id,
            tapps_reason,
        )
        if tapps_reason == "key_already_bound":
            return _fail(
                409,
                "key_already_bound",
                "Token already registered for another device",
            )
        return _fail(
            500,
            "tapps_sync_failed",
            "Device registration failed; retry /client/register",
        )

    # ── Шаг 5: пакет + реестр + тело ответа ──
    body = await record_and_build_response(
        user_id=user_id,
        raw_sid=bundle.get("sid"),
        raw_snc=bundle.get("snc"),
        raw_dtp=bundle.get("dtp"),
        raw_prm=bundle.get("prm"),
        source="login",
    )
    body["usi"] = user_id

    # ── Шаг 6: pending-сигналы из TPushPending → поле psh ──
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
    except Exception as pending_exc:
        api_logger.warning(
            "client.login: failed to take pending pushes user=%s: %r",
            user_id,
            pending_exc,
        )

    if psh:
        body["psh"] = psh

    api_logger.info(
        "client.login: response user=%s keys=%s",
        user_id,
        sorted(body.keys()),
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

    Требует sch="3" (usi присутствует в plaintext).

    Вызывает ext.PA_mbl_TokenFinish_Exec через
    TeamdroidProcedureRepository.logout(usi, dvc, api).
    """
    data = decrypt_ws_token(payload.tkn)
    if data is None:
        return _fail(400, "invalid_token", "Token decryption or validation failed")

    ids = _require_usi(data)
    if isinstance(ids, JSONResponse):
        return ids
    user_id, fid, app_id = ids

    finish_ok = False
    if app_id:
        try:
            finish_ok, finish_err = await asyncio.wait_for(
                asyncio.to_thread(
                    TeamdroidProcedureRepository.logout,
                    usi=user_id,
                    app_id=app_id,
                    fcm_id=fid,
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
        from ...db.repositories import AppRepository as _AppRepository

        async with db_manager.get_session() as session:
            app = await _AppRepository.get_app_by_fid(session, fid)
            if app is not None and app.FUserID == user_id:
                # delete TApps: устройство больше не зарегистрировано.
                # Каскад удалит связанные TAppUploads / TAppLogs / TAppLogsRequests.
                await session.delete(app)
                await session.commit()
    except Exception as tapps_exc:
        api_logger.warning(
            "client.unregister: TApps delete failed user=%s fid=%s: %r",
            user_id,
            fid[-8:] if len(fid) >= 8 else "***",
            tapps_exc,
            exc_info=True,
        )

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
    """Проверка актуальности версии клиента.

    Требует sch="3" (usi присутствует в plaintext).

    CHANGED (v3): принимает 7-полевой токен; legacy 5-полевой удалён.
    """
    data = decrypt_ws_token(payload.tkn)
    if data is None:
        return _fail(400, "invalid_token", "Token decryption or validation failed")

    ids = _require_usi(data)
    if isinstance(ids, JSONResponse):
        return ids
    user_id, fid, app_id = ids
    assert isinstance(user_id, str) and isinstance(fid, str)

    try:
        info = await asyncio.wait_for(
            asyncio.to_thread(
                TeamdroidProcedureRepository.app_update_check,
                user_id=user_id,
                app_id=app_id,
                fcm_id=fid,
            ),
            timeout=10.0,
        )
    except TimeoutError:
        api_logger.warning("client.app_update_check: timeout user=%s", user_id)
        return JSONResponse(
            status_code=504,
            content={
                "scs": 0,
                "err": "check_timeout",
                "rtr": "sync-edit",
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
                "err": settings.APP_CLIENT_ERROR_DEVICE_NOT_REGISTERED,
                "msg": "Active device session not found",
                "rtr": "register",
            },
        )

    api_logger.info(
        "client.app_update_check: user=%s result_len=%s",
        user_id,
        len(info) if info else 0,
    )

    try:
        from ...db import db_manager
        from ...db.repositories import AppRepository as _AppRepository

        async with db_manager.get_session() as session:
            app = await _AppRepository.get_app_by_fid(session, fid)
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

    params["client_ip"] = extract_request_client_ip(request)

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
    client_ip = extract_request_client_ip(request)

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
                "err": f"validation_error: {val_exc}",
            },
        )
    except Exception as note_exc:  # noqa: BLE001
        api_logger.error("[client/note] failed: %r", note_exc, exc_info=True)
        return JSONResponse(
            status_code=500,
            content={
                "scs": 0,
                "err": f"{type(note_exc).__name__}: {note_exc}",
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
                "err": f"tinode_ctrl_error: code={ctrl_code} text={ctrl_text!r}",
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
    data = decrypt_ws_token(payload.tkn)
    if data is None:
        return _error_response(400, "invalid_token")

    ids = _require_usi(data)
    if isinstance(ids, JSONResponse):
        return ids
    user_id, fcm_id, app_id = ids

    client_ip = extract_request_client_ip(request)

    ok_iter, iters = await sync_session_registry.check_iterations(user_id)
    if not ok_iter:
        api_logger.warning("sync_base.load: too many iterations user=%s n=%d", user_id, iters)
        return JSONResponse(
            status_code=429,
            content={
                "scs": 0,
                "status_code": 429,
                "err": "too_many_iterations",
                "msg": "Too many Load calls without a successful Edit",
                "rtr": "sync-edit",
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
                app_id=app_id,
                fcm_id=fcm_id,
                client_ip=client_ip,
                data_types=payload.data_types,
                force=force_flag,
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
                "err": "load_timeout",
                "rtr": "sync-load",
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
                    "err": "device_session_not_found",
                    "msg": "Device session not found; re-register via /client/register",
                    "rtr": "register",
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
                "err": "invalid_sql_payload",
                "msg": "SQL returned empty sid",
                "rtr": None,
            },
        )

    # Инкремент итераций Load ДО регистрации пакета — защита от HasMore-цикла.
    await sync_session_registry.bump_iteration(user_id)

    # Унифицированная регистрация + тело ответа.
    body = await record_and_build_response(
        user_id=user_id,
        raw_sid=sid,
        raw_snc=snc,
        raw_dtp=dtp_from_sql,
        raw_prm=prm,
        source="sync-load",
    )
    api_logger.info(
        "sync_base.load: OK user=%s sid=%s snc=%r dtp=%s prm_rows=%d",
        user_id,
        sid,
        snc,
        dtp_from_sql,
        len(prm),
    )
    return JSONResponse(status_code=200, content=body)


@router.post(
    "/sync-edit",
    summary="Подтвердить применение пакетов по списку sid (tkn в заголовке)",
)
@log_exceptions(api_logger)
async def sync_base_edit(
    payload: SyncEditHeaderRequest,
    request: Request,
) -> JSONResponse:
    """Подтверждение применения пакетов базовых данных.

    Контракт:
        Header ``tkn``: 7-полевой WS-токен, ``sch="3"`` (post-login).
        Body: ``{"sid": ["<guid>", "<guid>", ...]}``.

    Сервер:
      1) расшифровывает ``tkn`` из заголовка (один раз на запрос);
      2) для каждого ``sid`` ищет запись в ``sync_session_registry``,
         проверяет, что ``entry["user_id"] == user_id`` из токена;
      3) собирает ``sql_items`` (usi/api/dvc общие на все sid) и вызывает
         ``TeamdroidProcedureRepository.edit_base_data``;
      4) удаляет подтверждённые sid из реестра, сбрасывает итерации;
      5) возвращает единый контракт sync-канала (scs/sid/prm/cmi/cmt).
    """
    # ── 0. Лимит на количество sid ──
    max_items = int(getattr(settings, "APP_CLIENT_SYNC_BASE_MAX_EDIT_ITEMS", 100) or 100)
    if len(payload.sid) > max_items:
        return JSONResponse(
            status_code=400,
            content={
                "scs": 0,
                "status_code": 400,
                "err": f"too many sid (max {max_items})",
            },
        )

    # ── 1. Токен из заголовка (один раз на запрос) ──
    token = _token_from_header(request)
    if not token:
        api_logger.warning("sync_base.edit: missing tkn header")
        return JSONResponse(
            status_code=401,
            content={
                "scs": 0,
                "status_code": 401,
                "err": "missing_token",
                "msg": "Header 'tkn' is required",
                "rtr": None,
            },
        )

    data = decrypt_ws_token(token)
    ids = _require_usi(data)  # проверяет sch="3" и TEAMDROID_APP_ID
    if isinstance(ids, JSONResponse):
        return ids
    user_id, fcm_id, app_id = ids

    client_ip = extract_request_client_ip(request)

    # ── 2. Разбор sid'ов через реестр ──
    items: list[dict[str, Any]] = []
    issues: list[dict[str, Any]] = []
    seen_sids: set[str] = set()

    for idx, sid_raw in enumerate(payload.sid):
        if not sid_raw:
            issues.append({"index": idx, "sid": sid_raw, "reason": "empty_sid"})
            continue

        if sid_raw in seen_sids:
            api_logger.warning(
                "sync_base.edit: sid[%d] duplicate user=%s sid=%s",
                idx,
                user_id,
                sid_raw,
            )
            issues.append({"index": idx, "sid": sid_raw, "reason": "duplicate_sid"})
            continue
        seen_sids.add(sid_raw)

        entry = await sync_session_registry.lookup_sid(sid_raw)
        if entry is None:
            api_logger.warning(
                "sync_base.edit: sid[%d] unknown user=%s sid=%s",
                idx,
                user_id,
                sid_raw,
            )
            issues.append({"index": idx, "sid": sid_raw, "reason": "unknown_sid"})
            continue

        if entry["user_id"] != user_id:
            api_logger.warning(
                "sync_base.edit: sid[%d] user mismatch sid=%s registry=%s token=%s",
                idx,
                sid_raw,
                entry["user_id"],
                user_id,
            )
            issues.append({"index": idx, "sid": sid_raw, "reason": "sid_user_mismatch"})
            continue

        snc: str | None = entry.get("snc")
        dtp: list[int] = list(entry.get("dtp") or [])
        if not snc or not dtp:
            api_logger.warning(
                "sync_base.edit: sid[%d] empty snc/dtp sid=%s snc=%r dtp=%r",
                idx,
                sid_raw,
                snc,
                dtp,
            )
            issues.append({"index": idx, "sid": sid_raw, "reason": "sid_empty"})
            continue

        items.append(
            {
                "usi": user_id,
                "api": int(app_id),
                "dvc": fcm_id,
                "dtp": [int(t) for t in dtp],
                "ts": snc,
                "_sid": sid_raw,
            }
        )

    if issues:
        _bump_sync_stat("edit_invalid", 1)
        return JSONResponse(
            status_code=400,
            content={
                "scs": 0,
                "status_code": 400,
                "err": "invalid_edit",
                "iss": issues,
                "rtr": "sync-load",
            },
        )

    if not items:
        return JSONResponse(
            status_code=400,
            content={
                "scs": 0,
                "status_code": 400,
                "err": "nothing_to_commit",
                "msg": "sid list produced no items",
                "rtr": None,
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
        client_ip,
    )

    # ── 3. Вызов edit_base_data ──
    edit_timeout = int(getattr(settings, "APP_CLIENT_SYNC_BASE_EDIT_TIMEOUT_SEC", 20) or 20)
    try:
        bundle = await asyncio.wait_for(
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
                "err": "edit_timeout",
                "msg": (
                    "Edit timed out. MERGE may have committed or not. "
                    "Call sync-load to get a fresh sid/sync_time; "
                    "do NOT retry with the same sid."
                ),
                "merge_may_have_committed": True,
                "rtr": "sync-load",
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
                    "err": "bad_ts",
                    "msg": (
                        "SQL Server could not parse 'ts' as DATETIME. "
                        "Request a fresh sync-load and retry with the new sid."
                    ),
                    "fli": failed_rows_0based,
                    "rtr": "sync-load",
                },
            )

        if "PRC_mbl_SyncBaseDataEdit_NoData" in err_text:
            api_logger.warning("sync_base.edit: NoData (ничего не записано)")
            failed_rows = _parse_failed_rows_from_sql_error(err_text)
            failed_rows_0based = sorted({r - 1 for r in failed_rows if 1 <= r <= len(sql_items)})
            failed_set = set(failed_rows_0based)
            ok_indices = [i for i in range(len(sql_items)) if i not in failed_set]

            _bump_sync_stat("edit_partial", 1)

            return JSONResponse(
                status_code=207,
                content={
                    "scs": 1,
                    "status_code": 207,
                    "err": "device_session_not_found",
                    "msg": "Some items failed: device session not found for those users",
                    "fli": failed_rows_0based,
                    "oki": ok_indices,
                    "total_items": len(sql_items),
                    "rtr": None,
                },
            )

        raise

    # ── 4. Успех: чистим реестр по подтверждённым sid ──
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
            api_logger.warning(
                "sync_base.edit: iterations reset failed user=%s: %r",
                usi,
                iter_exc,
            )

    # ── 5. Единый контракт ответа sync-edit ──
    #
    #   Есть новый пакет:
    #       {"scs": 1, "sid": "<uuid>", "prm": [...], "cmi": N, "cmt": M}
    #
    #   Изменений нет:
    #       {"scs": 1, "cmi": N, "cmt": M}
    #
    committed_items = len(sql_items)
    committed_types = sum(len(i["dtp"]) for i in sql_items)

    raw_sid = bundle.get("sid") if bundle else None
    raw_snc = bundle.get("snc") if bundle else None
    raw_dtp = bundle.get("dtp") if bundle else None
    raw_prm = bundle.get("prm") if bundle else None

    seen_users: set[str] = set()
    unique_users: list[str] = []
    for it in items:
        usi = it["usi"]
        if usi not in seen_users:
            seen_users.add(usi)
            unique_users.append(usi)

    first_body: dict[str, Any] | None = None
    for usi in unique_users:
        body = await record_and_build_response(
            user_id=usi,
            raw_sid=raw_sid,
            raw_snc=raw_snc,
            raw_dtp=raw_dtp,
            raw_prm=raw_prm,
            source="sync-edit",
        )
        if first_body is None:
            first_body = body

    assert first_body is not None

    first_body["cmi"] = committed_items
    first_body["cmt"] = committed_types

    if raw_sid:
        api_logger.info(
            "sync_base.edit: delivered new packet sid=%s users=%s prm_rows=%d cmi=%d cmt=%d",
            raw_sid,
            unique_users,
            len(first_body.get("prm") or []),
            committed_items,
            committed_types,
        )
    else:
        api_logger.info(
            "sync_base.edit: no changes after edit users=%s cmi=%d cmt=%d",
            unique_users,
            committed_items,
            committed_types,
        )

    return JSONResponse(status_code=200, content=first_body)


# ===========================================================================
# 5. SYNC STATS — GET /sync-stats
# ===========================================================================


async def _uploads_stats_safe() -> dict[str, int]:
    try:
        from ...db import db_manager

        async with db_manager.get_session() as session:
            return await AppRepository.upload_stats_snapshot(session)
    except Exception as exc:  # noqa: BLE001
        api_logger.warning("uploads stats failed: %r", exc)
        return {}


@router.get(
    "/sync-stats",
    summary="Диагностика sync-механизма",
)
@log_exceptions(api_logger)
async def sync_stats() -> JSONResponse:
    metrics_from_registry = sync_session_registry.metrics_snapshot()
    stats_snapshot = TeamdroidProcedureRepository.sync_base_stats_snapshot()
    uploads_snapshot = await _uploads_stats_safe()

    return JSONResponse(
        status_code=200,
        content={
            "scs": 1,
            "stats": stats_snapshot,
            "registry": sync_session_registry.snapshot(),
            "sids_pending": sync_session_registry.sids_snapshot(),
            "iterations": sync_session_registry.iterations_snapshot(),
            "activity": sync_session_registry.activity_snapshot(),
            "uploads": uploads_snapshot,
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
                "upload_backend": getattr(settings, "UPLOAD_STORAGE_BACKEND", "local"),
                "upload_chunk_size": int(getattr(settings, "UPLOAD_CHUNK_SIZE", 1048576)),
                "upload_max_file_size": int(getattr(settings, "UPLOAD_MAX_FILE_SIZE", 104857600)),
                "upload_retention_days": int(getattr(settings, "UPLOAD_RETENTION_DAYS", 7)),
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
            "upload_backend": getattr(settings, "UPLOAD_STORAGE_BACKEND", "local"),
            "upload_chunk_size": int(getattr(settings, "UPLOAD_CHUNK_SIZE", 1048576)),
            "upload_max_file_size": int(getattr(settings, "UPLOAD_MAX_FILE_SIZE", 104857600)),
            "upload_retention_days": int(getattr(settings, "UPLOAD_RETENTION_DAYS", 7)),
        },
    )


# ===========================================================================
# 7. UPLOADS
# ===========================================================================


@router.post("/uploads", summary="Создать загрузку файла")
@log_exceptions(api_logger)
async def upload_create(payload: UploadCreateRequest) -> JSONResponse:
    """Создаёт временную загрузку. ``upload_id`` сохраняется на устройстве."""
    data = decrypt_ws_token(payload.tkn)
    ids = _require_usi(data)
    if isinstance(ids, JSONResponse):
        return ids
    user_id, fid, _app_id = ids

    max_size = int(getattr(settings, "UPLOAD_MAX_FILE_SIZE", 100 * 1024 * 1024))
    if payload.fsz > max_size:
        return _upload_error("too_large", size=payload.fsz, max_size=max_size)

    if payload.fex:
        allowed = {e.lower().lstrip(".") for e in settings.UPLOAD_ALLOWED_EXTENSIONS}
        if payload.fex.lower().lstrip(".") not in allowed:
            return _upload_error("bad_params", err_detail="extension_not_allowed")

    upload_id = (payload.uid or "").strip() or uuid.uuid4().hex
    storage_key = f"out/{upload_id}"
    chunk_size = int(getattr(settings, "UPLOAD_CHUNK_SIZE", 1024 * 1024))

    try:
        from ...db import db_manager

        async with db_manager.get_session() as session:
            # Группа 3: устройство уже прошло проверку TApps.FKey в AuthMiddleware.
            app = await AppRepository.get_app_by_fid(session, fid)
            if app is None:
                return _upload_error("not_found", err_detail="device not registered")

            existing = await AppRepository.upload_get_by_upload_id(session, upload_id)

            if existing is not None:
                if existing.FUserID != user_id:
                    return _upload_error("forbidden")

                existing_path = _storage_path(existing.FStorageKey)

                # Повторный запрос: запись есть, но физический файл потерян.
                if not existing_path.is_file():
                    api_logger.error(
                        "client.upload_create: DB row exists but storage file missing uid=%s status=%s path=%s",
                        upload_id,
                        existing.FStatus,
                        existing_path,
                    )
                    return _upload_error(
                        "not_found",
                        err_detail="upload record exists but storage file is missing; use a new uid",
                    )

                # Не переиспользуем уже завершённую загрузку для новой отправки.
                if existing.FStatus != "active":
                    return _upload_error(
                        "already_final",
                        err_detail=f"upload_id already has status={existing.FStatus}; use a new uid",
                    )

                # Проверяем, что повторный запрос относится к тому же файлу.
                if existing.FFileSize != payload.fsz or existing.FFileName != payload.fnm:
                    return _upload_error(
                        "bad_params",
                        err_detail="upload_id already exists with different file metadata",
                    )

                return JSONResponse(
                    status_code=200,
                    content={
                        "scs": 1,
                        "id": existing.FUploadID,
                        "chs": existing.FChunkSize,
                    },
                )

            await AppRepository.upload_create(
                session,
                fk_app=app.FID,
                fid=fid,
                user_id=user_id,
                upload_id=upload_id,
                file_name=payload.fnm,
                file_ext=payload.fex,
                file_size=payload.fsz,
                chunk_size=chunk_size,
                storage_key=storage_key,
                sha256=payload.sha,
                retention_days=int(getattr(settings, "UPLOAD_RETENTION_DAYS", 7)),
            )
            await session.commit()
    except Exception as exc:  # noqa: BLE001
        api_logger.error("client.upload_create: db error user=%s: %r", user_id, exc, exc_info=True)
        return _upload_error("sql_error", err_detail=type(exc).__name__)

    # создаём файл нужного размера (разреженный) — чтобы seek/write работали
    try:
        path = _storage_path(storage_key)
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("wb") as f:
            f.truncate(payload.fsz)
    except Exception as exc:  # noqa: BLE001
        api_logger.error("client.upload_create: storage error: %r", exc, exc_info=True)
        return _upload_error("sql_error", err_detail="storage_unavailable")

    api_logger.info("client.upload_create: OK user=%s uid=%s fsz=%d", user_id, upload_id, payload.fsz)
    return JSONResponse(
        status_code=200,
        content={"scs": 1, "id": upload_id, "chs": chunk_size},
    )


@router.patch("/uploads/{upload_id}", summary="Передать очередную часть файла")
@log_exceptions(api_logger)
async def upload_patch(
    upload_id: str,
    request: Request,
) -> JSONResponse:
    """Тело — бинарные данные чанка. Смещение в заголовке ``offst``."""
    ids, err = _auth_header(request)
    if err is not None:
        return err
    assert ids is not None
    user_id, _fid, _app_id = ids

    raw_offst = request.headers.get("offst")
    if raw_offst is None:
        return _upload_error("bad_params", err_detail="header 'offst' required")
    try:
        offst = int(raw_offst)
    except ValueError:
        return _upload_error("bad_params", err_detail="invalid offst")
    if offst < 0:
        return _upload_error("bad_params", err_detail="negative offst")

    async with await _upload_lock(upload_id):
        from ...db import db_manager

        async with db_manager.get_session() as session:
            row = await AppRepository.upload_get_by_upload_id(session, upload_id)
            if row is None:
                return _upload_error("not_found")
            if row.FUserID != user_id:
                return _upload_error("forbidden", offst=row.FUploadedBytes)
            if row.FStatus != "active":
                return _upload_error(row.FStatus, offst=row.FUploadedBytes)
            if is_expired(row.FExpiresAt):
                return _upload_error("expired", offst=row.FUploadedBytes)

            cur = row.FUploadedBytes
            file_size = row.FFileSize
            storage_key = row.FStorageKey
            path = _storage_path(storage_key)

        # идемпотентный ретрай последнего чанка
        clen = int(request.headers.get("content-length") or 0)
        if clen and offst + clen <= cur and offst < cur:
            return JSONResponse(status_code=200, content={"scs": 1, "offst": cur})

        if offst != cur:
            return _upload_error("offset_mismatch", offst=cur)

        if clen and offst + clen > file_size:
            return _upload_error("too_large", offst=cur, size=file_size)

        # ── запись в storage потоково ──
        written = 0
        try:
            with path.open("r+b") as f:
                f.seek(offst)
                async for chunk in request.stream():
                    if not chunk:
                        continue
                    if written + len(chunk) > file_size - offst:
                        f.write(chunk[: file_size - offst - written])
                        f.truncate(file_size)
                        f.flush()
                        return _upload_error("too_large", offst=cur, size=file_size)
                    f.write(chunk)
                    written += len(chunk)
                f.flush()
        except Exception as exc:  # noqa: BLE001
            api_logger.error("client.upload_patch: write failed uid=%s: %r", upload_id, exc, exc_info=True)
            return _upload_error("sql_error", err_detail="storage_error", offst=cur)

        if written == 0:
            return JSONResponse(status_code=200, content={"scs": 1, "offst": cur})

        # ── атомарное продвижение offset ──
        async with db_manager.get_session() as session:
            ok, actual, aerr = await AppRepository.upload_advance_offset(
                session,
                upload_id=upload_id,
                expected_offset=offst,
                chunk_len=written,
            )

        if not ok:
            if aerr == "offset_mismatch":
                try:
                    with path.open("r+b") as f:
                        f.truncate(actual)
                except OSError as trunc_exc:
                    api_logger.error(
                        "client.upload_patch: rollback truncate failed uid=%s expected=%d path=%s: %r",
                        upload_id,
                        actual,
                        path,
                        trunc_exc,
                        exc_info=True,
                    )
                return _upload_error("offset_mismatch", offst=actual)
            return _upload_error(aerr or "sql_error", offst=actual)

    return JSONResponse(status_code=200, content={"scs": 1, "offst": offst + written})


@router.head("/uploads/{upload_id}", summary="Текущая позиция загрузки")
@log_exceptions(api_logger)
async def upload_head(upload_id: str, request: Request) -> Response:
    """offst / size в заголовках. Тело пустое (HEAD)."""
    ids, err = _auth_header(request)
    if err is not None:
        return Response(status_code=err.status_code)

    assert ids is not None
    user_id, _fid, _app_id = ids

    from ...db import db_manager

    async with db_manager.get_session() as session:
        row = await AppRepository.upload_get_by_upload_id(session, upload_id)
        if row is None:
            return Response(status_code=404)
        if row.FUserID != user_id:
            return Response(status_code=403)
        if row.FStatus == "expired" or is_expired(row.FExpiresAt):
            return Response(status_code=410)
        if row.FStatus != "active":
            return Response(status_code=409)

    return Response(
        status_code=200,
        headers={
            "offst": str(row.FUploadedBytes),
            "size": str(row.FFileSize),
            "Accept-Ranges": "bytes",
        },
    )


@router.post("/uploads/{upload_id}/complete", summary="Завершить загрузку")
@log_exceptions(api_logger)
async def upload_complete(
    upload_id: str,
    #        payload: UploadCompleteRequest,
    request: Request,
) -> JSONResponse:
    ids, err = _auth_header(request)
    if err is not None:
        return err
    assert ids is not None
    user_id, _fid, _app_id = ids

    async with await _upload_lock(upload_id):
        from ...db import db_manager

        async with db_manager.get_session() as session:
            row = await AppRepository.upload_get_by_upload_id(session, upload_id)
            if row is None:
                return _upload_error("not_found")
            if row.FUserID != user_id:
                return _upload_error("forbidden")

            # идемпотентный повтор — отдаём тот же upload_id
            if row.FStatus == "completed":
                return JSONResponse(
                    status_code=200,
                    content={"scs": 1, "id": row.FUploadID},
                )
            if row.FStatus != "active":
                return _upload_error(row.FStatus)
            if is_expired(row.FExpiresAt):
                return _upload_error("expired")
            if row.FUploadedBytes != row.FFileSize:
                return _upload_error(
                    "incomplete",
                    offst=row.FUploadedBytes,
                    size=row.FFileSize,
                )

            storage_key = row.FStorageKey
            expected_sha = row.FSHA256
            file_size = row.FFileSize

        # checksum — до пометки completed
        path = _storage_path(storage_key)
        if not path.exists():
            return _upload_error("not_found", err_detail="storage file missing")

        actual_size = await asyncio.to_thread(lambda: path.stat().st_size)
        if actual_size != file_size:
            return _upload_error(
                "incomplete",
                err_detail=f"storage size {actual_size} != declared {file_size}",
            )

        if expected_sha:
            actual = await asyncio.to_thread(_sha256_file, path)
            if actual.lower() != expected_sha.lower():
                return _upload_error("checksum_mismatch")

        ok = await AppRepository.upload_mark_completed(
            session,
            upload_id=upload_id,
            remote_file_id="",  # локальное хранилище: remote id не нужен
        )

        if not ok:
            async with db_manager.get_session() as s2:
                row2 = await AppRepository.upload_get_by_upload_id(s2, upload_id)
                if row2 is not None and row2.FStatus == "completed":
                    return JSONResponse(
                        status_code=200,
                        content={"scs": 1, "id": row2.FUploadID},
                    )
            return _upload_error("already_final")

    api_logger.info(
        "client.upload_complete: OK user=%s uid=%s",
        user_id,
        upload_id,
    )
    return JSONResponse(
        status_code=200,
        content={"scs": 1, "id": upload_id},
    )


@router.delete("/uploads/{upload_id}", summary="Отменить загрузку")
@log_exceptions(api_logger)
async def upload_cancel(upload_id: str, request: Request) -> JSONResponse:
    """Явная отмена пользователем. Обрыв/таймаут сюда НЕ попадают."""
    ids, err = _auth_header(request)
    if err is not None:
        return err
    assert ids is not None
    user_id, _fid, _app_id = ids

    from ...db import db_manager

    async with db_manager.get_session() as session:
        row = await AppRepository.upload_get_by_upload_id(session, upload_id)
        if row is None:
            return _upload_error("not_found")
        if row.FUserID != user_id:
            return _upload_error("forbidden")
        if row.FStatus != "active":
            return _upload_error(row.FStatus)

        storage_key = row.FStorageKey
        ok = await AppRepository.upload_mark_cancelled(session, upload_id=upload_id)

    if not ok:
        return _upload_error("already_final")

    try:
        await asyncio.to_thread(lambda: _storage_path(storage_key).unlink(missing_ok=True))
    except Exception as exc:  # noqa: BLE001
        api_logger.warning("client.upload_cancel: storage delete failed uid=%s: %r", upload_id, exc)

    api_logger.info("client.upload_cancel: OK user=%s uid=%s", user_id, upload_id)
    return JSONResponse(status_code=200, content={"scs": 1})


# ===========================================================================
# 8. FILES
# ===========================================================================


@router.get("/files/{file_id}", summary="Подготовить файл или скачать его по Range")
@log_exceptions(api_logger)
async def file_download(file_id: str, request: Request) -> Response:
    """
    Два режима:

    1. GET /files/{fid} + tkn:
       Проверка доступа, загрузка BLOB из SQL, сохранение на диск,
       возврат временной ссылки.

    2. GET /files/{fid}?exp=...&sig=...:
       Скачивание подготовленного файла с поддержкой Range.
    """
    if not re.fullmatch(r"[A-Za-z0-9_-]+", file_id or ""):
        return JSONResponse(
            status_code=400,
            content={"scs": 0, "err": "invalid_file_id"},
        )

    # ---------------------------------------------------------
    # РЕЖИМ 1. Скачивание по временной подписанной ссылке
    # ---------------------------------------------------------
    exp = request.query_params.get("exp")
    sig = request.query_params.get("sig")

    if exp is not None or sig is not None:
        if not exp or not sig or not _verify_file_link(file_id, exp, sig):
            return JSONResponse(
                status_code=403,
                content={"scs": 0, "err": "invalid_or_expired_link"},
            )

        try:
            path = _client_download_path(file_id)
        except ValueError:
            return JSONResponse(
                status_code=400,
                content={"scs": 0, "err": "invalid_file_id"},
            )

        if not path.is_file():
            return JSONResponse(
                status_code=404,
                content={"scs": 0, "err": "file_not_cached"},
            )

        file_size = path.stat().st_size
        range_header = request.headers.get("range")

        headers = {
            "Accept-Ranges": "bytes",
            "Content-Disposition": f'attachment; filename="{file_id}"',
            "Cache-Control": "private, no-store",
        }

        # Полный файл.
        if not range_header:
            headers["Content-Length"] = str(file_size)

            def full_stream():
                with path.open("rb") as stream:
                    while True:
                        chunk = stream.read(1024 * 1024)
                        if not chunk:
                            break
                        yield chunk

            return StreamingResponse(
                full_stream(),
                status_code=200,
                media_type="application/octet-stream",
                headers=headers,
            )

        # Поддерживаем один диапазон bytes=start-end.
        match = re.fullmatch(r"bytes=(\d*)-(\d*)", range_header.strip())
        if not match or file_size <= 0:
            return Response(
                status_code=416,
                headers={"Content-Range": f"bytes */{file_size}"},
            )

        start_raw, end_raw = match.groups()

        if not start_raw and not end_raw:
            return Response(
                status_code=416,
                headers={"Content-Range": f"bytes */{file_size}"},
            )

        if not start_raw:
            # Суффиксный диапазон: последние N байт.
            suffix_length = int(end_raw)
            if suffix_length <= 0:
                return Response(
                    status_code=416,
                    headers={"Content-Range": f"bytes */{file_size}"},
                )
            start = max(0, file_size - suffix_length)
            end = file_size - 1
        else:
            start = int(start_raw)
            end = int(end_raw) if end_raw else file_size - 1

        if start >= file_size or end < start:
            return Response(
                status_code=416,
                headers={"Content-Range": f"bytes */{file_size}"},
            )

        end = min(end, file_size - 1)
        content_length = end - start + 1

        headers.update(
            {
                "Content-Length": str(content_length),
                "Content-Range": f"bytes {start}-{end}/{file_size}",
            }
        )

        def range_stream():
            with path.open("rb") as stream:
                stream.seek(start)
                remaining = content_length

                while remaining > 0:
                    chunk = stream.read(min(1024 * 1024, remaining))
                    if not chunk:
                        break
                    remaining -= len(chunk)
                    yield chunk

        return StreamingResponse(
            range_stream(),
            status_code=206,
            media_type="application/octet-stream",
            headers=headers,
        )

    # ---------------------------------------------------------
    # РЕЖИМ 2. Первый запрос: авторизация по WS-токену
    # ---------------------------------------------------------
    token = _token_from_header(request)
    if not token:
        token = request.query_params.get("tkn")

    if not token:
        return JSONResponse(
            status_code=401,
            content={"scs": 0, "err": "missing_token"},
        )

    data = decrypt_ws_token(token)
    ids = _require_usi(data)

    if isinstance(ids, JSONResponse):
        return ids

    user_id, fid, app_id = ids
    client_ip = extract_request_client_ip(request)

    # Проверяем доступ к файлу через существующую SQL-процедуру.
    try:
        info = await asyncio.wait_for(
            asyncio.to_thread(
                TeamdroidFileProcedureRepository.file_load,
                user_id=user_id,
                app_id=int(app_id),
                fcm_id=fid,
                client_ip=client_ip,
                fids=file_id,
            ),
            timeout=30.0,
        )
    except TimeoutError:
        return JSONResponse(
            status_code=504,
            content={"scs": 0, "err": "timeout"},
        )

    if info.get("scs") != 1:
        err = info.get("err") or "not_found"
        code = {
            "not_found": 404,
            "no_data": 409,
            "forbidden": 403,
            "invalid_usi": 400,
            "empty_ids": 400,
            "invalid_app_id": 400,
            "empty_dvc": 400,
        }.get(err, 404)

        return JSONResponse(
            status_code=code,
            content={
                "scs": 0,
                "err": err,
                "dtl": info.get("dtl"),
            },
        )

    fls: list[dict[str, Any]] = info.get("fls") or []

    # Не используем fls[0]: SQL не гарантирует порядок строк.
    file_row = next(
        (item for item in fls if item.get("fid") is not None and str(item["fid"]) == str(file_id)),
        None,
    )

    if file_row is None:
        return JSONResponse(
            status_code=404,
            content={"scs": 0, "err": "not_found"},
        )

    fdt_b64: Any = file_row.get("fdt")
    if not fdt_b64:
        return JSONResponse(
            status_code=404,
            content={"scs": 0, "err": "no_data"},
        )

    try:
        content = base64.b64decode(fdt_b64, validate=True)
    except (ValueError, TypeError) as exc:
        api_logger.error(
            "client.file_download: base64 decode failed fid=%s: %r",
            file_id,
            exc,
        )
        return JSONResponse(
            status_code=500,
            content={"scs": 0, "err": "decode_error"},
        )

    # Контроль размера по метаданным SQL.
    expected_size = int(file_row.get("fsz") or 0)
    if expected_size and len(content) != expected_size:
        api_logger.error(
            "client.file_download: size mismatch fid=%s expected=%d actual=%d",
            file_id,
            expected_size,
            len(content),
        )
        return JSONResponse(
            status_code=502,
            content={"scs": 0, "err": "file_size_mismatch"},
        )

    # Сохраняем файл атомарно: клиент не увидит недописанный файл.
    path = _client_download_path(file_id)
    try:
        await asyncio.to_thread(path.parent.mkdir, parents=True, exist_ok=True)

        temp_path = path.with_suffix(".tmp")

        def save_file():
            with temp_path.open("wb") as stream:
                stream.write(content)
                stream.flush()
            temp_path.replace(path)

        await asyncio.to_thread(save_file)

    except OSError as exc:
        api_logger.error(
            "client.file_download: disk write failed fid=%s: %r",
            file_id,
            exc,
            exc_info=True,
        )
        return JSONResponse(
            status_code=507,
            content={"scs": 0, "err": "storage_write_failed"},
        )

    # Создаём временную ссылку.
    ttl = int(getattr(settings, "CLIENT_FILE_LINK_TTL_SEC", 3600))
    ttl = max(60, min(ttl, 24 * 60 * 60))

    expires = int(time.time()) + ttl
    signature = _sign_file_link(file_id, expires)

    base = getattr(settings, "APP_UPDATE_PUBLIC_URL", None) or str(request.base_url).rstrip("/")
    download_url = f"{base}/api/v1/client/files/{file_id}?exp={expires}&sig={signature}"
    #    download_url = f"{str(request.base_url).rstrip('/')}/api/v1/client/files/{file_id}?exp={expires}&sig={signature}"

    #    fnm = file_row.get("fnm") or file_id
    #    fex = (file_row.get("fex") or "").lstrip(".")

    api_logger.info(
        "client.file_prepare: OK user=%s fid=%s size=%d",
        user_id,
        file_id,
        len(content),
    )

    return JSONResponse(
        status_code=200,
        content={
            "scs": 1,
            "url": download_url,
        },
    )


# ===========================================================================
# 9. MESSAGES
# ===========================================================================


@router.post("/msgs", summary="Отправить сообщение (текст + файлы)")
@log_exceptions(api_logger)
async def message_send(
    payload: MessageCreateRequest,
    request: Request,
) -> JSONResponse:
    data = decrypt_ws_token(payload.tkn)
    ids = _require_usi(data)
    if isinstance(ids, JSONResponse):
        return ids
    user_id, fid, app_id = ids

    from ...db import db_manager

    # 1) Собрать все upload_id (FUploadID) из всех сообщений
    wanted_upload_ids: set[str] = set()
    for m in payload.p:
        for uid in m.fls:
            wanted_upload_ids.add(uid)

    # 2) Загрузить upload-записи и прочитать файлы из storage
    files_payload: dict[str, dict[str, Any]] = {}  # FUploadID → {hex, fsz, sha, fnm, fex}
    if wanted_upload_ids:
        async with db_manager.get_session() as session:
            uploads = await AppRepository.upload_get_many_by_upload_ids(session, list(wanted_upload_ids))

        for uid in wanted_upload_ids:
            up = uploads.get(uid)
            if up is None:
                return _upload_error(
                    "not_found",
                    err_detail=f"upload_id {uid!r} not found",
                )
            if up.FUserID != user_id:
                return _upload_error(
                    "forbidden",
                    err_detail=f"upload_id {uid!r} belongs to another user",
                )
            if up.FStatus != "completed":
                return _upload_error(
                    "incomplete",
                    err_detail=f"upload_id {uid!r} status={up.FStatus}",
                )

            path = _storage_path(up.FStorageKey)
            if not path.exists():
                return _upload_error(
                    "not_found",
                    err_detail=f"upload_id {uid!r}: storage file missing",
                )

            raw = await asyncio.to_thread(path.read_bytes)
            files_payload[uid] = {
                "hex": raw.hex(),  # стиль 2 в TRY_CONVERT(..., 2)
                "fsz": len(raw),
                "sha": hashlib.md5(raw).hexdigest(),  # p.FSHA256,
                "fnm": up.FFileName,
                "fex": up.FFileExt or "",
            }

    # 3) Собрать items для TeamdroidFileProcedureRepository.msg_send
    sql_items: list[dict[str, Any]] = []
    for m in payload.p:
        item: dict[str, Any] = {
            "i": m.i,
            "idk": m.idk,
            "tpc": m.tpc,
            "tid": m.tid,
            "fdt": datetime_now().strftime("%Y-%m-%d %H:%M:%S"),
        }
        if m.txt is not None:
            item["txt"] = m.txt

        if m.fls:
            item["fls"] = [
                {
                    "idk": uid,  # FUploadID как idk файла
                    "fnm": files_payload[uid]["fnm"],
                    "fex": files_payload[uid]["fex"].lstrip("."),
                    "fsz": files_payload[uid]["fsz"],
                    "sha": files_payload[uid]["sha"],
                    "fdt": files_payload[uid]["hex"],  # hex, НЕ base64
                }
                for uid in m.fls
            ]
        sql_items.append(item)

    # 4) Вызвать процедуру
    try:
        result = await asyncio.wait_for(
            asyncio.to_thread(
                TeamdroidFileProcedureRepository.msg_send,
                user_id=user_id,
                app_id=int(app_id),
                fcm_id=fid,
                client_ip=extract_request_client_ip(request),
                msgs=sql_items,
            ),
            timeout=30.0,
        )
    except TimeoutError:
        return _fail(504, "msg_out_timeout", "MsgOut timeout", rtr="sync-edit")
    except Exception as exc:
        api_logger.error("client.msgs: procedure error: %r", exc, exc_info=True)
        return _fail(502, "sql_error", str(exc))

    if not result or result.get("scs") != 1:
        err_code = (result or {}).get("err") or "sql_error"
        dtl = (result or {}).get("dtl")
        api_logger.warning("client.msgs: rejected user=%s err=%s dtl=%s", user_id, err_code, dtl)
        return _fail(502, "msg_rejected", err_code, dtl=dtl)

    # 5) После успешной отправки — удалить временные файлы (опционально)
    if files_payload:
        async with db_manager.get_session() as session:
            for uid in files_payload:
                up = await AppRepository.upload_get_by_upload_id(session, uid)
                if up is None:
                    continue
                try:
                    _storage_path(up.FStorageKey).unlink(missing_ok=True)
                except OSError as unlink_exc:
                    api_logger.warning("client.msgs: unlink failed uid=%s: %r", uid, unlink_exc)
                await AppRepository.upload_delete_by_upload_id(session, upload_id=up.FUploadID)

    return JSONResponse(
        status_code=200,
        content={
            "scs": 1,
            "prm": result.get("prm", []),
        },
    )


__all__ = ["router"]
