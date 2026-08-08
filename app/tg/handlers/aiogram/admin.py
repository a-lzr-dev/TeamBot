from aiogram import Bot, Router
from aiogram.exceptions import TelegramAPIError
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, Message

from ....config import settings
from ....db import ChatRepository, db_manager
from ....exceptions import log_exceptions
from ....logger import tg_logger
from ....models import MessageActionType, MessageType, datetime_now
from ....tg.dependencies import get_tg_manager
from ...keyboards import AdminKeyboard

router = Router(name="aiogram_admin")


class BroadcastStates(StatesGroup):
    """Состояния для рассылки"""

    waiting_for_text = State()
    waiting_for_confirmation = State()


class DeleteMessageStates(StatesGroup):
    """Состояния для удаления сообщения"""

    waiting_for_chat_id = State()
    waiting_for_message_id = State()
    waiting_for_confirmation = State()


@router.message(Command("broadcast"))
@log_exceptions(tg_logger)
async def cmd_broadcast(message: Message, state: FSMContext) -> None:
    """Команда для рассылки сообщений всем чатам"""
    tg_manager = get_tg_manager()

    # Проверка прав администратора
    if not message.from_user or message.from_user.id not in settings.ADMIN_IDS:
        await tg_manager.send_answer(
            message_type=MessageType.COMMAND_ADMIN,
            event=message,
            text="⛔ У вас нет прав для этой команды.",
            clear_previous=True,
        )
        return

    print(f"🔍 [DEBUG] cmd_broadcast from user: {message.from_user.id}")
    print(f"🔍 [DEBUG] User: {message.from_user.first_name} (@{message.from_user.username})")

    await state.set_state(BroadcastStates.waiting_for_text)

    await tg_manager.send_answer(
        text="📨 **Рассылка сообщений**\n\n"
        "Отправьте текст для рассылки во все чаты.\n"
        "Поддерживается HTML разметка.\n\n"
        "Для отмены используйте /cancel",
        event=message,
        message_type=MessageType.COMMAND_ADMIN,
        delete_by_type=MessageActionType.COMMAND_ADMIN_CLEANUP,
        parse_mode="Markdown",
    )


@router.message(BroadcastStates.waiting_for_text)
@log_exceptions(tg_logger)
async def broadcast_get_text(message: Message, state: FSMContext) -> None:
    """Получение текста для рассылки"""
    tg_manager = get_tg_manager()

    # Проверка отмены
    if message.text and message.text.lower() in ["/cancel", "отмена", "cancel"]:
        await state.clear()
        await tg_manager.send_answer(
            text="❌ Рассылка отменена.",
            event=message,
            message_type=MessageType.COMMAND_ADMIN,
            delete_by_type=MessageActionType.COMMAND_ADMIN_CLEANUP,
        )
        return

    # Проверка, что текст не пустой
    if not message.text or not message.text.strip():
        await tg_manager.send_answer(
            text="❌ Текст сообщения не может быть пустым.\nПожалуйста, отправьте текст для рассылки.",
            event=message,
            message_type=MessageType.COMMAND_ADMIN,
            delete_by_type=MessageActionType.COMMAND_ADMIN_CLEANUP,
        )
        return

    # Получение количества чатов
    async with db_manager.get_session() as session:
        chats = await ChatRepository.get_chats(session, is_active=True)
        chat_count = len(chats)

    if chat_count == 0:
        await state.clear()
        await tg_manager.send_answer(
            text="❌ Нет активных чатов для рассылки.",
            event=message,
            message_type=MessageType.COMMAND_ADMIN,
            delete_by_type=MessageActionType.COMMAND_ADMIN_CLEANUP,
        )
        return

    # Сохранение информации о сообщении и отправителе
    await state.update_data(
        text=message.text,
        parse_mode="HTML",
        sender_user_id=message.from_user.id,
        sender_first_name=message.from_user.first_name,
        sender_username=message.from_user.username,
    )

    print(f"🔍 [DEBUG] broadcast_get_text - saved sender_user_id: {message.from_user.id}")

    await state.set_state(BroadcastStates.waiting_for_confirmation)

    keyboard = AdminKeyboard.get_broadcast_confirm_keyboard()
    print(f"🔍 Keyboard: {keyboard}")  # Должен быть объект InlineKeyboardMarkup
    print(f"🔍 Keyboard inline_keyboard: {keyboard.inline_keyboard}")  # Должен быть список

    await tg_manager.send_answer(
        text=f"📊 **Подтверждение рассылки**\n\n"
        f"Текст будет отправлен в **{chat_count}** чатов.\n\n"
        f"Текст сообщения:\n"
        f"```\n{message.text[:200]}{'...' if len(message.text) > 200 else ''}\n```\n\n"
        f"Отправить?",
        event=message,
        message_type=MessageType.COMMAND_ADMIN,
        delete_by_type=MessageActionType.COMMAND_ADMIN_CLEANUP,
        parse_mode="Markdown",
        reply_markup=keyboard,
    )
    print("✅ Сообщение отправлено через tg_manager")


@router.message(BroadcastStates.waiting_for_confirmation)
@log_exceptions(tg_logger)
async def broadcast_confirm(message: Message, state: FSMContext) -> None:
    """Подтверждение рассылки"""
    tg_manager = get_tg_manager()

    # Проверка отмены
    if message.text and message.text.lower() in ["нет", "no", "n", "отмена", "cancel"]:
        await state.clear()
        await tg_manager.send_answer(
            text="❌ Рассылка отменена.",
            event=message,
            message_type=MessageType.COMMAND_ADMIN,
            delete_by_type=MessageActionType.COMMAND_ADMIN_CLEANUP,
        )
        return

    # Проверка подтверждения
    if not message.text or message.text.lower() not in ["да", "yes", "y", "д"]:
        await tg_manager.send_answer(
            text="Пожалуйста, ответьте 'да' или 'нет'.",
            event=message,
            message_type=MessageType.COMMAND_ADMIN,
            delete_by_type=MessageActionType.COMMAND_ADMIN_CLEANUP,
        )
        return

    # Получение данных из состояния
    data = await state.get_data()
    text = data.get("text")
    parse_mode = data.get("parse_mode", "HTML")
    sender_user_id = data.get("sender_user_id")
    sender_first_name = data.get("sender_first_name")
    sender_username = data.get("sender_username")

    print(f"🔍 [DEBUG] broadcast_confirm - sender_user_id: {sender_user_id}")
    print(f"🔍 [DEBUG] sender_first_name: {sender_first_name}, sender_username: {sender_username}")

    if not text:
        await state.clear()
        await tg_manager.send_answer(
            text="❌ Текст сообщения не найден. Попробуйте начать заново.",
            event=message,
            message_type=MessageType.COMMAND_ADMIN,
            delete_by_type=MessageActionType.COMMAND_ADMIN_CLEANUP,
        )
        return

    # Отображение Toast - заменено на обычное сообщение
    await tg_manager.send_answer(
        text="🔄 Начинаю рассылку...",
        event=message,
        message_type=MessageType.COMMAND_ADMIN,
        delete_by_type=MessageActionType.COMMAND_ADMIN_CLEANUP,
    )

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

    # Отправка отчета
    await tg_manager.send_answer(
        text=report,
        event=message,
        message_type=MessageType.COMMAND_ADMIN,
        delete_by_type=MessageActionType.COMMAND_ADMIN_CLEANUP,
        parse_mode="Markdown",
    )

    await state.clear()
    tg_logger.info(f"✅ Broadcast completed by {message.from_user.id}: {result['successful']}/{result['total']}")


@router.message(Command("delete"))
@log_exceptions(tg_logger)
async def cmd_delete_message(message: Message, state: FSMContext) -> None:
    """Команда для удаления сообщения по ID"""
    tg_manager = get_tg_manager()

    # Проверка прав администратора
    if not message.from_user or message.from_user.id not in settings.ADMIN_IDS:
        await tg_manager.send_answer(
            text="⛔ У вас нет прав для этой команды.",
            event=message,
            message_type=MessageType.COMMAND_ADMIN,
            delete_by_type=MessageActionType.COMMAND_ADMIN_CLEANUP,
        )
        return

    # Сохраняем текст команды до удаления
    command_text = message.text or ""

    args = command_text.split()
    if len(args) >= 3:
        # Если аргументы переданы сразу: /delete chat_id message_id
        try:
            chat_id = int(args[1])
            message_id = int(args[2])
            await state.update_data(chat_id=chat_id, message_id=message_id)
            await process_delete_confirmation(message, state)
            return
        except ValueError:
            await tg_manager.send_answer(
                text="❌ Неверный формат ID. Используйте числа.",
                event=message,
                message_type=MessageType.COMMAND_ADMIN,
                delete_by_type=MessageActionType.COMMAND_ADMIN_CLEANUP,
            )
            return

    await state.set_state(DeleteMessageStates.waiting_for_chat_id)
    await tg_manager.send_answer(
        text="📨 **Удаление сообщения**\n\n"
        "Введите ID чата, из которого нужно удалить сообщение.\n"
        "Для отмены используйте /cancel",
        event=message,
        message_type=MessageType.COMMAND_ADMIN,
        delete_by_type=MessageActionType.COMMAND_ADMIN_CLEANUP,
    )


@router.message(DeleteMessageStates.waiting_for_chat_id)
@log_exceptions(tg_logger)
async def delete_get_chat_id(message: Message, state: FSMContext) -> None:
    """Получение ID чата для удаления"""
    tg_manager = get_tg_manager()

    if message.text and message.text.lower() in ["/cancel", "отмена", "cancel"]:
        await state.clear()
        await tg_manager.send_answer(
            text="❌ Операция отменена.",
            event=message,
            message_type=MessageType.COMMAND_ADMIN,
            delete_by_type=MessageActionType.COMMAND_ADMIN_CLEANUP,
        )
        return

    try:
        chat_id = int(message.text.strip())
        await state.update_data(chat_id=chat_id)
        await state.set_state(DeleteMessageStates.waiting_for_message_id)
        await tg_manager.send_answer(
            text=f"📨 ID чата: `{chat_id}`\n\n"
            "Теперь введите ID сообщения для удаления.\n"
            "Для отмены используйте /cancel",
            event=message,
            message_type=MessageType.COMMAND_ADMIN,
            delete_by_type=MessageActionType.COMMAND_ADMIN_CLEANUP,
            parse_mode="Markdown",
        )
    except ValueError:
        await tg_manager.send_answer(
            text="❌ Неверный формат ID чата. Используйте число.",
            event=message,
            message_type=MessageType.COMMAND_ADMIN,
            delete_by_type=MessageActionType.COMMAND_ADMIN_CLEANUP,
        )


@router.message(DeleteMessageStates.waiting_for_message_id)
@log_exceptions(tg_logger)
async def delete_get_message_id(message: Message, state: FSMContext) -> None:
    """Получение ID сообщения для удаления"""
    tg_manager = get_tg_manager()

    if message.text and message.text.lower() in ["/cancel", "отмена", "cancel"]:
        await state.clear()
        await tg_manager.send_answer(
            text="❌ Операция отменена.",
            event=message,
            message_type=MessageType.COMMAND_ADMIN,
            delete_by_type=MessageActionType.COMMAND_ADMIN_CLEANUP,
        )
        return

    try:
        message_id = int(message.text.strip())
        await state.update_data(message_id=message_id)
        await process_delete_confirmation(message, state)
    except ValueError:
        await tg_manager.send_answer(
            text="❌ Неверный формат ID сообщения. Используйте число.",
            event=message,
            message_type=MessageType.COMMAND_ADMIN,
            delete_by_type=MessageActionType.COMMAND_ADMIN_CLEANUP,
        )


async def process_delete_confirmation(message: Message, state: FSMContext) -> None:
    """Подтверждение удаления сообщения"""
    tg_manager = get_tg_manager()

    data = await state.get_data()
    chat_id = data.get("chat_id")
    message_id = data.get("message_id")

    await state.set_state(DeleteMessageStates.waiting_for_confirmation)

    keyboard = AdminKeyboard.get_delete_confirm_keyboard()

    await tg_manager.send_answer(
        text=f"⚠️ **Подтверждение удаления**\n\n"
        f"Чат: `{chat_id}`\n"
        f"Сообщение: `{message_id}`\n\n"
        f"Вы уверены, что хотите удалить это сообщение?",
        event=message,
        message_type=MessageType.COMMAND_ADMIN,
        delete_by_type=MessageActionType.COMMAND_ADMIN_CLEANUP,
        parse_mode="Markdown",
        reply_markup=keyboard,
    )


@router.message(DeleteMessageStates.waiting_for_confirmation)
@log_exceptions(tg_logger)
async def delete_confirm(message: Message, state: FSMContext, bot: Bot) -> None:
    """Подтверждение удаления сообщения"""
    tg_manager = get_tg_manager()

    if message.text and message.text.lower() in ["нет", "no", "n", "отмена", "cancel"]:
        await state.clear()
        await tg_manager.send_answer(
            text="❌ Удаление отменено.",
            event=message,
            message_type=MessageType.COMMAND_ADMIN,
            delete_by_type=MessageActionType.COMMAND_ADMIN_CLEANUP,
        )
        return

    if not message.text or message.text.lower() not in ["да", "yes", "y", "д"]:
        await tg_manager.send_answer(
            text="Пожалуйста, ответьте 'да' или 'нет'.",
            event=message,
            message_type=MessageType.COMMAND_ADMIN,
            delete_by_type=MessageActionType.COMMAND_ADMIN_CLEANUP,
        )
        return

    data = await state.get_data()
    chat_id = data.get("chat_id")
    message_id = data.get("message_id")

    try:
        # Получение информации о сообщении перед удалением
        async with db_manager.get_session() as session:
            from ....models import ChatMessageModel

            db_message = await session.get(ChatMessageModel, message_id)
            if db_message:
                db_message.FFlagDeleted = True
                db_message.FDateDeleted = datetime_now()
                db_message.FK_DeletedByMessage = message.message_id
                db_message.FDeletedByType = "admin"
                await session.commit()
                tg_logger.info(f"✅ Message {message_id} marked as deleted in DB by admin {message.from_user.id}")

        await tg_manager.send_answer(
            text=f"✅ Сообщение `{message_id}` успешно удалено из чата `{chat_id}`.",
            event=message,
            message_type=MessageType.COMMAND_ADMIN,
            delete_by_type=MessageActionType.COMMAND_ADMIN_CLEANUP,
            parse_mode="Markdown",
        )
        tg_logger.info(f"✅ Message {message_id} deleted by admin {message.from_user.id} from chat {chat_id}")

    except TelegramAPIError as e:
        await tg_manager.send_answer(
            text=f"❌ Ошибка при удалении: {str(e)}",
            event=message,
            message_type=MessageType.COMMAND_ADMIN,
            delete_by_type=MessageActionType.COMMAND_ADMIN_CLEANUP,
        )
    except Exception as e:
        tg_logger.error(f"❌ Failed to delete message: {e}", exc_info=True)
        await tg_manager.send_answer(
            text=f"❌ Ошибка: {str(e)}",
            event=message,
            message_type=MessageType.COMMAND_ADMIN,
            delete_by_type=MessageActionType.COMMAND_ADMIN_CLEANUP,
        )
    finally:
        await state.clear()


@router.message(Command("cancel"))
@log_exceptions(tg_logger)
async def cmd_cancel(message: Message, state: FSMContext) -> None:
    """Отмена текущей операции"""
    tg_manager = get_tg_manager()

    current_state = await state.get_state()
    if current_state is None:
        await tg_manager.send_answer(
            text="❌ Нет активных операций для отмены.",
            event=message,
            message_type=MessageType.COMMAND_ADMIN,
            delete_by_type=MessageActionType.COMMAND_ADMIN_CLEANUP,
        )
        return

    await state.clear()
    await tg_manager.send_answer(
        text="✅ Операция отменена.",
        event=message,
        message_type=MessageType.COMMAND_ADMIN,
        delete_by_type=MessageActionType.COMMAND_ADMIN_CLEANUP,
    )


@router.message(Command("admins"))
@log_exceptions(tg_logger)
async def cmd_admins(message: Message) -> None:
    """Просмотр списка администраторов"""
    tg_manager = get_tg_manager()

    if not message.from_user or message.from_user.id not in settings.ADMIN_IDS:
        await tg_manager.send_answer(
            text="⛔ У вас нет прав для этой команды.",
            event=message,
            message_type=MessageType.COMMAND_ADMIN,
            delete_by_type=MessageActionType.COMMAND_ADMIN_CLEANUP,
        )
        return

    admin_list = []
    for admin_id in settings.ADMIN_IDS:
        admin_list.append(f"• `{admin_id}`")

    response = (
        "👑 **Список администраторов**\n\n"
        f"{chr(10).join(admin_list) if admin_list else 'Нет администраторов'}\n\n"
        "Для добавления администратора используйте /add_admin <user_id>"
    )

    await tg_manager.send_answer(
        text=response,
        event=message,
        message_type=MessageType.COMMAND_ADMIN,
        delete_by_type=MessageActionType.COMMAND_ADMIN_CLEANUP,
        parse_mode="Markdown",
    )


@router.message(Command("add_admin"))
@log_exceptions(tg_logger)
async def cmd_add_admin(message: Message) -> None:
    """Добавление администратора"""
    tg_manager = get_tg_manager()

    if not message.from_user or message.from_user.id not in settings.ADMIN_IDS:
        await tg_manager.send_answer(
            text="⛔ У вас нет прав для этой команды.",
            event=message,
            message_type=MessageType.COMMAND_ADMIN,
            delete_by_type=MessageActionType.COMMAND_ADMIN_CLEANUP,
        )
        return

    # Сохраняем текст команды до удаления
    command_text = message.text or ""

    args = command_text.split()
    if len(args) < 2:
        await tg_manager.send_answer(
            text="❌ Использование: /add_admin <user_id>\n"
            "Например: /add_admin 123456789\n\n"
            "💡 Чтобы узнать свой ID, используйте /id",
            event=message,
            message_type=MessageType.COMMAND_ADMIN,
            delete_by_type=MessageActionType.COMMAND_ADMIN_CLEANUP,
        )
        return

    try:
        new_admin_id = int(args[1])

        if new_admin_id in settings.ADMIN_IDS:
            await tg_manager.send_answer(
                text=f"ℹ️ Пользователь {new_admin_id} уже является администратором.",
                event=message,
                message_type=MessageType.COMMAND_ADMIN,
                delete_by_type=MessageActionType.COMMAND_ADMIN_CLEANUP,
            )
            return

        settings.ADMIN_IDS.append(new_admin_id)

        await tg_manager.send_answer(
            text=f"✅ Пользователь {new_admin_id} добавлен в админы!\n\n"
            f"⚠️ **Важно:** Для постоянного добавления обновите `ADMIN_IDS` в файле `.env`.\n"
            f"Текущий список админов: {settings.ADMIN_IDS}",
            event=message,
            message_type=MessageType.COMMAND_ADMIN,
            delete_by_type=MessageActionType.COMMAND_ADMIN_CLEANUP,
        )
        tg_logger.info(f"✅ User {new_admin_id} added to admins by {message.from_user.id}")

    except ValueError:
        await tg_manager.send_answer(
            text="❌ Неверный формат ID. Используйте число.",
            event=message,
            message_type=MessageType.COMMAND_ADMIN,
            delete_by_type=MessageActionType.COMMAND_ADMIN_CLEANUP,
        )
    except Exception as err:
        tg_logger.error(f"❌ Failed to add admin: {err}")
        await tg_manager.send_answer(
            text=f"❌ Ошибка: {err}",
            event=message,
            message_type=MessageType.COMMAND_ADMIN,
            delete_by_type=MessageActionType.COMMAND_ADMIN_CLEANUP,
        )


@router.message(Command("remove_admin"))
@log_exceptions(tg_logger)
async def cmd_remove_admin(message: Message) -> None:
    """Удаление администратора"""
    tg_manager = get_tg_manager()

    if not message.from_user or message.from_user.id not in settings.ADMIN_IDS:
        await tg_manager.send_answer(
            text="⛔ У вас нет прав для этой команды.",
            event=message,
            message_type=MessageType.COMMAND_ADMIN,
            delete_by_type=MessageActionType.COMMAND_ADMIN_CLEANUP,
        )
        return

    if len(settings.ADMIN_IDS) <= 1:
        await tg_manager.send_answer(
            text="⚠️ Нельзя удалить единственного администратора.",
            event=message,
            message_type=MessageType.COMMAND_ADMIN,
            delete_by_type=MessageActionType.COMMAND_ADMIN_CLEANUP,
        )
        return

    # Сохраняем текст команды до удаления
    command_text = message.text or ""

    args = command_text.split()
    if len(args) < 2:
        await tg_manager.send_answer(
            text="❌ Использование: /remove_admin <user_id>\nНапример: /remove_admin 123456789",
            event=message,
            message_type=MessageType.COMMAND_ADMIN,
            delete_by_type=MessageActionType.COMMAND_ADMIN_CLEANUP,
        )
        return

    try:
        admin_id = int(args[1])

        if admin_id not in settings.ADMIN_IDS:
            await tg_manager.send_answer(
                text=f"ℹ️ Пользователь {admin_id} не является администратором.",
                event=message,
                message_type=MessageType.COMMAND_ADMIN,
                delete_by_type=MessageActionType.COMMAND_ADMIN_CLEANUP,
            )
            return

        if admin_id == message.from_user.id:
            await tg_manager.send_answer(
                text="⚠️ Вы не можете удалить сами себя из списка админов.",
                event=message,
                message_type=MessageType.COMMAND_ADMIN,
                delete_by_type=MessageActionType.COMMAND_ADMIN_CLEANUP,
            )
            return

        settings.ADMIN_IDS.remove(admin_id)

        await tg_manager.send_answer(
            text=f"✅ Пользователь {admin_id} удален из админов!\n\n"
            f"⚠️ **Важно:** Для постоянного удаления обновите `ADMIN_IDS` в файле `.env`.\n"
            f"Текущий список админов: {settings.ADMIN_IDS}",
            event=message,
            message_type=MessageType.COMMAND_ADMIN,
            delete_by_type=MessageActionType.COMMAND_ADMIN_CLEANUP,
        )
        tg_logger.info(f"✅ User {admin_id} removed from admins by {message.from_user.id}")

    except ValueError:
        await tg_manager.send_answer(
            text="❌ Неверный формат ID. Используйте число.",
            event=message,
            message_type=MessageType.COMMAND_ADMIN,
            delete_by_type=MessageActionType.COMMAND_ADMIN_CLEANUP,
        )
    except Exception as err:
        tg_logger.error(f"❌ Failed to remove admin: {err}")
        await tg_manager.send_answer(
            text=f"❌ Ошибка: {err}",
            event=message,
            message_type=MessageType.COMMAND_ADMIN,
            delete_by_type=MessageActionType.COMMAND_ADMIN_CLEANUP,
        )


# ============ ОБРАБОТЧИКИ КОЛБЭКОВ ============


@router.callback_query(lambda c: c.data in ["broadcast_confirm", "broadcast_cancel"])
@log_exceptions(tg_logger)
async def handle_broadcast_callback(callback: CallbackQuery, state: FSMContext) -> None:
    """Обработка колбэков для рассылки"""
    from ...callbacks.admin import admin_callback_handler

    await admin_callback_handler.handle(callback, state)


@router.callback_query(lambda c: c.data in ["delete_confirm", "delete_cancel"])
@log_exceptions(tg_logger)
async def handle_delete_callback(callback: CallbackQuery, state: FSMContext) -> None:
    """Обработка колбэков для удаления"""
    from ...callbacks.admin import admin_callback_handler

    await admin_callback_handler.handle(callback, state)


__all__ = [
    "router",
    "BroadcastStates",
    "DeleteMessageStates",
    "cmd_broadcast",
    "broadcast_get_text",
    "broadcast_confirm",
    "cmd_delete_message",
    "delete_get_chat_id",
    "delete_get_message_id",
    "delete_confirm",
    "cmd_cancel",
    "cmd_admins",
    "cmd_add_admin",
    "cmd_remove_admin",
]
