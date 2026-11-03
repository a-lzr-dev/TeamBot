"""Публичный API для регистрации FID через WS-токен.

Клиент вызывает POST /api/v1/push/register_fid с {"token": "<base64>"}:
  - токен расшифровывается (IV||AES-GCM, plaintext = FID|usrXXX|yyMMdd|ver|code);
  - вызывается ext.PA_mbl_TokenVerify_Exec (usi=usrXXX, api=TEAMDROID_APP_ID,
    dvc=FID, tkn=yyMMdd, cip=client_ip, ver, vcd);
  - при успехе FID регистрируется в push_notification_service.

DELETE /api/v1/push/register_fid с {"token": "<base64>"}:
  - токен расшифровывается;
  - вызывается ext.PA_mbl_TokenFinish_Exec (usi, api, dvc);
  - FID удаляется из push_notification_service.

Старый контракт {user_id, fid} больше не поддерживается.
"""

from __future__ import annotations

import asyncio

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

router = APIRouter(prefix="/push", tags=["Push"])


# ---------------------------------------------------------------------------
# Модели
# ---------------------------------------------------------------------------


class _TokenPayload(BaseModel):
    token: str = Field(..., min_length=1, description="Base64(IV||AES-256-GCM(plaintext))")

    @field_validator("token")
    @classmethod
    def _strip(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("empty token")
        return v


# ---------------------------------------------------------------------------
# Хелперы
# ---------------------------------------------------------------------------


def _extract_client_ip(request: Request) -> str:
    """IP клиента с учётом прокси (последний в X-Forwarded-For)."""
    xff = request.headers.get("x-forwarded-for")
    if xff:
        parts = [p.strip() for p in xff.split(",") if p.strip()]
        if parts:
            return parts[-1][:64]
    xri = request.headers.get("x-real-ip")
    if xri:
        return xri.strip()[:64]
    if request.client is not None:
        return (request.client.host or "")[:64]
    return ""


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


# ---------------------------------------------------------------------------
# POST — регистрация FID (TokenVerify)
# ---------------------------------------------------------------------------


@router.post("/register_fid", summary="Зарегистрировать FID (с проверкой токена)")
@log_exceptions(api_logger)
async def register_fid(payload: _TokenPayload, request: Request) -> JSONResponse:
    data, err = _decrypt_or_error(payload.token)
    if err is not None:
        return err
    # data: WsTokenData — но mypy его не знает, приводим по месту
    from ...ws.token_crypto import WsTokenData

    assert isinstance(data, WsTokenData)

    user_id = data.user_id
    fid = data.fcm_id
    client_ip = _extract_client_ip(request)

    app_id = int(getattr(settings, "TEAMDROID_APP_ID", 0) or 0)
    if not app_id:
        api_logger.error("push.register_fid: TEAMDROID_APP_ID=0 — TokenVerify невозможен")
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
        api_logger.warning("push.register_fid: verify_token timeout user=%s", user_id)
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
            "push.register_fid: verify_token rejected user=%s fid_suffix=%s err=%s",
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
        "push.register_fid: OK user=%s fid_suffix=...%s",
        user_id,
        fid[-8:] if len(fid) >= 8 else "***",
    )

    return JSONResponse(
        status_code=200,
        content={
            "success": True,
            "user_id": user_id,
            "fid_registered": True,
            "timestamp": get_timestamp(),
        },
    )


# ---------------------------------------------------------------------------
# DELETE — удаление FID (TokenFinish)
# ---------------------------------------------------------------------------


@router.delete("/register_fid", summary="Удалить FID (с завершением сессии токена)")
@log_exceptions(api_logger)
async def unregister_fid(payload: _TokenPayload, request: Request) -> JSONResponse:
    data, err = _decrypt_or_error(payload.token)
    if err is not None:
        return err
    from ...ws.token_crypto import WsTokenData

    assert isinstance(data, WsTokenData)

    user_id = data.user_id
    fid = data.fcm_id
    client_ip = _extract_client_ip(request)
    _ = client_ip  # TokenFinish IP не использует, оставлено для симметрии

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
                    "push.unregister_fid: token_finish non-OK user=%s err=%s",
                    user_id,
                    finish_err,
                )
        except TimeoutError:
            api_logger.warning("push.unregister_fid: token_finish timeout user=%s", user_id)
    else:
        api_logger.warning("push.unregister_fid: TEAMDROID_APP_ID=0 — TokenFinish пропущен")

    # 2) Удаляем FID из сервиса
    await push_notification_service.remove_fid(user_id, fid)
    api_logger.info(
        "push.unregister_fid: OK user=%s fid_suffix=...%s finish_ok=%s",
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


__all__ = ["router"]
