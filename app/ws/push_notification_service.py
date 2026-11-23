"""Менеджер WebSocket-соединений мобильных клиентов и рассылки push.

Хранит активные соединения по user_id, обеспечивает:
- регистрацию/удаление соединений (с привязкой к Firebase Installation ID — FID);
- отправку JSON-сообщений через WS;
- heartbeat (ping) для обнаружения мёртвых соединений;
- дедупликацию пушей и батчей с ограниченным по размеру LRU-кэшем;
- ограничение числа соединений на пользователя;
- маршрутизацию push по FID (fcm_id) — на случай, если Go-адаптер
  присылает адресата как FID, а не как usrXXX;
- FCM-доставку (Firebase Cloud Messaging) в дополнение к WS.

Режим FCM задаётся `settings.FCM_SEND_MODE`:
  - "always" — всегда (WS + FCM одновременно);
  - "fallback" — только если WS не доставил (для msg) или всегда (для sub);
  - "never" — только WS, FCM не отправляется.

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

  // NEW (v11): сигнал "сходи в sync-load"
  {"type": "sync"}

Возвращаемое значение dispatch():
  DeliveryStatus — статус доставки одного push. Используется
  relay-обработчиком (app/ws/relay_handler.py) для подсчёта статистики
  доставки батча.

CHANGED (v11):
  * добавлен публичный is_online(user_id) — используется
    TeamdroidListenerService вместо приватного _connections;
  * добавлен публичный dispatch_ws_raw(user_id, payload) — отправка
    произвольного JSON-payload по всем сокетам пользователя
    (для {"type":"sync"} из TeamdroidListenerService).
"""

from __future__ import annotations

import asyncio
import json
import time
from collections import OrderedDict, defaultdict
from collections.abc import Callable
from enum import StrEnum
from typing import Any

from fastapi import WebSocket
from starlette.websockets import WebSocketDisconnect

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


# ============================================================
# FCM-клиент (firebase-admin)
# ============================================================


class _FcmClient:
    """Ленивая инициализация firebase-admin и отправка FCM-сообщений.

    Инициализация выполняется один раз при первом использовании.
    Если FCM отключён (`FCM_ENABLED=false`) или не задан путь к
    service account JSON (`FCM_CREDENTIALS_PATH`), клиент считается
    недоступным, а `send()` возвращает False.
    """

    def __init__(self) -> None:
        self._initialized: bool = False
        self._available: bool = False
        self._messaging: Any = None
        self._lock = asyncio.Lock()

    @property
    def available(self) -> bool:
        return self._available

    async def ensure_initialized(self) -> None:
        if self._initialized:
            return
        async with self._lock:
            if self._initialized:
                return

            if not getattr(settings, "FCM_ENABLED", False):
                api_logger.info("fcm: disabled (FCM_ENABLED=false)")
                self._initialized = True
                return

            cred_path = (getattr(settings, "FCM_CREDENTIALS_PATH", "") or "").strip()
            if not cred_path:
                api_logger.warning("fcm: FCM_CREDENTIALS_PATH is empty, FCM will be unavailable")
                self._initialized = True
                return

            try:
                import firebase_admin
                from firebase_admin import credentials, messaging

                try:
                    firebase_admin.get_app()
                    api_logger.info("fcm: firebase-admin already initialized")
                except ValueError:
                    cred = credentials.Certificate(cred_path)
                    firebase_admin.initialize_app(cred)
                    api_logger.info("fcm: firebase-admin initialized from %s", cred_path)

                self._messaging = messaging
                self._available = True
            except Exception as exc:  # noqa: BLE001
                api_logger.error("fcm: failed to initialize firebase-admin: %r", exc, exc_info=True)
                self._available = False
                # ВАЖНО: не ставим _initialized=True — даём шанс повторить
                return

            self._initialized = True

    async def send(
        self,
        fids: list[str],
        *,
        title: str,
        body: str,
        data: dict[str, str] | None = None,
        silent: bool = False,
    ) -> bool:
        """Отправить FCM-сообщение на список FID.

        Возвращает True, если хотя бы одно сообщение было отправлено
        успешно (или принято FCM), False — при полной неудаче/недоступности.
        """
        if not fids:
            return False

        await self.ensure_initialized()
        if not self._available or self._messaging is None:
            return False

        messaging = self._messaging

        # Данные всегда передаём как строки (требование FCM).
        data_str: dict[str, str] = {k: str(v) for k, v in (data or {}).items()}

        # title/body кладём в data — клиент сам построит уведомление через NotificationHelper.
        if title:
            data_str.setdefault("title", title)
        if body:
            data_str.setdefault("body", body)

        try:
            # ВСЕГДА data-only, без notification-блока.
            # Иначе FCM SDK сам покажет уведомление и не вызовет
            # FBaseMessagingService.onMessageReceived — note recv не уйдёт.
            message = messaging.MulticastMessage(
                tokens=fids,
                data=data_str,
                android=messaging.AndroidConfig(priority="high"),
            )

            # Прямая передача messaging.send_each_for_multicast в
            # asyncio.to_thread ломает вывод ParamSpec в PyCharm:
            # firebase_admin не поставляет py.typed, поэтому
            # `Callable[P, T]` из to_thread остаётся неразрешённым,
            # и `message` подсвечивается как "Unexpected argument".
            # Оборачиваем вызов в локальную функцию с явной сигнатурой
            # Callable[[Any], Any] — PyCharm выведет её тип корректно.
            sender: Callable[[Any], Any] = messaging.send_each_for_multicast
            response = await asyncio.to_thread(sender, message)
            success = sum(1 for r in response.responses if r.success)
            failure = len(response.responses) - success
            if success > 0:
                api_logger.info("fcm: sent %d/%d (failures=%d)", success, len(response.responses), failure)
                for i, r in enumerate(response.responses):
                    if not r.success and r.exception is not None:
                        api_logger.warning("fcm: token[%d] failed: %r", i, r.exception)
                return True
            api_logger.warning("fcm: all %d messages failed (silent=%s)", failure, silent)
            return False
        except Exception as exc:
            api_logger.error("fcm: send failed: %r", exc, exc_info=True)
            return False


# ============================================================
# Push Notification Service
# ============================================================


class PushNotificationService:
    def __init__(self) -> None:
        self._connections: dict[str, set[WebSocket]] = defaultdict(set)
        # fcm_id -> user_id: используется, если push приходит на FID.
        self._fcm_to_user: dict[str, str] = {}
        # user_id -> fcm_id: обратная связь, чтобы при unregister почистить FID.
        self._user_to_fcms: dict[str, set[str]] = defaultdict(set)

        self._lock = asyncio.Lock()
        # OrderedDict обеспечивает O(1) popitem(last=False) для LRU-очистки.
        self._seen_pushes: OrderedDict[tuple, float] = OrderedDict()
        self._seen_events: OrderedDict[str, float] = OrderedDict()
        self._heartbeat_task: asyncio.Task | None = None
        self._running = False
        self._started_at: float | None = None
        self.fcm = _FcmClient()
        self.stats = {
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
            "fcm_sent": 0,
            "fcm_failed": 0,
            "fcm_skipped": 0,
        }

    # ---------- lifecycle ----------

    async def start(self) -> None:
        if self._running:
            return
        self._running = True
        self._started_at = time.time()

        # Восстановить FID из SQL Server
        if getattr(settings, "FCM_LOAD_FIDS_ON_START", True) and getattr(settings, "FCM_ENABLED", False):
            await self._restore_fids_from_sql()

        # Прогреваем FCM-клиент на старте (инициализация firebase-admin).
        if getattr(settings, "FCM_ENABLED", False):
            try:
                await self.fcm.ensure_initialized()
            except Exception as exc:  # noqa: BLE001
                api_logger.error("fcm: warm-up failed: %r", exc)

        if settings.WS_NOTIFY_HEARTBEAT_INTERVAL > 0:
            self._heartbeat_task = asyncio.create_task(self._heartbeat_loop())

        api_logger.info(
            "push_service: started (fcm_enabled=%s, fcm_mode=%s, fcm_available=%s, fids=%d, users=%d)",
            getattr(settings, "FCM_ENABLED", False),
            getattr(settings, "FCM_SEND_MODE", "fallback"),
            self.fcm.available,
            len(self._fcm_to_user),
            len(self._user_to_fcms),
        )

    async def _restore_fids_from_sql(self) -> None:
        """Загрузить активные (usi, dvc) из ext.PA_mbl_TokenDevices_Load.

        Дополнительно: для каждого восстановленного usi проверяем, что
        в TApps есть запись с FUserID = usi (или создаём/обновляем),
        чтобы FCM-доставка logs_request работала.
        """
        try:
            from ..db.repositories import TeamdroidProcedureRepository

            loaded = await asyncio.wait_for(
                asyncio.to_thread(TeamdroidProcedureRepository.load_token_devices),
                timeout=15.0,
            )
        except TimeoutError:
            api_logger.warning("push_service: load_token_devices timeout — starting with empty FID registry")
            return
        except Exception as exc:  # noqa: BLE001
            api_logger.error("push_service: load_token_devices failed: %r", exc, exc_info=True)
            return

        if not loaded:
            api_logger.info("push_service: no FIDs restored from SQL (empty result)")
            return

        async with self._lock:
            for user_id, fids in loaded.items():
                self._user_to_fcms[user_id].update(fids)
                for fid in fids:
                    self._fcm_to_user[fid] = user_id

        # Синхронизация TApps.FUserID с usi (только если FUserID пуст или числовой).
        try:
            from ..db import db_manager
            from ..db.repositories import AppRepository

            async with db_manager.get_session() as session:
                for user_id, fids in loaded.items():
                    for fid in fids:
                        app = await AppRepository.get_app_by_fid(session, fid)
                        if app is not None and app.FUserID != user_id:
                            api_logger.warning(
                                "push_service: TApps.FUserID mismatch fid=%s db=%r sql=%r — updating",
                                fid[-8:],
                                app.FUserID,
                                user_id,
                            )
                            app.FUserID = user_id
                await session.commit()
        except Exception as exc:  # noqa: BLE001
            api_logger.error("push_service: TApps sync failed: %r", exc, exc_info=True)

        api_logger.info(
            "push_service: restored %d FIDs for %d users from SQL Server",
            sum(len(s) for s in loaded.values()),
            len(loaded),
        )

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

    # ---------- FID registry ----------

    async def update_fid(self, user_id: str, fid: str | None) -> None:
        """Зарегистрировать/обновить FID пользователя.

        Вызывается из `POST /internal/client/register`.

        Поддерживает НЕСКОЛЬКО FID на пользователя (телефон + планшет).
        Ограничение — APP_CLIENT_MAX_FIDS_PER_USER (default 10).
        При превышении вытесняется самый старый FID (FIFO).

        Если `fid=None` — удалить ВСЕ FID пользователя (logout).
        """
        if not user_id or not user_id.startswith("usr"):
            raise ValueError(f"Invalid user_id: {user_id!r}")

        async with self._lock:
            if fid is None:
                # Удалить все FID пользователя.
                old = self._user_to_fcms.pop(user_id, set())
                for f in old:
                    self._fcm_to_user.pop(f, None)
                api_logger.info("push_service: cleared FIDs for user=%s", user_id)
                return

            fid = fid.strip()
            if not fid:
                raise ValueError("empty fid")

            max_fids = int(getattr(settings, "APP_CLIENT_MAX_FIDS_PER_USER", 10) or 10)
            fcms = self._user_to_fcms.setdefault(user_id, set())

            if fid not in fcms:
                if len(fcms) >= max_fids:
                    # Вытесняем самый старый FID (FIFO).
                    evicted = next(iter(fcms))
                    fcms.discard(evicted)
                    self._fcm_to_user.pop(evicted, None)
                    api_logger.warning(
                        "push_service: evicted FID user=%s fid=...%s (max=%d)",
                        user_id,
                        evicted[-8:] if len(evicted) >= 8 else "***",
                        max_fids,
                    )
                fcms.add(fid)

            self._fcm_to_user[fid] = user_id

        api_logger.info(
            "push_service: fid registered user=%s fid=...%s total_fids=%d",
            user_id,
            fid[-8:] if len(fid) >= 8 else "***",
            len(fcms),
        )

    async def remove_fid(self, user_id: str, fid: str) -> None:
        """Удалить конкретный FID пользователя.

        Вызывается из `DELETE /api/v1/client/register` и из
        `relay_handler.unregister_fid`.
        """
        if not user_id or not user_id.startswith("usr"):
            return

        async with self._lock:
            fcms = self._user_to_fcms.get(user_id)
            if not fcms:
                return
            fcms.discard(fid)
            self._fcm_to_user.pop(fid, None)
            if not fcms:
                self._user_to_fcms.pop(user_id, None)

        api_logger.info(
            "push_service: fid removed user=%s fid=...%s",
            user_id,
            fid[-8:] if len(fid) >= 8 else "***",
        )

    # ---------- registration ----------

    async def register(
        self,
        user_id: str,
        ws: WebSocket,
        fcm_id: str | None = None,
        *,
        fcm_id_kw: str | None = None,
    ) -> None:
        """Регистрирует WS-соединение пользователя."""
        if not user_id or not user_id.startswith("usr"):
            raise ValueError(f"Invalid user_id: {user_id!r}")

        effective_fcm = fcm_id or fcm_id_kw

        async with self._lock:
            user_conns = self._connections[user_id]
            if ws in user_conns:
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
                except (TimeoutError, RuntimeError, ConnectionError) as exc:
                    api_logger.warning(
                        "push_service: failed to close oldest ws user=%s: %r",
                        user_id,
                        exc,
                    )

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

    async def unregister(
        self,
        user_id: str,
        ws: WebSocket,
        *,
        keep_fid: bool = True,
    ) -> None:
        """Снять WS-соединение пользователя.

        Args:
            user_id: Tinode user ID.
            ws: сокет, который нужно снять.
            keep_fid: если True (по умолчанию) — FID пользователя
                остаётся в реестре ``_user_to_fcms``/``_fcm_to_user``,
                даже если это был последний сокет. Это нужно для того,
                чтобы FCM-доставка работала, когда приложение закрыто
                (WS нет, но устройство всё ещё "живое" для FCM).

                FID удаляется только при явном логауте — через
                ``remove_fid()`` (``DELETE /api/v1/client/register``).
                Если keep_fid=False — поведение как раньше (удалить FID
                при пустом списке сокетов).
        """
        async with self._lock:
            user_conns = self._connections.get(user_id)
            if user_conns is None:
                return
            user_conns.discard(ws)
            if not user_conns:
                del self._connections[user_id]
                if not keep_fid:
                    fcms = self._user_to_fcms.pop(user_id, set())
                    for fcm in fcms:
                        self._fcm_to_user.pop(fcm, None)
        api_logger.debug(
            "push_service: unregistered user=%s keep_fid=%s",
            user_id,
            keep_fid,
        )

    # ---------- dedup ----------

    @staticmethod
    def _prune(od: OrderedDict, max_size: int, now: float) -> None:
        while od:
            key, ts = next(iter(od.items()))
            if now - ts <= _SEEN_TTL_SECONDS:
                break
            od.popitem(last=False)
        while len(od) > max_size:
            od.popitem(last=False)

    def is_duplicate_batch(self, event_id: str) -> bool:
        if not event_id:
            return False

        now = time.time()
        self._prune(self._seen_events, _SEEN_EVENTS_MAX, now)

        if event_id in self._seen_events:
            self._seen_events.move_to_end(event_id)
            self._seen_events[event_id] = now
            self.stats["batches_duplicate"] += 1
            return True

        self._seen_events[event_id] = now
        return False

    def _is_duplicate_push(self, push: RelayPush) -> bool:
        now = time.time()
        self._prune(self._seen_pushes, _SEEN_PUSHES_MAX, now)

        if push.seq is not None:
            key: tuple = (push.user_id, push.topic, push.type, push.seq)
        else:
            key = (push.user_id, push.topic, push.type, push.ts)

        if key in self._seen_pushes:
            self._seen_pushes.move_to_end(key)
            self._seen_pushes[key] = now
            self.stats["pushes_duplicate"] += 1
            return True

        self._seen_pushes[key] = now
        return False

    # ---------- FID helpers ----------

    def resolve_fcm_id(self, fcm_id: str | None) -> str | None:
        if not fcm_id:
            return None
        return self._fcm_to_user.get(fcm_id)

    def get_fcms_for_user(self, user_id: str) -> set[str]:
        return set(self._user_to_fcms.get(user_id, ()))

    def get_primary_fid(self, user_id: str) -> str | None:
        fcms = self._user_to_fcms.get(user_id)
        if fcms:
            return next(iter(fcms))
        return None

    # ---------- NEW (v11): публичные helpers для listener ----------

    def is_online(self, user_id: str) -> bool:
        """True, если у пользователя есть хотя бы одно активное WS-соединение.

        Публичный аналог проверки ``user_id in self._connections``.
        Используется TeamdroidListenerService, чтобы не лезть
        в приватное поле.
        """
        return bool(self._connections.get(user_id))

    async def dispatch_ws_raw(self, user_id: str, payload: dict[str, Any]) -> bool:
        """Отправить произвольный JSON-payload по всем WS-сокетам пользователя.

        Используется TeamdroidListenerService для сигнала
        ``{"type":"sync"}``. Мёртвые сокеты удаляются из реестра.

        Args:
            user_id: Tinode user ID (usrXXX).
            payload: JSON-сериализуемый dict.

        Returns:
            True, если доставлено хотя бы на один сокет,
            False — если сокетов нет или все умерли при отправке.
        """
        if not payload:
            return False

        async with self._lock:
            targets = list(self._connections.get(user_id, ()))
            if not targets:
                return False

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
        ok_count = 0
        for i, result in enumerate(results):
            if isinstance(result, Exception):
                dead.append(targets[i])
            else:
                ok_count += 1

        if dead:
            async with self._lock:
                user_conns = self._connections.get(user_id)
                if user_conns:
                    for ws in dead:
                        user_conns.discard(ws)
                    if not user_conns:
                        del self._connections[user_id]

        if ok_count > 0:
            api_logger.info(
                "push_service: raw WS delivered user=%s type=%s sockets=%d/%d",
                user_id,
                payload.get("type"),
                ok_count,
                len(targets),
            )
            return True

        return False

    # ---------- WS message formatting ----------

    @staticmethod
    def _extract_text(content: Any) -> str:
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
        if push.silent:
            return {}

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

        if push.type == "sub":
            return {
                "type": "subscription",
                "topic": push.topic,
                "title": "New chat",
                "body": push.from_id or "",
                "seq": 0,
            }

        return {}

    # ---------- FCM building ----------

    @staticmethod
    def _to_fcm_payload(push: RelayPush) -> tuple[str, str, dict[str, str], bool] | None:
        """Построить FCM-сообщение из RelayPush.

        Возвращает (title, body, data, silent) или None, если сообщение
        не подлежит отправке (read/recv-квитанции, неизвестный тип).
        """
        if push.silent:
            # Silent-сообщение: только data, без нотификации.
            return (
                "",
                "",
                {
                    "type": push.type,
                    "what": push.type,
                    "topic": push.topic,
                    "seq": str(push.seq or 0),
                },
                True,
            )

        if push.type == "msg":
            if push.webrtc:
                return (
                    "Call",
                    push.webrtc,
                    {
                        "type": "call",
                        "what": "msg",
                        "topic": push.topic,
                        "seq": str(push.seq or 0),
                        "webrtc": push.webrtc,
                        "aonly": "1" if push.aonly else "0",
                    },
                    False,
                )

            text = PushNotificationService._extract_text(push.content) or "New message"
            return (
                "New message",
                text[:200],
                {
                    "type": "message",
                    "what": "msg",
                    "topic": push.topic,
                    "seq": str(push.seq or 0),
                },
                False,
            )

        if push.type == "sub":
            return (
                "New chat",
                push.from_id or "",
                {
                    "type": "subscription",
                    "what": "sub",
                    "topic": push.topic,
                    "seq": "0",
                },
                False,
            )

        return None

    # ---------- dispatch ----------

    async def dispatch(self, push: RelayPush) -> DeliveryStatus:
        """Доставить один push: WS (приоритет) + FCM (согласно режиму).

        Returns:
            DeliveryStatus — статус WS-доставки. Используется
            relay-обработчиком для подсчёта статистики батча.
        """
        self.stats["pushes_received"] += 1

        if self._is_duplicate_push(push):
            api_logger.info(
                "push_service: duplicate user=%s type=%s seq=%s",
                push.user_id,
                push.type,
                push.seq,
            )
            return DeliveryStatus.DUPLICATE

        payload = self._to_ws_message(push)
        ws_status = await self._dispatch_ws(push, payload)

        # FCM отправляем согласно режиму.
        await self._dispatch_fcm(push, ws_status)

        return ws_status

    async def _dispatch_ws(self, push: RelayPush, payload: dict[str, Any]) -> DeliveryStatus:
        """Отправить push по WS. Возвращает DeliveryStatus."""
        if not payload:
            if push.silent:
                self.stats["pushes_skipped_silent"] += 1
                api_logger.info(
                    "push_service: skipped WS user=%s type=%s seq=%s reason=silent",
                    push.user_id,
                    push.type,
                    push.seq,
                )
                return DeliveryStatus.SKIPPED_SILENT

            reason = "read-receipt" if push.type == "read" else "unknown-type"
            self.stats["pushes_skipped_silent"] += 1
            api_logger.info(
                "push_service: skipped WS user=%s type=%s seq=%s reason=%s",
                push.user_id,
                push.type,
                push.seq,
                reason,
            )
            return DeliveryStatus.SKIPPED_TYPE

        target_user = push.user_id
        if not target_user.startswith("usr"):
            resolved = self.resolve_fcm_id(target_user)
            if resolved is None:
                self.stats["pushes_fid_unresolved"] += 1
                api_logger.info(
                    "push_service: fid unresolved fid=%s type=%s seq=%s",
                    target_user,
                    push.type,
                    push.seq,
                )
                return DeliveryStatus.NO_CONNECTIONS
            target_user = resolved
            self.stats["pushes_fid_resolved"] += 1

        async with self._lock:
            targets = list(self._connections.get(target_user, ()))
            online_users = len(self._connections)

        if not targets:
            self.stats["pushes_no_connections"] += 1
            api_logger.info(
                "push_service: WS dropped user=%s type=%s seq=%s reason=offline online_users=%d",
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
                self.stats["pushes_failed_send"] += 1
                dead.append(targets[i])

        if dead:
            errors = [str(r) for r in results if isinstance(r, Exception)]
            api_logger.warning(
                "push_service: partial WS user=%s type=%s seq=%s failed=%d/%d errors=%s",
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
            self.stats["pushes_dispatched"] += 1
            api_logger.info(
                "push_service: WS delivered user=%s type=%s seq=%s sockets=%d/%d",
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

    async def _dispatch_fcm(self, push: RelayPush, ws_status: DeliveryStatus) -> None:
        """Отправить push через FCM согласно FCM_SEND_MODE.

        Логика:
          - "never": не отправлять.
          - "always": отправлять ВСЕГДА для msg/sub (WS + FCM одновременно),
                        КРОМЕ silent-сообщений, которые уже доставлены по WS
                        (это фоновая синхронизация данных, UI-уведомление не нужно).
          - "fallback": для type="sub" — всегда; для msg — только если WS
                        не доставил (NO_CONNECTIONS/FAILED/PARTIAL).
          - silent=True: только если WS не доставил.
          - type="read": не отправлять через FCM.
        """
        if not getattr(settings, "FCM_ENABLED", False):
            self.stats["fcm_skipped"] += 1
            return

        mode = (getattr(settings, "FCM_SEND_MODE", "fallback") or "fallback").lower()
        if mode == "never":
            self.stats["fcm_skipped"] += 1
            return

        # read-квитанции через FCM не шлём.
        if push.type == "read":
            self.stats["fcm_skipped"] += 1
            return

        # Определяем, надо ли отправлять FCM.
        if push.silent:
            # Silent: только если WS не доставил.
            should_send = ws_status == DeliveryStatus.NO_CONNECTIONS
        elif mode == "always":
            # ТЗ п.5: помимо WS-оповещения отправляется FCM FID.
            # Для msg и sub — всегда.
            should_send = True
        elif push.type == "sub":
            # Приглашения в чат — всегда (даже если WS доставил).
            should_send = True
        elif mode == "fallback":
            should_send = ws_status in (
                DeliveryStatus.NO_CONNECTIONS,
                DeliveryStatus.FAILED,
                DeliveryStatus.PARTIAL,
            )
        else:
            should_send = False

        if not should_send:
            self.stats["fcm_skipped"] += 1
            return

        # Определяем целевого пользователя (usrXXX).
        target_user = push.user_id
        if not target_user.startswith("usr"):
            resolved = self.resolve_fcm_id(target_user)
            if resolved is None:
                self.stats["fcm_failed"] += 1
                api_logger.debug(
                    "fcm: fid unresolved fid=%s type=%s seq=%s",
                    target_user,
                    push.type,
                    push.seq,
                )
                return
            target_user = resolved

        if push.fid:
            fids = [push.fid]
        else:
            fids = sorted(self.get_fcms_for_user(target_user))

        if not fids:
            self.stats["fcm_skipped"] += 1
            api_logger.info(
                "fcm: no FID for user=%s type=%s seq=%s",
                target_user,
                push.type,
                push.seq,
            )
            return

        payload = self._to_fcm_payload(push)
        if payload is None:
            self.stats["fcm_skipped"] += 1
            return

        title, body, data, silent = payload
        ok = await self.fcm.send(
            fids,
            title=title,
            body=body,
            data=data,
            silent=silent,
        )
        if ok:
            self.stats["fcm_sent"] += 1
            api_logger.info(
                "fcm: sent user=%s type=%s seq=%s fids=%d mode=%s ws_status=%s",
                target_user,
                push.type,
                push.seq,
                len(fids),
                mode,
                ws_status.value,
            )
        else:
            self.stats["fcm_failed"] += 1
            api_logger.warning(
                "fcm: failed user=%s type=%s seq=%s fids=%d mode=%s ws_status=%s",
                target_user,
                push.type,
                push.seq,
                len(fids),
                mode,
                ws_status.value,
            )

    async def notify_update(
        self,
        user_id: str,
        payload: dict[str, Any],
    ) -> bool:
        """Отправить клиенту уведомление «доступно обновление».

        WS — приоритет; если WS нет — FCM (data-only).

        Args:
            user_id: Tinode user ID (usrXXX).
            payload: {"type":"update","force":bool,"prm":{frc,ver,vcd,fph,fsz,fhs}}

        Returns:
            True, если доставлено хотя бы одним каналом.
        """
        if not user_id.startswith("usr"):
            return False

        raw = json.dumps(payload, ensure_ascii=False)
        delivered_ws = False

        async with self._lock:
            targets = list(self._connections.get(user_id, ()))

        if targets:
            send_tasks = [
                asyncio.wait_for(ws.send_text(raw), timeout=settings.WS_NOTIFY_SEND_TIMEOUT) for ws in targets
            ]
            results = await asyncio.gather(*send_tasks, return_exceptions=True)
            dead: list[WebSocket] = []
            ok_count = 0
            for i, r in enumerate(results):
                if isinstance(r, Exception):
                    dead.append(targets[i])
                else:
                    ok_count += 1
            if ok_count > 0:
                delivered_ws = True
            if dead:
                async with self._lock:
                    user_conns = self._connections.get(user_id)
                    if user_conns:
                        for ws in dead:
                            user_conns.discard(ws)
                        if not user_conns:
                            del self._connections[user_id]

        if delivered_ws:
            self.stats["pushes_dispatched"] += 1
            api_logger.info("push_service: update pushed via WS user=%s", user_id)
            return True

        fids = sorted(self.get_fcms_for_user(user_id))
        if not fids:
            api_logger.info("push_service: update not delivered — no WS, no FID user=%s", user_id)
            return False

        # data-only FCM (тип update, без notification-блока)
        data_str: dict[str, str] = {}
        if isinstance(payload.get("prm"), dict):
            for k, v in payload["prm"].items():
                data_str[k] = str(v)
        data_str["type"] = str(payload.get("type") or "update")
        data_str["force"] = "1" if payload.get("force") else "0"

        ok = await self.fcm.send(fids, title="", body="", data=data_str, silent=False)
        if ok:
            self.stats["fcm_sent"] += 1
            api_logger.info("push_service: update pushed via FCM user=%s", user_id)
        else:
            self.stats["fcm_failed"] += 1
        return ok

    # ---------- heartbeat ----------

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
                    except (TimeoutError, RuntimeError, ConnectionError, WebSocketDisconnect) as exc:
                        api_logger.debug("heartbeat: dropping user=%s: %r", uid, exc)
                        await self.unregister(uid, ws)

    # ---------- properties ----------

    @property
    def fcm_available(self) -> bool:
        """True, если firebase-admin инициализирован и готов отправлять.

        False, если:
          - FCM_ENABLED=false;
          - FCM_CREDENTIALS_PATH пуст или файл не найден;
          - firebase-admin не установлен или упал при инициализации.
        """
        return self.fcm.available

    # ---------- status ----------

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
            "fcm_enabled": getattr(settings, "FCM_ENABLED", False),
            "fcm_send_mode": getattr(settings, "FCM_SEND_MODE", "fallback"),
            "fcm_available": self.fcm.available,
            "stats": self.stats,
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
