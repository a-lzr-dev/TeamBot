"""Фоновый поллер устаревших приложений.

Раз в ``APP_UPDATE_CHECK_INTERVAL_SEC`` секунд:
  1. Вызывает ext.PA_mbl_AppUpdateCheckAll_Exec — SQL уже отфильтровал
     «кому нужно предложить обновление сейчас» (учитывая dov4 vs vuo.DateChanged).
  2. Рассылает push через WS (если онлайн) или FCM (data-only).
  3. Батчем фиксирует предложенные vcd через ext.PA_mbl_AppUpdateOffered_Exec.

Локальная дедупликация (usi, vcd) с cooldown — вторичная защита
от быстрого повторного прохода поллера; основная — на SQL.
"""

from __future__ import annotations

import asyncio
import time
from typing import Any

from ..config import settings
from ..db.repositories import TeamdroidProcedureRepository
from ..logger import app_logger
from ..ws.push_notification_service import push_notification_service


class AppService:
    def __init__(self) -> None:
        self._running = False
        self._task: asyncio.Task | None = None
        self._notified: dict[tuple[str, int], float] = {}
        self._cooldown = int(getattr(settings, "APP_UPDATE_NOTIFY_COOLDOWN_SEC", 12 * 3600))
        self._interval = int(getattr(settings, "APP_UPDATE_CHECK_INTERVAL_SEC", 300))
        self.stats = {"checks": 0, "outdated_found": 0, "pushes_sent": 0, "batches_recorded": 0}

    async def start(self) -> None:
        if self._running:
            return
        if not getattr(settings, "APP_UPDATE_POLLING_ENABLED", True):
            app_logger.info("app_service: polling disabled")
            return
        self._running = True
        self._task = asyncio.create_task(self._loop())
        app_logger.info(
            "app_service: started (interval=%ds, cooldown=%ds)",
            self._interval,
            self._cooldown,
        )

    async def stop(self) -> None:
        self._running = False
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            self._task = None
        app_logger.info("app_service: stopped")

    async def _loop(self) -> None:
        while self._running:
            try:
                await self._check_once()
            except asyncio.CancelledError:
                break
            except Exception as exc:  # noqa: BLE001
                app_logger.error("app_service: check failed: %r", exc, exc_info=True)
            try:
                await asyncio.sleep(self._interval)
            except asyncio.CancelledError:
                break

    async def _check_once(self) -> None:
        self.stats["checks"] += 1
        outdated = await asyncio.to_thread(TeamdroidProcedureRepository.list_outdated_sessions)
        self.stats["outdated_found"] = len(outdated)
        if not outdated:
            return

        now = time.time()
        to_record: list[dict[str, Any]] = []

        for row in outdated:
            usi = row.get("usi") or ""
            if not usi.startswith("usr"):
                continue
            dvc = row.get("dvc") or ""
            api = int(row.get("api") or 0)
            vcd = int(row.get("vcd") or 0)
            frc = row.get("frc")  # 1 = обязательное обновление, иначе None
            if api <= 0 or vcd <= 0 or not dvc:
                continue

            key = (usi, vcd)
            last = self._notified.get(key)
            if last is not None and (now - last) < self._cooldown:
                continue

            payload = {
                "type": "update",
                "force": bool(frc == 1),
                "prm": {
                    "frc": frc,
                    "ver": row.get("ver"),
                    "vcd": vcd,
                    "fph": row.get("fph"),
                    "fsz": row.get("fsz"),
                    "fhs": row.get("fhs"),
                },
            }

            try:
                ok = await push_notification_service.notify_update(
                    user_id=usi,
                    payload=payload,
                )
                if ok:
                    self._notified[key] = now
                    self.stats["pushes_sent"] += 1
                    to_record.append({"usi": usi, "api": api, "dvc": dvc, "vcd": vcd})
            except Exception as exc:  # noqa: BLE001
                app_logger.warning(
                    "app_service: notify failed user=%s: %r",
                    usi,
                    exc,
                )

        if to_record:
            try:
                result = await asyncio.to_thread(
                    TeamdroidProcedureRepository.app_update_offered_batch,
                    to_record,
                )
                if not result.get("success"):
                    app_logger.warning(
                        "app_service: batch record failed rows=%d err=%s",
                        len(to_record),
                        result.get("error"),
                    )
                else:
                    self.stats["batches_recorded"] += 1
                    app_logger.info(
                        "app_service: batch recorded rows=%d",
                        len(to_record),
                    )
            except Exception as exc:  # noqa: BLE001
                app_logger.warning(
                    "app_service: batch record raised: %r",
                    exc,
                )

        if len(self._notified) > 10_000:
            cutoff = now - self._cooldown
            self._notified = {k: v for k, v in self._notified.items() if v >= cutoff}


app_service = AppService()

__all__ = ["AppService", "app_service"]
