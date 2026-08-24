"""
Сервис для управления уведомлениями.

Назначение:
    Централизованное управление отправкой уведомлений об ошибках и событиях
    с поддержкой гибкой настройки, фильтрации и группировки.

Основные функции:
    1. Проверка необходимости отправки уведомления (с учётом настроек)
    2. Фильтрация уведомлений по категориям и уровням серьёзности
    3. Группировка ошибок для предотвращения спама
    4. Режим тишины (silent mode) для отдельных чатов
    5. Форматирование сообщений об ошибках
    6. Генерация автоматических отчетов
    7. Очередь уведомлений для асинхронной отправки

Технические особенности:
    - Поддержка индивидуальных настроек для каждого чата
    - Группировка ошибок по хешу с настраиваемым окном
    - Режим тишины с поддержкой временных диапазонов
    - Фильтрация по категориям и уровням серьёзности
    - Кеширование для оптимизации проверок

Архитектура:
    - Использует репозитории для работы с БД
    - Интегрируется с BotManager для отправки
    - Поддерживает асинхронную обработку через очередь
"""

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

# ============================================================
# 1. ОСНОВНОЙ КЛАСС СЕРВИСА
# ============================================================


class NotificationService:
    """
    Сервис для управления уведомлениями.

    Предоставляет методы для:
    - Проверки необходимости отправки уведомлений
    - Форматирования сообщений об ошибках
    - Генерации автоматических отчетов
    - Управления очередью уведомлений

    Attributes:
        _notification_queue (list[dict]): Очередь уведомлений
        _processed_errors (set): Множество обработанных ошибок
        _error_cache (dict[str, datetime]): Кеш ошибок для группировки
    """

    def __init__(self) -> None:
        """Инициализация сервиса уведомлений."""
        self._notification_queue: list[dict] = []  # Очередь уведомлений
        self._processed_errors: set = set()  # Множество обработанных ошибок
        self._error_cache: dict[str, datetime] = {}  # Кеш ошибок для группировки

    # ============================================================
    # 1.1. ПРОВЕРКА НЕОБХОДИМОСТИ УВЕДОМЛЕНИЯ
    # ============================================================

    @log_exceptions(app_logger)
    async def should_notify_error(
        self,
        error: ErrorModel,
        chat_id: int,
        session: AsyncSession,
    ) -> bool:
        """
        Проверка, нужно ли отправлять уведомление об ошибке.

        Выполняет последовательную проверку всех настроек:
        1. Режим тишины
        2. Категория ошибки
        3. Уровень серьёзности
        4. Фильтры ошибок
        5. Группировка ошибок

        Args:
            error: Модель ошибки
            chat_id: ID чата
            session: Сессия БД

        Returns:
            bool: True если уведомление нужно отправить
        """
        # 1. Получение настроек через репозиторий
        settings = await NotificationSettingsRepository.get_by_chat_id(session, chat_id)
        if not settings:
            return True

        # 2. Проверка режима тишины
        if settings.FSilenceEnabled and settings.FSilenceStart and settings.FSilenceEnd:
            now = datetime_now()
            current_time = now.strftime("%H:%M")

            if self._is_time_in_range(current_time, settings.FSilenceStart, settings.FSilenceEnd):
                return False

        # 3. Проверка категории
        if not self._is_category_enabled(error.FCategory, settings):
            return False

        # 4. Проверка уровня серьёзности
        if error.FSeverity.value not in self._get_allowed_severities(settings):
            return False

        # 5. Проверка фильтров через репозиторий
        if await ErrorFilterRepository.is_error_filtered(session, chat_id, error):
            return False

        # 6. Проверка группировки
        if settings.FGroupingEnabled and error.FGroupHash:
            cache_key = f"{chat_id}:{error.FGroupHash}"
            last_notified = self._error_cache.get(cache_key)

            if last_notified and (datetime_now() - last_notified).seconds < settings.FGroupingWindowMinutes * 60:
                return False

            self._error_cache[cache_key] = datetime_now()

        return True

    # ============================================================
    # 1.2. ВСПОМОГАТЕЛЬНЫЕ МЕТОДЫ ПРОВЕРКИ
    # ============================================================

    @staticmethod
    def _is_time_in_range(current: str, start: str, end: str) -> bool:
        """
        Проверка, находится ли текущее время в диапазоне.

        Поддерживает диапазоны, пересекающие полночь (например, 23:00-07:00).

        Args:
            current: Текущее время (HH:MM)
            start: Начало диапазона (HH:MM)
            end: Конец диапазона (HH:MM)

        Returns:
            bool: True если время входит в диапазон
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
            bool: True если категория включена
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
        Получение списка разрешённых уровней серьёзности.

        Args:
            settings: Настройки уведомлений

        Returns:
            list[str]: Список разрешённых уровней
        """
        mapping = {
            ErrorSeverity.CRITICAL: ["critical"],
            ErrorSeverity.ERROR: ["critical", "error"],
            ErrorSeverity.WARNING: ["critical", "error", "warning"],
            ErrorSeverity.INFO: ["critical", "error", "warning", "info"],
        }
        return mapping.get(settings.FNotificationLevel, ["critical", "error"])

    # ============================================================
    # 1.3. ФОРМАТИРОВАНИЕ СООБЩЕНИЙ
    # ============================================================

    @log_exceptions(app_logger)
    async def format_error_message(self, error: ErrorModel, include_details: bool = True) -> str:
        """
        Форматирование сообщения об ошибке для отправки.

        Args:
            error: Модель ошибки
            include_details: Включать ли детали ошибки

        Returns:
            str: Отформатированное сообщение в Markdown
        """
        # Эмодзи для статуса
        status_emoji = {
            ErrorStatus.NEW: "🆕",
            ErrorStatus.IN_PROGRESS: "🔄",
            ErrorStatus.RESOLVED: "✅",
            ErrorStatus.DISMISSED: "⏭️",
            ErrorStatus.REOPENED: "🔁",
        }.get(error.FStatus, "❌")

        # Эмодзи для серьёзности
        severity_emoji = {
            ErrorSeverity.CRITICAL: "🚨",
            ErrorSeverity.ERROR: "❌",
            ErrorSeverity.WARNING: "⚠️",
            ErrorSeverity.INFO: "ℹ️",
        }.get(error.FSeverity, "📌")

        # Формирование сообщения
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

        message += f"\n🔗 `/resolve_{error.FID}` - отметить как решённое"

        return message

    # ============================================================
    # 1.4. ГЕНЕРАЦИЯ ОТЧЕТОВ
    # ============================================================

    @log_exceptions(app_logger)
    async def generate_auto_report(self, chat_id: int, session: AsyncSession) -> str:
        """
        Генерация автоматического отчёта об ошибках.

        Собирает статистику за последний час и с начала дня,
        а также список лидеров по решению ошибок.

        Args:
            chat_id: ID чата
            session: Сессия БД

        Returns:
            str: Отчёт в формате Markdown
        """
        now = datetime_now()
        hour_ago = now - timedelta(hours=1)
        day_start = now.replace(hour=0, minute=0, second=0, microsecond=0)

        # 1. Получение статистики за час через репозиторий
        hour_stats = await ErrorRepository.get_stats(
            session=session,
            start_date=hour_ago,
            end_date=now,
        )

        # 2. Получение статистики за день через репозиторий
        day_stats = await ErrorRepository.get_stats(
            session=session,
            start_date=day_start,
            end_date=now,
        )

        # 3. Получение лидеров дня через репозиторий
        leaders = await ErrorRepository.get_top_resolvers(
            session=session,
            start_date=day_start,
            end_date=now,
            limit=5,
        )

        # 4. Формирование отчёта
        report = "📊 **Ежечасный отчёт об ошибках**\n\n"
        report += f"📅 **{now.strftime('%d.%m.%Y %H:%M')}**\n\n"

        # Статистика за час
        report += "**За последний час:**\n"
        report += f"• 🆕 Новых ошибок: {hour_stats.get('new', 0)}\n"
        report += f"• ✅ Решено: {hour_stats.get('resolved', 0)}\n\n"

        # Статистика с начала дня
        report += "**С начала дня:**\n"
        total = day_stats.get("total", 0)
        new = day_stats.get("new", 0)
        resolved = day_stats.get("resolved", 0)
        report += f"• 📋 Всего ошибок: {total}\n"
        report += f"• 🆕 Новых: {new}\n"
        report += f"• ✅ Решено: {resolved}\n"
        report += f"• 📈 Эффективность: {resolved / total * 100 if total else 0:.1f}%\n\n"

        # Лидеры дня
        if leaders:
            report += "**🏆 Лидеры дня:**\n"
            for i, leader in enumerate(leaders[:5], 1):
                name = f"{leader.get('first_name', '')} {leader.get('last_name', '')}".strip() or leader.get(
                    "username", "Unknown"
                )
                report += f"• {i}. {name} - {leader.get('solved', 0)} решено\n"

        report += "\n📌 Используйте /errors для просмотра всех ошибок"

        return report

    # ============================================================
    # 1.5. УПРАВЛЕНИЕ ОЧЕРЕДЬЮ УВЕДОМЛЕНИЙ
    # ============================================================

    async def process_notification_queue(self) -> None:
        """
        Обработка очереди уведомлений.

        Последовательно отправляет все уведомления из очереди.
        В случае ошибки логирует её и продолжает обработку.
        """
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

                app_logger.info(f"✅ Sent notification to chat {notification['chat_id']}")
            except Exception as e:
                app_logger.error(f"❌ Failed to send notification: {e}")

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
        app_logger.debug(f"📥 Added notification to queue for chat {chat_id}")

    # ============================================================
    # 1.6. УПРАВЛЕНИЕ КЕШЕМ
    # ============================================================

    def clear_cache(self) -> None:
        """Очистка кеша ошибок."""
        self._error_cache.clear()
        app_logger.debug("🧹 Error cache cleared")

    def get_cache_size(self) -> int:
        """
        Получение размера кеша ошибок.

        Returns:
            int: Количество записей в кеше
        """
        return len(self._error_cache)

    def get_queue_size(self) -> int:
        """
        Получение размера очереди уведомлений.

        Returns:
            int: Количество уведомлений в очереди
        """
        return len(self._notification_queue)


notification_service = NotificationService()
