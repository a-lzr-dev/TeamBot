"""Менеджер WebSocket-соединений мобильных клиентов и рассылки push.

Хранит активные соединения по user_id, обеспечивает:
- регистрацию/удаление соединений;
- отправку JSON-сообщений через WS;
- heartbeat (ping) для обнаружения мёртвых соединений;
- дедупликацию пушей и батчей с ограниченным по размеру LRU-кэшем;
- ограничение числа соединений на пользователя.

Совместим с Go-адаптером server/push/myrelay: принимает snake_case JSON
(user_id, event_id, ts, mime, aonly, want, given).

Формат сообщений, отправляемых мобильному клиенту (NotificationsWsService.java):

  // Новое сообщение
  {"type": "message", "topic": "usrXXX", "title": "New message",
   "body": "Добрый день", "seq": 140}

  // Новая подписка / новый чат
  {"type": "subscription", "topic": "grpYYY", "title": "New chat",
   "body": "usrZZZ", "seq": 0}

  // WebRTC-событие
  {"type": "call", "topic": "usrXXX", "title": "Call",
   "body": "started", "seq": 140, "aonly": false}
"""

from __future__ import annotations

import asyncio
import json
import time
from collections import OrderedDict, defaultdict
from enum import Enum
from typing import Any

from fastapi import WebSocket

from ..config import settings
from ..logger import api_logger
from .models import RelayPush

# Ограничения кэшей дедупликации, чтобы память не росла бесконечно
# при DDoS/баге клиента.
_SEEN_PUSHES_MAX = 100_000
_SEEN_EVENTS_MAX = 10_000
_SEEN_TTL_SECONDS = 300


class DeliveryStatus(str, Enum):
    """Результат доставки одного пуша через WS.

    str-подмешивание позволяет удобно сериализовать статус в JSON
    (например, для диагностического ответа на /internal/push).
    """

    DELIVERED = "delivered"  # доставлено хотя бы в один WS-сокет
    PARTIAL = "partial"  # доставлено частично (часть сокетов упала)
    NO_CONNECTIONS = "no_connections"  # нет активных WS-соединений (offline)
    SKIPPED_SILENT = "skipped_silent"  # silent=true, показывать не надо
    SKIPPED_TYPE = "skipped_type"  # тип read/recv или неизвестный — не показываем
    DUPLICATE = "duplicate"  # уже был обработан (дедуп)
    FAILED = "failed"  # все send_text() упали


class PushNotificationService:
    def __init__(self) -> None:
        self._connections: dict[str, set[WebSocket]] = defaultdict(set)
        self._lock = asyncio.Lock()
        # OrderedDict обеспечивает O(1) popitem(last=False) для LRU-очистки.
        self._seen_pushes: OrderedDict[tuple, float] = OrderedDict()
        self._seen_events: OrderedDict[str, float] = OrderedDict()
        self._heartbeat_task: asyncio.Task | None = None
        self._running = False
        self._started_at: float | None = None
        self._stats = {
            "pushes_received": 0,
            "pushes_dispatched": 0,
            "pushes_duplicate": 0,
            "pushes_skipped_silent": 0,
            "pushes_skipped_type": 0,
            "pushes_no_connections": 0,
            "pushes_failed_send": 0,
            "pushes_undelivered": 0,
            "batches_duplicate": 0,
            "batches_empty": 0,
        }

    async def start(self) -> None:
        if self._running:
            return
        self._running = True
        self._started_at = time.time()
        if settings.WS_NOTIFY_HEARTBEAT_INTERVAL > 0:
            self._heartbeat_task = asyncio.create_task(self._heartbeat_loop())
        api_logger.info("push_service: started")

    async def stop(self) -> None:
        self._running = False
        if self._heartbeat_task:
            self._heartbeat_task.cancel()
            try:
                await self._heartbeat_task
            except asyncio.CancelledError:
                pass
            self._heartbeat_task = None

        async with self._lock:
            conns = [ws for s in self._connections.values() for ws in s]
            self._connections.clear()

        close_tasks = [asyncio.wait_for(ws.close(code=1001, reason="server shutdown"), timeout=2.0) for ws in conns]
        if close_tasks:
            await asyncio.gather(*close_tasks, return_exceptions=True)

        api_logger.info("push_service: stopped")

    async def register(self, user_id: str, ws: WebSocket) -> None:
        if not user_id or not user_id.startswith("usr"):
            raise ValueError(f"Invalid user_id: {user_id!r}")
        async with self._lock:
            user_conns = self._connections[user_id]
            if ws in user_conns:
                return
            if len(user_conns) >= settings.WS_NOTIFY_MAX_CONNECTIONS_PER_USER:
                oldest = next(iter(user_conns))
                user_conns.discard(oldest)
                try:
                    await asyncio.wait_for(
                        oldest.close(code=1013, reason="too many connections"),
                        timeout=2.0,
                    )
                except Exception:  # noqa: BLE001
                    pass
            user_conns.add(ws)
        api_logger.debug(
            "push_service: registered user=%s total=%d",
            user_id,
            len(self._connections[user_id]),
        )

    async def unregister(self, user_id: str, ws: WebSocket) -> None:
        async with self._lock:
            user_conns = self._connections.get(user_id)
            if user_conns is None:
                return
            user_conns.discard(ws)
            if not user_conns:
                del self._connections[user_id]
        api_logger.debug("push_service: unregistered user=%s", user_id)

    # ---------- дедупликация ----------

    @staticmethod
    def _prune(od: OrderedDict, max_size: int, now: float) -> None:
        """Удаляет устаревшие и лишние записи из OrderedDict (LRU-очистка)."""
        while od:
            key, ts = next(iter(od.items()))
            if now - ts <= _SEEN_TTL_SECONDS:
                break
            od.popitem(last=False)
        while len(od) > max_size:
            od.popitem(last=False)

    def is_duplicate_batch(self, event_id: str) -> bool:
        """Дедупликация батча по event_id. Публичный метод.

        Возвращает True, если батч с таким event_id уже обрабатывался.
        Пустой event_id не дедуплицируется (Go всегда шлёт непустой).
        """
        if not event_id:
            return False

        now = time.time()
        self._prune(self._seen_events, _SEEN_EVENTS_MAX, now)

        if event_id in self._seen_events:
            self._seen_events.move_to_end(event_id)
            self._seen_events[event_id] = now
            self._stats["batches_duplicate"] += 1
            return True

        self._seen_events[event_id] = now
        return False

    def _is_duplicate_push(self, push: RelayPush) -> bool:
        """Проверяет, был ли этот push уже обработан."""
        now = time.time()
        self._prune(self._seen_pushes, _SEEN_PUSHES_MAX, now)

        if push.seq is not None:
            key: tuple = (push.user_id, push.topic, push.type, push.seq)
        else:
            key = (push.user_id, push.topic, push.type, push.ts)

        if key in self._seen_pushes:
            self._seen_pushes.move_to_end(key)
            self._seen_pushes[key] = now
            self._stats["pushes_duplicate"] += 1
            return True

        self._seen_pushes[key] = now
        return False

    # ---------- доставка ----------

    async def dispatch(self, push: RelayPush) -> DeliveryStatus:
        """Доставить один push всем активным WS-соединениям получателя.

        Возвращает DeliveryStatus — что реально произошло:
        - DELIVERED / PARTIAL — доставлено (все/часть сокетов);
        - NO_CONNECTIONS     — у получателя нет активных WS;
        - FAILED             — все send_text() упали;
        - DUPLICATE          — push уже обрабатывался;
        - SKIPPED_SILENT     — silent=true, показывать не надо;
        - SKIPPED_TYPE       — тип read/recv/неизвестный, не показываем.
        """
        self._stats["pushes_received"] += 1

        # 1. Дубликат.
        if self._is_duplicate_push(push):
            self._stats["pushes_duplicate"] += 1
            api_logger.info(
                "push_service: duplicate user=%s type=%s seq=%s",
                push.user_id,
                push.type,
                push.seq,
            )
            return DeliveryStatus.DUPLICATE

        # 2. Не подлежит показу (silent / read-receipt / неизвестный тип).
        payload = self._to_ws_message(push)
        if not payload:
            if push.silent:
                self._stats["pushes_skipped_silent"] += 1
                api_logger.info(
                    "push_service: skipped user=%s type=%s topic=%s seq=%s "
                    "from=%s reason=silent unread=%r delivered=%r webrtc=%r",
                    push.user_id,
                    push.type,
                    push.topic,
                    push.seq,
                    push.from_id,
                    push.unread,
                    push.delivered,
                    push.webrtc,
                )
                return DeliveryStatus.SKIPPED_SILENT

            self._stats["pushes_skipped_type"] += 1
            api_logger.info(
                "push_service: skipped user=%s type=%s seq=%s reason=type_not_showable",
                push.user_id,
                push.type,
                push.seq,
            )
            return DeliveryStatus.SKIPPED_TYPE

        # 3. Получатели.
        async with self._lock:
            targets = list(self._connections.get(push.user_id, ()))
            online_users = len(self._connections)

        if not targets:
            self._stats["pushes_no_connections"] += 1
            self._stats["pushes_undelivered"] += 1
            api_logger.info(
                "push_service: dropped user=%s type=%s seq=%s reason=offline online_users=%d",
                push.user_id,
                push.type,
                push.seq,
                online_users,
            )
            return DeliveryStatus.NO_CONNECTIONS

        # 4. Рассылка.
        raw = json.dumps(payload, ensure_ascii=False)
        send_tasks = [
            asyncio.wait_for(
                ws.send_text(raw),
                timeout=settings.WS_NOTIFY_SEND_TIMEOUT,
            )
            for ws in targets
        ]
        results = await asyncio.gather(*send_tasks, return_exceptions=True)

        dead: list[WebSocket] = []
        for i, result in enumerate(results):
            if isinstance(result, Exception):
                self._stats["pushes_failed_send"] += 1
                dead.append(targets[i])

        if dead:
            errors = [str(r) for r in results if isinstance(r, Exception)]
            api_logger.warning(
                "push_service: partial delivery user=%s type=%s seq=%s failed=%d/%d errors=%s",
                push.user_id,
                push.type,
                push.seq,
                len(dead),
                len(targets),
                errors,
            )
            async with self._lock:
                user_conns = self._connections.get(push.user_id)
                if user_conns:
                    for ws in dead:
                        user_conns.discard(ws)
                    if not user_conns:
                        del self._connections[push.user_id]

        ok_count = len(targets) - len(dead)
        if ok_count > 0:
            api_logger.info(
                "push_service: delivered user=%s type=%s seq=%s sockets=%d/%d",
                push.user_id,
                push.type,
                push.seq,
                ok_count,
                len(targets),
            )
            self._stats["pushes_dispatched"] += 1
            return DeliveryStatus.PARTIAL if dead else DeliveryStatus.DELIVERED

        # ok_count == 0: все сокеты умерли.
        self._stats["pushes_undelivered"] += 1
        api_logger.warning(
            "push_service: failed user=%s type=%s seq=%s reason=all_sockets_dead",
            push.user_id,
            push.type,
            push.seq,
        )
        return DeliveryStatus.FAILED

    @staticmethod
    def _extract_text(content: Any) -> str:
        """Извлекает plain-текст из Drafty-content.

        Drafty обычно приходит как dict {"txt": "...", "fmt": [...], "ent": [...]}.
        Реже — как готовая строка. Всё остальное считаем «нет текста».
        """
        if not content:
            return ""
        if isinstance(content, str):
            return content
        if isinstance(content, dict):
            txt = content.get("txt")
            if isinstance(txt, str):
                return txt
        return ""

    @staticmethod
    def _to_ws_message(push: RelayPush) -> dict[str, Any]:
        """Формат сообщения для мобильного клиента (NotificationsWsService.java).

        Возвращает пустой dict, если push не подлежит показу:
        - silent=true (пользователь уже видел сообщение интерактивно);
        - тип read/recv-квитанций;
        - неизвестный тип.

        Контракт (см. app/src/main/java/by/aps/teamdroid/services/NotificationsWsService.java):
            {"type": "...", "topic": "...", "title": "...", "body": "...", "seq": N}
        """
        # Silent-пуши — не показываем. Логирование — в dispatch().
        if push.silent:
            return {}

        # --- Сообщение ---
        if push.type == "msg":
            # WebRTC-событие: started / accepted / hang-up / ...
            if push.webrtc:
                return {
                    "type": "call",
                    "topic": push.topic,
                    "title": "Call",
                    "body": push.webrtc,
                    "seq": push.seq or 0,
                    "aonly": bool(push.aonly),
                }

            # Обычное сообщение.
            return {
                "type": "message",
                "topic": push.topic,
                # TODO: имя отправителя (push.from_id) — подтянуть из БД
                # или расширить Go-адаптер полем sender_name.
                "title": push.from_id or "New message",
                "mime": push.mime,
                "from": push.from_id,
                "body": PushNotificationService._extract_text(push.content) or "New message",
                "seq": push.seq or 0,
            }

        # --- Новая подписка / новый чат ---
        if push.type == "sub":
            return {
                "type": "subscription",
                "topic": push.topic,
                "title": "New chat",
                "body": push.from_id or "",
                "seq": 0,
            }

        # read/recv-квитанции и всё прочее — не пробрасываем.
        return {}

    async def _heartbeat_loop(self) -> None:
        interval = settings.WS_NOTIFY_HEARTBEAT_INTERVAL
        while self._running:
            await asyncio.sleep(interval)
            async with self._lock:
                snapshot = [(uid, list(ws_set)) for uid, ws_set in self._connections.items()]
            for uid, ws_list in snapshot:
                for ws in ws_list:
                    try:
                        await asyncio.wait_for(ws.send_json({"type": "ping"}), timeout=2.0)
                    except Exception:  # noqa: BLE001
                        await self.unregister(uid, ws)

    async def get_status(self, include_per_user: bool = False) -> dict[str, Any]:
        async with self._lock:
            total_users = len(self._connections)
            total_conns = sum(len(s) for s in self._connections.values())
            per_user = {uid: len(s) for uid, s in self._connections.items()} if include_per_user else None
        result: dict[str, Any] = {
            "running": self._running,
            "started_at": self._started_at,
            "total_users": total_users,
            "total_connections": total_conns,
            "seen_pushes_cache_size": len(self._seen_pushes),
            "seen_events_cache_size": len(self._seen_events),
            "stats": self._stats,
        }
        if per_user is not None:
            result["per_user"] = per_user
        return result


push_notification_service = PushNotificationService()
