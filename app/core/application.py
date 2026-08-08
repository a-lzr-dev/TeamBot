import asyncio
from datetime import timedelta
from enum import StrEnum
from typing import Any, Optional

from ..api.manager import api_manager
from ..config import settings
from ..db.manager import db_manager
from ..db.repositories import ReminderRepository
from ..exceptions import log_exceptions
from ..logger import app_logger
from ..models import MessageType, ReminderModel, datetime_now
from ..services.log_handler_service import log_handler_service
from ..tg.manager import tg_manager


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

    VALID_COMPONENTS: set[str] = {"db", "api", "tg"}
    COMPONENT_ORDER_START: list[str] = ["db", "api", "tg"]
    COMPONENT_ORDER_STOP: list[str] = ["api", "tg", "db"]

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
        self.tg = tg_manager

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
        elif component == "tg":
            await self._start_telegram()
        else:
            app_logger.warning(f"⚠️ Unknown component: {component}")

    async def _start_database(self) -> None:
        app_logger.debug("🗄️ Starting database...")
        await self.db.initialize_all()
        await self.db.init_tables(drop_first=False)
        app_logger.info("✅ Database started")

        # Инициализация LogHandlerService
        try:
            await log_handler_service.initialize()
        except Exception as e:
            app_logger.error(f"❌ Failed to initialize LogHandlerService: {e}", exc_info=True)

    async def _start_api(self) -> None:
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

    async def _start_telegram(self) -> None:
        """Запуск Telegram компонента"""
        app_logger.debug("🤖 Starting Telegram...")

        # Запуск бота
        if hasattr(self.tg, "start") and callable(self.tg.start):
            tg_start_coro = self.tg.start()
            if asyncio.iscoroutine(tg_start_coro):
                task: asyncio.Task[Any] = asyncio.create_task(tg_start_coro, name="telegram_bot")
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

        app_logger.info("✅ Telegram started")

    # ============ ПРОВЕРКА НАПОМИНАНИЙ ============

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

            async with self.db.get_session() as session, session.begin():
                reminders = await ReminderRepository.get_active_reminders(
                    session=session,
                    before_time=now,
                    limit=self.REMINDER_BATCH_SIZE,
                )

                if not reminders:
                    return

                app_logger.info(f"⏰ Found {len(reminders)} reminders to process")

                for reminder in reminders:
                    try:
                        # Отправка уведомления
                        await self._send_reminder_notification(reminder)

                        # Обновление статуса через репозиторий
                        remind_count = reminder.FRemindCount + 1
                        last_reminded = now
                        is_active = True
                        new_remind_at = None

                        # Определение, нужно ли деактивировать напоминание
                        should_deactivate = False

                        if reminder.FMaxRemindCount and remind_count >= reminder.FMaxRemindCount:
                            should_deactivate = True
                            app_logger.debug(f"⏰ Reminder {reminder.FID} deactivated (max count reached)")
                        elif reminder.FRemindUntil and now > reminder.FRemindUntil:
                            should_deactivate = True
                            app_logger.debug(f"⏰ Reminder {reminder.FID} deactivated (until date passed)")

                        if not should_deactivate and reminder.FRemindInterval and reminder.FRemindInterval > 0:
                            new_remind_at = now + timedelta(minutes=reminder.FRemindInterval)
                            app_logger.debug(f"⏰ Reminder {reminder.FID} rescheduled to {new_remind_at}")
                        elif not should_deactivate:
                            should_deactivate = True
                            app_logger.debug(f"⏰ Reminder {reminder.FID} deactivated (one-time)")

                        if should_deactivate:
                            is_active = False

                        await ReminderRepository.update_reminder_status(
                            session=session,
                            reminder_id=reminder.FID,
                            remind_count=remind_count,
                            last_reminded=last_reminded,
                            is_active=is_active,
                            remind_at=new_remind_at,
                        )

                    except Exception as e:
                        app_logger.error(f"❌ Failed to process reminder {reminder.FID}: {e}", exc_info=True)
                        # session.begin() автоматически откатит транзакцию при ошибке
                        continue

        except Exception as e:
            app_logger.error(f"❌ Failed to check reminders: {e}", exc_info=True)
            raise

    async def _send_reminder_notification(self, reminder: ReminderModel) -> None:
        """Отправка уведомления о напоминании"""
        try:
            # Формирование текста уведомления
            message = self._format_reminder_message(reminder)

            # Отправка в зависимости от типа уведомления
            notification_type = getattr(reminder, "FNotificationType", "private")

            if notification_type in ["private", "both"]:
                # В личные сообщения пользователю
                try:
                    await tg_manager.send_message(
                        chat_id=reminder.FK_User, message_type=MessageType.REMINDER, text=message, parse_mode="Markdown"
                    )
                    app_logger.debug(f"📨 Sent private reminder to {reminder.FK_User}")
                except Exception as e:
                    app_logger.error(f"❌ Failed to send private reminder to {reminder.FK_User}: {e}")

            if notification_type in ["group", "both"] and reminder.FK_Chat:
                # В групповой чат
                try:
                    await tg_manager.send_message(
                        chat_id=reminder.FK_Chat, message_type=MessageType.REMINDER, text=message, parse_mode="Markdown"
                    )
                    app_logger.debug(f"📨 Sent group reminder to {reminder.FK_Chat}")
                except Exception as e:
                    app_logger.error(f"❌ Failed to send group reminder to {reminder.FK_Chat}: {e}")

        except Exception as e:
            app_logger.error(f"❌ Failed to send reminder notification: {e}", exc_info=True)
            raise

    @staticmethod
    def _format_reminder_message(reminder: ReminderModel) -> str:
        """Форматирование сообщения для напоминания"""
        message = "🔔 **Напоминание!**\n\n"
        message += f"📌 **{reminder.FTitle or 'Без названия'}**\n"

        if reminder.FDescription:
            message += f"📝 {reminder.FDescription}\n"

        if reminder.FCategory:
            message += f"📂 Категория: {reminder.FCategory}\n"

        # Информация о повторениях
        if reminder.FRemindCount > 0:
            message += f"🔄 Повтор: {reminder.FRemindCount + 1}"

            if reminder.FMaxRemindCount:
                message += f" (макс. {reminder.FMaxRemindCount})"
            message += "\n"

        # Информация о следующем напоминании
        if reminder.FIsActive and reminder.FRemindInterval and reminder.FRemindInterval > 0:
            next_time = reminder.FRemindAt + timedelta(minutes=reminder.FRemindInterval)
            message += f"⏰ Следующее: {next_time.strftime('%d.%m.%Y %H:%M')}\n"

        # Добавление инструкции
        message += "\n✅ Для завершения дела используйте /complete"

        return message

    # ============ ОСТАНОВКА ============

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

            # Останавливаение LogHandlerService в последнюю очередь
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
        elif component == "tg":
            await self._stop_telegram(graceful)
        elif component == "db":
            await self._stop_database(graceful)
        else:
            app_logger.warning(f"⚠️ Unknown component: {component}")

    @staticmethod
    async def _stop_log_handler(graceful: bool = True) -> None:
        """Остановка LogHandlerService"""
        app_logger.debug("🚀 Stopping LogHandlerService...")
        try:
            # Проверка наличия атрибутов перед использованием
            if hasattr(log_handler_service, "_shutting_down"):
                log_handler_service._shutting_down = True

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

    async def _stop_telegram(self, graceful: bool = True) -> None:
        """Остановка Telegram компонента"""
        app_logger.debug("🚀 Telegram Stopped starting...")

        # Остановка сервиса времени жизни сообщений
        try:
            from ..services.message_lifetime_service import message_lifetime_service

            if hasattr(message_lifetime_service, "stop") and callable(message_lifetime_service.stop):
                await message_lifetime_service.stop()
                app_logger.info("⛔ MessageLifetimeService stopped")
        except Exception as e:
            app_logger.error(f"❌ Failed to stop MessageLifetimeService: {e}")

        try:
            if hasattr(self.tg, "stop") and callable(self.tg.stop):
                await self.tg.stop()
                app_logger.info("⛔ Telegram stopped")
        except Exception as e:
            app_logger.error(f"❌ Failed to stop Telegram: {e}")
            if not graceful:
                raise

    async def _stop_database(self, graceful: bool = True) -> None:
        app_logger.debug("🚀 Stopping database starting...")
        try:
            # Останавка LogHandlerService перед закрытием БД
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

        # Получение статуса Telegram
        tg_status = {}
        if hasattr(self.tg, "get_status") and callable(self.tg.get_status):
            try:
                tg_status = await self.tg.get_status()
            except Exception:
                tg_status = {"error": "Failed to get status"}

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
            "telegram": tg_status,
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

        # Проверка Telegram
        tg_health = False
        if hasattr(self.tg, "health_check") and callable(self.tg.health_check):
            try:
                result = await self.tg.health_check()
                if isinstance(result, dict):
                    tg_health = result.get("is_running", False) or result.get("manager_running", False)
                else:
                    tg_health = bool(result)
            except Exception:
                tg_health = False
        elif hasattr(self.tg, "is_running"):
            tg_health = bool(self.tg.is_running)

        log_handler_health = getattr(log_handler_service, "_initialized", False)

        return {
            "app": self.is_running,
            "database": db_health,
            "api": api_health,
            "telegram": tg_health,
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
