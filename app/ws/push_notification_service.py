"""Менеджер WebSocket-соединений мобильных клиентов и рассылки push.

Хранит активные соединения по user_id, обеспечивает:
- регистрацию/удаление соединений (с привязкой к Firebase Installation ID — FID);
- отправку JSON-сообщений через WS;
- heartbeat (ping) для обнаружения мёртвых соединений;
- дедупликацию пушей и батчей с ограниченным по размеру LRU-кэшем;
- ограничение числа соединений на пользователя;
- маршрутизацию push по FID (fcm_id) — на случай, если Go-адаптер
  присылает адресата как FID, а не как usrXXX.

Совместим с Go-адаптером server/push/myrelay: принимает snake_case JSON
(user_id, event_id, ts, mime, aonly, want, given), а также fcm_id.

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

Возвращаемое значение dispatch():
  DeliveryStatus — статус доставки одного push. Используется
  relay-обработчиком (app/ws/relay_handler.py) для подсчёта статистики
  доставки батча.
"""

from __future__ import annotations

import asyncio
import json
import time
from collections import OrderedDict, defaultdict
from enum import StrEnum
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


class DeliveryStatus(StrEnum):
    """Результат попытки доставить один push конкретному получателю.

    Используется в relay_handler для подсчёта статистики батча.

    Attributes:
        DELIVERED: push доставлен хотя бы на один активный сокет.
        PARTIAL: push доставлен, но часть сокетов умерла при отправке.
        NO_CONNECTIONS: получатель офлайн (нет активных сокетов) или
            FID не удалось сопоставить с user_id.
        FAILED: все попытки отправки завершились ошибкой.
        SKIPPED_SILENT: push помечен silent=True, клиенту не показываем.
        SKIPPED_TYPE: тип push не подлежит показу (read-квитанции,
            неизвестные типы).
        DUPLICATE: push уже был обработан ранее (дедупликация).
    """

    DELIVERED = "delivered"
    PARTIAL = "partial"
    NO_CONNECTIONS = "no_connections"
    FAILED = "failed"
    SKIPPED_SILENT = "skipped_silent"
    SKIPPED_TYPE = "skipped_type"
    DUPLICATE = "duplicate"


class PushNotificationService:
    def __init__(self) -> None:
        self._connections: dict[str, set[WebSocket]] = defaultdict(set)
        # --- FID <-> user_id (CHANGED) ---
        # fcm_id -> user_id: используется, если push приходит на FID.
        self._fcm_to_user: dict[str, str] = {}
        # user_id -> fcm_id: обратная связь, чтобы при unregister почистить FID.
        # Один user может иметь несколько FID (несколько устройств) —
        # храним множество.
        self._user_to_fcms: dict[str, set[str]] = defaultdict(set)

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
            "pushes_no_connections": 0,
            "pushes_failed_send": 0,
            "batches_duplicate": 0,
            "batches_empty": 0,
            "pushes_fid_resolved": 0,
            "pushes_fid_unresolved": 0,
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
            self._fcm_to_user.clear()
            self._user_to_fcms.clear()

        close_tasks = [asyncio.wait_for(ws.close(code=1001, reason="server shutdown"), timeout=2.0) for ws in conns]
        if close_tasks:
            await asyncio.gather(*close_tasks, return_exceptions=True)

        api_logger.info("push_service: stopped")

    # ---------- регистрация / удаление ----------

    async def register(
        self,
        user_id: str,
        ws: WebSocket,
        fcm_id: str | None = None,
        *,
        fcm_id_kw: str | None = None,
    ) -> None:
        """Регистрирует WS-соединение пользователя.

        Args:
            user_id: Tinode user ID (``usrXXX``).
            ws: WebSocket-соединение.
            fcm_id: Firebase Installation ID (FID) клиента, если известен.
                Может быть передан как позиционно, так и по имени.
            fcm_id_kw: алиас для совместимости со старыми вызовами
                ``register(..., fcm_id=...)``; склеивается с ``fcm_id``.
        """
        if not user_id or not user_id.startswith("usr"):
            raise ValueError(f"Invalid user_id: {user_id!r}")

        # Поддержка обоих вариантов передачи FID.
        effective_fcm = fcm_id or fcm_id_kw

        async with self._lock:
            user_conns = self._connections[user_id]
            if ws in user_conns:
                # Соединение уже зарегистрировано — обновим FID, если он пришёл.
                if effective_fcm:
                    self._fcm_to_user[effective_fcm] = user_id
                    self._user_to_fcms[user_id].add(effective_fcm)
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

            if effective_fcm:
                self._fcm_to_user[effective_fcm] = user_id
                self._user_to_fcms[user_id].add(effective_fcm)

        api_logger.debug(
            "push_service: registered user=%s fcm=%s total=%d",
            user_id,
            (effective_fcm or "-")[-6:],
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
                # Соединений у пользователя не осталось — чистим FID-связи.
                fcms = self._user_to_fcms.pop(user_id, set())
                for fcm in fcms:
                    self._fcm_to_user.pop(fcm, None)
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

    # ---------- FID ----------

    def resolve_fcm_id(self, fcm_id: str | None) -> str | None:
        """Возвращает user_id по FID, если устройство онлайн."""
        if not fcm_id:
            return None
        return self._fcm_to_user.get(fcm_id)

    def get_fcms_for_user(self, user_id: str) -> set[str]:
        """Возвращает множество FID, привязанных к пользователю."""
        return set(self._user_to_fcms.get(user_id, ()))

    def get_primary_fid(self, user_id: str) -> str | None:
        """Возвращает один FID пользователя (для token_finish при disconnect).

        Используется при разъединении WS-соединения, чтобы вызвать
        ``ext.PA_mbl_TokenFinish_Exec``. ВАЖНО: вызывать ДО
        ``unregister()`` — иначе FID уже будет удалён из словаря.

        Args:
            user_id: Tinode user ID (``usrXXX``).

        Returns:
            Один из FID пользователя или ``None``, если FID неизвестен.
        """
        fcms = self._user_to_fcms.get(user_id)
        if fcms:
            return next(iter(fcms))
        return None

    # ---------- доставка ----------

    async def dispatch(self, push: RelayPush) -> DeliveryStatus:
        """Доставить один push всем активным WS-соединениям получателя.

        Returns:
            DeliveryStatus — статус доставки. Используется relay-обработчиком
            для подсчёта статистики батча.
        """
        self._stats["pushes_received"] += 1

        if self._is_duplicate_push(push):
            api_logger.info(
                "push_service: duplicate user=%s type=%s seq=%s",
                push.user_id,
                push.type,
                push.seq,
            )
            return DeliveryStatus.DUPLICATE

        payload = self._to_ws_message(push)
        if not payload:
            # Определяем причину пропуска для точной статистики/логов.
            if push.silent:
                self._stats["pushes_skipped_silent"] += 1
                reason = "silent"
                status = DeliveryStatus.SKIPPED_SILENT
            else:
                reason = "read-receipt" if push.type == "read" else "unknown-type"
                status = DeliveryStatus.SKIPPED_TYPE

            api_logger.info(
                "push_service: skipped user=%s type=%s seq=%s reason=%s",
                push.user_id,
                push.type,
                push.seq,
                reason,
            )
            return status

        # --- Разрешение адресата (CHANGED): ---
        # Если push.user_id — это FID (начинается не с "usr", а, например,
        # с короткого Firebase Installation ID), пробуем найти user_id
        # по _fcm_to_user. Это позволяет Go-адаптеру шлать push прямо на
        # FID устройства, не зная Tinode user_id.
        target_user = push.user_id
        if not target_user.startswith("usr"):
            resolved = self.resolve_fcm_id(target_user)
            if resolved is None:
                self._stats["pushes_fid_unresolved"] += 1
                api_logger.info(
                    "push_service: fid unresolved fid=%s type=%s seq=%s",
                    target_user,
                    push.type,
                    push.seq,
                )
                return DeliveryStatus.NO_CONNECTIONS
            target_user = resolved
            self._stats["pushes_fid_resolved"] += 1

        async with self._lock:
            targets = list(self._connections.get(target_user, ()))
            online_users = len(self._connections)

        if not targets:
            self._stats["pushes_no_connections"] += 1
            api_logger.info(
                "push_service: dropped user=%s type=%s seq=%s reason=offline online_users=%d",
                target_user,
                push.type,
                push.seq,
                online_users,
            )
            return DeliveryStatus.NO_CONNECTIONS

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
                target_user,
                push.type,
                push.seq,
                len(dead),
                len(targets),
                errors,
            )
            async with self._lock:
                user_conns = self._connections.get(target_user)
                if user_conns:
                    for ws in dead:
                        user_conns.discard(ws)
                    if not user_conns:
                        del self._connections[target_user]
                        fcms = self._user_to_fcms.pop(target_user, set())
                        for fcm in fcms:
                            self._fcm_to_user.pop(fcm, None)

        ok_count = len(targets) - len(dead)

        if ok_count > 0:
            self._stats["pushes_dispatched"] += 1
            api_logger.info(
                "push_service: delivered user=%s type=%s seq=%s sockets=%d/%d",
                target_user,
                push.type,
                push.seq,
                ok_count,
                len(targets),
            )
            if dead:
                return DeliveryStatus.PARTIAL
            return DeliveryStatus.DELIVERED

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
        if push.silent:
            return {}

        # --- Сообщение ---
        if push.type == "msg":
            if push.webrtc:
                return {
                    "type": "call",
                    "topic": push.topic,
                    "title": "Call",
                    "body": push.webrtc,
                    "seq": push.seq or 0,
                    "aonly": bool(push.aonly),
                }

            return {
                "type": "message",
                "topic": push.topic,
                "title": "New message",
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
            total_fcms = len(self._fcm_to_user)
            per_user_fcms = {uid: sorted(s) for uid, s in self._user_to_fcms.items()} if include_per_user else None

        result: dict[str, Any] = {
            "running": self._running,
            "started_at": self._started_at,
            "total_users": total_users,
            "total_connections": total_conns,
            "total_fcm_ids": total_fcms,
            "seen_pushes_cache_size": len(self._seen_pushes),
            "seen_events_cache_size": len(self._seen_events),
            "stats": self._stats,
        }
        if per_user is not None:
            result["per_user"] = per_user
        if per_user_fcms is not None:
            result["per_user_fcms"] = per_user_fcms
        return result


push_notification_service = PushNotificationService()

__all__ = [
    "DeliveryStatus",
    "PushNotificationService",
    "push_notification_service",
]
