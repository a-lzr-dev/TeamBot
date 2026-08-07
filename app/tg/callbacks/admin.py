from typing import TYPE_CHECKING, Any

from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message

from ...logger import tg_logger
from .base import BaseCallbackHandler, CallbackHandler

if TYPE_CHECKING:
    from ...tg import TelegramManager


def get_tg_manager() -> "TelegramManager":
    """Получение глобального tg_manager"""
    from ...tg import tg_manager

    return tg_manager


class AdminCallbackHandler(BaseCallbackHandler):
    """Обработчик колбэков для администратора"""

    PREFIX_BROADCAST_CONFIRM = "broadcast_confirm"
    PREFIX_BROADCAST_CANCEL = "broadcast_cancel"
    PREFIX_DELETE_CONFIRM = "delete_confirm"
    PREFIX_DELETE_CANCEL = "delete_cancel"

    def __init__(self) -> None:
        super().__init__("admin")

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

        tg_logger.warning(f"⚠️ Unknown admin callback: {callback_data}")
        await CallbackHandler.answer(callback, "Неизвестное действие")
        return None

    @staticmethod
    async def _handle_broadcast_confirm(callback: CallbackQuery, state: FSMContext) -> None:
        """Подтверждение рассылки через callback"""
        from ...tg import tg_manager

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
            await callback.message.edit_text("❌ Текст сообщения не найден.")
            return

        # Обновление сообщения о начале рассылки
        await callback.message.edit_text("🔄 Начинаю рассылку...")

        # Выполнение рассылки
        result = await tg_manager.broadcast_message(
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
        await callback.message.edit_text(report, parse_mode="Markdown")

        await state.clear()
        tg_logger.info(f"✅ Broadcast completed via callback: {result['successful']}/{result['total']}")

    @staticmethod
    async def _handle_broadcast_cancel(callback: CallbackQuery, state: FSMContext) -> None:
        """Отмена рассылки"""
        from ...tg import tg_manager

        await state.clear()
        await tg_manager.send_toast(text="❌ Рассылка отменена.", event=callback)

    @staticmethod
    async def _handle_delete_confirm(callback: CallbackQuery, state: FSMContext) -> None:
        """Подтверждение удаления"""
        from ...tg import tg_manager

        await tg_manager.send_toast(text="✅ Удаление подтверждено.", event=callback)

        # Получение данных из состояния
        data = await state.get_data()
        chat_id = data.get("chat_id")
        message_id = data.get("message_id")

        if not chat_id or not message_id:
            await state.clear()
            await tg_manager.send_toast(text="❌ Данные для удаления не найдены.", event=callback)
            return

        try:
            # Выполнение удаления через бота
            await callback.bot.delete_message(chat_id, message_id)

            # Отмачание в БД
            from ...db import db_manager
            from ...models import ChatMessageModel, datetime_now

            async with db_manager.get_session() as session:
                db_message = await session.get(ChatMessageModel, message_id)
                if db_message:
                    db_message.FFlagDeleted = True
                    db_message.FDateDeleted = datetime_now()
                    db_message.FK_DeletedByMessage = callback.message.message_id
                    db_message.FDeletedByType = "admin"
                    await session.commit()

            await tg_manager.send_toast(
                text=f"✅ Сообщение `{message_id}` успешно удалено из чата `{chat_id}`.",
                event=callback,
            )
        except Exception as e:
            await tg_manager.send_toast(text=f"❌ Ошибка при удалении: {str(e)}", event=callback)
        finally:
            await state.clear()

    @staticmethod
    async def _handle_delete_cancel(callback: CallbackQuery, state: FSMContext) -> None:
        """Отмена удаления"""
        from ...tg import tg_manager

        await state.clear()
        await tg_manager.send_toast(text="❌ Удаление отменено.", event=callback)

    # Методы для совместимости с Message (если нужно)
    async def handle_broadcast(self, message: Message, state: FSMContext) -> None:
        """Обработка колбэка для рассылки (для Message)"""
        pass

    async def handle_delete(self, message: Message, state: FSMContext) -> None:
        """Обработка колбэка для удаления (для Message)"""
        pass


admin_callback_handler = AdminCallbackHandler()
