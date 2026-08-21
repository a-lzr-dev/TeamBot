from datetime import datetime, timedelta

from sqlalchemy.ext.asyncio import AsyncSession

from ..bot.dependencies import get_bot_manager
from ..db.repositories import ErrorFilterRepository, ErrorRepository, NotificationSettingsRepository
from ..logger import app_logger
from ..models import (
    ChatNotificationSettingsModel,
    ErrorCategory,
    ErrorModel,
    ErrorSeverity,
    ErrorStatus,
    MessageType,
    datetime_now,
)
from ..utils.decorators import log_exceptions


class NotificationService:
    """Сервис для управления уведомлениями"""

    def __init__(self) -> None:
        self._notification_queue: list[dict] = []
        self._processed_errors: set = set()
        self._error_cache: dict[str, datetime] = {}

    @log_exceptions(app_logger)
    async def should_notify_error(
        self,
        error: ErrorModel,
        chat_id: int,
        session: AsyncSession,
    ) -> bool:
        """
        Проверка, нужно ли отправлять уведомление об ошибке.

        Args:
            error: Ошибка
            chat_id: ID чата
            session: Сессия БД

        Returns:
            bool: Нужно ли отправлять уведомление
        """
        # Получение настроек через репозиторий
        settings = await NotificationSettingsRepository.get_by_chat_id(session, chat_id)
        if not settings:
            return True

        # Проверка режима тишины
        if settings.FSilenceEnabled and settings.FSilenceStart and settings.FSilenceEnd:
            now = datetime_now()
            current_time = now.strftime("%H:%M")

            if self._is_time_in_range(current_time, settings.FSilenceStart, settings.FSilenceEnd):
                return False

        # Проверка категории
        if not self._is_category_enabled(error.FCategory, settings):
            return False

        # Проверка уровня серьезности
        if error.FSeverity.value not in self._get_allowed_severities(settings):
            return False

        # Проверка фильтров через репозиторий
        if await ErrorFilterRepository.is_error_filtered(session, chat_id, error):
            return False

        # Проверка группировки
        if settings.FGroupingEnabled and error.FGroupHash:
            cache_key = f"{chat_id}:{error.FGroupHash}"
            last_notified = self._error_cache.get(cache_key)

            if last_notified and (datetime_now() - last_notified).seconds < settings.FGroupingWindowMinutes * 60:
                return False

            self._error_cache[cache_key] = datetime_now()

        return True

    @staticmethod
    def _is_time_in_range(current: str, start: str, end: str) -> bool:
        """
        Проверка, находится ли текущее время в диапазоне.

        Args:
            current: Текущее время (HH:MM)
            start: Начало диапазона (HH:MM)
            end: Конец диапазона (HH:MM)

        Returns:
            bool: Входит ли в диапазон
        """
        try:
            current_dt = datetime.strptime(current, "%H:%M")
            start_dt = datetime.strptime(start, "%H:%M")
            end_dt = datetime.strptime(end, "%H:%M")

            if start_dt <= end_dt:
                return start_dt <= current_dt <= end_dt
            else:
                return current_dt >= start_dt or current_dt <= end_dt
        except ValueError:
            return False

    @staticmethod
    def _is_category_enabled(category: ErrorCategory, settings: ChatNotificationSettingsModel) -> bool:
        """
        Проверка, включена ли категория ошибок.

        Args:
            category: Категория ошибки
            settings: Настройки уведомлений

        Returns:
            bool: Включена ли категория
        """
        mapping = {
            ErrorCategory.ARBITRARY: settings.FNotifyErrors,
            ErrorCategory.PERIODIC_TASK: settings.FNotifyPeriodicTasks,
            ErrorCategory.TASK_EXECUTION: settings.FNotifyTaskExecution,
            ErrorCategory.SYSTEM: settings.FNotifySystem,
            ErrorCategory.EXTERNAL: settings.FNotifyErrors,
        }
        result = mapping.get(category, True)
        return bool(result)

    @staticmethod
    def _get_allowed_severities(settings: ChatNotificationSettingsModel) -> list[str]:
        """
        Получение списка разрешенных уровней серьезности.

        Args:
            settings: Настройки уведомлений

        Returns:
            list[str]: Список разрешенных уровней
        """
        mapping = {
            ErrorSeverity.CRITICAL: ["critical"],
            ErrorSeverity.ERROR: ["critical", "error"],
            ErrorSeverity.WARNING: ["critical", "error", "warning"],
            ErrorSeverity.INFO: ["critical", "error", "warning", "info"],
        }
        return mapping.get(settings.FNotificationLevel, ["critical", "error"])

    @log_exceptions(app_logger)
    async def format_error_message(self, error: ErrorModel, include_details: bool = True) -> str:
        """
        Форматирование сообщения об ошибке для отправки.

        Args:
            error: Ошибка
            include_details: Включать детали

        Returns:
            str: Отформатированное сообщение
        """
        status_emoji = {
            ErrorStatus.NEW: "🆕",
            ErrorStatus.IN_PROGRESS: "🔄",
            ErrorStatus.RESOLVED: "✅",
            ErrorStatus.DISMISSED: "⏭️",
            ErrorStatus.REOPENED: "🔁",
        }.get(error.FStatus, "❌")

        severity_emoji = {
            ErrorSeverity.CRITICAL: "🚨",
            ErrorSeverity.ERROR: "❌",
            ErrorSeverity.WARNING: "⚠️",
            ErrorSeverity.INFO: "ℹ️",
        }.get(error.FSeverity, "📌")

        message = f"{status_emoji} **Ошибка #{error.FID}**\n"
        message += f"{severity_emoji} **{error.FSeverity.value.upper()}**\n"
        message += f"📋 **Код:** `{error.FErrorCode}`\n"
        message += f"📝 **Сообщение:** {error.FErrorMessage[:500]}\n"

        if error.FSourceSystem:
            message += f"🖥️ **Система:** {error.FSourceSystem}\n"

        if error.FSourceModule:
            message += f"📦 **Модуль:** {error.FSourceModule}\n"

        if error.FUserLogin:
            message += f"👤 **Пользователь:** {error.FUserLogin}\n"
        elif error.FUserID:
            message += f"👤 **User ID:** {error.FUserID}\n"

        if error.FCountOccurrences > 1:
            message += f"🔄 **Повторений:** {error.FCountOccurrences}\n"

        message += f"📅 **Время:** {error.FLastOccurrence.strftime('%d.%m.%Y %H:%M:%S')}\n"

        if include_details and error.FErrorDetails:
            message += f"\n📎 **Детали:**\n```\n{error.FErrorDetails[:300]}\n```\n"

        message += f"\n🔗 `/resolve_{error.FID}` - отметить как решенное"

        return message

    @log_exceptions(app_logger)
    async def generate_auto_report(self, chat_id: int, session: AsyncSession) -> str:
        """
        Генерация автоматического отчета об ошибках.

        Args:
            chat_id: ID чата
            session: Сессия БД

        Returns:
            str: Отчет в формате Markdown
        """
        now = datetime_now()
        hour_ago = now - timedelta(hours=1)
        day_start = now.replace(hour=0, minute=0, second=0, microsecond=0)

        # Получение статистики за час через репозиторий
        hour_stats = await ErrorRepository.get_stats(
            session=session,
            start_date=hour_ago,
            end_date=now,
        )

        # Получение статистики за день через репозиторий
        day_stats = await ErrorRepository.get_stats(
            session=session,
            start_date=day_start,
            end_date=now,
        )

        # Получение лидеров дня через репозиторий
        leaders = await ErrorRepository.get_top_resolvers(
            session=session,
            start_date=day_start,
            end_date=now,
            limit=5,
        )

        # Формирование отчета
        report = "📊 **Ежечасный отчет об ошибках**\n\n"
        report += f"📅 **{now.strftime('%d.%m.%Y %H:%M')}**\n\n"

        report += "**За последний час:**\n"
        report += f"• 🆕 Новых ошибок: {hour_stats.get('new', 0)}\n"
        report += f"• ✅ Решено: {hour_stats.get('resolved', 0)}\n\n"

        report += "**С начала дня:**\n"
        total = day_stats.get("total", 0)
        new = day_stats.get("new", 0)
        resolved = day_stats.get("resolved", 0)
        report += f"• 📋 Всего ошибок: {total}\n"
        report += f"• 🆕 Новых: {new}\n"
        report += f"• ✅ Решено: {resolved}\n"
        report += f"• 📈 Эффективность: {resolved / total * 100 if total else 0:.1f}%\n\n"

        if leaders:
            report += "**🏆 Лидеры дня:**\n"
            for i, leader in enumerate(leaders[:5], 1):
                name = f"{leader.get('first_name', '')} {leader.get('last_name', '')}".strip() or leader.get(
                    "username", "Unknown"
                )
                report += f"• {i}. {name} - {leader.get('solved', 0)} решено\n"

        report += "\n📌 Используйте /errors для просмотра всех ошибок"

        return report

    async def process_notification_queue(self) -> None:
        """Обработка очереди уведомлений"""
        while self._notification_queue:
            notification = self._notification_queue.pop(0)
            try:
                bot_manager = get_bot_manager()
                await bot_manager.send_message(
                    chat_id=notification["chat_id"],
                    message_type=MessageType.SYSTEM_ALERT,
                    text=notification["message"],
                    parse_mode="Markdown",
                )

                app_logger.info(f"Sent notification to chat {notification['chat_id']}")
            except Exception as e:
                app_logger.error(f"Failed to send notification: {e}")

    def add_to_queue(self, chat_id: int, message: str) -> None:
        """
        Добавление уведомления в очередь.

        Args:
            chat_id: ID чата
            message: Текст сообщения
        """
        self._notification_queue.append(
            {
                "chat_id": chat_id,
                "message": message,
            }
        )
        app_logger.debug(f"Added notification to queue for chat {chat_id}")


notification_service = NotificationService()
