"""
Сервис для отправки уведомлений о напоминаниях.

Назначение:
    Отправка уведомлений пользователям о наступивших напоминаниях
    с поддержкой различных типов уведомлений и повторений.

Основные функции:
    1. Отправка уведомлений о напоминаниях в личные сообщения
    2. Отправка уведомлений в групповые чаты
    3. Поддержка повторяющихся напоминаний с интервалом
    4. Автоматическое обновление статуса напоминаний
    5. Деактивация напоминаний по достижении лимита

Технические особенности:
    - Поддержка приватных и групповых уведомлений
    - Автоматическое распознавание типа уведомления
    - Обновление статуса после отправки
    - Поддержка максимального количества повторений
    - Поддержка даты окончания повторений

Архитектура:
    - Использует ReminderRepository для работы с БД
    - Интегрируется с BotManager для отправки
    - Работает через DTO для передачи данных
"""

from datetime import timedelta

from sqlalchemy.ext.asyncio import AsyncSession

from ..bot.dependencies import get_bot_manager
from ..db.repositories import ReminderRepository
from ..dtos.reminder import ReminderNotificationDTO
from ..logger import app_logger
from ..models import MessageType, datetime_now
from ..utils.decorators import log_exceptions

# ============================================================
# 1. ОСНОВНОЙ КЛАСС СЕРВИСА
# ============================================================


class ReminderNotificationService:
    """
    Сервис для отправки уведомлений о напоминаниях.

    Предоставляет методы для:
    - Отправки уведомлений в личные и групповые чаты
    - Форматирования сообщений о напоминаниях
    - Обновления статуса напоминаний после отправки

    Attributes:
        _repository (ReminderRepository): Репозиторий для работы с напоминаниями
    """

    def __init__(self) -> None:
        """Инициализация сервиса уведомлений о напоминаниях."""
        self._repository = ReminderRepository()

    # ============================================================
    # 1.1. ОТПРАВКА УВЕДОМЛЕНИЯ
    # ============================================================

    @log_exceptions(app_logger)
    async def send_notification(self, reminder: ReminderNotificationDTO, session: AsyncSession) -> bool:
        """
        Отправка уведомления о напоминании.

        Отправляет уведомление в зависимости от типа:
        - private: только в личные сообщения
        - group: только в групповой чат
        - both: и в личные, и в групповой чат

        Args:
            reminder: DTO напоминания с данными для отправки
            session: Сессия БД

        Returns:
            bool: True если успешно отправлено хотя бы одно уведомление
        """
        try:
            # 1. Формирование сообщения
            message = self._format_message(reminder)

            # 2. Получение бота
            bot_manager = get_bot_manager()

            # 3. Проверка статуса бота
            status = await bot_manager.get_status()
            if not status.get("is_running", False):
                app_logger.warning("⚠️ Bot not running, cannot send reminder notification")
                return False

            # 4. Отправка в зависимости от типа уведомления
            success = False

            # 4.1. Приватное уведомление
            if reminder.notification_type in ["private", "both"]:
                try:
                    result = await bot_manager.send_message(
                        chat_id=reminder.user_id, message_type=MessageType.REMINDER, text=message, parse_mode="Markdown"
                    )

                    if result.get("success"):
                        success = True
                        app_logger.debug(f"✅ Private reminder sent to user {reminder.user_id}")
                    else:
                        app_logger.warning(f"⚠️ Failed to send private reminder: {result.get('error')}")

                except Exception as e:
                    app_logger.error(f"❌ Failed to send private reminder: {e}")

            # 4.2. Групповое уведомление
            if reminder.notification_type in ["group", "both"] and reminder.chat_id:
                try:
                    result = await bot_manager.send_message(
                        chat_id=reminder.chat_id, message_type=MessageType.REMINDER, text=message, parse_mode="Markdown"
                    )

                    if result.get("success"):
                        success = True
                        app_logger.debug(f"✅ Group reminder sent to chat {reminder.chat_id}")
                    else:
                        app_logger.warning(f"⚠️ Failed to send group reminder: {result.get('error')}")

                except Exception as e:
                    app_logger.error(f"❌ Failed to send group reminder: {e}")

            # 5. Обновление статуса напоминания
            if success:
                await self._update_reminder_status(reminder.id, session)

            return success

        except Exception as e:
            app_logger.error(f"❌ Failed to send reminder notification: {e}")
            return False

    # ============================================================
    # 1.2. ФОРМАТИРОВАНИЕ СООБЩЕНИЯ
    # ============================================================

    @staticmethod
    def _format_message(reminder: ReminderNotificationDTO) -> str:
        """
        Форматирование сообщения для напоминания.

        Создаёт структурированное сообщение с:
        - Заголовком и описанием
        - Категорией
        - Информацией о повторениях
        - Временем следующего напоминания
        - Инструкцией по завершению

        Args:
            reminder: DTO напоминания

        Returns:
            str: Отформатированное сообщение в Markdown
        """
        message = "🔔 **Напоминание!**\n\n"
        message += f"📌 **{reminder.title or 'Без названия'}**\n"

        if reminder.description:
            message += f"📝 {reminder.description}\n"

        if reminder.category:
            message += f"📂 Категория: {reminder.category}\n"

        # Информация о повторениях
        if reminder.remind_count > 0:
            message += f"🔄 Повтор: {reminder.remind_count + 1}"

            if reminder.max_remind_count:
                message += f" (макс. {reminder.max_remind_count})"
            message += "\n"

        # Информация о следующем напоминании
        if reminder.remind_interval and reminder.remind_interval > 0:
            next_time = reminder.remind_at + timedelta(minutes=reminder.remind_interval)
            message += f"⏰ Следующее: {next_time.strftime('%d.%m.%Y %H:%M')}\n"

        # Добавление инструкции
        message += "\n✅ Для завершения дела используйте /complete"

        return message

    # ============================================================
    # 1.3. ОБНОВЛЕНИЕ СТАТУСА
    # ============================================================

    @staticmethod
    async def _update_reminder_status(reminder_id: int, session: AsyncSession) -> None:
        """
        Обновление статуса напоминания после отправки.

        Определяет необходимость:
        - Деактивации при достижении максимального количества повторений
        - Деактивации при истечении даты окончания
        - Перепланирования для повторяющихся напоминаний

        Args:
            reminder_id: ID напоминания
            session: Сессия БД
        """
        now = datetime_now()

        # 1. Получение напоминания для определения интервала
        reminder = await ReminderRepository.get_reminder_by_id(session, reminder_id)

        if not reminder:
            return

        # 2. Расчёт нового состояния
        remind_count = reminder.FRemindCount + 1
        is_active = True
        new_remind_at = None

        # 3. Определение, нужно ли деактивировать напоминание
        should_deactivate = False

        # 3.1. Проверка максимального количества повторений
        if reminder.FMaxRemindCount and remind_count >= reminder.FMaxRemindCount:
            should_deactivate = True
            app_logger.debug(f"⏰ Reminder {reminder_id} deactivated (max count reached)")

        # 3.2. Проверка даты окончания
        elif reminder.FRemindUntil and now > reminder.FRemindUntil:
            should_deactivate = True
            app_logger.debug(f"⏰ Reminder {reminder_id} deactivated (until date passed)")

        # 4. Перепланирование для повторяющихся напоминаний
        if not should_deactivate and reminder.FRemindInterval and reminder.FRemindInterval > 0:
            new_remind_at = now + timedelta(minutes=reminder.FRemindInterval)
            app_logger.debug(f"⏰ Reminder {reminder_id} rescheduled to {new_remind_at}")
        elif not should_deactivate:
            should_deactivate = True
            app_logger.debug(f"⏰ Reminder {reminder_id} deactivated (one-time)")

        if should_deactivate:
            is_active = False

        # 5. Обновление статуса
        await ReminderRepository.update_reminder_status(
            session=session,
            reminder_id=reminder_id,
            remind_count=remind_count,
            last_reminded=now,
            is_active=is_active,
            remind_at=new_remind_at,
        )


reminder_notification_service = ReminderNotificationService()
