"""Публичный API мобильного клиента: FID-регистрация, note-relay, auth-code.

Все эндпоинты — client-sync канал, ключ из APP_CLIENT_SYNC_INGEST_API_KEYS
(проверяется в app/middlewares/api/auth.py).

Эндпоинты:

    POST   /api/v1/client/register
        Регистрация Firebase Installation ID (FID) по WS-токену.
        Body: {"token": "<base64(IV||AES-256-GCM(plaintext))>"}
        Plaintext: "FID|usrXXXX|yyMMdd|ver|code"
        Действия:
          1. decrypt_ws_token() — расшифровка и валидация формы токена;
          2. ext.PA_mbl_TokenVerify_Exec через TeamdroidProcedureRepository
             (usi=usrXXX, api=TEAMDROID_APP_ID, dvc=FID, tkn=yyMMdd,
              cip=client_ip, ver, vcd);
          3. push_notification_service.update_fid(user_id, fid);
          4. AppRepository.get_or_create_app(session, fid, user_id=user_id)
             — синхронизация TApps.FUserID для /api/v1/logs/request.

    DELETE /api/v1/client/register
        Снятие FID (logout) + завершение сессии токена.
        Body: {"token": "<base64>"}
        Действия:
          1. decrypt_ws_token();
          2. ext.PA_mbl_TokenFinish_Exec (best-effort — при ошибке FID
             всё равно снимается);
          3. push_notification_service.remove_fid(user_id, fid);
          4. очистка TApps.FUserID (если FID принадлежал этому user_id).

    POST   /api/v1/client/send-code
        Отправка кода авторизации (SMS/звонок) через SQL Server
        Teamdroid: EXEC settings.TEAMDROID_SQL_PROC_AUTH_START @Params = N'<json>'.
        Поле phone (если есть) минимально валидируется, к params
        добавляется client_ip. Тело запроса — произвольный JSON.
        Перенесено из app/api/routers/teamdroid.py.

    POST   /api/v1/client/verify-code
        Проверка кода авторизации через SQL Server Teamdroid:
        EXEC settings.TEAMDROID_SQL_PROC_AUTH_FINISH @Params = N'<json>'.
        Поля request_id/code (если есть) минимально валидируются,
        к params добавляется client_ip. Тело запроса — произвольный JSON.
        Перенесено из app/api/routers/teamdroid.py.

    POST   /api/v1/client/note
        Пересылка {note} (recv/read/kp) от мобильного клиента в Tinode
        через gRPC и сохранение recv/read в Teamdroid SQL Server
        (ext.PA_mbl_MsgsDeliveryStatus_Edit).
        Body: {
            "topic": "usrXXX" | "grpXXX" | "p2pXXX",
            "what": "recv" | "read" | "kp",
            "seq": <int>,
            "user_id": "usrXXX",      # ОБЯЗАТЕЛЕН, он же usi
            "tinode_server": "<...>"  # опционально, игнорируется
        }
        ``user_id`` берётся из тела запроса (не из заголовков) — клиент
        не передаёт свою идентичность в headers.
"""

from __future__ import annotations

import asyncio
import re
from typing import Any

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field, field_validator

from ...config import settings
from ...db.repositories import TeamdroidProcedureRepository
from ...logger import api_logger
from ...utils.datetime import get_timestamp
from ...utils.decorators import log_exceptions
from ...ws.push_notification_service import push_notification_service
from ...ws.token_crypto import decrypt_ws_token

router = APIRouter(prefix="/client", tags=["Client"])


# ---------------------------------------------------------------------------
# Общие константы
# ---------------------------------------------------------------------------

_USER_ID_RE = re.compile(r"^usr[A-Za-z0-9_\-]{10,}$")
_TOPIC_PREFIXES = ("usr", "grp", "p2p", "fnd", "me")
_NOTE_WHAT_ALLOWED = frozenset({"recv", "read", "kp"})


# ---------------------------------------------------------------------------
# Хелперы
# ---------------------------------------------------------------------------


def _extract_client_ip(request: Request) -> str:
    """IP клиента с учётом прокси.

    ВАЖНО: nginx (docker/nginx/conf.d/app.conf) делает **перезапись**
    заголовка ``X-Forwarded-For: $remote_addr`` (не append), поэтому
    здесь всегда будет ровно один адрес — реальный IP клиента.
    Берём последний элемент на случай, если в будущем nginx начнёт
    append (тогда последний — ближайший доверенный прокси).
    """
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
    """Стандартный JSON-ответ об ошибке для client-канала."""
    return JSONResponse(
        status_code=status_code,
        content={
            "success": False,
            "status_code": status_code,
            "error": error,
            "timestamp": get_timestamp(),
        },
    )


# ===========================================================================
# 1. FID REGISTRATION — POST /register
# ===========================================================================


class _TokenPayload(BaseModel):
    """Тело запроса с base64-токеном."""

    token: str = Field(
        ...,
        min_length=1,
        description="Base64(IV||AES-256-GCM(plaintext))",
    )

    @field_validator("token")
    @classmethod
    def _strip(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("empty token")
        return v


def _decrypt_or_error(token: str) -> tuple[object | None, JSONResponse | None]:
    payload = decrypt_ws_token(token)
    if payload is None:
        return None, JSONResponse(
            status_code=400,
            content={
                "success": False,
                "error": "invalid_token",
                "message": "Token decryption or validation failed",
                "timestamp": get_timestamp(),
            },
        )
    return payload, None


@router.post(
    "/register",
    summary="Зарегистрировать FID (с проверкой токена)",
)
@log_exceptions(api_logger)
async def register_fid(payload: _TokenPayload, request: Request) -> JSONResponse:
    """Регистрация FID по WS-токену (TokenVerify)."""
    from ...ws.token_crypto import WsTokenData

    data, err = _decrypt_or_error(payload.token)
    if err is not None:
        return err
    assert isinstance(data, WsTokenData)

    user_id = data.user_id
    fid = data.fcm_id
    client_ip = _extract_client_ip(request)

    app_id = int(getattr(settings, "TEAMDROID_APP_ID", 0) or 0)
    if not app_id:
        api_logger.error("client.register: TEAMDROID_APP_ID=0 — TokenVerify невозможен")
        return JSONResponse(
            status_code=503,
            content={
                "success": False,
                "error": "server_misconfigured",
                "message": "TEAMDROID_APP_ID is not configured",
                "timestamp": get_timestamp(),
            },
        )

    # 1) TokenVerify в Teamdroid SQL Server
    try:
        ok, verify_err = await asyncio.wait_for(
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
            timeout=10.0,
        )
    except TimeoutError:
        api_logger.warning("client.register: verify_token timeout user=%s", user_id)
        return JSONResponse(
            status_code=504,
            content={
                "success": False,
                "error": "verify_timeout",
                "timestamp": get_timestamp(),
            },
        )

    if not ok:
        api_logger.warning(
            "client.register: verify_token rejected user=%s fid_suffix=%s err=%s",
            user_id,
            fid[-6:] if len(fid) >= 6 else "***",
            verify_err,
        )
        return JSONResponse(
            status_code=401,
            content={
                "success": False,
                "error": "token_rejected",
                "message": verify_err or "TokenVerify failed",
                "timestamp": get_timestamp(),
            },
        )

    # 2) Регистрация FID в in-memory сервисе
    await push_notification_service.update_fid(user_id, fid)
    api_logger.info(
        "client.register: OK user=%s fid_suffix=...%s",
        user_id,
        fid[-8:] if len(fid) >= 8 else "***",
    )

    # 3) Синхронизация TApps (нужно для /api/v1/logs/request)
    try:
        from ...db import db_manager
        from ...db.repositories import AppRepository

        async with db_manager.get_session() as session:
            await AppRepository.get_or_create_app(session, fid, user_id=user_id)
            await session.commit()
    except Exception as exc:  # noqa: BLE001
        api_logger.warning("client.register: TApps sync failed user=%s: %r", user_id, exc)

    return JSONResponse(
        status_code=200,
        content={
            "success": True,
            "user_id": user_id,
            "fid_registered": True,
            "timestamp": get_timestamp(),
        },
    )


# ===========================================================================
# 2. FID UNREGISTRATION — DELETE /register
# ===========================================================================


@router.delete(
    "/register",
    summary="Удалить FID (с завершением сессии токена)",
)
@log_exceptions(api_logger)
async def unregister_fid(payload: _TokenPayload) -> JSONResponse:
    """Снятие FID (logout) + TokenFinish (best-effort)."""
    from ...ws.token_crypto import WsTokenData

    data, err = _decrypt_or_error(payload.token)
    if err is not None:
        return err
    assert isinstance(data, WsTokenData)

    user_id = data.user_id
    fid = data.fcm_id

    app_id = int(getattr(settings, "TEAMDROID_APP_ID", 0) or 0)

    # 1) TokenFinish (best-effort — при ошибке всё равно снимаем FID)
    finish_ok = False
    if app_id:
        try:
            finish_ok, finish_err = await asyncio.wait_for(
                asyncio.to_thread(
                    TeamdroidProcedureRepository.token_finish,
                    user_id=user_id,
                    fcm_id=fid,
                    app_id=app_id,
                ),
                timeout=10.0,
            )
            if not finish_ok:
                api_logger.warning(
                    "client.unregister: token_finish non-OK user=%s err=%s",
                    user_id,
                    finish_err,
                )
        except TimeoutError:
            api_logger.warning("client.unregister: token_finish timeout user=%s", user_id)
    else:
        api_logger.warning("client.unregister: TEAMDROID_APP_ID=0 — TokenFinish пропущен")

    # 2) Удаляем FID из сервиса
    await push_notification_service.remove_fid(user_id, fid)

    # 3) Очистить FUserID в TApps (FID может быть переиспользован)
    try:
        from ...db import db_manager
        from ...db.repositories import AppRepository

        async with db_manager.get_session() as session:
            app = await AppRepository.get_app_by_fid(session, fid)
            if app is not None and app.FUserID == user_id:
                app.FUserID = None
            await session.commit()
    except Exception as exc:  # noqa: BLE001
        api_logger.warning("client.unregister: TApps sync failed: %r", exc)

    api_logger.info(
        "client.unregister: OK user=%s fid_suffix=...%s finish_ok=%s",
        user_id,
        fid[-8:] if len(fid) >= 8 else "***",
        finish_ok,
    )

    return JSONResponse(
        status_code=200,
        content={
            "success": True,
            "user_id": user_id,
            "fid_registered": False,
            "token_finished": finish_ok,
            "timestamp": get_timestamp(),
        },
    )


# ===========================================================================
# 2.5. AUTH CODE — POST /send-code, POST /verify-code
# ===========================================================================
#
# Перенесено из app/api/routers/teamdroid.py.
# Используют TeamdroidProcedureRepository.auth_start / auth_finish через
# asyncio.to_thread (pyodbc блокирующий).
# Идентичность клиента — IP из заголовков (X-Forwarded-For / X-Real-IP).
#
# Контракт процедур:
#   EXEC <proc> @Params = N'<json>'
#   Выход: одна JSON-строка в одной колонке одной строки.
# ===========================================================================


@router.post(
    "/send-code",
    summary="Запустить хранимую процедуру SQL Server для отправки кода",
    description=(
        "Принимает произвольный JSON, минимально валидирует поле phone (если оно есть) "
        "и запускает хранимую процедуру SQL Server, передавая ей весь входной JSON "
        "в качестве параметра @Params. Дополнительно в @Params добавляется client_ip "
        "(из стандартных заголовков X-Forwarded-For / X-Real-IP, проставленных nginx). "
        "Имя процедуры задаётся в settings.TEAMDROID_SQL_PROC_AUTH_START "
        "(по умолчанию ext.PA_mbl_AuthStart_Exec). "
        "Процедура должна возвращать JSON-строку (одна колонка, одна строка)."
    ),
)
@log_exceptions(api_logger)
async def send_code(params: dict[str, Any], request: Request) -> JSONResponse:
    """Запуск хранимой процедуры SQL Server с JSON-параметром (отправка кода)."""
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
        api_logger.error(
            "❌ [client] send_code procedure failed: %r",
            proc_exc,
            exc_info=True,
        )
        return _error_response(
            500,
            f"send_code_proc_failed: {type(proc_exc).__name__}: {proc_exc}",
        )

    api_logger.debug(
        "✅ [client] send_code procedure executed: ip=%r",
        params.get("client_ip"),
    )

    return JSONResponse(
        status_code=200,
        content={
            "success": True,
            "result": result.get("result"),
            "timestamp": result.get("timestamp") or get_timestamp(),
        },
    )


@router.post(
    "/verify-code",
    summary="Запустить хранимую процедуру SQL Server для проверки кода",
    description=(
        "Принимает произвольный JSON, минимально валидирует поля request_id и code "
        "(если они есть) и запускает хранимую процедуру SQL Server, передавая ей весь "
        "входной JSON в качестве параметра @Params. Дополнительно в @Params добавляется "
        "client_ip (из стандартных заголовков X-Forwarded-For / X-Real-IP, проставленных "
        "nginx). Имя процедуры задаётся в settings.TEAMDROID_SQL_PROC_AUTH_FINISH "
        "(по умолчанию ext.PA_mbl_AuthFinish_Exec). "
        "Процедура должна возвращать JSON-строку (одна колонка, одна строка), "
        "которая парсится и возвращается клиенту в поле result."
    ),
)
@log_exceptions(api_logger)
async def verify_code(params: dict[str, Any], request: Request) -> JSONResponse:
    """Запуск хранимой процедуры SQL Server с JSON-параметром (проверка кода)."""
    request_id = params.get("request_id")
    code = params.get("code")

    if request_id is not None and not str(request_id or "").strip():
        return _error_response(400, "invalid_request_id")

    if code is not None:
        code_str = str(code or "").strip()
        if len(code_str) < 4:
            return _error_response(400, "invalid_code")
        params["code"] = code_str

    params["client_ip"] = _extract_client_ip(request)

    try:
        result = await asyncio.to_thread(
            TeamdroidProcedureRepository.auth_finish,
            params,
        )
    except Exception as proc_exc:  # noqa: BLE001
        api_logger.error(
            "❌ [client] verify_code procedure failed: %r",
            proc_exc,
            exc_info=True,
        )
        return _error_response(
            500,
            f"verify_code_proc_failed: {type(proc_exc).__name__}: {proc_exc}",
        )

    api_logger.debug(
        "✅ [client] verify_code executed: proc=%s rows=%s raw=%r",
        result.get("proc"),
        result.get("rows_affected"),
        result.get("raw"),
    )

    return JSONResponse(
        status_code=200,
        content={
            "success": True,
            "result": result.get("result"),
            "timestamp": result.get("timestamp") or get_timestamp(),
        },
    )


# ===========================================================================
# 3. NOTE RELAY — POST /note
# ===========================================================================
#
# Модели и логика перенесены из app/api/routers/teamdroid.py (relay_note).
# user_id (usrXXX) — обязателен, берётся из тела; он же usi для Teamdroid SQL.
# ===========================================================================


class NoteRelayRequest(BaseModel):
    """Запрос от мобильного клиента: {note} для пересылки в Tinode.

    ``user_id`` (Tinode user ID ``usrXXX``) — одновременно ``usi``
    (хэш пользователя Teamdroid) и ``on_behalf_of`` в Tinode.
    Хранимая процедура ``ext.PA_mbl_MsgsDeliveryStatus_Edit`` ищет
    пользователя по ``uv.FValue = jsn.UserHash`` (FK_Link=4), поэтому
    в ``usi`` передаётся тот же ``usrXXX``, что и в ``user_id``.
    """

    topic: str = Field(
        ...,
        description="Tinode topic (usrXXX/grpXXX/p2pXXX)",
        min_length=1,
        max_length=64,
    )
    what: str = Field(
        ...,
        description="Тип note: recv | read | kp",
        min_length=1,
        max_length=8,
    )
    seq: int = Field(..., description="Seq ID сообщения", ge=0)
    user_id: str = Field(
        ...,
        description=(
            "Tinode user ID (usrXXX). Одновременно является usi — "
            "хэшем пользователя Teamdroid (FValue из TRSAppUsersValues, "
            "FK_Link=4)."
        ),
        max_length=32,
    )
    tinode_server: str | None = Field(
        None,
        description=("Origin Tinode-сервера (для совместимости с мобильным клиентом; игнорируется)"),
        max_length=255,
    )

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
    """Ответ на /note: подтверждение пересылки в Tinode."""

    success: bool = Field(True, description="Успешность операции")
    topic: str = Field(..., description="Tinode topic")
    what: str = Field(..., description="Тип note (recv/read/kp)")
    seq: int = Field(..., description="Seq ID сообщения")
    user_id: str = Field(..., description="ID пользователя, от имени которого отправлен note")
    ctrl_code: int | None = Field(None, description="Код CTRL-ответа Tinode (200 = OK)")
    ctrl_text: str | None = Field(None, description="Текст CTRL-ответа Tinode")
    teamdroid_saved: bool = Field(False, description="Факт recv/read сохранён в Teamdroid SQL Server")
    timestamp: str = Field(..., description="Время операции")


def _do_note(
    topic: str,
    what: str,
    seq: int,
    on_behalf_of: str,
    client_ip: str,
) -> tuple[dict[str, Any], bool]:
    """Синхронная отправка {note} в Tinode и сохранение в Teamdroid SQL Server.

    Args:
        topic: имя топика Tinode.
        what: "recv" | "read" | "kp".
        seq: seq ID сообщения.
        on_behalf_of: Tinode user ID (usrXXX) — от имени кого отправить
            note. Он же используется как ``usi`` для Teamdroid SQL.
        client_ip: IP клиента ($.cip).

    Returns:
        tuple[dict, bool]: (ctrl_dict, teamdroid_saved)
    """
    from .teamdroid import _ctrl_to_dict, get_teamdroid_client

    client = get_teamdroid_client()

    ctrl = client.note(
        topic=topic,
        what=what,
        seq=seq,
        on_behalf_of=on_behalf_of,
    )
    ctrl_dict = _ctrl_to_dict(ctrl) if ctrl is not None else {}

    # Сохраняем факт recv/read в Teamdroid SQL Server.
    # kp (key press) не сохраняем — эфемерное событие.
    teamdroid_saved = False
    if what in ("recv", "read"):
        teamdroid_saved = TeamdroidProcedureRepository.edit_msg_status_delivery(
            topic=topic,
            what=what,
            seq=seq,
            user_id=on_behalf_of,  # usrXXX == usi
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
    """Приём {note} от мобильного клиента и пересылка в Tinode.

    Дополнительно факт recv/read сохраняется в Teamdroid SQL Server через
    ext.PA_mbl_MsgsDeliveryStatus_Edit. Используется вместо прямой
    отправки {note} с мобильного клиента в Tinode, чтобы обойти
    блокировку note-канала на сервере/клиенте.

    Аутентификация — X-API-Key (APP_CLIENT_SYNC_INGEST_API_KEYS,
    см. app/middlewares/api/auth.py). Идентификатор пользователя
    ОБЯЗАТЕЛЕН и берётся из поля user_id в теле запроса.
    """
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
                "success": False,
                "error": f"validation_error: {val_exc}",
                "timestamp": get_timestamp(),
            },
        )
    except Exception as note_exc:  # noqa: BLE001
        api_logger.error("[client/note] failed: %r", note_exc, exc_info=True)
        return JSONResponse(
            status_code=500,
            content={
                "success": False,
                "error": f"{type(note_exc).__name__}: {note_exc}",
                "timestamp": get_timestamp(),
            },
        )

    ctrl_code = ctrl_dict.get("code")
    ctrl_text = ctrl_dict.get("text")

    response = NoteRelayResponse(
        success=True,
        topic=payload.topic,
        what=payload.what,
        seq=payload.seq,
        user_id=user_id,
        ctrl_code=ctrl_code if isinstance(ctrl_code, int) else None,
        ctrl_text=ctrl_text if isinstance(ctrl_text, str) else None,
        teamdroid_saved=teamdroid_saved,
        timestamp=get_timestamp(),
    )

    if isinstance(ctrl_code, int) and ctrl_code >= 400:
        api_logger.warning(
            "⚠️ [client/note] Tinode returned CTRL code=%s text=%r",
            ctrl_code,
            ctrl_text,
        )
        return JSONResponse(
            status_code=502,
            content={
                **response.model_dump(),
                "success": False,
                "error": f"tinode_ctrl_error: code={ctrl_code} text={ctrl_text!r}",
            },
        )

    return JSONResponse(status_code=200, content=response.model_dump())


__all__ = ["router"]
