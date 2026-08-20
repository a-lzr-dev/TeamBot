from typing import Any

from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message

from ...db import db_manager
from ...db.repositories import MessageRepository
from ...logger import bot_logger
from ..dependencies import get_bot_manager
from .base import BaseCallbackHandler, CallbackHandler


class AdminCallbackHandler(BaseCallbackHandler):
    """Обработчик колбэков для администратора"""

    PREFIX_BROADCAST_CONFIRM = "broadcast_confirm"
    PREFIX_BROADCAST_CANCEL = "broadcast_cancel"
    PREFIX_DELETE_CONFIRM = "delete_confirm"
    PREFIX_DELETE_CANCEL = "delete_cancel"

    def __init__(self) -> None:
        super().__init__("admin")
        # Репозиторий для работы с сообщениями
        self._message_repo = MessageRepository()

    async def handle(self, callback: CallbackQuery, state: FSMContext, **kwargs: Any) -> Any:
        """Обработка колбэка администратора"""
        callback_data = callback.data

        if callback_data == self.PREFIX_BROADCAST_CONFIRM:
            return await self._handle_broadcast_confirm(callback, state)
        elif callback_data == self.PREFIX_BROADCAST_CANCEL:
            return await self._handle_broadcast_cancel(callback, state)
        elif callback_data == self.PREFIX_DELETE_CONFIRM:
            return await self._handle_delete_confirm(callback, state)
        elif callback_data == self.PREFIX_DELETE_CANCEL:
            return await self._handle_delete_cancel(callback, state)

        bot_logger.warning(f"⚠️ Unknown admin callback: {callback_data}")
        await CallbackHandler.answer(callback, "Неизвестное действие")
        return None

    @staticmethod
    async def _handle_broadcast_confirm(callback: CallbackQuery, state: FSMContext) -> None:
        """Подтверждение рассылки через callback"""
        # Ответ на колбэк (показываем Toast)
        await CallbackHandler.answer(callback, "✅ Рассылка подтверждена")

        # Получение данных из состояния
        data = await state.get_data()
        text = data.get("text")
        parse_mode = data.get("parse_mode", "HTML")
        sender_user_id = data.get("sender_user_id")
        sender_first_name = data.get("sender_first_name")
        sender_username = data.get("sender_username")

        print(f"🔍 [DEBUG] _handle_broadcast_confirm - sender_user_id from state: {sender_user_id}")

        if not sender_user_id and callback.from_user:
            sender_user_id = callback.from_user.id
            sender_first_name = callback.from_user.first_name
            sender_username = callback.from_user.username
            print(f"🔍 [DEBUG] Using callback user as sender: {sender_user_id}")

        if not text:
            await state.clear()
            if callback.message and hasattr(callback.message, "edit_text"):
                await callback.message.edit_text("❌ Текст сообщения не найден.")
            return

        # Обновление сообщения о начале рассылки
        if callback.message and hasattr(callback.message, "edit_text"):
            await callback.message.edit_text("🔄 Начинаю рассылку...")

        # Выполнение рассылки
        bot_manager = get_bot_manager()
        result = await bot_manager.broadcast_message(
            text=text,
            parse_mode=parse_mode,
            disable_web_page_preview=True,
            sender_user_id=sender_user_id,
            sender_first_name=sender_first_name,
            sender_username=sender_username,
        )

        # Формирование отчета
        report = (
            f"📊 **Результат рассылки**\n\n"
            f"• ✅ Успешно отправлено: {result['successful']}\n"
            f"• ❌ Ошибок: {result['failed']}\n"
            f"• 📊 Всего чатов: {result['total']}\n"
            f"• 📈 Успешность: {result['successful'] * 100 // result['total'] if result['total'] > 0 else 0}%\n"
        )

        if result.get("failed_chats"):
            report += "\n**❌ Чаты с ошибками:**\n"
            for failed in result["failed_chats"][:5]:
                title = failed.get("title", f"Chat {failed['chat_id']}")
                report += f"• {title} (ID: {failed['chat_id']}): {failed['error'][:50]}\n"
            if len(result["failed_chats"]) > 5:
                report += f"• ... и еще {len(result['failed_chats']) - 5} чатов\n"

        # Обновление сообщение с результатом
        if callback.message and hasattr(callback.message, "edit_text"):
            await callback.message.edit_text(report, parse_mode="Markdown")

        await state.clear()
        bot_logger.info(f"✅ Broadcast completed via callback: {result['successful']}/{result['total']}")

    @staticmethod
    async def _handle_broadcast_cancel(callback: CallbackQuery, state: FSMContext) -> None:
        """Отмена рассылки"""
        await state.clear()
        bot_manager = get_bot_manager()
        await bot_manager.send_toast(text="❌ Рассылка отменена.", event=callback)

    async def _handle_delete_confirm(self, callback: CallbackQuery, state: FSMContext) -> None:
        """Подтверждение удаления"""
        bot_manager = get_bot_manager()
        await bot_manager.send_toast(text="✅ Удаление подтверждено.", event=callback)

        # Получение данных из состояния
        data = await state.get_data()
        chat_id = data.get("chat_id")
        message_id = data.get("message_id")

        if not chat_id or not message_id:
            await state.clear()
            await bot_manager.send_toast(text="❌ Данные для удаления не найдены.", event=callback)
            return

        try:
            bot = callback.bot
            if not bot:
                await bot_manager.send_toast(text="❌ Бот не инициализирован.", event=callback)
                return

            # Выполнение удаления через бота
            await bot.delete_message(chat_id, message_id)

            # ИСПОЛЬЗУЕМ MessageRepository ДЛЯ ОТМЕТКИ УДАЛЕНИЯ В БД
            async with db_manager.get_session() as session:
                # Проверяем существование сообщения через репозиторий
                db_message = await self._message_repo.get_message_by_id(session, message_id)

                if db_message:
                    # ИСПОЛЬЗУЕМ MessageRepository ДЛЯ ОТМЕТКИ УДАЛЕНИЯ
                    deleted_count = await self._message_repo.mark_messages_as_deleted(
                        session=session,
                        message_ids=[message_id],
                        deleted_by_type="admin",
                        deleted_by_message_id=callback.message.message_id if callback.message else None,
                    )

                    if deleted_count > 0:
                        bot_logger.info(f"✅ Message {message_id} marked as deleted in DB by admin")
                    else:
                        bot_logger.warning(f"⚠️ Message {message_id} already deleted or not found")
                else:
                    bot_logger.warning(f"⚠️ Message {message_id} not found in DB")

                await session.commit()

            await bot_manager.send_toast(
                text=f"✅ Сообщение `{message_id}` успешно удалено из чата `{chat_id}`.",
                event=callback,
            )

        except Exception as e:
            bot_logger.error(f"❌ Failed to delete message {message_id}: {e}", exc_info=True)
            await bot_manager.send_toast(text=f"❌ Ошибка при удалении: {str(e)}", event=callback)
        finally:
            await state.clear()

    @staticmethod
    async def _handle_delete_cancel(callback: CallbackQuery, state: FSMContext) -> None:
        """Отмена удаления"""
        await state.clear()
        bot_manager = get_bot_manager()
        await bot_manager.send_toast(text="❌ Удаление отменено.", event=callback)

    # Методы для совместимости с Message (если нужно)
    async def handle_broadcast(self, message: Message, state: FSMContext) -> None:
        """Обработка колбэка для рассылки (для Message)"""
        pass

    async def handle_delete(self, message: Message, state: FSMContext) -> None:
        """Обработка колбэка для удаления (для Message)"""
        pass


admin_callback_handler = AdminCallbackHandler()
