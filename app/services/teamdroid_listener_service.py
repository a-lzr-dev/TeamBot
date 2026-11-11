"""Фоновый слушатель Service Broker: RECEIVE -> доставить -> SEND результат.

CHANGED:
  * единый формат пуша {"type":"sync"} в WS и FCM (раньше был рассинхрон
    "new_data" vs "sync_needed");
  * coalesce по user_id: события для одного пользователя выполняются
    строго последовательно, шквал событий не превращается в шквал пушей;
  * Semaphore(N) на общее число параллельных доставок;
  * _persist_pending реализован через AppPushPendingRepository
    (TPushPending) — офлайн-клиент не теряет сигнал;
  * send_result(handle) вызывается в finally — handle из Service Broker
    всегда закрывается, даже при исключении.
"""

from __future__ import annotations

import asyncio
from collections import defaultdict
from typing import Any

from ..config import settings
from ..db.repositories import TeamdroidServiceBrokerRepository
from ..db.repositories.app_push_pending import app_push_pending_repo
from ..logger import app_logger
from ..ws.push_notification_service import push_notification_service

# Ограничения параллелизма (можно вынести в settings при необходимости).
_MAX_CONCURRENT_DELIVERIES = 32


class TeamdroidListenerService:
    def __init__(self) -> None:
        self._running = False
        self._task: asyncio.Task | None = None
        self._user_locks: dict[str, asyncio.Lock] = defaultdict(asyncio.Lock)
        self._sem = asyncio.Semaphore(_MAX_CONCURRENT_DELIVERIES)

    async def start(self) -> None:
        if self._running:
            return
        if not getattr(settings, "TEAMDROID_SQL_SERVER", ""):
            app_logger.info("sb_listener: TEAMDROID_SQL_SERVER not configured, skipping")
            return
        self._running = True
        self._task = asyncio.create_task(self._loop())
        app_logger.info("sb_listener: started")

    async def stop(self) -> None:
        self._running = False
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            self._task = None
        app_logger.info("sb_listener: stopped")

    async def _loop(self) -> None:
        while self._running:
            try:
                signals = await asyncio.to_thread(TeamdroidServiceBrokerRepository.receive_signals)
                if not signals:
                    continue
                for sig in signals:
                    await self._process(sig["handle"], sig["payload"])
            except asyncio.CancelledError:
                break
            except Exception as exc:  # noqa: BLE001
                app_logger.error("sb_listener: loop error: %r", exc, exc_info=True)
                await asyncio.sleep(3)

    async def _process(self, handle: Any, payload: dict) -> None:
        """Обработать один сигнал: доставить пуш и закрыть handle.

        send_result вызывается в finally, чтобы handle всегда закрывался.
        """
        user_id: str | None = payload.get("user_id")
        msg_type: str | None = payload.get("type")
        topic: str | None = payload.get("topic")

        if not user_id or not user_id.startswith("usr"):
            await self._safe_send_result(
                handle,
                {
                    "status": "invalid",
                    "via": None,
                    "user_id": user_id,
                    "topic": topic,
                    "type": msg_type,
                },
            )
            return

        # Coalesce по user_id: события одного пользователя — последовательно.
        async with self._user_locks[user_id]:
            channel: str | None = None
            try:
                async with self._sem:
                    channel = await self._deliver(user_id, {"type": "sync"})
            except Exception as exc:  # noqa: BLE001
                app_logger.error(
                    "sb_listener: delivery error user=%s: %r",
                    user_id,
                    exc,
                    exc_info=True,
                )
                channel = "pending"
                await self._persist_pending(user_id, {"type": "sync"})

            # Если доставить не удалось ни WS, ни FCM — в TPushPending.
            if channel is None:
                await self._persist_pending(user_id, {"type": "sync"})
                channel = "pending"

        status = "delivered" if channel in ("ws", "fcm") else "deferred"
        await self._safe_send_result(
            handle,
            {
                "status": status,
                "via": channel,
                "user_id": user_id,
                "topic": topic,
                "type": msg_type,
            },
        )

        # mark_sent только для реально доставленных каналов.
        if channel in ("ws", "fcm"):
            try:
                await asyncio.to_thread(
                    TeamdroidServiceBrokerRepository.mark_sent,
                    user_id,
                    topic or "",
                    msg_type or "",
                    channel,
                )
            except Exception as exc:  # noqa: BLE001
                app_logger.error(
                    "sb_listener: mark_sent failed user=%s: %r",
                    user_id,
                    exc,
                    exc_info=True,
                )

    @staticmethod
    async def _deliver(user_id: str, payload: dict) -> str | None:
        """Доставить пуш: WS приоритет, FCM fallback.

        Возвращает "ws" | "fcm" | None (не удалось).
        """
        # 1) WS — через публичный is_online(), без доступа к _connections.
        if push_notification_service.is_online(user_id):
            ok = await push_notification_service.dispatch_ws_raw(user_id, payload)
            if ok:
                return "ws"

        # 2) FCM
        fids = sorted(push_notification_service.get_fcms_for_user(user_id))
        if fids and getattr(settings, "FCM_ENABLED", False):
            ok = await push_notification_service.fcm.send(
                fids=fids,
                title="",
                body="",
                data={"type": "sync"},
                silent=True,
            )
            if ok:
                return "fcm"

        return None

    @staticmethod
    async def _persist_pending(user_id: str, payload: dict) -> None:
        """Положить pending-сигнал в TPushPending."""
        from ..db import db_manager

        try:
            async with db_manager.get_session() as session:
                await app_push_pending_repo.add(session, user_id, payload)
                await session.commit()
            app_logger.info(
                "sb_listener: pending persisted user=%s type=%s",
                user_id,
                payload.get("type"),
            )
        except Exception as exc:  # noqa: BLE001
            app_logger.error(
                "sb_listener: failed to persist pending user=%s: %r",
                user_id,
                exc,
                exc_info=True,
            )

    @staticmethod
    async def _safe_send_result(handle: Any, result: dict) -> None:
        try:
            await asyncio.to_thread(TeamdroidServiceBrokerRepository.send_result, handle, result)
        except Exception as exc:  # noqa: BLE001
            app_logger.error("sb_listener: send_result failed: %r", exc, exc_info=True)


teamdroid_listener_service = TeamdroidListenerService()
