"""
Менеджер жизненного цикла приложения TeamBot.

CHANGED (v5):
  * добавлена фоновая задача `_pending_push_cleanup_loop`, которая
    раз в 6 часов чистит TPushPending от записей старше 7 дней
    (клиент так и не забрал pending-сигнал — например, удалил
    приложение или сменил устройство);
  * `_start_pending_push_cleanup` вызывается из `_start_database`
    сразу после `_start_sync_registry_cleanup`;
  * останавливается вместе с приложением через
    `_cancel_tasks_gracefully`/`_cancel_tasks_force`, как и
    остальные фоновые loop-ы.

CHANGED (v4, stale iterations):
  * интервал cleanup-loop учитывает
    APP_CLIENT_SYNC_BASE_REGISTRY_ITERATIONS_STALE_SEC.

CHANGED (v3):
  * добавлен фоновый loop очистки in-memory реестра sync-пакетов.
"""

import asyncio
import inspect
from collections.abc import Awaitable, Callable, Coroutine
from enum import StrEnum
from typing import Any, Optional, cast

from ..api.manager import api_manager
from ..bot.manager import bot_manager
from ..config import settings
from ..db.manager import db_manager
from ..db.repositories import ReminderRepository
from ..dtos.reminder import ReminderNotificationDTO
from ..logger import app_logger, stat_logger
from ..models import datetime_now
from ..services.avanpost_sync_service import AvanpostSyncService
from ..services.log_handler_service import log_handler_service
from ..services.message_lifetime_service import message_lifetime_service
from ..services.reminder_notification_service import reminder_notification_service
from ..services.sync_session_registry import sync_session_registry
from ..utils.decorators import log_exceptions, suppress_debug_logs


def _get_async_method(obj: Any, name: str) -> Callable[..., Awaitable[Any]] | None:
    """Безопасно получить асинхронный метод у объекта."""
    method = getattr(obj, name, None)
    if method is None or not callable(method):
        return None
    if not inspect.iscoroutinefunction(method):
        return None
    return cast("Callable[..., Awaitable[Any]]", method)


def _get_coroutine_method(obj: Any, name: str) -> Callable[..., Coroutine[Any, Any, Any]] | None:
    """Безопасно получить корутинный метод у объекта."""
    method = getattr(obj, name, None)
    if method is None or not callable(method):
        return None
    if not inspect.iscoroutinefunction(method):
        return None
    return cast("Callable[..., Coroutine[Any, Any, Any]]", method)


class AppState(StrEnum):
    """Состояния жизненного цикла приложения."""

    INITIALIZED = "initialized"
    STARTING = "starting"
    RUNNING = "running"
    STOPPING = "stopping"
    STOPPED = "stopped"
    ERROR = "error"


class ApplicationManager:
    """Менеджер для управления жизненным циклом всего приложения."""

    _instance: Optional["ApplicationManager"] = None

    VALID_COMPONENTS: set[str] = {"db", "api", "bot"}
    COMPONENT_ORDER_START: list[str] = ["db", "api", "bot"]
    COMPONENT_ORDER_STOP: list[str] = ["api", "bot", "db"]

    def __new__(cls) -> Any:
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    def __init__(self) -> None:
        if hasattr(self, "_initialized"):
            return

        self._state: AppState = AppState.INITIALIZED
        self._tasks: list[asyncio.Task[Any]] = []
        self._stop_event: asyncio.Event = asyncio.Event()
        self._start_time: float | None = None

        self.db = db_manager
        self.api = api_manager
        self.bot = bot_manager

        self._reminder_repo = ReminderRepository()

        self.REMINDER_CHECK_INTERVAL: int = getattr(settings, "REMINDER_CHECK_INTERVAL", 60)
        self.REMINDER_BATCH_SIZE: int = getattr(settings, "REMINDER_BATCH_SIZE", 100)

        self._initialized = True
        app_logger.debug("✅ ApplicationManager created")

    # ==================== СВОЙСТВА СОСТОЯНИЯ ====================

    @property
    def state(self) -> AppState:
        return self._state

    @property
    def is_running(self) -> bool:
        return self._state == AppState.RUNNING

    @property
    def is_stopped(self) -> bool:
        return self._state == AppState.STOPPED

    @property
    def is_error(self) -> bool:
        return self._state == AppState.ERROR

    @property
    def uptime(self) -> float | None:
        if self._start_time is None or not self.is_running:
            return None
        return asyncio.get_event_loop().time() - self._start_time

    # ==================== ВСПОМОГАТЕЛЬНЫЕ МЕТОДЫ ====================

    def _validate_components(self, components: list[str] | None) -> list[str]:
        if not components:
            return list(self.VALID_COMPONENTS)

        unique_components = list(dict.fromkeys(components))
        invalid = set(unique_components) - self.VALID_COMPONENTS
        if invalid:
            app_logger.warning(f"⚠️ Unknown components ignored: {invalid}")

        valid = [c for c in unique_components if c in self.VALID_COMPONENTS]

        if not valid:
            app_logger.warning("⚠️ No valid components specified, using all")
            return list(self.VALID_COMPONENTS)

        return valid

    # ==================== УПРАВЛЕНИЕ ЗАПУСКОМ ====================

    @log_exceptions(app_logger)
    async def start(self, components: list[str] | None = None) -> None:
        if self._state == AppState.RUNNING:
            app_logger.warning("⚠️ Application already running")
            return

        if self._state == AppState.ERROR:
            raise RuntimeError("Cannot start from ERROR state. Please restart the application.")

        self._state = AppState.STARTING
        self._start_time = asyncio.get_event_loop().time()

        to_start = self._validate_components(components)

        try:
            for component in self.COMPONENT_ORDER_START:
                if component in to_start:
                    await self._start_component(component)

            self._state = AppState.RUNNING
            app_logger.info(f"✅ Application started successfully (components: {', '.join(to_start)})")

        except Exception as e:  # noqa: BLE001
            self._state = AppState.ERROR
            app_logger.error(f"❌ Application start failed: {e}", exc_info=True)
            await self._emergency_stop()
            raise

    async def _start_component(self, component: str) -> None:
        if component == "db":
            await self._start_database()
        elif component == "api":
            await self._start_api()
        elif component == "bot":
            await self._start_bot()
        else:
            app_logger.warning(f"⚠️ Unknown component: {component}")

    # ==================== ЗАПУСК: БАЗА ДАННЫХ ====================

    async def _start_database(self) -> None:
        app_logger.debug("🗄️ Starting database...")

        await self.db.initialize_all()
        app_logger.debug("✅ Database initialized")

        await self.db.init_tables(drop_first=False)
        app_logger.info("✅ Database tables created")

        try:
            await self.db.seed_tables()
            app_logger.info("✅ Seed data completed")
        except Exception as e:  # noqa: BLE001
            app_logger.error(f"❌ Failed to seed data: {e}", exc_info=True)
            raise RuntimeError(f"Seed failed: {e}") from e

        await self._sync_avanpost_base_if_enabled()
        await self._sync_avanpost_users_if_enabled()
        await self._init_log_handler()
        await self._start_logs_retention()

        # NEW: фоновая очистка in-memory реестра sync-пакетов
        await self._start_sync_registry_cleanup()

        # NEW (v5): фоновая очистка TPushPending от старых записей
        await self._start_pending_push_cleanup()

    async def _sync_avanpost_base_if_enabled(self) -> None:
        if not getattr(settings, "AVANPOST_AUTO_SYNC_ON_START", True):
            return
        try:
            sync_force = getattr(settings, "AVANPOST_SYNC_FORCE", False)
            sync_timeout = getattr(settings, "AVANPOST_SYNC_TIMEOUT", 300)
            sync_required = getattr(settings, "AVANPOST_SYNC_REQUIRED", False)

            app_logger.info(f"🚀 Starting Users Base Data Sync (force={sync_force})...")

            try:
                await asyncio.wait_for(
                    self._sync_avanpost_base_data(force=sync_force),
                    timeout=sync_timeout if sync_timeout > 0 else None,
                )
                app_logger.info("✅ Avanpost Base Data Sync completed successfully")
            except TimeoutError as err:
                error_msg = f"Avanpost Base Data Sync timed out after {sync_timeout}s"
                if sync_required:
                    raise TimeoutError(error_msg) from err
                app_logger.error(f"❌ {error_msg}")
        except Exception as e:  # noqa: BLE001
            app_logger.error(f"❌ Avanpost base sync error: {e}", exc_info=True)
            if getattr(settings, "AVANPOST_SYNC_REQUIRED", False):
                raise

    async def _sync_avanpost_users_if_enabled(self) -> None:
        sync_force = getattr(settings, "AVANPOST_SYNC_FORCE", False)

        async def _sequential_sync() -> None:
            try:
                if getattr(settings, "AVANPOST_SYNC_USERS_BASE", False):
                    app_logger.debug("🚀 Step 1/2: Starting Avanpost Users Base Data Sync...")
                    await self._sync_avanpost_users_in_background(force=sync_force, mode=1)
                    app_logger.info("✅ Step 1/2: Avanpost Users Base Data Sync completed")
                else:
                    app_logger.debug("⏭️ Step 1/2: Avanpost Users Base Data Sync skipped (disabled)")

                if getattr(settings, "AVANPOST_SYNC_USERS_DETAILS", False):
                    app_logger.debug("🚀 Step 2/2: Starting Avanpost Users Details Data Sync...")
                    user_ids = getattr(settings, "AVANPOST_SYNC_USERS_DETAILS_IDS", None)
                    await self._sync_avanpost_users_in_background(force=sync_force, mode=2, user_ids=user_ids)
                    app_logger.info("✅ Step 2/2: Avanpost Users Details Data Sync completed")
                else:
                    app_logger.debug("⏭️ Step 2/2: Avanpost Users Details Data Sync skipped (disabled)")

            except asyncio.CancelledError:
                app_logger.debug("ℹ️ Avanpost Users Data Sync cancelled")
                raise
            except Exception as e:  # noqa: BLE001
                app_logger.error(f"❌ Avanpost Users Data Sync failed: {e}", exc_info=True)

        task: asyncio.Task[None] = asyncio.create_task(_sequential_sync(), name="avanpost_users_sync")
        self._tasks.append(task)
        app_logger.info("🚀 Starting Avanpost Users Data Sync in background (sequential)")

    @staticmethod
    async def _init_log_handler() -> None:
        try:
            await log_handler_service.initialize()
        except Exception as e:  # noqa: BLE001
            app_logger.error(f"❌ Failed to initialize LogHandlerService: {e}", exc_info=True)

    # ==================== ЗАПУСК: РЕТЕНШН ДИАГНОСТИЧЕСКИХ ЛОГОВ ====================

    async def _start_logs_retention(self) -> None:
        if not getattr(settings, "APP_CLIENT_SUPPORT_LOGS_INGEST_ENABLED", True):
            app_logger.debug("⏭️ Logs retention skipped (APP_CLIENT_SUPPORT_LOGS_INGEST_ENABLED=false)")
            return

        task: asyncio.Task[None] = asyncio.create_task(self._logs_retention_loop(), name="logs_retention")
        self._tasks.append(task)
        app_logger.info("✅ Logs retention loop started")

    async def _logs_retention_loop(self) -> None:
        from ..db.repositories import AppRepository

        info_days = getattr(settings, "APP_CLIENT_SUPPORT_LOGS_RETENTION_INFO_DAYS", 30)
        error_days = getattr(settings, "APP_CLIENT_SUPPORT_LOGS_RETENTION_ERROR_DAYS", 90)
        req_days = getattr(settings, "APP_CLIENT_SUPPORT_LOGS_REQUESTS_RETENTION_DAYS", 30)

        app_logger.info(
            "✅ Logs retention loop started (info=%dd, error=%dd, requests=%dd)",
            info_days,
            error_days,
            req_days,
        )

        while self.is_running:
            try:
                async with self.db.get_session() as session:
                    stats = await AppRepository.run_retention(
                        session,
                        info_days=info_days,
                        error_days=error_days,
                        requests_retention_days=req_days,
                    )
                    await session.commit()

                if stats["logs_deleted"] or stats["requests_deleted"] or stats.get("requests_expired"):
                    app_logger.info(
                        "🧹 Logs retention: logs_deleted=%d requests_deleted=%d requests_expired=%d",
                        stats["logs_deleted"],
                        stats["requests_deleted"],
                        stats.get("requests_expired", 0),
                    )

                await asyncio.sleep(3600)

            except asyncio.CancelledError:
                app_logger.debug("ℹ️ Logs retention cancelled")
                break
            except Exception as e:  # noqa: BLE001
                app_logger.error(f"❌ Logs retention error: {e}", exc_info=True)
                await asyncio.sleep(300)

        app_logger.debug("ℹ️ Logs retention loop finished")

    # ==================== NEW: ОЧИСТКА РЕЕСТРА SYNC ====================

    async def _start_sync_registry_cleanup(self) -> None:
        """Фоновая очистка in-memory реестра sync-пакетов.

        CHANGED (v5): критично для продакшена. Без этого loop-а
        `_by_user` и `_iterations` растут бесконечно при большом
        числе мобильных клиентов (утечка памяти).

        CHANGED (v6, stale iterations): интервал теперь учитывает
        APP_CLIENT_SYNC_BASE_REGISTRY_ITERATIONS_STALE_SEC, чтобы
        «залипшие» счётчики итераций сбрасывались за ~stale + interval,
        а не за ~ttl + interval.

        Вызывается из `_start_database()` (после seed-а).
        Останавливается вместе с приложением через
        `_cancel_tasks_gracefully()`/`_cancel_tasks_force()`.
        """
        task: asyncio.Task[None] = asyncio.create_task(self._sync_registry_cleanup_loop(), name="sync_registry_cleanup")
        self._tasks.append(task)
        app_logger.info("✅ Sync registry cleanup loop started")

    async def _sync_registry_cleanup_loop(self) -> None:
        ttl = int(getattr(settings, "APP_CLIENT_SYNC_BASE_REGISTRY_TTL_SEC", 3600) or 3600)
        stale = int(getattr(settings, "APP_CLIENT_SYNC_BASE_REGISTRY_ITERATIONS_STALE_SEC", 300) or 300)
        # Просыпаемся не реже, чем нужно для своевременного сброса итераций.
        # max(30, ...) — минимальный интервал, чтобы не жрать CPU на пустом
        # реестре. min(ttl // 2, stale // 2) — не спим дольше половины
        # самого короткого из двух таймаутов.
        interval = max(30, min(ttl // 2, stale // 2))

        app_logger.info(
            "✅ Sync registry cleanup loop started (interval=%ds, ttl=%ds, iterations_stale=%ds)",
            interval,
            ttl,
            stale,
        )

        while self.is_running:
            try:
                sync_session_registry.cleanup_expired()
            except Exception as exc:  # noqa: BLE001
                app_logger.error("❌ Sync registry cleanup failed: %r", exc, exc_info=True)

            try:
                await asyncio.sleep(interval)
            except asyncio.CancelledError:
                app_logger.debug("ℹ️ Sync registry cleanup cancelled")
                break

        app_logger.debug("ℹ️ Sync registry cleanup loop finished")

    # ==================== NEW (v5): ОЧИСТКА TPushPending ====================

    async def _start_pending_push_cleanup(self) -> None:
        """Фоновая очистка TPushPending от записей старше N дней.

        Клиент мог удалить приложение, сменить устройство или так и не
        выйти в сеть — pending-сигналы накапливались бы вечно.
        Чистим раз в 6 часов, порог — 7 дней.

        Вызывается из `_start_database()` сразу после
        `_start_sync_registry_cleanup()`.
        """
        task: asyncio.Task[None] = asyncio.create_task(self._pending_push_cleanup_loop(), name="pending_push_cleanup")
        self._tasks.append(task)
        app_logger.info("✅ Pending push cleanup loop started")

    async def _pending_push_cleanup_loop(self) -> None:
        from ..db.repositories.app_push_pending import app_push_pending_repo

        interval = 6 * 3600  # раз в 6 часов
        retention_days = 7

        app_logger.info(
            "✅ Pending push cleanup loop started (interval=%ds, retention=%dd)",
            interval,
            retention_days,
        )

        while self.is_running:
            try:
                async with self.db.get_session() as session:
                    deleted = await app_push_pending_repo.cleanup_older_than(session, days=retention_days)
                if deleted:
                    app_logger.info(
                        "🧹 Pending push cleanup: deleted=%d (older than %dd)",
                        deleted,
                        retention_days,
                    )
            except Exception as exc:  # noqa: BLE001
                app_logger.error("❌ Pending push cleanup failed: %r", exc, exc_info=True)

            try:
                await asyncio.sleep(interval)
            except asyncio.CancelledError:
                app_logger.debug("ℹ️ Pending push cleanup cancelled")
                break

        app_logger.debug("ℹ️ Pending push cleanup loop finished")

    # ==================== СИНХРОНИЗАЦИЯ ДАННЫХ ====================

    @staticmethod
    @suppress_debug_logs
    async def _sync_avanpost_base_data(force: bool = False, show_logs: bool = False) -> None:
        try:
            app_logger.debug(f"🔄 Syncing Avanpost base data (force={force})...")
            sync_service = AvanpostSyncService()
            await sync_service.initialize()

            stats = await sync_service.sync_base_data(force=force, show_logs=show_logs)
            stats_dict = stats.to_dict() if hasattr(stats, "to_dict") else {}

            if stats_dict.get("total_inserted", 0) > 0 or stats_dict.get("total_updated", 0) > 0:
                stat_logger.info(
                    f"📊 Base data sync: "
                    f"inserted={stats_dict.get('total_inserted', 0)}, "
                    f"updated={stats_dict.get('total_updated', 0)}, "
                    f"deleted={stats_dict.get('total_deleted', 0)}"
                )
            else:
                app_logger.info("📊 Base data sync: no changes detected")

        except ImportError as e:
            app_logger.warning(f"⚠️ Sync service not available: {e}")
            raise
        except Exception as e:  # noqa: BLE001
            app_logger.error(f"❌ Failed to sync base data: {e}", exc_info=True)
            raise

    @staticmethod
    @suppress_debug_logs
    async def _sync_avanpost_users(
        force: bool = False,
        mode: int = 1,
        user_ids: list[int] | None = None,
        show_logs: bool = False,
    ) -> None:
        try:
            mode_name = "base" if mode == 1 else "details"
            app_logger.debug(f"👤 Syncing Avanpost user {mode_name} data (force={force})...")

            sync_service = AvanpostSyncService()
            await sync_service.initialize()

            await sync_service.sync_all_users(
                force=force,
                mode=mode,
                user_ids=user_ids if user_ids else None,
                show_logs=show_logs,
            )

        except ImportError as e:
            app_logger.warning(f"⚠️ Sync service not available: {e}")
        except Exception as e:  # noqa: BLE001
            app_logger.error(f"❌ Failed to sync users: {e}", exc_info=True)
            raise

    async def _sync_avanpost_users_in_background(
        self,
        force: bool = False,
        mode: int = 1,
        user_ids: list[int] | None = None,
        show_logs: bool = False,
    ) -> None:
        mode_name = "base" if mode == 1 else "details"
        try:
            app_logger.info(f"👤 Starting Avanpost users {mode_name} sync in background...")
            await self._sync_avanpost_users(force=force, mode=mode, user_ids=user_ids, show_logs=show_logs)
            app_logger.info(f"✅ Avanpost users {mode_name} background sync completed")

        except asyncio.CancelledError:
            app_logger.debug(f"ℹ️ Avanpost users {mode_name} sync cancelled")
            raise
        except Exception as e:  # noqa: BLE001
            app_logger.error(f"❌ Avanpost users {mode_name} background sync failed: {e}", exc_info=True)

    # ==================== ЗАПУСК: API ====================

    async def _start_api(self) -> None:
        app_logger.debug("🌐 Starting API...")

        initialize = _get_async_method(self.api, "initialize")
        if initialize is not None:
            await initialize()
        else:
            app_logger.debug("ℹ️ API initialize not needed or not available")

        start = _get_coroutine_method(self.api, "start")
        if start is not None:
            task: asyncio.Task[Any] = asyncio.create_task(start(), name="api_server")
            self._tasks.append(task)
        else:
            app_logger.warning("⚠️ API start is not an async method, skipping")

    # ==================== ЗАПУСК: БОТ ====================

    async def _start_bot(self) -> None:
        app_logger.debug("🤖 Starting Bot...")

        start = _get_coroutine_method(self.bot, "start")
        if start is not None:
            task: asyncio.Task[Any] = asyncio.create_task(start(), name="bot_main")
            self._tasks.append(task)

        await asyncio.sleep(2)
        await self._start_reminder_checker()

        lifetime_start = _get_async_method(message_lifetime_service, "start")
        if lifetime_start is not None:
            try:
                await lifetime_start()
                app_logger.info("✅ MessageLifetimeService started")
            except Exception as e:  # noqa: BLE001
                app_logger.error(f"❌ Failed to start MessageLifetimeService: {e}")

        try:
            from ..services.app_service import app_service

            await app_service.start()
            app_logger.info("✅ AppService started")
        except Exception as e:  # noqa: BLE001
            app_logger.error(f"❌ Failed to start AppService: {e}")

        app_logger.info("✅ Bot started")

    # ==================== ПРОВЕРКА НАПОМИНАНИЙ ====================

    async def _start_reminder_checker(self) -> None:
        app_logger.debug("⏰ Starting reminder checker...")

        task: asyncio.Task[None] = asyncio.create_task(self._reminder_check_loop(), name="reminder_checker")
        self._tasks.append(task)
        app_logger.info(
            f"✅ Reminder checker started (interval: {self.REMINDER_CHECK_INTERVAL}s, "
            f"batch: {self.REMINDER_BATCH_SIZE})"
        )

    async def _reminder_check_loop(self) -> None:
        app_logger.debug("🔄 Reminder check loop started")

        while self.is_running:
            try:
                await self._check_and_send_reminders()

                try:
                    await asyncio.sleep(self.REMINDER_CHECK_INTERVAL)
                except asyncio.CancelledError:
                    app_logger.debug("⏰ Reminder checker cancelled during sleep")
                    break

            except asyncio.CancelledError:
                app_logger.debug("⏰ Reminder checker cancelled")
                break
            except Exception as e:  # noqa: BLE001
                app_logger.error(f"❌ Reminder checker error: {e}", exc_info=True)
                await asyncio.sleep(self.REMINDER_CHECK_INTERVAL)

        app_logger.debug("⏰ Reminder check loop finished")

    async def _check_and_send_reminders(self) -> None:
        try:
            now = datetime_now()
            app_logger.debug(f"⏰ Checking reminders at {now}")

            async with self.db.get_session() as session:
                reminders = await self._reminder_repo.get_active_reminders(
                    session=session,
                    before_time=now,
                    limit=self.REMINDER_BATCH_SIZE,
                )

                if not reminders:
                    return

                app_logger.info(f"⏰ Found {len(reminders)} reminders to process")

                for reminder in reminders:
                    try:
                        reminder_dto = ReminderNotificationDTO.from_model(reminder)
                        await reminder_notification_service.send_notification(
                            reminder=reminder_dto,
                            session=session,
                        )
                    except Exception as e:  # noqa: BLE001
                        app_logger.error(f"❌ Failed to process reminder {reminder.FID}: {e}", exc_info=True)
                        continue

        except Exception as e:  # noqa: BLE001
            app_logger.error(f"❌ Failed to check reminders: {e}", exc_info=True)
            raise

    # ==================== УПРАВЛЕНИЕ ОСТАНОВКОЙ ====================

    @log_exceptions(app_logger)
    async def stop(self, components: list[str] | None = None, graceful: bool = True) -> None:
        if self._state == AppState.STOPPED:
            app_logger.warning("⚠️ Application already stopped")
            return

        if self._state == AppState.ERROR:
            app_logger.warning("⚠️ Application in ERROR state, forcing stop...")
            await self._emergency_stop()
            return

        self._state = AppState.STOPPING
        app_logger.debug("🚀 Application stopping starting...")

        to_stop = self._validate_components(components)
        app_logger.debug(f"📋 Components to stop: {to_stop}")

        try:
            for component in self.COMPONENT_ORDER_STOP:
                if component in to_stop:
                    await self._stop_component(component, graceful)

            await self._stop_log_handler(graceful)

            if graceful:
                await self._cancel_tasks_gracefully()
            else:
                await self._cancel_tasks_force()

            self._state = AppState.STOPPED
            self._start_time = None
            app_logger.debug(f"✅ Application stopped successfully (components: {', '.join(to_stop)})")

        except Exception as e:  # noqa: BLE001
            self._state = AppState.ERROR
            app_logger.error(f"❌ Application stop failed: {e}", exc_info=True)
            raise

    async def _stop_component(self, component: str, graceful: bool) -> None:
        if component == "api":
            await self._stop_api(graceful)
        elif component == "bot":
            await self._stop_bot(graceful)
        elif component == "db":
            await self._stop_database(graceful)
        else:
            app_logger.warning(f"⚠️ Unknown component: {component}")

    @staticmethod
    async def _stop_log_handler(graceful: bool = True) -> None:
        app_logger.debug("🚀 Stopping LogHandlerService...")
        try:
            set_shutting_down = _get_async_method(log_handler_service, "set_shutting_down")
            if set_shutting_down is not None:
                await set_shutting_down(True)

            shutdown = _get_async_method(log_handler_service, "shutdown")
            if shutdown is not None:
                await shutdown()

            app_logger.info("⛔ LogHandlerService stopped")
        except Exception as e:  # noqa: BLE001
            app_logger.error(f"❌ Failed to stop LogHandlerService: {e}")
            if not graceful:
                raise

    async def _stop_api(self, graceful: bool = True) -> None:
        app_logger.debug("🚀 API stopping starting...")
        try:
            if getattr(self.api, "is_running", False):
                stop = _get_async_method(self.api, "stop")
                if stop is not None:
                    await stop()
            else:
                app_logger.debug("ℹ️ API was not running")
        except Exception as e:  # noqa: BLE001
            app_logger.error(f"❌ Failed to stop API: {e}")
            if not graceful:
                raise

    async def _stop_bot(self, graceful: bool = True) -> None:
        app_logger.debug("🚀 Bot stopping starting...")

        try:
            from ..ws import push_notification_service

            if getattr(push_notification_service, "is_running", False):
                stop = _get_async_method(push_notification_service, "stop")
                if stop is not None:
                    await stop()
                    app_logger.info("⛔ PushNotificationService stopped")
                else:
                    app_logger.warning("⚠️ PushNotificationService.stop is not async, skipping")
            else:
                app_logger.debug("ℹ️ PushNotificationService was not running")
        except Exception as e:  # noqa: BLE001
            app_logger.error(f"❌ Failed to stop PushNotificationService: {e}")
            if not graceful:
                raise

        lifetime_stop = _get_async_method(message_lifetime_service, "stop")
        if lifetime_stop is not None:
            try:
                await lifetime_stop()
                app_logger.info("⛔ MessageLifetimeService stopped")
            except Exception as e:  # noqa: BLE001
                app_logger.error(f"❌ Failed to stop MessageLifetimeService: {e}")
                if not graceful:
                    raise

        try:
            from ..services.app_service import app_service

            await app_service.stop()
            app_logger.info("⛔ AppService stopped")
        except Exception as e:  # noqa: BLE001
            app_logger.error(f"❌ Failed to stop AppService: {e}")

        bot_stop = _get_async_method(self.bot, "stop")
        if bot_stop is not None:
            try:
                await bot_stop()
                app_logger.info("⛔ Bot stopped")
            except Exception as e:  # noqa: BLE001
                app_logger.error(f"❌ Failed to stop Bot: {e}")
                if not graceful:
                    raise

    async def _stop_database(self, graceful: bool = True) -> None:
        app_logger.debug("🚀 Stopping database starting...")
        try:
            await self._stop_log_handler(graceful)

            close_all = _get_async_method(self.db, "close_all")
            if close_all is not None:
                await close_all()

            app_logger.info("⛔ Database stopped")
        except Exception as e:  # noqa: BLE001
            app_logger.error(f"❌ Failed to stop database: {e}")
            if not graceful:
                raise

    # ==================== АВАРИЙНАЯ ОСТАНОВКА ====================

    async def _emergency_stop(self) -> None:
        app_logger.warning("🚨 Emergency stop initiated...")

        try:
            await self._stop_log_handler(graceful=False)
        except Exception as e:  # noqa: BLE001
            app_logger.error(f"❌ Emergency stop failed for LogHandlerService: {e}")

        for component in self.COMPONENT_ORDER_STOP:
            try:
                await self._stop_component(component, graceful=False)
            except Exception as e:  # noqa: BLE001
                app_logger.error(f"❌ Emergency stop failed for {component}: {e}")

        await self._cancel_tasks_force()

        self._state = AppState.STOPPED
        self._start_time = None
        app_logger.info("✅ Emergency stop completed")

    # ==================== УПРАВЛЕНИЕ ЗАДАЧАМИ ====================

    async def _cancel_tasks_gracefully(self) -> None:
        if not self._tasks:
            return

        app_logger.debug(f"⏳ Cancelling {len(self._tasks)} tasks gracefully...")

        for task in self._tasks:
            if not task.done():
                task.cancel()

        try:
            await asyncio.wait_for(asyncio.gather(*self._tasks, return_exceptions=True), timeout=10.0)
            app_logger.debug("⛔ All tasks completed gracefully")
        except TimeoutError:
            app_logger.warning("⚠️ Some tasks didn't finish in time, forcing cancel...")
            for task in self._tasks:
                if not task.done():
                    task.cancel()
            await asyncio.gather(*self._tasks, return_exceptions=True)

        self._tasks.clear()

    async def _cancel_tasks_force(self) -> None:
        if not self._tasks:
            return

        app_logger.debug(f"⛔ Force cancelling {len(self._tasks)} tasks...")

        for task in self._tasks:
            if not task.done():
                task.cancel()

        await asyncio.gather(*self._tasks, return_exceptions=True)
        self._tasks.clear()
        app_logger.debug("✅ All tasks force cancelled")

    # ==================== УПРАВЛЕНИЕ ПЕРЕЗАПУСКОМ ====================

    @log_exceptions(app_logger)
    async def restart(self, components: list[str] | None = None) -> None:
        app_logger.info("🔄 Application restarting...")
        await self.stop(components, graceful=True)
        await asyncio.sleep(1)
        await self.start(components)
        app_logger.info("✅ Application restarted")

    # ==================== СТАТУС И ЗДОРОВЬЕ ====================

    @log_exceptions(app_logger)
    async def get_status(self) -> dict[str, Any]:
        db_status: dict[str, Any] = {}
        get_stats = _get_async_method(self.db, "get_stats")
        if get_stats is not None:
            try:
                db_status = await get_stats()
            except Exception:  # noqa: BLE001
                db_status = {"error": "Failed to get stats"}

        api_status: dict[str, Any] = {}
        api_get_status = _get_async_method(self.api, "get_status")
        if api_get_status is not None:
            try:
                api_status = await api_get_status()
            except Exception:  # noqa: BLE001
                api_status = {"error": "Failed to get status"}

        bot_status: dict[str, Any] = {}
        bot_get_status = _get_async_method(self.bot, "get_status")
        if bot_get_status is not None:
            try:
                bot_status = await bot_get_status()
            except Exception:  # noqa: BLE001
                bot_status = {"error": "Failed to get status"}

        log_handler_status = {
            "initialized": getattr(log_handler_service, "_initialized", False),
        }

        return {
            "app": {
                "state": self._state.value,
                "is_running": self.is_running,
                "tasks_count": len(self._tasks),
                "uptime": self.uptime,
            },
            "database": db_status,
            "api": api_status,
            "bot": bot_status,
            "log_handler": log_handler_status,
        }

    @log_exceptions(app_logger)
    async def health_check(self) -> dict[str, Any]:
        db_health = False
        db_check = _get_async_method(self.db, "check_connection")
        if db_check is not None:
            try:
                db_health = bool(await db_check())
            except Exception:  # noqa: BLE001
                db_health = False

        api_health = bool(getattr(self.api, "is_running", False))

        bot_health_check = _get_async_method(self.bot, "health_check")
        if bot_health_check is not None:
            try:
                result = await bot_health_check()
                if isinstance(result, dict):
                    bot_health = bool(result.get("is_running", False) or result.get("manager_running", False))
                else:
                    bot_health = bool(result)
            except Exception:  # noqa: BLE001
                bot_health = False
        else:
            bot_health = bool(getattr(self.bot, "is_running", False))

        log_handler_health = bool(getattr(log_handler_service, "_initialized", False))

        return {
            "app": self.is_running,
            "database": db_health,
            "api": api_health,
            "bot": bot_health,
            "log_handler": log_handler_health,
        }

    # ==================== КОНТЕКСТНЫЙ МЕНЕДЖЕР ====================

    async def __aenter__(self) -> "ApplicationManager":
        await self.start()
        return self

    async def __aexit__(self, exc_type: Any, exc_val: Any, exc_tb: Any) -> None:
        await self.stop()

    def __repr__(self) -> str:
        uptime = self.uptime
        uptime_str = f"{uptime:.1f}s" if uptime is not None else "N/A"
        return f"<ApplicationManager state={self._state.value} tasks={len(self._tasks)} uptime={uptime_str}>"


app_manager = ApplicationManager()


def get_app_manager() -> ApplicationManager:
    return app_manager


__all__ = [
    "AppState",
    "ApplicationManager",
    "app_manager",
    "get_app_manager",
]
