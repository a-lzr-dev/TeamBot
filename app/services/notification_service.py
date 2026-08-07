import re
from datetime import datetime, timedelta
from typing import TYPE_CHECKING

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

if TYPE_CHECKING:
    from sqlalchemy.engine import Result

from ..db import db_manager
from ..exceptions import log_exceptions
from ..logger import app_logger
from ..models import (
    ChatNotificationSettingsModel,
    ErrorCategory,
    ErrorFilterModel,
    ErrorModel,
    ErrorSeverity,
    ErrorStatus,
    MessageType,
    UserModel,
    datetime_now,
)


class NotificationService:
    """Сервис для управления уведомлениями"""

    def __init__(self) -> None:
        self._notification_queue: list[dict] = []
        self._processed_errors: set = set()
        self._error_cache: dict[str, datetime] = {}

    @log_exceptions(app_logger)
    async def should_notify_error(self, error: ErrorModel, chat_id: int, session: AsyncSession | None = None) -> bool:
        """Проверка, нужно ли отправлять уведомление об ошибке"""

        if session is None:
            async with db_manager.get_session() as sess:
                return await self.should_notify_error(error, chat_id, sess)

        # Проверка настроек чата
        settings = await self._get_chat_settings(chat_id, session)
        if not settings:
            return True

        # Проверка тишины
        if settings.FSilenceEnabled and settings.FSilenceStart and settings.FSilenceEnd:
            now = datetime_now()
            current_time = now.strftime("%H:%M")

            if self._is_time_in_range(current_time, settings.FSilenceStart, settings.FSilenceEnd):
                return False

        # Проверка категории
        if not self._is_category_enabled(error.FCategory, settings):
            return False

        # Проверка уровня
        if error.FSeverity.value not in self._get_allowed_severities(settings):
            return False

        # Проверка фильтров
        if await self._is_error_filtered(error, chat_id, session):
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
        """Проверка, находится ли время в диапазоне"""
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
        """Проверка, включено ли уведомление для категории"""
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
        """Получение разрешенных уровней серьезности"""
        mapping = {
            ErrorSeverity.CRITICAL: ["critical"],
            ErrorSeverity.ERROR: ["critical", "error"],
            ErrorSeverity.WARNING: ["critical", "error", "warning"],
            ErrorSeverity.INFO: ["critical", "error", "warning", "info"],
        }
        return mapping.get(settings.FNotificationLevel, ["critical", "error"])

    @staticmethod
    async def _is_error_filtered(error: ErrorModel, chat_id: int, session: AsyncSession) -> bool:
        """Проверка, отфильтрована ли ошибка"""

        stmt = select(ErrorFilterModel).where(ErrorFilterModel.FK_Chat == chat_id, ErrorFilterModel.FIsActive.is_(True))

        result: Result = await session.execute(stmt)
        filters: list[ErrorFilterModel] = list(result.scalars().all())

        for filter_ in filters:
            # Проверка категории
            if filter_.FCategory is not None and filter_.FCategory != error.FCategory:
                continue

            # Проверка кода ошибки
            if filter_.FErrorCode is not None and filter_.FErrorCode != error.FErrorCode:
                continue

            # Проверка системы
            if filter_.FSourceSystem is not None and filter_.FSourceSystem != error.FSourceSystem:
                continue

            # Проверка паттерна
            if filter_.FPattern:
                if filter_.FIsRegex:
                    try:
                        if re.search(filter_.FPattern, error.FErrorMessage):
                            return True
                    except re.error:
                        continue
                else:
                    pattern_type = filter_.FPatternType
                    if pattern_type == "exact":
                        if error.FErrorMessage == filter_.FPattern:
                            return True
                    elif pattern_type == "contains" and filter_.FPattern.lower() in error.FErrorMessage.lower():
                        return True

        return False

    @staticmethod
    async def _get_chat_settings(chat_id: int, session: AsyncSession) -> ChatNotificationSettingsModel | None:
        """Получение настроек чата"""

        stmt = select(ChatNotificationSettingsModel).where(ChatNotificationSettingsModel.FK_Chat == chat_id)
        result: Result = await session.execute(stmt)
        settings: ChatNotificationSettingsModel | None = result.scalar_one_or_none()
        return settings

    @log_exceptions(app_logger)
    async def format_error_message(self, error: ErrorModel, include_details: bool = True) -> str:
        """Форматирование сообщения об ошибке"""

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
    async def generate_auto_report(self, chat_id: int, session: AsyncSession | None = None) -> str:
        """Генерация автоматического отчета о состоянии ошибок"""

        if session is None:
            async with db_manager.get_session() as sess:
                return await self.generate_auto_report(chat_id, sess)

        now = datetime_now()
        hour_ago = now - timedelta(hours=1)
        day_start = now.replace(hour=0, minute=0, second=0, microsecond=0)

        # Статистика за час
        hour_stmt = select(
            func.count(ErrorModel.FID).filter(ErrorModel.FStatus == ErrorStatus.NEW).label("new"),
            func.count(ErrorModel.FID)
            .filter(ErrorModel.FStatus == ErrorStatus.RESOLVED, ErrorModel.FResolvedAt >= hour_ago)
            .label("resolved"),
        ).where(ErrorModel.FCreatedAt >= hour_ago)

        hour_result: Result = await session.execute(hour_stmt)
        hour_stats = hour_result.first()

        # Статистика за день
        day_stmt = select(
            func.count(ErrorModel.FID).filter(ErrorModel.FStatus == ErrorStatus.NEW).label("new"),
            func.count(ErrorModel.FID).filter(ErrorModel.FStatus == ErrorStatus.RESOLVED).label("resolved"),
            func.count(ErrorModel.FID).label("total"),
        ).where(ErrorModel.FCreatedAt >= day_start)

        day_result: Result = await session.execute(day_stmt)
        day_stats = day_result.first()

        # Лидеры за день
        leaders_stmt = (
            select(
                UserModel.FFirstName,
                UserModel.FLastName,
                UserModel.FUserName,
                func.count(ErrorModel.FID).label("solved"),
            )
            .join(ErrorModel, ErrorModel.FResolvedBy == UserModel.FID)
            .where(ErrorModel.FResolvedAt >= day_start, ErrorModel.FStatus == ErrorStatus.RESOLVED)
            .group_by(UserModel.FID, UserModel.FFirstName, UserModel.FLastName, UserModel.FUserName)
            .order_by(func.count(ErrorModel.FID).desc())
            .limit(5)
        )

        leaders_result: Result = await session.execute(leaders_stmt)
        leaders = leaders_result.all()

        # Формирование отчета
        report = "📊 **Ежечасный отчет об ошибках**\n\n"
        report += f"📅 **{now.strftime('%d.%m.%Y %H:%M')}**\n\n"

        report += "**За последний час:**\n"
        report += f"• 🆕 Новых ошибок: {hour_stats.new or 0}\n"
        report += f"• ✅ Решено: {hour_stats.resolved or 0}\n\n"

        report += "**С начала дня:**\n"
        report += f"• 📋 Всего ошибок: {day_stats.total or 0}\n"
        report += f"• 🆕 Новых: {day_stats.new or 0}\n"
        report += f"• ✅ Решено: {day_stats.resolved or 0}\n"
        report += f"• 📈 Эффективность: {day_stats.resolved / day_stats.total * 100 if day_stats.total else 0:.1f}%\n\n"

        if leaders:
            report += "**🏆 Лидеры дня:**\n"
            for i, leader in enumerate(leaders[:5], 1):
                name = f"{leader.FFirstName or ''} {leader.FLastName or ''}".strip() or leader.FUserName
                report += f"• {i}. {name} - {leader.solved} решено\n"

        report += "\n📌 Используйте /errors для просмотра всех ошибок"

        return report

    async def process_notification_queue(self) -> None:
        """Обработка очереди уведомлений"""
        while self._notification_queue:
            notification = self._notification_queue.pop(0)
            try:
                from ..tg import tg_manager

                await tg_manager.send_message(
                    chat_id=notification["chat_id"],
                    message_type=MessageType.SYSTEM_ALERT,
                    text=notification["message"],
                    parse_mode="Markdown",
                )

                app_logger.info(f"Sent notification to chat {notification['chat_id']}")
            except Exception as e:
                app_logger.error(f"Failed to send notification: {e}")


notification_service = NotificationService()
