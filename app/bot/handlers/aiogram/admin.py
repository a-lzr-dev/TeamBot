from aiogram import Bot, Router
from aiogram.exceptions import TelegramAPIError
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, Message

from ....bot.dependencies import get_bot_manager
from ....config import settings
from ....db import ChatRepository, MessageRepository, db_manager
from ....exceptions import log_exceptions
from ....logger import bot_logger
from ....models import MessageActionType, MessageType
from ....services.avanpost_sync_service import AvanpostSyncService
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
@log_exceptions(bot_logger)
async def cmd_broadcast(message: Message, state: FSMContext) -> None:
    """Команда для рассылки сообщений всем чатам"""
    bot_manager = get_bot_manager()

    # Проверка прав администратора
    if not message.from_user or message.from_user.id not in settings.ADMIN_IDS:
        await bot_manager.send_answer(
            message_type=MessageType.COMMAND_ADMIN,
            event=message,
            text="⛔ У вас нет прав для этой команды.",
            clear_previous=True,
        )
        return

    if not message.from_user:
        await bot_manager.send_answer(
            text="❌ Не удалось определить пользователя.",
            event=message,
            message_type=MessageType.COMMAND_ADMIN,
            delete_by_type=MessageActionType.COMMAND_ADMIN_CLEANUP,
        )
        return

    print(f"🔍 [DEBUG] cmd_broadcast from user: {message.from_user.id}")
    print(f"🔍 [DEBUG] User: {message.from_user.first_name} (@{message.from_user.username})")

    await state.set_state(BroadcastStates.waiting_for_text)

    await bot_manager.send_answer(
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
@log_exceptions(bot_logger)
async def broadcast_get_text(message: Message, state: FSMContext) -> None:
    """Получение текста для рассылки"""
    bot_manager = get_bot_manager()

    if not message.from_user:
        await bot_manager.send_answer(
            text="❌ Не удалось определить пользователя.",
            event=message,
            message_type=MessageType.COMMAND_ADMIN,
            delete_by_type=MessageActionType.COMMAND_ADMIN_CLEANUP,
        )
        return

    # Проверка отмены
    if message.text and message.text.lower() in ["/cancel", "отмена", "cancel"]:
        await state.clear()
        await bot_manager.send_answer(
            text="❌ Рассылка отменена.",
            event=message,
            message_type=MessageType.COMMAND_ADMIN,
            delete_by_type=MessageActionType.COMMAND_ADMIN_CLEANUP,
        )
        return

    # Проверка, что текст не пустой
    if not message.text or not message.text.strip():
        await bot_manager.send_answer(
            text="❌ Текст сообщения не может быть пустым.\nПожалуйста, отправьте текст для рассылки.",
            event=message,
            message_type=MessageType.COMMAND_ADMIN,
            delete_by_type=MessageActionType.COMMAND_ADMIN_CLEANUP,
        )
        return

    # Получение количества чатов через репозиторий
    async with db_manager.get_session() as session:
        chats = await ChatRepository.get_chats(session, is_active=True)
        chat_count = len(chats)

    if chat_count == 0:
        await state.clear()
        await bot_manager.send_answer(
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
    print(f"🔍 Keyboard: {keyboard}")
    print(f"🔍 Keyboard inline_keyboard: {keyboard.inline_keyboard}")

    await bot_manager.send_answer(
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
    print("✅ Сообщение отправлено через bot_manager")


@router.message(BroadcastStates.waiting_for_confirmation)
@log_exceptions(bot_logger)
async def broadcast_confirm(message: Message, state: FSMContext) -> None:
    """Подтверждение рассылки"""
    bot_manager = get_bot_manager()

    # Проверка отмены
    if message.text and message.text.lower() in ["нет", "no", "n", "отмена", "cancel"]:
        await state.clear()
        await bot_manager.send_answer(
            text="❌ Рассылка отменена.",
            event=message,
            message_type=MessageType.COMMAND_ADMIN,
            delete_by_type=MessageActionType.COMMAND_ADMIN_CLEANUP,
        )
        return

    # Проверка подтверждения
    if not message.text or message.text.lower() not in ["да", "yes", "y", "д"]:
        await bot_manager.send_answer(
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
        await bot_manager.send_answer(
            text="❌ Текст сообщения не найден. Попробуйте начать заново.",
            event=message,
            message_type=MessageType.COMMAND_ADMIN,
            delete_by_type=MessageActionType.COMMAND_ADMIN_CLEANUP,
        )
        return

    # Отображение Toast - заменено на обычное сообщение
    await bot_manager.send_answer(
        text="🔄 Начинаю рассылку...",
        event=message,
        message_type=MessageType.COMMAND_ADMIN,
        delete_by_type=MessageActionType.COMMAND_ADMIN_CLEANUP,
    )

    # Выполнение рассылки
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

    # Отправка отчета
    await bot_manager.send_answer(
        text=report,
        event=message,
        message_type=MessageType.COMMAND_ADMIN,
        delete_by_type=MessageActionType.COMMAND_ADMIN_CLEANUP,
        parse_mode="Markdown",
    )

    await state.clear()
    if message.from_user:
        bot_logger.info(f"✅ Broadcast completed by {message.from_user.id}: {result['successful']}/{result['total']}")


@router.message(Command("delete"))
@log_exceptions(bot_logger)
async def cmd_delete_message(message: Message, state: FSMContext) -> None:
    """Команда для удаления сообщения по ID"""
    bot_manager = get_bot_manager()

    # Проверка прав администратора
    if not message.from_user or message.from_user.id not in settings.ADMIN_IDS:
        await bot_manager.send_answer(
            text="⛔ У вас нет прав для этой команды.",
            event=message,
            message_type=MessageType.COMMAND_ADMIN,
            delete_by_type=MessageActionType.COMMAND_ADMIN_CLEANUP,
        )
        return

    # Сохраняем текст команды до удаления
    command_text = message.text or ""

    if command_text is None:
        await bot_manager.send_answer(
            text="❌ Не удалось получить текст команды.",
            event=message,
            message_type=MessageType.COMMAND_ADMIN,
            delete_by_type=MessageActionType.COMMAND_ADMIN_CLEANUP,
        )
        return

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
            await bot_manager.send_answer(
                text="❌ Неверный формат ID. Используйте числа.",
                event=message,
                message_type=MessageType.COMMAND_ADMIN,
                delete_by_type=MessageActionType.COMMAND_ADMIN_CLEANUP,
            )
            return

    await state.set_state(DeleteMessageStates.waiting_for_chat_id)
    await bot_manager.send_answer(
        text="📨 **Удаление сообщения**\n\n"
        "Введите ID чата, из которого нужно удалить сообщение.\n"
        "Для отмены используйте /cancel",
        event=message,
        message_type=MessageType.COMMAND_ADMIN,
        delete_by_type=MessageActionType.COMMAND_ADMIN_CLEANUP,
    )


@router.message(DeleteMessageStates.waiting_for_chat_id)
@log_exceptions(bot_logger)
async def delete_get_chat_id(message: Message, state: FSMContext) -> None:
    """Получение ID чата для удаления"""
    bot_manager = get_bot_manager()

    if message.text and message.text.lower() in ["/cancel", "отмена", "cancel"]:
        await state.clear()
        await bot_manager.send_answer(
            text="❌ Операция отменена.",
            event=message,
            message_type=MessageType.COMMAND_ADMIN,
            delete_by_type=MessageActionType.COMMAND_ADMIN_CLEANUP,
        )
        return

    text = message.text
    if text is None or not text.strip():
        await bot_manager.send_answer(
            text="❌ Введите ID чата.",
            event=message,
            message_type=MessageType.COMMAND_ADMIN,
            delete_by_type=MessageActionType.COMMAND_ADMIN_CLEANUP,
        )
        return

    try:
        chat_id = int(text.strip())
        await state.update_data(chat_id=chat_id)
        await state.set_state(DeleteMessageStates.waiting_for_message_id)
        await bot_manager.send_answer(
            text=f"📨 ID чата: `{chat_id}`\n\n"
            "Теперь введите ID сообщения для удаления.\n"
            "Для отмены используйте /cancel",
            event=message,
            message_type=MessageType.COMMAND_ADMIN,
            delete_by_type=MessageActionType.COMMAND_ADMIN_CLEANUP,
            parse_mode="Markdown",
        )
    except ValueError:
        await bot_manager.send_answer(
            text="❌ Неверный формат ID чата. Используйте число.",
            event=message,
            message_type=MessageType.COMMAND_ADMIN,
            delete_by_type=MessageActionType.COMMAND_ADMIN_CLEANUP,
        )


@router.message(DeleteMessageStates.waiting_for_message_id)
@log_exceptions(bot_logger)
async def delete_get_message_id(message: Message, state: FSMContext) -> None:
    """Получение ID сообщения для удаления"""
    bot_manager = get_bot_manager()

    if message.text and message.text.lower() in ["/cancel", "отмена", "cancel"]:
        await state.clear()
        await bot_manager.send_answer(
            text="❌ Операция отменена.",
            event=message,
            message_type=MessageType.COMMAND_ADMIN,
            delete_by_type=MessageActionType.COMMAND_ADMIN_CLEANUP,
        )
        return

    text = message.text
    if text is None or not text.strip():
        await bot_manager.send_answer(
            text="❌ Введите ID сообщения.",
            event=message,
            message_type=MessageType.COMMAND_ADMIN,
            delete_by_type=MessageActionType.COMMAND_ADMIN_CLEANUP,
        )
        return

    try:
        message_id = int(text.strip())
        await state.update_data(message_id=message_id)
        await process_delete_confirmation(message, state)
    except ValueError:
        await bot_manager.send_answer(
            text="❌ Неверный формат ID сообщения. Используйте число.",
            event=message,
            message_type=MessageType.COMMAND_ADMIN,
            delete_by_type=MessageActionType.COMMAND_ADMIN_CLEANUP,
        )


async def process_delete_confirmation(message: Message, state: FSMContext) -> None:
    """Подтверждение удаления сообщения"""
    bot_manager = get_bot_manager()

    data = await state.get_data()
    chat_id = data.get("chat_id")
    message_id = data.get("message_id")

    await state.set_state(DeleteMessageStates.waiting_for_confirmation)

    keyboard = AdminKeyboard.get_delete_confirm_keyboard()

    await bot_manager.send_answer(
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
@log_exceptions(bot_logger)
async def delete_confirm(message: Message, state: FSMContext, _bot: Bot) -> None:
    """Подтверждение удаления сообщения"""
    bot_manager = get_bot_manager()

    if message.text and message.text.lower() in ["нет", "no", "n", "отмена", "cancel"]:
        await state.clear()
        await bot_manager.send_answer(
            text="❌ Удаление отменено.",
            event=message,
            message_type=MessageType.COMMAND_ADMIN,
            delete_by_type=MessageActionType.COMMAND_ADMIN_CLEANUP,
        )
        return

    if not message.text or message.text.lower() not in ["да", "yes", "y", "д"]:
        await bot_manager.send_answer(
            text="Пожалуйста, ответьте 'да' или 'нет'.",
            event=message,
            message_type=MessageType.COMMAND_ADMIN,
            delete_by_type=MessageActionType.COMMAND_ADMIN_CLEANUP,
        )
        return

    data = await state.get_data()
    chat_id = data.get("chat_id")
    message_id = data.get("message_id")

    if chat_id is None or message_id is None:
        await bot_manager.send_answer(
            text="❌ Данные для удаления не найдены.",
            event=message,
            message_type=MessageType.COMMAND_ADMIN,
            delete_by_type=MessageActionType.COMMAND_ADMIN_CLEANUP,
        )
        await state.clear()
        return

    try:
        async with db_manager.get_session() as session:
            db_message = await MessageRepository.get_message_by_id(session, message_id)

            if db_message:
                deleted_count = await MessageRepository.mark_messages_as_deleted(
                    session=session,
                    message_ids=[message_id],
                    deleted_by_type="admin",
                    deleted_by_message_id=message.message_id,
                )

                if deleted_count > 0:
                    if message.from_user:
                        bot_logger.info(
                            f"✅ Message {message_id} marked as deleted in DB by admin {message.from_user.id}"
                        )
                    await bot_manager.send_answer(
                        text=f"✅ Сообщение `{message_id}` успешно удалено из чата `{chat_id}`.",
                        event=message,
                        message_type=MessageType.COMMAND_ADMIN,
                        delete_by_type=MessageActionType.COMMAND_ADMIN_CLEANUP,
                        parse_mode="Markdown",
                    )
                else:
                    # Сообщение уже было удалено или не найдено
                    await bot_manager.send_answer(
                        text=f"⚠️ Сообщение `{message_id}` уже было удалено ранее.",
                        event=message,
                        message_type=MessageType.COMMAND_ADMIN,
                        delete_by_type=MessageActionType.COMMAND_ADMIN_CLEANUP,
                        parse_mode="Markdown",
                    )
            else:
                await bot_manager.send_answer(
                    text=f"❌ Сообщение `{message_id}` не найдено в базе данных.",
                    event=message,
                    message_type=MessageType.COMMAND_ADMIN,
                    delete_by_type=MessageActionType.COMMAND_ADMIN_CLEANUP,
                    parse_mode="Markdown",
                )

            await session.commit()

        # Пытаемся удалить из Telegram (если бот имеет права)
        try:
            if chat_id is not None and message_id is not None:
                await _bot.delete_message(chat_id, message_id)
                if message.from_user:
                    bot_logger.info(f"✅ Message {message_id} deleted from Telegram by admin {message.from_user.id}")
        except TelegramAPIError as e:
            # Если не удалось удалить из Telegram - логируем, но не прерываем
            bot_logger.warning(f"⚠️ Could not delete message {message_id} from Telegram: {e}")

    except TelegramAPIError as e:
        await bot_manager.send_answer(
            text=f"❌ Ошибка при удалении из Telegram: {str(e)}",
            event=message,
            message_type=MessageType.COMMAND_ADMIN,
            delete_by_type=MessageActionType.COMMAND_ADMIN_CLEANUP,
        )
    except Exception as e:
        bot_logger.error(f"❌ Failed to delete message: {e}", exc_info=True)
        await bot_manager.send_answer(
            text=f"❌ Ошибка: {str(e)}",
            event=message,
            message_type=MessageType.COMMAND_ADMIN,
            delete_by_type=MessageActionType.COMMAND_ADMIN_CLEANUP,
        )
    finally:
        await state.clear()


@router.message(Command("cancel"))
@log_exceptions(bot_logger)
async def cmd_cancel(message: Message, state: FSMContext) -> None:
    """Отмена текущей операции"""
    bot_manager = get_bot_manager()

    current_state = await state.get_state()
    if current_state is None:
        await bot_manager.send_answer(
            text="❌ Нет активных операций для отмены.",
            event=message,
            message_type=MessageType.COMMAND_ADMIN,
            delete_by_type=MessageActionType.COMMAND_ADMIN_CLEANUP,
        )
        return

    await state.clear()
    await bot_manager.send_answer(
        text="✅ Операция отменена.",
        event=message,
        message_type=MessageType.COMMAND_ADMIN,
        delete_by_type=MessageActionType.COMMAND_ADMIN_CLEANUP,
    )


@router.message(Command("admins"))
@log_exceptions(bot_logger)
async def cmd_admins(message: Message) -> None:
    """Просмотр списка администраторов"""
    bot_manager = get_bot_manager()

    if not message.from_user or message.from_user.id not in settings.ADMIN_IDS:
        await bot_manager.send_answer(
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

    await bot_manager.send_answer(
        text=response,
        event=message,
        message_type=MessageType.COMMAND_ADMIN,
        delete_by_type=MessageActionType.COMMAND_ADMIN_CLEANUP,
        parse_mode="Markdown",
    )


@router.message(Command("add_admin"))
@log_exceptions(bot_logger)
async def cmd_add_admin(message: Message) -> None:
    """Добавление администратора"""
    bot_manager = get_bot_manager()

    if not message.from_user or message.from_user.id not in settings.ADMIN_IDS:
        await bot_manager.send_answer(
            text="⛔ У вас нет прав для этой команды.",
            event=message,
            message_type=MessageType.COMMAND_ADMIN,
            delete_by_type=MessageActionType.COMMAND_ADMIN_CLEANUP,
        )
        return

    # Сохраняем текст команды до удаления
    command_text = message.text or ""

    if command_text is None:
        await bot_manager.send_answer(
            text="❌ Не удалось получить текст команды.",
            event=message,
            message_type=MessageType.COMMAND_ADMIN,
            delete_by_type=MessageActionType.COMMAND_ADMIN_CLEANUP,
        )
        return

    args = command_text.split()
    if len(args) < 2:
        await bot_manager.send_answer(
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
            await bot_manager.send_answer(
                text=f"ℹ️ Пользователь {new_admin_id} уже является администратором.",
                event=message,
                message_type=MessageType.COMMAND_ADMIN,
                delete_by_type=MessageActionType.COMMAND_ADMIN_CLEANUP,
            )
            return

        settings.ADMIN_IDS.append(new_admin_id)

        await bot_manager.send_answer(
            text=f"✅ Пользователь {new_admin_id} добавлен в админы!\n\n"
            f"⚠️ **Важно:** Для постоянного добавления обновите `ADMIN_IDS` в файле `.env`.\n"
            f"Текущий список админов: {settings.ADMIN_IDS}",
            event=message,
            message_type=MessageType.COMMAND_ADMIN,
            delete_by_type=MessageActionType.COMMAND_ADMIN_CLEANUP,
        )
        if message.from_user:
            bot_logger.info(f"✅ User {new_admin_id} added to admins by {message.from_user.id}")

    except ValueError:
        await bot_manager.send_answer(
            text="❌ Неверный формат ID. Используйте число.",
            event=message,
            message_type=MessageType.COMMAND_ADMIN,
            delete_by_type=MessageActionType.COMMAND_ADMIN_CLEANUP,
        )
    except Exception as err:
        bot_logger.error(f"❌ Failed to add admin: {err}")
        await bot_manager.send_answer(
            text=f"❌ Ошибка: {err}",
            event=message,
            message_type=MessageType.COMMAND_ADMIN,
            delete_by_type=MessageActionType.COMMAND_ADMIN_CLEANUP,
        )


@router.message(Command("remove_admin"))
@log_exceptions(bot_logger)
async def cmd_remove_admin(message: Message) -> None:
    """Удаление администратора"""
    bot_manager = get_bot_manager()

    if not message.from_user or message.from_user.id not in settings.ADMIN_IDS:
        await bot_manager.send_answer(
            text="⛔ У вас нет прав для этой команды.",
            event=message,
            message_type=MessageType.COMMAND_ADMIN,
            delete_by_type=MessageActionType.COMMAND_ADMIN_CLEANUP,
        )
        return

    if len(settings.ADMIN_IDS) <= 1:
        await bot_manager.send_answer(
            text="⚠️ Нельзя удалить единственного администратора.",
            event=message,
            message_type=MessageType.COMMAND_ADMIN,
            delete_by_type=MessageActionType.COMMAND_ADMIN_CLEANUP,
        )
        return

    # Сохраняем текст команды до удаления
    command_text = message.text or ""

    if command_text is None:
        await bot_manager.send_answer(
            text="❌ Не удалось получить текст команды.",
            event=message,
            message_type=MessageType.COMMAND_ADMIN,
            delete_by_type=MessageActionType.COMMAND_ADMIN_CLEANUP,
        )
        return

    args = command_text.split()
    if len(args) < 2:
        await bot_manager.send_answer(
            text="❌ Использование: /remove_admin <user_id>\nНапример: /remove_admin 123456789",
            event=message,
            message_type=MessageType.COMMAND_ADMIN,
            delete_by_type=MessageActionType.COMMAND_ADMIN_CLEANUP,
        )
        return

    try:
        admin_id = int(args[1])

        if admin_id not in settings.ADMIN_IDS:
            await bot_manager.send_answer(
                text=f"ℹ️ Пользователь {admin_id} не является администратором.",
                event=message,
                message_type=MessageType.COMMAND_ADMIN,
                delete_by_type=MessageActionType.COMMAND_ADMIN_CLEANUP,
            )
            return

        if admin_id == message.from_user.id:
            await bot_manager.send_answer(
                text="⚠️ Вы не можете удалить сами себя из списка админов.",
                event=message,
                message_type=MessageType.COMMAND_ADMIN,
                delete_by_type=MessageActionType.COMMAND_ADMIN_CLEANUP,
            )
            return

        settings.ADMIN_IDS.remove(admin_id)

        await bot_manager.send_answer(
            text=f"✅ Пользователь {admin_id} удален из админов!\n\n"
            f"⚠️ **Важно:** Для постоянного удаления обновите `ADMIN_IDS` в файле `.env`.\n"
            f"Текущий список админов: {settings.ADMIN_IDS}",
            event=message,
            message_type=MessageType.COMMAND_ADMIN,
            delete_by_type=MessageActionType.COMMAND_ADMIN_CLEANUP,
        )
        if message.from_user:
            bot_logger.info(f"✅ User {admin_id} removed from admins by {message.from_user.id}")

    except ValueError:
        await bot_manager.send_answer(
            text="❌ Неверный формат ID. Используйте число.",
            event=message,
            message_type=MessageType.COMMAND_ADMIN,
            delete_by_type=MessageActionType.COMMAND_ADMIN_CLEANUP,
        )
    except Exception as err:
        bot_logger.error(f"❌ Failed to remove admin: {err}")
        await bot_manager.send_answer(
            text=f"❌ Ошибка: {err}",
            event=message,
            message_type=MessageType.COMMAND_ADMIN,
            delete_by_type=MessageActionType.COMMAND_ADMIN_CLEANUP,
        )


# ============================================================
# НОВЫЕ АДМИН-КОМАНДЫ ДЛЯ СИНХРОНИЗАЦИИ AVANPOST
# ============================================================


@router.message(Command("sync_base"))
@log_exceptions(bot_logger)
async def cmd_sync_base(message: Message) -> None:
    """Синхронизация справочных данных (модели до 205)."""
    bot_manager = get_bot_manager()

    if not message.from_user or message.from_user.id not in settings.ADMIN_IDS:
        await bot_manager.send_answer(text="⛔ У вас нет прав.", event=message)
        return

    await bot_manager.delete_message_by_link(message)
    await bot_manager.send_answer(text="🔄 Запуск синхронизации справочников...", event=message)

    try:
        sync_service = AvanpostSyncService()
        await sync_service.initialize()

        # Определение ID справочников (1-17, 101-108, 201-205)
        base_ids = list(range(1, 18)) + list(range(101, 109)) + list(range(201, 206))
        bot_logger.info(f"📊 Синхронизация справочников: {base_ids}")

        stats = await sync_service.sync_base_data(force=False)
        stats_dict = stats.to_dict()

        report = (
            f"✅ Синхронизация справочников завершена!\n"
            f"📊 Обработано типов: {stats_dict.get('processed_data_types', 0)}\n"
            f"📈 Вставлено: {stats_dict.get('total_inserted', 0)}\n"
            f"🔄 Обновлено: {stats_dict.get('total_updated', 0)}\n"
            f"🗑️ Удалено: {stats_dict.get('total_deleted', 0)}\n"
            f"⏭️ Без изменений: {stats_dict.get('total_unchanged', 0)}\n"
            f"❌ Ошибок: {len(stats_dict.get('error_messages', []))}"
        )
        if stats_dict.get("error_messages"):
            report += f"\n⚠️ Первая ошибка: {stats_dict['error_messages'][0][:100]}"

        await bot_manager.send_answer(text=report, event=message)

    except Exception as e:
        bot_logger.error(f"❌ sync_base failed: {e}", exc_info=True)
        await bot_manager.send_answer(text=f"❌ Ошибка: {e}", event=message)


@router.message(Command("sync_contacts"))
@log_exceptions(bot_logger)
async def cmd_sync_contacts(message: Message) -> None:
    """Синхронизация контактов (модели 301-303)."""
    bot_manager = get_bot_manager()

    if not message.from_user or message.from_user.id not in settings.ADMIN_IDS:
        await bot_manager.send_answer(text="⛔ У вас нет прав.", event=message)
        return

    await bot_manager.delete_message_by_link(message)
    await bot_manager.send_answer(text="🔄 Запуск синхронизации контактов...", event=message)

    try:
        sync_service = AvanpostSyncService()
        await sync_service.initialize()

        # Определение ID контактов (301-303)
        contact_ids = list(range(301, 304))
        bot_logger.info(f"📊 Синхронизация контактов: {contact_ids}")

        stats = await sync_service.sync_base_data(force=False)
        stats_dict = stats.to_dict()

        # Фильтруем статистику только для контактов
        table_stats = stats_dict.get("table_stats", {})
        contact_tables = ["TAvanpostContacts", "TAvanpostContactsLangs", "TAvanpostContactsLinks"]
        contact_stats = {k: v for k, v in table_stats.items() if k in contact_tables}

        total_inserted = sum(s.get("inserted", 0) for s in contact_stats.values())
        total_updated = sum(s.get("updated", 0) for s in contact_stats.values())
        total_deleted = sum(s.get("deleted", 0) for s in contact_stats.values())

        report = (
            f"✅ Синхронизация контактов завершена!\n"
            f"📈 Вставлено: {total_inserted}\n"
            f"🔄 Обновлено: {total_updated}\n"
            f"🗑️ Удалено: {total_deleted}\n"
        )

        if contact_stats:
            report += "\n📊 Детали по таблицам:\n"
            for table, s in contact_stats.items():
                report += f"  • {table}: +{s.get('inserted', 0)} / ~{s.get('updated', 0)} / -{s.get('deleted', 0)}\n"

        await bot_manager.send_answer(text=report, event=message)

    except Exception as e:
        bot_logger.error(f"❌ sync_contacts failed: {e}", exc_info=True)
        await bot_manager.send_answer(text=f"❌ Ошибка: {e}", event=message)


@router.message(Command("sync_user"))
@log_exceptions(bot_logger)
async def cmd_sync_user(message: Message) -> None:
    """Синхронизация данных конкретного пользователя."""
    bot_manager = get_bot_manager()

    if not message.from_user or message.from_user.id not in settings.ADMIN_IDS:
        await bot_manager.send_answer(text="⛔ У вас нет прав.", event=message)
        return

    await bot_manager.delete_message_by_link(message)

    command_text = message.text or ""
    if command_text is None:
        await bot_manager.send_answer(
            text="❌ Не удалось получить текст команды.",
            event=message,
        )
        return

    parts = command_text.split()
    if len(parts) < 2:
        await bot_manager.send_answer(
            text="❌ Использование: /sync_user <user_id>\n"
            "Например: /sync_user 123456789\n\n"
            "💡 user_id - это ID пользователя в Telegram",
            event=message,
        )
        return

    try:
        user_id = int(parts[1])
        await bot_manager.send_answer(text=f"🔄 Запуск синхронизации для пользователя {user_id}...", event=message)

        sync_service = AvanpostSyncService()
        await sync_service.initialize()

        stats = await sync_service.sync_user_data(user_id=user_id, force=False)
        stats_dict = stats.to_dict()

        report = (
            f"✅ Синхронизация пользователя {user_id} завершена!\n"
            f"📊 Обработано типов: {stats_dict.get('processed_data_types', 0)}\n"
            f"📈 Вставлено: {stats_dict.get('total_inserted', 0)}\n"
            f"🔄 Обновлено: {stats_dict.get('total_updated', 0)}\n"
            f"🗑️ Удалено: {stats_dict.get('total_deleted', 0)}\n"
            f"⏭️ Без изменений: {stats_dict.get('total_unchanged', 0)}\n"
            f"❌ Ошибок: {len(stats_dict.get('error_messages', []))}"
        )

        # Показываем детали по таблицам, если есть изменения
        table_stats = stats_dict.get("table_stats", {})
        changed_tables = {
            k: v
            for k, v in table_stats.items()
            if v.get("inserted", 0) > 0 or v.get("updated", 0) > 0 or v.get("deleted", 0) > 0
        }
        if changed_tables:
            report += "\n\n📊 Изменения по таблицам:\n"
            for table, s in list(changed_tables.items())[:5]:
                report += f"  • {table}: +{s.get('inserted', 0)} / ~{s.get('updated', 0)} / -{s.get('deleted', 0)}\n"
            if len(changed_tables) > 5:
                report += f"  • ... и еще {len(changed_tables) - 5} таблиц"

        await bot_manager.send_answer(text=report, event=message)

    except ValueError:
        await bot_manager.send_answer(text="❌ Неверный формат ID. Используйте число.", event=message)
    except Exception as e:
        bot_logger.error(f"❌ sync_user failed: {e}", exc_info=True)
        await bot_manager.send_answer(text=f"❌ Ошибка: {e}", event=message)


@router.message(Command("sync_all_users"))
@log_exceptions(bot_logger)
async def cmd_sync_all_users(message: Message) -> None:
    """Синхронизация данных всех пользователей."""
    bot_manager = get_bot_manager()

    if not message.from_user or message.from_user.id not in settings.ADMIN_IDS:
        await bot_manager.send_answer(text="⛔ У вас нет прав.", event=message)
        return

    await bot_manager.delete_message_by_link(message)
    await bot_manager.send_answer(
        text="🔄 Запуск синхронизации для всех пользователей...\n"
        "Это может занять длительное время в зависимости от количества пользователей.",
        event=message,
    )

    try:
        sync_service = AvanpostSyncService()
        await sync_service.initialize()

        result = await sync_service.sync_all_users(force=False)

        report = (
            f"✅ Синхронизация всех пользователей завершена!\n"
            f"👥 Всего пользователей: {result.get('total_users', 0)}\n"
            f"✅ Успешно: {result.get('successful', 0)}\n"
            f"❌ Ошибок: {result.get('failed', 0)}\n"
            f"📈 Вставлено: {result.get('total_inserted', 0)}\n"
            f"🔄 Обновлено: {result.get('total_updated', 0)}\n"
            f"🗑️ Удалено: {result.get('total_deleted', 0)}\n"
            f"⏭️ Без изменений: {result.get('total_unchanged', 0)}"
        )

        if result.get("errors"):
            report += f"\n⚠️ Первая ошибка: {result['errors'][0][:100]}"

        await bot_manager.send_answer(text=report, event=message)

    except Exception as e:
        bot_logger.error(f"❌ sync_all_users failed: {e}", exc_info=True)
        await bot_manager.send_answer(text=f"❌ Ошибка: {e}", event=message)


@router.message(Command("sync_light"))
@log_exceptions(bot_logger)
async def cmd_sync_light(message: Message) -> None:
    """Стандартная синхронизация (без Force)."""
    bot_manager = get_bot_manager()

    if not message.from_user or message.from_user.id not in settings.ADMIN_IDS:
        await bot_manager.send_answer(text="⛔ У вас нет прав.", event=message)
        return

    await bot_manager.delete_message_by_link(message)
    await bot_manager.send_answer(text="🔄 Запуск стандартной синхронизации...", event=message)

    try:
        result = await db_manager.sync_avanpost(force=False)

        if result.get("success"):
            stats = result.get("stats", {})
            report = (
                f"✅ Стандартная синхронизация завершена!\n"
                f"📈 Вставлено: {stats.get('total_inserted', 0)}\n"
                f"🔄 Обновлено: {stats.get('total_updated', 0)}\n"
                f"🗑️ Удалено: {stats.get('total_deleted', 0)}\n"
                f"⏭️ Без изменений: {stats.get('total_unchanged', 0)}\n"
                f"❌ Ошибок: {len(stats.get('error_messages', []))}"
            )
            if stats.get("error_messages"):
                report += f"\n⚠️ Первая ошибка: {stats['error_messages'][0][:100]}"
        else:
            report = f"❌ Синхронизация завершена с ошибкой: {result.get('message', 'Unknown error')}"

        await bot_manager.send_answer(text=report, event=message)

    except Exception as e:
        bot_logger.error(f"❌ sync_light failed: {e}", exc_info=True)
        await bot_manager.send_answer(text=f"❌ Ошибка: {e}", event=message)


@router.message(Command("sync_force"))
@log_exceptions(bot_logger)
async def cmd_sync_force(message: Message) -> None:
    """Полная синхронизация с Force=True."""
    bot_manager = get_bot_manager()

    if not message.from_user or message.from_user.id not in settings.ADMIN_IDS:
        await bot_manager.send_answer(text="⛔ У вас нет прав.", event=message)
        return

    await bot_manager.delete_message_by_link(message)
    await bot_manager.send_answer(
        text="🔄 Запуск полной синхронизации (Force)...\nЭто может занять длительное время.", event=message
    )

    try:
        result = await db_manager.sync_avanpost(force=True)

        if result.get("success"):
            stats = result.get("stats", {})
            report = (
                f"✅ Полная синхронизация (Force) завершена!\n"
                f"📈 Вставлено: {stats.get('total_inserted', 0)}\n"
                f"🔄 Обновлено: {stats.get('total_updated', 0)}\n"
                f"🗑️ Удалено: {stats.get('total_deleted', 0)}\n"
                f"⏭️ Без изменений: {stats.get('total_unchanged', 0)}\n"
                f"❌ Ошибок: {len(stats.get('error_messages', []))}"
            )
            if stats.get("error_messages"):
                report += f"\n⚠️ Первая ошибка: {stats['error_messages'][0][:100]}"
        else:
            report = f"❌ Полная синхронизация завершена с ошибкой: {result.get('message', 'Unknown error')}"

        await bot_manager.send_answer(text=report, event=message)

    except Exception as e:
        bot_logger.error(f"❌ sync_force failed: {e}", exc_info=True)
        await bot_manager.send_answer(text=f"❌ Ошибка: {e}", event=message)


# ============================================================
# ОБРАБОТЧИКИ КОЛБЭКОВ
# ============================================================


@router.callback_query(lambda c: c.data in ["broadcast_confirm", "broadcast_cancel"])
@log_exceptions(bot_logger)
async def handle_broadcast_callback(callback: CallbackQuery, state: FSMContext) -> None:
    """Обработка колбэков для рассылки"""
    from ...callbacks.admin import admin_callback_handler

    await admin_callback_handler.handle(callback, state)


@router.callback_query(lambda c: c.data in ["delete_confirm", "delete_cancel"])
@log_exceptions(bot_logger)
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
    "cmd_sync_base",
    "cmd_sync_contacts",
    "cmd_sync_user",
    "cmd_sync_all_users",
    "cmd_sync_light",
    "cmd_sync_force",
]
