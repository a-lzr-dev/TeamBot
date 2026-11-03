"""WebSocket-эндпоинт для мобильных клиентов: GET /ws/notify?token=...&fid=...

Порядок действий:
  1. Извлечь token из ``?token=`` или ``Authorization: Bearer``.
  2. Извлечь FID (Firebase Installation ID) из ``?fid=``.
  3. Определить реальный IP клиента (X-Forwarded-For / X-Real-IP / client.host)
     для передачи в SQL Server (ext.PA_mbl_TokenVerify_Exec, поле $.cip).
  4. Проверить token согласно ``settings.ws_notify_verify_mode``.
     ``verify_ws_token`` возвращает ``VerifiedToken`` (см. ``app/ws/auth.py``).
  5. Если ``VerifiedToken.ok`` — false, закрыть WS с кодом 4401 и выйти.
  6. Зарегистрировать соединение в ``push_notification_service`` с FID.
  7. При отключении — снять регистрацию, **сохранив FID** в реестре
     (``keep_fid=True``), чтобы FCM-доставка продолжала работать, когда
     приложение закрыто.

Завершение сессии токена (``ext.PA_mbl_TokenFinish_Exec``) здесь
**не выполняется**: обычный разрыв WS (закрытие приложения, потеря сети,
рестарт сервера) не является логаутом. Если вызывать TokenFinish на каждый
disconnect, SQL Server помечает устройство завершённым, и FCM перестаёт
доставлять push на закрытое приложение.

TokenFinish выполняется только при явном логауте — через
``DELETE /api/v1/client/register`` (см. ``app/api/routers/client.py``).

Берётся ПОСЛЕДНИЙ адрес из X-Forwarded-For (добавлен доверенным nginx),
а не первый — первый может быть подделан клиентом.
"""

from __future__ import annotations

from fastapi import WebSocket, WebSocketDisconnect

from ..config import settings
from ..logger import api_logger
from .auth import VerifiedToken, verify_ws_token
from .push_notification_service import push_notification_service


def _extract_token(websocket: WebSocket) -> str | None:
    token = websocket.query_params.get("token")
    if token:
        return token
    auth = websocket.headers.get("authorization", "")
    if auth.startswith("Bearer "):
        return auth[7:].strip()
    return None


def _extract_fid(websocket: WebSocket) -> str | None:
    """Достаёт FID (Firebase Installation ID) из query ``?fid=``."""
    fid = websocket.query_params.get("fid")
    if fid:
        return fid.strip()
    return None


def _extract_client_ip(websocket: WebSocket) -> str | None:
    """Определяет реальный IP клиента с учётом прокси.

    Берём ПОСЛЕДНИЙ адрес из X-Forwarded-For (первый может быть
    подделан клиентом, последний добавлен нашим доверенным прокси).
    Если заголовка нет — X-Real-IP, затем websocket.client.host.
    """
    xff = websocket.headers.get("x-forwarded-for")
    if xff:
        parts = [p.strip() for p in xff.split(",") if p.strip()]
        if parts:
            return parts[-1][:64]

    xri = websocket.headers.get("x-real-ip")
    if xri:
        return xri.strip()[:64]

    client = websocket.client
    if client is not None:
        host = client.host or ""
        return host[:64] or None
    return None


def _verified_for_trust_mode(websocket: WebSocket, token: str | None) -> VerifiedToken:
    """В режиме ``trust`` разрешаем клиенту самому прислать user_id.

    Допустимо только в development; проверка ``APP_ENV`` уже выполнена
    внутри ``verify_ws_token``.
    """
    header_user = websocket.headers.get("x-user-id")
    if header_user and header_user.startswith("usr"):
        return VerifiedToken(user_id=header_user)
    if token and token.startswith("usr") and len(token) > 5:
        return VerifiedToken(user_id=token)
    return VerifiedToken(user_id=None)


async def ws_notify_handler(websocket: WebSocket) -> None:
    # 1) token / fid / client_ip
    api_logger.info(
        "ws: connect attempt path=%s client=%r query_keys=%s headers_upgrade=%r",
        websocket.url.path,
        websocket.client,
        sorted(websocket.query_params.keys()),
        websocket.headers.get("upgrade"),
    )

    token = _extract_token(websocket)
    query_fid = _extract_fid(websocket)
    client_ip = _extract_client_ip(websocket)

    mode = settings.ws_notify_verify_mode
    api_logger.info(
        "ws: verify_mode=%s token_present=%s fcm_present=%s client_ip=%r",
        mode,
        bool(token),
        bool(query_fid),
        client_ip,
    )

    # 2) аутентификация
    if mode == "trust":
        verified = _verified_for_trust_mode(websocket, token)
    else:
        verified = await verify_ws_token(token, client_ip=client_ip)

    user_id = verified.user_id
    # FID из query имеет приоритет, т.к. клиент передаёт его явно.
    # Fallback — FID, извлечённый сервером из токена (SQL Server / Tinode).
    fcm_id = query_fid or verified.fcm_id

    if not user_id or not user_id.startswith("usr"):
        api_logger.warning(
            "ws: rejected connection user_id=%r mode=%s token_prefix=%r",
            user_id,
            mode,
            token[:16] if token else None,
        )
        await websocket.close(code=4401, reason="unauthorized")
        return

    # 3) accept + регистрация
    await websocket.accept()
    await push_notification_service.register(user_id, websocket, fcm_id=fcm_id)
    api_logger.info(
        "ws: connected user=%s fcm=%s",
        user_id,
        (fcm_id or "-")[-6:] if fcm_id else "-",
    )

    try:
        while True:
            message = await websocket.receive()
            if message.get("type") == "websocket.disconnect":
                break
    except WebSocketDisconnect:
        pass
    finally:
        # Обычный disconnect: снимаем WS, но НЕ завершаем токен.
        #
        # Закрытие приложения/сети ≠ логаут. TokenFinish в SQL Server
        # делается только через DELETE /api/v1/client/register
        # (app/api/routers/client.py::unregister_fid), иначе FCM
        # перестанет доставлять push на закрытое приложение.
        await push_notification_service.unregister(
            user_id,
            websocket,
            keep_fid=True,
        )
        api_logger.info(
            "ws: disconnected user=%s (fid kept for FCM)",
            user_id,
        )


__all__ = ["ws_notify_handler"]
