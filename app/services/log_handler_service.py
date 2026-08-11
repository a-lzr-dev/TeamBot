import asyncio
import contextlib
import logging
import sys
import traceback
from typing import TYPE_CHECKING, Any

from ..config import settings
from ..logger import app_logger
from ..models import ErrorCategory, ErrorSeverity, ErrorStatus, MessageType, datetime_now
from ..tg.dependencies import get_tg_manager
from .error_service import error_service

if TYPE_CHECKING:
    from datetime import datetime


class LogHandlerService:
    """Сервис-мост для обработки логов уровня ERROR и CRITICAL"""

    def __init__(self) -> None:
        self._initialized = False
        self._shutting_down = False
        self._error_cache: dict[str, datetime] = {}
        self._cache_ttl = getattr(settings, "LOG_ERROR_NOTIFICATION_INTERVAL", 60)
        self._error_handling = False
        self._handler: logging.Handler | None = None
        self._queue: asyncio.Queue = asyncio.Queue(maxsize=getattr(settings, "LOG_QUEUE_MAX_SIZE", 1000))
        self._worker_task: asyncio.Task | None = None
        self._is_worker_running = False
        self._notification_stats: dict[str, int] = {
            "total_errors": 0,
            "sent_notifications": 0,
            "failed_notifications": 0,
            "cache_hits": 0,
        }

    @property
    def is_initialized(self) -> bool:
        """Проверка, инициализирован ли сервис"""
        return self._initialized

    async def initialize(self) -> None:
        """Инициализация сервиса"""
        if self._initialized:
            return

        self._setup_log_handler()
        self._initialized = True
        self._shutting_down = False

        self._worker_task = asyncio.create_task(self._worker_loop())

        app_logger.info("✅ LogHandlerService initialized")

    async def send_notification(self, error_model: Any) -> None:
        """
        Отправка уведомления об ошибке в чаты техподдержки.

        Args:
            error_model: Модель ошибки
        """
        if self._shutting_down or not self._initialized:
            app_logger.debug("ℹ️ Service is shutting down or not initialized, skipping notification")
            return
        await self._send_notification(error_model)

    def _setup_log_handler(self) -> None:
        """Настройка обработчика для перехвата логов"""
        if self._handler:
            return

        class SyncLogHandler(logging.Handler):
            def emit(self, record: logging.LogRecord) -> None:
                with contextlib.suppress(asyncio.QueueFull):
                    log_handler_service._queue.put_nowait(record)

        self._handler = SyncLogHandler()
        self._handler.setLevel(logging.ERROR)

        root_logger = logging.getLogger()
        root_logger.addHandler(self._handler)

        app_logger.debug("✅ Log handler attached to root logger")

    async def _worker_loop(self) -> None:
        """Фоновый воркер для обработки логов из очереди"""
        app_logger.debug("🔄 LogHandler worker started")
        self._is_worker_running = True

        worker_timeout = getattr(settings, "LOG_WORKER_TIMEOUT", 0.3)

        try:
            while self._initialized and not self._shutting_down:
                try:
                    try:
                        record = await asyncio.wait_for(self._queue.get(), timeout=worker_timeout)
                    except TimeoutError:
                        continue

                    if self._shutting_down or not self._initialized:
                        app_logger.debug("⏹️ Shutdown detected, discarding record")
                        self._queue.task_done()
                        break

                    await self._handle_log_record(record)
                    self._queue.task_done()

                except asyncio.CancelledError:
                    app_logger.debug("⏹️ LogHandler worker cancelled")
                    break
                except Exception as e:
                    app_logger.error(f"❌ LogHandler worker error: {e}", exc_info=True)
                    await asyncio.sleep(0.5)

        finally:
            self._is_worker_running = False
            app_logger.debug("⏹️ LogHandler worker finished")

    async def _handle_log_record(self, record: logging.LogRecord) -> None:
        """Обработка записи лога"""
        if self._shutting_down or not self._initialized:
            app_logger.debug("ℹ️ Shutdown detected, skipping log record")
            return

        try:
            if record.levelno < logging.ERROR:
                return

            self._notification_stats["total_errors"] += 1

            # Проверка кеша
            cache_key = self._get_cache_key(record)
            if cache_key in self._error_cache:
                last_sent = self._error_cache[cache_key]
                if (datetime_now() - last_sent).total_seconds() < self._cache_ttl:
                    self._notification_stats["cache_hits"] += 1
                    return

            error_message = record.getMessage()
            traceback_text = None

            if record.exc_info:
                error_obj = record.exc_info[1] if record.exc_info[1] else Exception(error_message)
                if not isinstance(error_obj, Exception):
                    error_obj = Exception(str(error_obj))
                tb_lines = traceback.format_exception(*record.exc_info)
                traceback_text = "".join(tb_lines)[:1000]
            else:
                error_obj = Exception(error_message)

            category = self._determine_category(record.name)
            severity = self._determine_severity(record.levelno)

            context = getattr(record, "extra", {}) or {}
            context.update(
                {
                    "logger_name": record.name,
                    "level": record.levelname,
                    "filename": record.filename,
                    "lineno": record.lineno,
                    "funcName": record.funcName,
                }
            )

            # Логирование ошибки через error_service
            error_model, chat_message = await error_service.log_error(
                error=error_obj,
                session=None,
                component=record.name,
                user_id=context.get("user_id"),
                chat_id=context.get("chat_id"),
                category=category,
                severity=severity,
                context={
                    "traceback": traceback_text,
                    "logger_name": record.name,
                    "level": record.levelname,
                    "filename": record.filename,
                    "lineno": record.lineno,
                    "funcName": record.funcName,
                    **context,
                },
            )

            if error_model and not self._shutting_down and self._initialized:
                try:
                    await self._send_notification(error_model)
                    self._notification_stats["sent_notifications"] += 1
                except asyncio.CancelledError:
                    app_logger.debug("ℹ️ _send_notification cancelled in _handle_log_record")
                    raise
                except Exception as e:
                    self._notification_stats["failed_notifications"] += 1
                    app_logger.error(f"❌ Failed to send notification: {e}")

            self._error_cache[cache_key] = datetime_now()
            self._cleanup_cache()

        except asyncio.CancelledError:
            app_logger.debug("ℹ️ _handle_log_record cancelled")
            raise
        except Exception as e:
            if not self._error_handling:
                self._error_handling = True
                try:
                    print(f"❌ Failed to handle log record: {e}", file=sys.stderr)
                finally:
                    self._error_handling = False

    @staticmethod
    def _get_cache_key(record: logging.LogRecord) -> str:
        """Создание ключа для кеша"""
        msg = record.getMessage()
        return f"{record.name}:{msg[:100]}"

    def _cleanup_cache(self) -> None:
        """Очистка кеша"""
        if len(self._error_cache) > 1000:
            now = datetime_now()
            expired = [
                key for key, value in self._error_cache.items() if (now - value).total_seconds() > self._cache_ttl * 3
            ]
            for key in expired:
                del self._error_cache[key]

    @staticmethod
    def _determine_category(logger_name: str) -> ErrorCategory:
        """Определение категории по имени логгера"""
        logger_lower = logger_name.lower()

        category_map = {
            "api": ErrorCategory.TASK_EXECUTION,
            "tg": ErrorCategory.TASK_EXECUTION,
            "telegram": ErrorCategory.TASK_EXECUTION,
            "db": ErrorCategory.SYSTEM,
            "database": ErrorCategory.SYSTEM,
            "admin": ErrorCategory.SYSTEM,
            "core": ErrorCategory.SYSTEM,
            "service": ErrorCategory.SYSTEM,
        }

        for key, category in category_map.items():
            if key in logger_lower:
                return category
        return ErrorCategory.ARBITRARY

    @staticmethod
    def _determine_severity(level: int) -> ErrorSeverity:
        """Определение серьезности по уровню лога"""
        if level >= logging.CRITICAL:
            return ErrorSeverity.CRITICAL
        elif level >= logging.ERROR:
            return ErrorSeverity.ERROR
        elif level >= logging.WARNING:
            return ErrorSeverity.WARNING
        else:
            return ErrorSeverity.INFO

    async def _send_notification(self, error_model: Any) -> None:
        """
        Отправка уведомления об ошибке в чат техподдержки.

        Поддерживает отправку в разные топики в зависимости от источника ошибки:
        - Globus → топик Globus
        - TeamBot → топик TeamBot
        - Avanpost → топик Avanpost
        - Jobs → топик Jobs
        - SyncFrom1C → топик SyncFrom1C
        - Unknown → основной чат (без топика)
        """
        if self._shutting_down or not self._initialized:
            app_logger.debug("ℹ️ Service is shutting down, skipping notification")
            return

        try:
            chat_id = getattr(settings, "SUPPORT_CHAT_ID", 0)
            topic_mapping = getattr(settings, "SUPPORT_CHAT_TOPIC_IDS", {})

            # Проверка настроек
            if not chat_id:
                app_logger.warning("⚠️ SUPPORT_CHAT_ID not configured, skipping notification")
                return

            if not topic_mapping:
                app_logger.warning("⚠️ SUPPORT_CHAT_TOPIC_IDS not configured, skipping notification")
                return

            message = self._format_notification(error_model)

            source = error_model.FSourceSystem or "Unknown"
            topic_id = topic_mapping.get(source)
            lifetime_seconds = getattr(settings, "ERROR_MESSAGE_LIFETIME_SECONDS", 604800)

            try:
                status = await asyncio.shield(get_tg_manager().get_status())
                if not status.get("is_running", False):
                    app_logger.warning("⚠️ Telegram manager not running, skipping notification")
                    return
            except asyncio.CancelledError:
                app_logger.debug("ℹ️ get_status cancelled during shutdown")
                return
            except Exception as e:
                app_logger.warning(f"⚠️ Failed to check tg_manager status: {e}")
                return

            if self._shutting_down:
                app_logger.debug("ℹ️ Shutdown detected, cancelling notification sending")
                return

            tg_manager = get_tg_manager()

            # Подготавка параметров к отправке
            send_kwargs = {
                "chat_id": chat_id,
                "text": message,
                "message_type": MessageType.SYSTEM_ALERT,
                "parse_mode": "HTML",
                "disable_notification": False,
                "lifetime_seconds": lifetime_seconds,
            }

            # Добавление топика, если он найден
            if topic_id:
                send_kwargs["message_thread_id"] = topic_id
                app_logger.debug(f"📨 Sending notification to topic {topic_id} in chat {chat_id} (source: {source})")
            else:
                app_logger.debug(f"📨 Sending notification to chat {chat_id} (no specific topic for source: {source})")

            try:
                result = await asyncio.shield(tg_manager.send_message(**send_kwargs))

                if result.get("success"):
                    self._notification_stats["sent_notifications"] += 1
                    if topic_id:
                        app_logger.info(f"✅ Error notification sent to topic {topic_id} (source: {source})")
                    else:
                        app_logger.info(f"✅ Error notification sent to chat {chat_id}")
                else:
                    self._notification_stats["failed_notifications"] += 1
                    app_logger.warning(f"⚠️ Failed to send notification: {result.get('error')}")
            except asyncio.CancelledError:
                app_logger.debug("ℹ️ send_message cancelled during shutdown")
            except Exception as e:
                self._notification_stats["failed_notifications"] += 1
                if topic_id:
                    app_logger.error(f"❌ Failed to send to topic {topic_id}: {e}")
                else:
                    app_logger.error(f"❌ Failed to send to chat {chat_id}: {e}")

        except asyncio.CancelledError:
            app_logger.debug("ℹ️ _send_notification cancelled")
            raise
        except Exception as e:
            app_logger.error(f"❌ Failed to send notification: {e}")

    @staticmethod
    def _format_notification(error: Any) -> str:
        """Форматирование сообщения для чата техподдержки (HTML)"""

        severity_emoji = {
            ErrorSeverity.CRITICAL: "🚨",
            ErrorSeverity.ERROR: "❌",
            ErrorSeverity.WARNING: "⚠️",
            ErrorSeverity.INFO: "ℹ️",
        }.get(error.FSeverity, "📌")

        status_emoji = {
            ErrorStatus.NEW: "🆕",
            ErrorStatus.IN_PROGRESS: "🔄",
            ErrorStatus.RESOLVED: "✅",
            ErrorStatus.DISMISSED: "⏭️",
            ErrorStatus.REOPENED: "🔁",
        }.get(error.FStatus, "❌")

        # Экранирование для HTML
        def escape_html(text: str) -> str:
            """Экранирование основных спецсимволов для HTML"""
            if not text:
                return ""
            return (
                text.replace("&", "&amp;")
                .replace("<", "&lt;")
                .replace(">", "&gt;")
                .replace('"', "&quot;")
                .replace("'", "&#39;")
            )

        # Экранируем только те поля, которые могут содержать спецсимволы
        error_code = escape_html(error.FErrorCode or "")
        error_message = escape_html(error.FErrorMessage[:300] if error.FErrorMessage else "")
        error_details = escape_html(error.FErrorDetails[:300] if error.FErrorDetails else "")
        source_system = escape_html(error.FSourceSystem or "")
        source_module = escape_html(error.FSourceModule or "") if error.FSourceModule else ""

        message = f"{severity_emoji} <b>Ошибка в логах приложения</b>\n\n"
        message += f"{status_emoji} <b>ID:</b> #{error.FID}\n"
        message += f"📊 <b>Уровень:</b> <code>{error.FSeverity.value.upper()}</code>\n"
        message += f"🔑 <b>Код:</b> <code>{error_code}</code>\n\n"
        message += f"📝 <b>Сообщение:</b>\n<pre>{error_message}</pre>\n"

        if error.FErrorDetails:
            message += f"📎 <b>Детали:</b>\n<pre>{error_details}</pre>\n"

        message += f"🖥️ <b>Система:</b> {source_system}\n"

        if source_module:
            message += f"📦 <b>Модуль:</b> {source_module}\n"

        if error.FUserID:
            message += f"👤 <b>User ID:</b> {error.FUserID}\n"

        if error.FCountOccurrences > 1:
            message += f"🔄 <b>Повторов:</b> {error.FCountOccurrences}\n"

        message += f"\n📅 <b>Время:</b> {error.FLastOccurrence.strftime('%d.%m.%Y %H:%M:%S')}\n\n"
        message += f"🔗 Используйте <code>/resolve_{error.FID}</code> для отметки как решенное"

        return message

    async def shutdown(self) -> None:
        """Корректное завершение сервиса"""
        app_logger.debug("🚀 Stopping LogHandlerService...")

        self._shutting_down = True
        self._initialized = False

        # Удаление обработчика из корневого логгера
        if self._handler:
            try:
                root_logger = logging.getLogger()
                root_logger.removeHandler(self._handler)
                app_logger.debug("✅ Log handler removed from root logger")
            except Exception as e:
                print(f"⚠️ Could not remove handler from root logger: {e}", file=sys.stderr)

            self._handler = None

        # Очистка очереди
        cleared = 0
        while not self._queue.empty():
            try:
                self._queue.get_nowait()
                self._queue.task_done()
                cleared += 1
            except asyncio.QueueEmpty:
                break

        if cleared > 0:
            app_logger.debug(f"🧹 Cleared {cleared} pending log records")

        # Остановка воркера
        if self._worker_task and not self._worker_task.done():
            app_logger.debug("⏳ Waiting for worker task to finish...")
            self._worker_task.cancel()
            try:
                await asyncio.wait_for(self._worker_task, timeout=1.0)
                app_logger.debug("✅ Worker task finished")
            except TimeoutError:
                app_logger.warning("⚠️ Worker task did not finish in time, forcing cancel")
                self._worker_task.cancel()
                await asyncio.sleep(0.1)
            except asyncio.CancelledError:
                app_logger.debug("✅ Worker task cancelled")
            except Exception as e:
                app_logger.error(f"❌ Error waiting for worker task: {e}")

        self._worker_task = None
        self._is_worker_running = False

        # Логирование финальной статистики
        app_logger.info(
            f"📊 LogHandlerService stats: "
            f"total_errors={self._notification_stats['total_errors']}, "
            f"sent={self._notification_stats['sent_notifications']}, "
            f"failed={self._notification_stats['failed_notifications']}, "
            f"cache_hits={self._notification_stats['cache_hits']}"
        )

        app_logger.info("⛔ LogHandlerService shut down")

    async def get_stats(self) -> dict[str, int]:
        """
        Получение статистики работы сервиса.

        Returns:
            dict: Статистика
        """
        return {
            "total_errors": self._notification_stats.get("total_errors", 0),
            "sent_notifications": self._notification_stats.get("sent_notifications", 0),
            "failed_notifications": self._notification_stats.get("failed_notifications", 0),
            "cache_hits": self._notification_stats.get("cache_hits", 0),
            "cache_size": len(self._error_cache),
            "queue_size": self._queue.qsize(),
            "is_worker_running": self._is_worker_running,
        }


log_handler_service = LogHandlerService()
