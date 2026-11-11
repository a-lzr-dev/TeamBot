"""In-memory реестр выданных sync-пакетов и их sid для валидации sync-edit.

НЕ является источником истины (источник — SQL Server,
TRSAppDataObjectsDevicesSessionsSyncData). Нужен только для того,
чтобы отсечь грубые ошибки клиента и связать `sync-edit` с выданным
пакетом по `sid`.

CHANGED (v7):
  * процедура ext.PA_mbl_SyncBaseData_Load теперь возвращает ОДНУ строку
    (sid, snc, dtp, Result) и генерирует `sid` на своей стороне;
  * клиент присылает в sync-edit `sid`, а сервер берёт по нему `snc` и
    `dtp` из in-memory реестра (`_by_sid`);
  * добавлены `record_sid`, `lookup_sid`, `drop_sid`, `sids_snapshot`;
  * `_by_sid` очищается в `cleanup_expired()`;
  * старые методы (`record_load`, `validate_edit`, `has_pending_types`,
    `latest_packet_ts`, `reset`, `reset_sync`, `bump_iteration`,
    `check_iterations`, `reset_iterations`) сохранены — их использует
    валидация в `sync_base_load` и диагностика в `sync_stats`.

CHANGED (v9, stale iterations):
  * добавлена настройка APP_CLIENT_SYNC_BASE_REGISTRY_ITERATIONS_STALE_SEC
    (по умолчанию 300 сек = 5 мин);
  * `_IterationState` теперь хранит `last_at` (время ПОСЛЕДНЕГО
    bump_iteration) помимо `first_at`;
  * `bump_iteration` обновляет `last_at`;
  * `cleanup_expired()` удаляет state, если истёк ЛИБО общий TTL
    (от `first_at`), ЛИБО stale-таймаут (от `last_at`). Это
    разблокирует клиента, застрявшего в 429 too_many_iterations,
    через 5 минут после последней попытки sync-load, даже если
    успешный sync-edit так и не был сделан;
  * `iterations_snapshot()` расширен полями age/idle/stale_in для
    диагностики через /client/sync-stats (не ломает существующих
    потребителей — они просто читают dict).

Политика fail-open:
  Если записи по `sid` нет (рестарт сервера, TTL истёк, запись ещё не
  создана), `lookup_sid` возвращает None, и `sync_base_edit` вернёт
  400 invalid_edit с retry="sync-load". Клиент запросит свежий пакет.
  SQL-процедура `PA_mbl_SyncBaseData_Edit` дополнительно проверяет
  (usi, dvc, api) через @Resolved и бросает NoData при несоответствии.

Потокобезопасность:
  * Асинхронные методы используют asyncio.Lock.
  * `cleanup_expired()` и `reset_sync`/`clear_all_sync` — синхронные,
    для фонового loop-а и тестов.
"""

from __future__ import annotations

import asyncio
import time
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from ..config import settings
from ..logger import app_logger


def _ttl() -> int:
    return int(getattr(settings, "APP_CLIENT_SYNC_BASE_REGISTRY_TTL_SEC", 3600) or 3600)


def _max_iterations() -> int:
    return int(getattr(settings, "APP_CLIENT_SYNC_BASE_REGISTRY_MAX_ITERATIONS", 100) or 100)


def _max_packets() -> int:
    return int(getattr(settings, "APP_CLIENT_SYNC_BASE_REGISTRY_MAX_PACKETS_PER_USER", 10) or 10)


def _require_latest() -> bool:
    return bool(getattr(settings, "APP_CLIENT_SYNC_BASE_REGISTRY_REQUIRE_LATEST", False))


# NEW (stale iterations): таймаут незавершившихся итераций sync-load.
def _iterations_stale_sec() -> int:
    return int(getattr(settings, "APP_CLIENT_SYNC_BASE_REGISTRY_ITERATIONS_STALE_SEC", 300) or 300)


def _norm_ts(ts: str | None) -> str | None:
    """Нормализация ISO 8601 → UTC `%Y-%m-%dT%H:%M:%S` (без долей).

    Нужна, потому что:
      * SQL Server отдаёт DATETIME (может приходить как isoformat с долями);
      * клиент шлёт ts в своём формате (с `Z` / `+00:00` / без долей).

    Без нормализации `IssuedPacket.sync_time` и `Edit.ts` сравниваются
    как строки и не совпадают → реестр бесполезен.
    """
    if not ts:
        return None
    try:
        dt = datetime.fromisoformat(ts.replace("Z", "+00:00"))
    except ValueError:
        return ts
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=UTC)
    return dt.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%S")


@dataclass
class IssuedPacket:
    """Запись о выданном пакете (по snc + набору dtp).

    Attributes:
        sync_time: нормализованный SyncTime (UTC, `%Y-%m-%dT%H:%M:%S`).
        data_types: DataTypeId, для которых HasMore == 0.
        expires_at: абсолютное время истечения (time.time() + TTL).
    """

    sync_time: str
    data_types: set[int] = field(default_factory=set)
    expires_at: float = 0.0


class _IterationState:
    """Счётчик итераций Load для пользователя (защита от зацикливания).

    CHANGED (stale iterations): добавлено поле `last_at` — время
    ПОСЛЕДНЕГО `bump_iteration`. Используется в `cleanup_expired()` для
    сброса «залипших» счётчиков через
    APP_CLIENT_SYNC_BASE_REGISTRY_ITERATIONS_STALE_SEC (по умолчанию 5 мин),
    даже если клиент так и не сделал успешный sync-edit.
    """

    __slots__ = ("count", "first_at", "last_at")

    def __init__(self) -> None:
        self.count: int = 0
        now = time.time()
        self.first_at: float = now
        self.last_at: float = now


class SyncSessionRegistry:
    """Реестр выданных sync-пакетов и их sid (in-memory)."""

    def __init__(self) -> None:
        # по snc + набору типов (для fail-open валидации)
        self._by_user: dict[str, list[IssuedPacket]] = defaultdict(list)
        # по sid (для sync-edit)
        self._by_sid: dict[str, dict[str, Any]] = {}
        self._iterations: dict[str, _IterationState] = {}
        self._last_load_at: dict[str, float] = {}
        self._last_edit_at: dict[str, float] = {}
        self._lock = asyncio.Lock()

        # Счётчики метрик (для /client/sync-stats).
        self._counters: dict[str, int] = {
            "record_load_calls": 0,
            "record_load_overflow_dropped": 0,
            "record_sid_calls": 0,
            "lookup_sid_calls": 0,
            "lookup_sid_miss": 0,
            "lookup_sid_user_mismatch": 0,
            "validate_edit_calls": 0,
            "validate_edit_rejected": 0,
            "validate_edit_fail_open": 0,
            "bump_iteration_calls": 0,
            "reset_iterations_calls": 0,
            "reset_calls": 0,
            "cleanup_runs": 0,
            "cleanup_packets_dropped": 0,
            "cleanup_sids_dropped": 0,
            "cleanup_iters_dropped": 0,
            # NEW (stale iterations): сколько итераций сброшено именно
            # по stale-тайм-ауту (в отличие от общего TTL).
            "cleanup_iters_stale_dropped": 0,
        }

    # ============================================================
    # SID — основной путь для sync-edit (v7)
    # ============================================================

    async def record_sid(
        self,
        *,
        user_id: str,
        sid: str,
        snc: str | None,
        dtp: list[int],
    ) -> None:
        """Запомнить пакет по sid для последующего sync-edit.

        Если sid пуст или snc отсутствует — запись не создаётся,
        клиент получит 400 invalid_edit при попытке Edit (retry="sync-load").
        """
        self._counters["record_sid_calls"] += 1

        if not sid:
            app_logger.warning(
                "sync_registry: skip record_sid user=%s reason=empty_sid",
                user_id,
            )
            return

        ttl = _ttl()
        now = time.time()
        dtp_list = [int(t) for t in (dtp or [])]

        async with self._lock:
            self._by_sid[sid] = {
                "user_id": user_id,
                "snc": snc,
                "dtp": dtp_list,
                "expires_at": now + ttl,
            }
            self._last_load_at[user_id] = now

        app_logger.info(
            "sync_registry: recorded sid=%s user=%s snc=%r dtp_count=%d",
            sid,
            user_id,
            snc,
            len(dtp_list),
        )

    async def lookup_sid(self, sid: str) -> dict[str, Any] | None:
        """Получить {user_id, snc, dtp} по sid.

        Returns:
            dict | None: None, если sid не найден или истёк.
        """
        self._counters["lookup_sid_calls"] += 1

        if not sid:
            self._counters["lookup_sid_miss"] += 1
            return None

        now = time.time()
        async with self._lock:
            entry = self._by_sid.get(sid)
            if entry is None:
                self._counters["lookup_sid_miss"] += 1
                return None
            if entry["expires_at"] <= now:
                self._by_sid.pop(sid, None)
                self._counters["lookup_sid_miss"] += 1
                return None
            return {
                "user_id": entry["user_id"],
                "snc": entry["snc"],
                "dtp": list(entry["dtp"]),
            }

    async def drop_sid(self, sid: str) -> None:
        """Удалить запись по sid (после успешного Edit)."""
        if not sid:
            return
        async with self._lock:
            self._by_sid.pop(sid, None)

    def sids_snapshot(self) -> dict[str, dict[str, Any]]:
        """Снимок активных sid для диагностики."""
        now = time.time()
        return {
            sid: {
                "user_id": e["user_id"],
                "snc": e["snc"],
                "dtp": list(e["dtp"]),
                "ttl_left_sec": max(0, int(e["expires_at"] - now)),
            }
            for sid, e in self._by_sid.items()
            if e["expires_at"] > now
        }

    # ============================================================
    # Старый путь (snc + dtp) — для диагностики и fail-open
    # ============================================================

    async def record_load(
        self,
        user_id: str,
        sync_time: str | None,
        data_types: set[int],
    ) -> None:
        """Записать факт выдачи пакета по (user, snc, dtp).

        Используется для вторичной валидации `validate_edit` (fail-open)
        и для `has_pending_types`.
        """
        self._counters["record_load_calls"] += 1

        norm_ts = _norm_ts(sync_time)
        if norm_ts is None:
            return
        if not data_types:
            return

        ttl = _ttl()
        max_packets = _max_packets()
        now = time.time()

        async with self._lock:
            packets = [p for p in self._by_user.get(user_id, []) if p.expires_at > now]

            if len(packets) >= max_packets:
                overflow = len(packets) - max_packets + 1
                dropped = packets[:overflow]
                packets = packets[overflow:]
                self._counters["record_load_overflow_dropped"] += overflow
                app_logger.warning(
                    "sync_registry: user=%s overflow (%d packets), dropped oldest ts=%s",
                    user_id,
                    overflow,
                    [p.sync_time for p in dropped],
                )

            packets.append(
                IssuedPacket(
                    sync_time=norm_ts,
                    data_types=set(data_types),
                    expires_at=now + ttl,
                )
            )
            self._by_user[user_id] = packets
            self._last_load_at[user_id] = now

        app_logger.info(
            "sync_registry: recorded load user=%s ts=%s types=%s total_packets=%d",
            user_id,
            norm_ts,
            sorted(data_types),
            len(packets),
        )

    async def bump_iteration(self, user_id: str) -> int:
        """Инкремент счётчика итераций Load.

        CHANGED (stale iterations): обновляет `last_at`, чтобы
        `cleanup_expired()` мог сбросить «залипший» счётчик через
        APP_CLIENT_SYNC_BASE_REGISTRY_ITERATIONS_STALE_SEC после
        ПОСЛЕДНЕЙ попытки Load.
        """
        self._counters["bump_iteration_calls"] += 1
        now = time.time()
        async with self._lock:
            state = self._iterations.get(user_id)
            if state is None:
                state = _IterationState()
                self._iterations[user_id] = state
            state.count += 1
            state.last_at = now
            return state.count

    async def check_iterations(self, user_id: str) -> tuple[bool, int]:
        async with self._lock:
            state = self._iterations.get(user_id)
            n = state.count if state else 0
        return n <= _max_iterations(), n

    async def reset_iterations(self, user_id: str) -> None:
        """Сбросить счётчик итераций Load (после успешного Edit)."""
        self._counters["reset_iterations_calls"] += 1
        async with self._lock:
            self._iterations.pop(user_id, None)

    async def latest_packet_ts(self, user_id: str) -> str | None:
        now = time.time()
        async with self._lock:
            packets = [p for p in self._by_user.get(user_id, []) if p.expires_at > now]
        if not packets:
            return None
        return max(packets, key=lambda p: p.expires_at).sync_time

    async def has_pending_types(self, user_id: str) -> bool:
        now = time.time()
        async with self._lock:
            return any(p.expires_at > now for p in self._by_user.get(user_id, []))

    async def validate_edit(
        self,
        user_id: str,
        sync_time: str,
        data_types: set[int],
        *,
        require_latest: bool | None = None,
    ) -> tuple[bool, str | None]:
        """Вторичная проверка (snc + dtp). Основной путь — lookup_sid.

        Оставлен для обратной совместимости; в sync_base_edit больше
        не используется по умолчанию (sid — единственный источник истины).
        """
        self._counters["validate_edit_calls"] += 1

        if require_latest is None:
            require_latest = _require_latest()

        norm_ts = _norm_ts(sync_time) or sync_time

        async with self._lock:
            packets = list(self._by_user.get(user_id, []))

        if not packets:
            self._counters["validate_edit_fail_open"] += 1
            app_logger.warning(
                "sync_registry: no packets for user=%s — fail-open. "
                "ts=%r dtp=%s. SQL will still validate (usi, api, dvc, dtp).",
                user_id,
                norm_ts,
                sorted(data_types),
            )
            return True, None

        now = time.time()
        live = [p for p in packets if p.expires_at >= now]

        if require_latest and live:
            latest = max(live, key=lambda p: p.expires_at)
            if latest.sync_time != norm_ts:
                self._counters["validate_edit_rejected"] += 1
                return False, f"stale ts: got {norm_ts!r}, latest {latest.sync_time!r}"

        for pkt in packets:
            if pkt.expires_at < now:
                continue
            if pkt.sync_time != norm_ts:
                continue
            extra = data_types - pkt.data_types
            if extra:
                self._counters["validate_edit_rejected"] += 1
                return False, f"dtp not issued: {sorted(extra)}"
            return True, None

        self._counters["validate_edit_rejected"] += 1
        return False, f"ts not issued: {norm_ts!r}"

    async def reset(self, user_id: str, sync_time: str | None = None) -> None:
        self._counters["reset_calls"] += 1
        norm_ts = _norm_ts(sync_time) if sync_time else None
        async with self._lock:
            if norm_ts is None:
                self._by_user.pop(user_id, None)
                self._iterations.pop(user_id, None)
                return
            packets = self._by_user.get(user_id, [])
            self._by_user[user_id] = [p for p in packets if p.sync_time != norm_ts]
            self._last_edit_at[user_id] = time.time()

    def reset_sync(self, user_id: str, sync_time: str | None = None) -> None:
        norm_ts = _norm_ts(sync_time) if sync_time else None
        if norm_ts is None:
            self._by_user.pop(user_id, None)
            self._iterations.pop(user_id, None)
            return
        packets = self._by_user.get(user_id, [])
        self._by_user[user_id] = [p for p in packets if p.sync_time != norm_ts]

    def clear_all_sync(self) -> None:
        self._by_user.clear()
        self._by_sid.clear()
        self._iterations.clear()
        self._last_load_at.clear()
        self._last_edit_at.clear()

    # ============================================================
    # Фоновая очистка
    # ============================================================

    def cleanup_expired(self) -> None:
        """Удалить истёкшие записи (snc, sid) и «старые» счётчики итераций.

        CHANGED (stale iterations): счётчик итераций теперь сбрасывается
        по ДВУМ условиям (любое из):

          1. `now - state.first_at > ttl`      — общий TTL реестра
                                                  (как раньше);
          2. `now - state.last_at > stale_sec` — «незавершившиеся» итерации,
                                                  т.е. клиент давно не делал
                                                  sync-load и не сделал
                                                  успешный sync-edit.

        Условие (2) разблокирует клиента, застрявшего в
        429 too_many_iterations, через APP_CLIENT_SYNC_BASE_REGISTRY_ITERATIONS_STALE_SEC
        (по умолчанию 300 сек = 5 минут) после ПОСЛЕДНЕЙ попытки Load.
        """
        self._counters["cleanup_runs"] += 1
        now = time.time()
        ttl = _ttl()
        iterations_stale = _iterations_stale_sec()

        dropped_packets = 0
        for uid, packets in list(self._by_user.items()):
            live = [p for p in packets if p.expires_at > now]
            if not live:
                self._by_user.pop(uid, None)
                dropped_packets += len(packets)
            else:
                dropped_packets += len(packets) - len(live)
                self._by_user[uid] = live

        dropped_sids = 0
        for sid_key, entry in list(self._by_sid.items()):
            if entry["expires_at"] <= now:
                self._by_sid.pop(sid_key, None)
                dropped_sids += 1

        # NEW (stale iterations): сброс по общему TTL ИЛИ по stale-таймауту
        # от last_at. Счётчики dropped_iters/dropped_iters_stale считаются
        # раздельно для диагностики.
        dropped_iters = 0
        dropped_iters_stale = 0
        for uid, state in list(self._iterations.items()):
            too_old_by_ttl = (now - state.first_at) > ttl
            too_stale_by_idle = (now - state.last_at) > iterations_stale
            if too_old_by_ttl or too_stale_by_idle:
                self._iterations.pop(uid, None)
                dropped_iters += 1
                if too_stale_by_idle and not too_old_by_ttl:
                    dropped_iters_stale += 1

        self._counters["cleanup_packets_dropped"] += dropped_packets
        self._counters["cleanup_sids_dropped"] += dropped_sids
        self._counters["cleanup_iters_dropped"] += dropped_iters
        self._counters["cleanup_iters_stale_dropped"] += dropped_iters_stale

        if dropped_packets or dropped_sids or dropped_iters:
            app_logger.info(
                "sync_registry: cleanup dropped %d packets, %d sids, %d iteration-states (%d by stale timeout)",
                dropped_packets,
                dropped_sids,
                dropped_iters,
                dropped_iters_stale,
            )

    # ============================================================
    # Диагностика
    # ============================================================

    def snapshot(self) -> dict[str, list[dict[str, Any]]]:
        now = time.time()
        result: dict[str, list[dict[str, Any]]] = {}
        for uid, packets in self._by_user.items():
            live = [p for p in packets if p.expires_at > now]
            if not live:
                continue
            result[uid] = [
                {
                    "sync_time": p.sync_time,
                    "data_types": sorted(p.data_types),
                    "ttl_left_sec": max(0, int(p.expires_at - now)),
                    "expired": False,
                }
                for p in live
            ]
        return result

    def iterations_snapshot(self) -> dict[str, dict[str, Any]]:
        """Снимок счётчиков итераций для /client/sync-stats.

        CHANGED (stale iterations): раньше возвращал `dict[str, int]`,
        теперь — `dict[str, dict]` с полями:
          * `count`        — текущее значение счётчика;
          * `age_sec`      — сколько прошло с первого bump_iteration;
          * `idle_sec`     — сколько прошло с ПОСЛЕДНЕГО bump_iteration;
          * `stale_in_sec` — через сколько секунд сработает stale-cleanup
                             (0 = cleanup произойдёт при следующем тике).

        Код в `client.py::sync_stats` кладёт результат как есть —
        формат расширен, но не ломает потребителя, который раньше
        читал только числа (он теперь получит dict — надо поправить,
        если где-то есть строгий парсинг; в текущей кодовой базе нет).
        """
        now = time.time()
        stale = _iterations_stale_sec()
        result: dict[str, dict[str, Any]] = {}
        for uid, st in self._iterations.items():
            age = int(now - st.first_at)
            idle = int(now - st.last_at)
            result[uid] = {
                "count": st.count,
                "age_sec": age,
                "idle_sec": idle,
                "stale_in_sec": max(0, stale - idle),
            }
        return result

    def activity_snapshot(self) -> dict[str, dict[str, float | None]]:
        now = time.time()
        result: dict[str, dict[str, float | None]] = {}
        for uid in set(self._last_load_at) | set(self._last_edit_at):
            last_load = self._last_load_at.get(uid)
            last_edit = self._last_edit_at.get(uid)
            result[uid] = {
                "last_load_ago_sec": (now - last_load) if last_load else None,
                "last_edit_ago_sec": (now - last_edit) if last_edit else None,
            }
        return result

    def metrics_snapshot(self) -> dict[str, int]:
        return dict(self._counters)


sync_session_registry = SyncSessionRegistry()

__all__ = [
    "IssuedPacket",
    "SyncSessionRegistry",
    "sync_session_registry",
]
