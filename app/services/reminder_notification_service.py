from datetime import timedelta

from sqlalchemy.ext.asyncio import AsyncSession

from ..bot.dependencies import get_bot_manager
from ..db.repositories import ReminderRepository
from ..dtos.reminder import ReminderNotificationDTO
from ..logger import app_logger
from ..models import MessageType, datetime_now
from ..utils.decorators import log_exceptions


class ReminderNotificationService:
    """Сервис для отправки уведомлений о напоминаниях"""

    def __init__(self) -> None:
        self._repository = ReminderRepository()

    @log_exceptions(app_logger)
    async def send_notification(self, reminder: ReminderNotificationDTO, session: AsyncSession) -> bool:
        """
        Отправка уведомления о напоминании.

        Args:
            reminder: DTO напоминания
            session: Сессия БД

        Returns:
            bool: Успешно ли отправлено
        """
        try:
            # Формирование сообщения
            message = self._format_message(reminder)

            # Получение бота
            bot_manager = get_bot_manager()

            # Проверка статуса бота
            status = await bot_manager.get_status()
            if not status.get("is_running", False):
                app_logger.warning("⚠️ Bot not running, cannot send reminder notification")
                return False

            # Отправка в зависимости от типа уведомления
            success = False

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

            # Обновление статуса напоминания
            if success:
                await self._update_reminder_status(reminder.id, session)

            return success

        except Exception as e:
            app_logger.error(f"❌ Failed to send reminder notification: {e}")
            return False

    @staticmethod
    def _format_message(reminder: ReminderNotificationDTO) -> str:
        """
        Форматирование сообщения для напоминания.
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

    @staticmethod
    async def _update_reminder_status(reminder_id: int, session: AsyncSession) -> None:
        """
        Обновление статуса напоминания после отправки.
        """
        now = datetime_now()

        # Получение напоминания для определения интервала
        reminder = await ReminderRepository.get_reminder_by_id(session, reminder_id)

        if not reminder:
            return

        remind_count = reminder.FRemindCount + 1
        is_active = True
        new_remind_at = None

        # Определение, нужно ли деактивировать напоминание
        should_deactivate = False

        if reminder.FMaxRemindCount and remind_count >= reminder.FMaxRemindCount:
            should_deactivate = True
            app_logger.debug(f"⏰ Reminder {reminder_id} deactivated (max count reached)")

        elif reminder.FRemindUntil and now > reminder.FRemindUntil:
            should_deactivate = True
            app_logger.debug(f"⏰ Reminder {reminder_id} deactivated (until date passed)")

        if not should_deactivate and reminder.FRemindInterval and reminder.FRemindInterval > 0:
            new_remind_at = now + timedelta(minutes=reminder.FRemindInterval)
            app_logger.debug(f"⏰ Reminder {reminder_id} rescheduled to {new_remind_at}")
        elif not should_deactivate:
            should_deactivate = True
            app_logger.debug(f"⏰ Reminder {reminder_id} deactivated (one-time)")

        if should_deactivate:
            is_active = False

        # Обновление статуса
        await ReminderRepository.update_reminder_status(
            session=session,
            reminder_id=reminder_id,
            remind_count=remind_count,
            last_reminded=now,
            is_active=is_active,
            remind_at=new_remind_at,
        )


reminder_notification_service = ReminderNotificationService()
