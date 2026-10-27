"""WebSocket-эндпоинт для мобильных клиентов: GET /ws/notify?token=..."""

from __future__ import annotations

from fastapi import WebSocket, WebSocketDisconnect

from ..config import settings
from ..logger import api_logger
from .auth import verify_ws_token
from .push_notification_service import push_notification_service


async def ws_notify_handler(websocket: WebSocket) -> None:
    # 1) Токен: сначала ?token=, потом Authorization: Bearer
    api_logger.info(
        "ws: connect attempt path=%s client=%r query=%s headers_upgrade=%r",
        websocket.url.path,
        websocket.client,
        dict(websocket.query_params),
        websocket.headers.get("upgrade"),
    )

    token = websocket.query_params.get("token")
    if not token:
        auth = websocket.headers.get("authorization", "")
        if auth.startswith("Bearer "):
            token = auth[7:].strip()

    mode = settings.ws_notify_verify_mode
    api_logger.info("ws: verify_mode=%s token_present=%s", mode, bool(token))

    if mode == "trust":
        user_id = websocket.headers.get("x-user-id")
        if not user_id:
            user_id = await verify_ws_token(token)
    else:
        user_id = await verify_ws_token(token)

    if not user_id or not user_id.startswith("usr"):
        api_logger.warning(
            "ws: rejected connection user_id=%r mode=%s token_prefix=%r",
            user_id,
            mode,
            token[:16] if token else None,
        )
        await websocket.close(code=4401, reason="unauthorized")
        return

    # 4) Регистрация
    await websocket.accept()
    await push_notification_service.register(user_id, websocket)
    api_logger.info("ws: connected user=%s", user_id)

    try:
        while True:
            message = await websocket.receive()
            if message.get("type") == "websocket.disconnect":
                break
    except WebSocketDisconnect:
        pass
    finally:
        await push_notification_service.unregister(user_id, websocket)
        api_logger.info("ws: disconnected user=%s", user_id)
