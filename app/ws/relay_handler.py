"""Приём push-батчей от Go myrelay-адаптера.

Эндпоинт POST по пути settings.WS_RELAY_INGEST_PATH (по умолчанию
/internal/push). Защищён Bearer-токеном (WS_RELAY_AUTH_TOKEN), который
должен совпадать с `auth_token` в tinode.conf (push -> myrelay).

Go-адаптер (server/push/myrelay) отправляет JSON в snake_case:
    {
      "event_id": "myrelay-...",
      "ts": "2026-...",
      "pushes": [
        {"user_id": "usrXXX", "type": "msg", "topic": "usrYYY",
         "from": "usrZZZ", "seq": 5, "unread": 1, "delivered": 2,
         "mime": "text/x-drafty", "content": {...}, "ts": "..."},
        ...
      ]
    }

Дедупликация выполняется:
  - на уровне батча по event_id (см. PushNotificationService.is_duplicate_batch);
  - на уровне отдельного push по (user_id, topic, type, seq|ts).
"""

from __future__ import annotations

import hmac
from typing import Annotated

from fastapi import APIRouter, Header, HTTPException, status
from fastapi.responses import JSONResponse

from ..config import settings
from ..logger import api_logger
from .models import RelayBatch
from .push_notification_service import DeliveryStatus, push_notification_service

router = APIRouter(tags=["Internal"])

# По умолчанию совпадает с settings.WS_RELAY_INGEST_PATH.
_DEFAULT_INGEST_PATH = "/internal/push"


def _ingest_path() -> str:
    return settings.WS_RELAY_INGEST_PATH or _DEFAULT_INGEST_PATH


def _check_auth(authorization: str | None, event_id: str | None) -> None:
    expected = settings.WS_RELAY_AUTH_TOKEN
    if not expected:
        # Токен не сконфигурирован: разрешаем только в development.
        if (settings.APP_ENV or "").lower() not in ("development", "dev"):
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="WS_RELAY_AUTH_TOKEN is not configured on server",
            )
        return

    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Missing bearer token")

    provided = authorization.removeprefix("Bearer ").strip()
    if not hmac.compare_digest(provided, expected):
        api_logger.warning("relay: invalid auth token (event_id=%s)", event_id or "-")
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token")


@router.post(_ingest_path(), include_in_schema=False)
async def ingest_relay_batch(
    batch: RelayBatch,
    authorization: Annotated[str | None, Header()] = None,
    x_event_id: Annotated[str | None, Header()] = None,
) -> JSONResponse:
    _check_auth(authorization, x_event_id or batch.event_id)

    if batch.pushes and push_notification_service.is_duplicate_batch(batch.event_id):
        api_logger.info("relay: duplicate batch event_id=%s, skipped", batch.event_id)
        return JSONResponse(
            status_code=200,
            content={
                "ok": True,
                "accepted": 0,
                "event_id": batch.event_id,
                "duplicate": True,
            },
        )

    if not batch.pushes:
        api_logger.warning("relay: empty batch event_id=%s", batch.event_id)
        return JSONResponse(
            status_code=200,
            content={"ok": True, "accepted": 0, "event_id": batch.event_id, "empty": True},
        )

    user_ids = sorted({p.user_id for p in batch.pushes})
    api_logger.info(
        "relay: batch received event_id=%s pushes=%d users=%s",
        batch.event_id,
        len(batch.pushes),
        user_ids,
    )

    # --- NEW: разбиваем на категории по статусу ---
    delivered = 0
    partial = 0
    no_connections = 0
    skipped = 0
    duplicate = 0
    failed = 0
    undelivered_users: list[str] = []

    for push in batch.pushes:
        try:
            api_logger.debug(
                "relay: push user=%s type=%s topic=%s from=%s seq=%s unread=%s silent=%s webrtc=%r",
                push.user_id,
                push.type,
                push.topic,
                push.from_id,
                push.seq,
                push.unread,
                push.silent,
                push.webrtc,
            )
            status = await push_notification_service.dispatch(push)
        except Exception as e:  # noqa: BLE001
            failed += 1
            undelivered_users.append(push.user_id)
            api_logger.error(
                "relay: dispatch raised user=%s type=%s err=%r",
                push.user_id,
                push.type,
                e,
            )
            continue

        if status == DeliveryStatus.DELIVERED:
            delivered += 1
        elif status == DeliveryStatus.PARTIAL:
            partial += 1
        elif status == DeliveryStatus.NO_CONNECTIONS:
            no_connections += 1
            undelivered_users.append(push.user_id)
        elif status == DeliveryStatus.FAILED:
            failed += 1
            undelivered_users.append(push.user_id)
        elif status in (DeliveryStatus.SKIPPED_SILENT, DeliveryStatus.SKIPPED_TYPE):
            skipped += 1
        elif status == DeliveryStatus.DUPLICATE:
            duplicate += 1

    # --- NEW: сводный лог по батчу ---
    if undelivered_users:
        # de-dup и сортируем — чтобы не спамить одним user_id дважды
        unique_undelivered = sorted(set(undelivered_users))
        api_logger.warning(
            "relay: batch event_id=%s undelivered users=%s "
            "(delivered=%d partial=%d no_connections=%d failed=%d "
            "skipped=%d duplicate=%d)",
            batch.event_id,
            unique_undelivered,
            delivered,
            partial,
            no_connections,
            failed,
            skipped,
            duplicate,
        )

    return JSONResponse(
        status_code=200,
        content={
            "ok": True,
            "event_id": batch.event_id,
            # обратная совместимость: accepted = всё, что не failed
            "accepted": delivered + partial + no_connections + skipped + duplicate,
            # расширенная статистика
            "delivered": delivered,
            "partial": partial,
            "no_connections": no_connections,
            "failed": failed,
            "skipped": skipped,
            "duplicate": duplicate,
            "undelivered_users": sorted(set(undelivered_users)),
        },
    )
