import asyncio
from enum import StrEnum
from typing import Any, Optional

from ..api.manager import api_manager
from ..bot.manager import bot_manager
from ..config import settings
from ..db.manager import db_manager
from ..db.repositories import ReminderRepository
from ..exceptions import log_exceptions
from ..logger import app_logger
from ..models import datetime_now
from ..services.log_handler_service import log_handler_service
from ..services.reminder_notification_service import reminder_notification_service


class AppState(StrEnum):
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

        self._state = AppState.INITIALIZED
        self._tasks: list[asyncio.Task[Any]] = []
        self._stop_event = asyncio.Event()
        self._start_time: float | None = None

        self.db = db_manager
        self.api = api_manager
        self.bot = bot_manager

        # Настройки из конфига с значениями по умолчанию
        self.REMINDER_CHECK_INTERVAL = getattr(settings, "REMINDER_CHECK_INTERVAL", 60)
        self.REMINDER_BATCH_SIZE = getattr(settings, "REMINDER_BATCH_SIZE", 100)

        self._initialized = True
        app_logger.debug("✅ ApplicationManager created")

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

        except Exception as e:
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

    # ==================== ЗАПУСК БАЗЫ ДАННЫХ (ПОСЛЕДОВАТЕЛЬНАЯ СИНХРОНИЗАЦИЯ) ====================

    async def _start_database(self) -> None:
        """
        Запуск базы данных с последовательной синхронизацией:
        1. Инициализация БД
        2. Создание таблиц
        3. SEED (системные данные)
        4. SYNC BASE (справочники Avanpost) - СИНХРОННО!
        5. ADD USERS (добавление пользователей из настроек)
        6. SYNC USERS (пользовательские данные Avanpost) - ОПЦИОНАЛЬНО, В ФОНЕ
        """
        app_logger.debug("🗄️ Starting database...")

        # 1. Инициализация и подключение к БД
        await self.db.initialize_all()
        app_logger.debug("✅ Database initialized")

        # 2. Создание таблиц
        await self.db.init_tables(drop_first=False)
        app_logger.info("✅ Database tables created")

        # 3. Заполнение системных данных
        try:
            await self.db.seed_tables()
            app_logger.info("✅ Seed data completed")
        except Exception as e:
            app_logger.error(f"❌ Failed to seed data: {e}", exc_info=True)
            raise RuntimeError(f"Seed failed: {e}") from e

        # 4. Синхронизация базовых данных (Синхронно)
        if getattr(settings, "AVANPOST_AUTO_SYNC_ON_START", True):
            try:
                sync_force = getattr(settings, "AVANPOST_SYNC_FORCE", False)
                sync_timeout = getattr(settings, "AVANPOST_SYNC_TIMEOUT", 300)
                sync_required = getattr(settings, "AVANPOST_SYNC_REQUIRED", False)

                app_logger.debug(f"🔄 Starting Avanpost base data sync (force={sync_force}, sync=True)...")

                # ВАЖНО: Ждем завершения синхронизации справочников
                try:
                    await asyncio.wait_for(
                        self._sync_avanpost_base_data(force=sync_force),
                        timeout=sync_timeout if sync_timeout > 0 else None,
                    )
                    app_logger.info("✅ Avanpost base data sync completed successfully")
                except TimeoutError as err:
                    error_msg = f"Avanpost base sync timed out after {sync_timeout}s"
                    if sync_required:
                        raise TimeoutError(error_msg) from err
                    app_logger.error(f"❌ {error_msg}")

            except Exception as e:
                app_logger.error(f"❌ Avanpost base sync error: {e}", exc_info=True)
                if getattr(settings, "AVANPOST_SYNC_REQUIRED", False):
                    raise

        # 5. Синхронизация пользовательских данных
        if getattr(settings, "AVANPOST_SYNC_USERS", False):
            try:
                sync_force = getattr(settings, "AVANPOST_SYNC_FORCE", False)
                app_logger.debug("👤 Starting Avanpost users data sync...")

                # Запуск в фоне, чтобы не блокировать старт
                task = asyncio.create_task(
                    self._sync_avanpost_users_in_background(force=sync_force), name="avanpost_users_sync"
                )
                self._tasks.append(task)
                app_logger.info("✅ Avanpost users sync started in background")
            except Exception as e:
                app_logger.error(f"❌ Avanpost users sync error: {e}", exc_info=True)

        # 6. Инициализация LogHandlerService
        try:
            await log_handler_service.initialize()
            app_logger.info("✅ LogHandlerService initialized")
        except Exception as e:
            app_logger.error(f"❌ Failed to initialize LogHandlerService: {e}", exc_info=True)

    # ==================== СИНХРОНИЗАЦИЯ ДАННЫХ ====================

    @staticmethod
    async def _sync_avanpost_base_data(force: bool = False) -> None:
        """Синхронизация базовых данных Avanpost (справочники)."""
        try:
            from app.services.avanpost_sync_service import AvanpostSyncService

            app_logger.debug(f"🔄 Syncing Avanpost base data (force={force})...")
            sync_service = AvanpostSyncService()
            await sync_service.initialize()

            stats = await sync_service.sync_base_data(force=force)

            stats_dict = stats.to_dict() if hasattr(stats, "to_dict") else {}

            if stats_dict.get("total_inserted", 0) > 0 or stats_dict.get("total_updated", 0) > 0:
                app_logger.info(
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
        except Exception as e:
            app_logger.error(f"❌ Failed to sync base data: {e}", exc_info=True)
            raise

    @staticmethod
    async def _sync_avanpost_users(force: bool = False) -> None:
        """Синхронизация пользовательских данных Avanpost."""
        try:
            from app.services.avanpost_sync_service import AvanpostSyncService

            app_logger.debug(f"👤 Syncing Avanpost user data (force={force})...")
            sync_service = AvanpostSyncService()
            await sync_service.initialize()
            await sync_service.sync_all_users(force=force)

        except ImportError as e:
            app_logger.warning(f"⚠️ Sync service not available: {e}")
        except Exception as e:
            app_logger.error(f"❌ Failed to sync users: {e}", exc_info=True)
            raise

    async def _sync_avanpost_users_in_background(self, force: bool = False) -> None:
        """Фоновая синхронизация пользовательских данных Avanpost."""
        try:
            app_logger.debug("👤 Starting Avanpost users sync in background...")
            await self._sync_avanpost_users(force=force)
            app_logger.info("✅ Avanpost users background sync completed")
        except asyncio.CancelledError:
            app_logger.debug("ℹ️ Avanpost users sync cancelled")
            raise
        except Exception as e:
            app_logger.error(f"❌ Avanpost users background sync failed: {e}", exc_info=True)

    # ==================== ЗАПУСК API ====================

    async def _start_api(self) -> None:
        """Запуск API компонента"""
        app_logger.debug("🌐 Starting API...")

        if hasattr(self.api, "initialize") and callable(self.api.initialize):
            await self.api.initialize()
        else:
            app_logger.debug("ℹ️ API initialize not needed or not available")

        # Создание задачи для запуска API
        if hasattr(self.api, "start") and callable(self.api.start):
            api_start_coro = self.api.start()
            if asyncio.iscoroutine(api_start_coro):
                task: asyncio.Task[Any] = asyncio.create_task(api_start_coro, name="api_server")
                self._tasks.append(task)
            else:
                app_logger.warning("⚠️ API start is not a coroutine, skipping")

    # ==================== ЗАПУСК БОТА ====================

    async def _start_bot(self) -> None:
        """Запуск Bot компонента"""
        app_logger.debug("🤖 Starting Bot...")

        # Запуск бота
        if hasattr(self.bot, "start") and callable(self.bot.start):
            bot_start_coro = self.bot.start()
            if asyncio.iscoroutine(bot_start_coro):
                task: asyncio.Task[Any] = asyncio.create_task(bot_start_coro, name="bot_main")
                self._tasks.append(task)

        # Запуск проверки напоминаний
        await asyncio.sleep(2)
        await self._start_reminder_checker()

        # Запуск сервиса времени жизни сообщений
        try:
            from ..services.message_lifetime_service import message_lifetime_service

            await message_lifetime_service.start()
            app_logger.info("✅ MessageLifetimeService started")
        except Exception as e:
            app_logger.error(f"❌ Failed to start MessageLifetimeService: {e}")

        app_logger.info("✅ Bot started")

    # ==================== ПРОВЕРКА НАПОМИНАНИЙ ====================

    async def _start_reminder_checker(self) -> None:
        """Запуск фоновой проверки напоминаний"""
        app_logger.debug("⏰ Starting reminder checker...")

        task: asyncio.Task[Any] = asyncio.create_task(self._reminder_check_loop(), name="reminder_checker")
        self._tasks.append(task)
        app_logger.info(
            f"✅ Reminder checker started (interval: {self.REMINDER_CHECK_INTERVAL}s, batch: {self.REMINDER_BATCH_SIZE})"
        )

    async def _reminder_check_loop(self) -> None:
        """Основной цикл проверки напоминаний"""
        app_logger.debug("🔄 Reminder check loop started")

        while self.is_running:
            try:
                await self._check_and_send_reminders()

                # Ожидание до следующей проверки с возможностью прерывания
                try:
                    await asyncio.sleep(self.REMINDER_CHECK_INTERVAL)
                except asyncio.CancelledError:
                    app_logger.debug("⏰ Reminder checker cancelled during sleep")
                    break

            except asyncio.CancelledError:
                app_logger.debug("⏰ Reminder checker cancelled")
                break

            except Exception as e:
                app_logger.error(f"❌ Reminder checker error: {e}", exc_info=True)
                await asyncio.sleep(self.REMINDER_CHECK_INTERVAL)

        app_logger.debug("⏰ Reminder check loop finished")

    async def _check_and_send_reminders(self) -> None:
        """Проверка и отправка наступивших напоминаний"""
        try:
            now = datetime_now()
            app_logger.debug(f"⏰ Checking reminders at {now}")

            async with self.db.get_session() as session:
                # Получаем активные напоминания
                reminders = await ReminderRepository.get_active_reminders(
                    session=session,
                    before_time=now,
                    limit=self.REMINDER_BATCH_SIZE,
                )

                if not reminders:
                    return

                app_logger.info(f"⏰ Found {len(reminders)} reminders to process")

                # Преобразование модели в DTO и отправление уведомления
                from app.dtos.reminder import ReminderNotificationDTO

                for reminder in reminders:
                    try:
                        # Создание DTO из модели
                        reminder_dto = ReminderNotificationDTO.from_model(reminder)

                        # Отправление уведомление через сервис с DTO
                        await reminder_notification_service.send_notification(reminder=reminder_dto, session=session)

                    except Exception as e:
                        app_logger.error(f"❌ Failed to process reminder {reminder.FID}: {e}", exc_info=True)
                        continue

        except Exception as e:
            app_logger.error(f"❌ Failed to check reminders: {e}", exc_info=True)
            raise

    # ==================== ОСТАНОВКА ====================

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
        app_logger.debug("🚀 Application Stopped starting...")

        to_stop = self._validate_components(components)
        app_logger.debug(f"📋 Components to stop: {to_stop}")

        try:
            for component in self.COMPONENT_ORDER_STOP:
                if component in to_stop:
                    await self._stop_component(component, graceful)

            # Останавливаем LogHandlerService в последнюю очередь
            await self._stop_log_handler(graceful)

            if graceful:
                await self._cancel_tasks_gracefully()
            else:
                await self._cancel_tasks_force()

            self._state = AppState.STOPPED
            self._start_time = None
            app_logger.debug(f"✅ Application stopped successfully (components: {', '.join(to_stop)})")

        except Exception as e:
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
        """Остановка LogHandlerService"""
        app_logger.debug("🚀 Stopping LogHandlerService...")
        try:
            if hasattr(log_handler_service, "set_shutting_down"):
                await log_handler_service.set_shutting_down(True)

            if hasattr(log_handler_service, "shutdown") and callable(log_handler_service.shutdown):
                await log_handler_service.shutdown()

            app_logger.info("⛔ LogHandlerService stopped")
        except Exception as e:
            app_logger.error(f"❌ Failed to stop LogHandlerService: {e}")
            if not graceful:
                raise

    async def _stop_api(self, graceful: bool = True) -> None:
        app_logger.debug("🚀 API Stopped starting...")
        try:
            if hasattr(self.api, "is_running") and self.api.is_running:
                if hasattr(self.api, "stop") and callable(self.api.stop):
                    await self.api.stop()
            else:
                app_logger.debug("ℹ️ API was not running")
        except Exception as e:
            app_logger.error(f"❌ Failed to stop API: {e}")
            if not graceful:
                raise

    async def _stop_bot(self, graceful: bool = True) -> None:
        """Остановка Bot компонента"""
        app_logger.debug("🚀 Bot Stopped starting...")

        # Остановка сервиса времени жизни сообщений
        try:
            from ..services.message_lifetime_service import message_lifetime_service

            if hasattr(message_lifetime_service, "stop") and callable(message_lifetime_service.stop):
                await message_lifetime_service.stop()
                app_logger.info("⛔ MessageLifetimeService stopped")
        except Exception as e:
            app_logger.error(f"❌ Failed to stop MessageLifetimeService: {e}")

        try:
            if hasattr(self.bot, "stop") and callable(self.bot.stop):
                await self.bot.stop()
                app_logger.info("⛔ Bot stopped")
        except Exception as e:
            app_logger.error(f"❌ Failed to stop Bot: {e}")
            if not graceful:
                raise

    async def _stop_database(self, graceful: bool = True) -> None:
        app_logger.debug("🚀 Stopping database starting...")
        try:
            # Останавливаем LogHandlerService перед закрытием БД
            await self._stop_log_handler(graceful)
            if hasattr(self.db, "close_all") and callable(self.db.close_all):
                await self.db.close_all()
            app_logger.info("⛔ Database stopped")
        except Exception as e:
            app_logger.error(f"❌ Failed to stop database: {e}")
            if not graceful:
                raise

    async def _emergency_stop(self) -> None:
        app_logger.warning("🚨 Emergency stop initiated...")

        # Останавливаем LogHandlerService в первую очередь при аварийной остановке
        try:
            await self._stop_log_handler(graceful=False)
        except Exception as e:
            app_logger.error(f"❌ Emergency stop failed for LogHandlerService: {e}")

        for component in self.COMPONENT_ORDER_STOP:
            try:
                await self._stop_component(component, graceful=False)
            except Exception as e:
                app_logger.error(f"❌ Emergency stop failed for {component}: {e}")

        await self._cancel_tasks_force()

        self._state = AppState.STOPPED
        self._start_time = None
        app_logger.info("✅ Emergency stop completed")

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

    @log_exceptions(app_logger)
    async def restart(self, components: list[str] | None = None) -> None:
        app_logger.info("🔄 Application restarting...")
        await self.stop(components, graceful=True)
        await asyncio.sleep(1)
        await self.start(components)
        app_logger.info("✅ Application restarted")

    @log_exceptions(app_logger)
    async def get_status(self) -> dict[str, Any]:
        # Получение статуса базы данных
        db_status = {}
        if hasattr(self.db, "get_stats") and callable(self.db.get_stats):
            try:
                db_status = await self.db.get_stats()
            except Exception:
                db_status = {"error": "Failed to get stats"}

        # Получение статуса API
        api_status = {}
        if hasattr(self.api, "get_status") and callable(self.api.get_status):
            try:
                api_status = await self.api.get_status()
            except Exception:
                api_status = {"error": "Failed to get status"}

        # Получение статуса бота
        bot_status = {}
        if hasattr(self.bot, "get_status") and callable(self.bot.get_status):
            try:
                bot_status = await self.bot.get_status()
            except Exception:
                bot_status = {"error": "Failed to get status"}

        # Получение статуса LogHandler
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
        # Проверка базы данных
        db_health = False
        if hasattr(self.db, "check_connection") and callable(self.db.check_connection):
            try:
                db_health = await self.db.check_connection()
            except Exception:
                db_health = False

        # Проверка API
        api_health = False
        if hasattr(self.api, "is_running"):
            api_health = bool(self.api.is_running)

        # Проверка бота
        bot_health = False
        if hasattr(self.bot, "health_check") and callable(self.bot.health_check):
            try:
                result = await self.bot.health_check()
                if isinstance(result, dict):
                    bot_health = result.get("is_running", False) or result.get("manager_running", False)
                else:
                    bot_health = bool(result)
            except Exception:
                bot_health = False
        elif hasattr(self.bot, "is_running"):
            bot_health = bool(self.bot.is_running)

        log_handler_health = getattr(log_handler_service, "_initialized", False)

        return {
            "app": self.is_running,
            "database": db_health,
            "api": api_health,
            "bot": bot_health,
            "log_handler": log_handler_health,
        }

    async def __aenter__(self) -> "ApplicationManager":
        await self.start()
        return self

    async def __aexit__(self, exc_type: Any, exc_val: Any, exc_tb: Any) -> None:
        await self.stop()

    def __repr__(self) -> str:
        uptime_str = f"{self.uptime:.1f}s" if self.uptime is not None else "N/A"
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
