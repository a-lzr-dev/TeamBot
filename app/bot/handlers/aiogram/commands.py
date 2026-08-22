# app/bot/handlers/aiogram/commands.py

"""
Модуль дополнительных команд.
"""

from aiogram import Router
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.types import Message

from ....bot.dependencies import get_bot_manager
from ....db import db_manager
from ....db.repositories import MessageRepository
from ....logger import bot_logger
from ....models import MessageActionType, MessageType
from ....utils.decorators import log_exceptions

router = Router(name="aiogram_commands")


# ============================================================
# КОМАНДА /help
# ============================================================


@router.message(Command("help"))
@log_exceptions(bot_logger)
async def cmd_help(message: Message, state: FSMContext) -> None:
    """Команда помощи."""
    bot_manager = get_bot_manager()

    if not message.from_user:
        await bot_manager.send_answer(
            text="❌ Не удалось определить пользователя.",
            event=message,
            message_type=MessageType.COMMAND_ACTION_INFO,
            delete_by_type=MessageActionType.COMMAND_ACTION_CLEANUP,
        )
        return

    help_text = (
        "🤖 **TeamBot - Помощь**\n\n"
        "**Основные команды:**\n"
        "/start - Авторизация\n"
        "/help - Эта справка\n"
        "/actions - Меню действий\n"
        "/automation - Автоматизация\n"
        "/stats - Статистика\n"
        "/id - Мой ID\n\n"
        "**Работа с сообщениями:**\n"
        "/msg <id> - Контекстное меню сообщения\n"
        "/find <id> - Найти сообщение в чате\n\n"
        "**Административные:**\n"
        "/users - Список пользователей\n"
        "/broadcast - Рассылка\n"
        "/delete - Удалить сообщение\n"
        "/sync - Синхронизация\n\n"
        "📌 Используйте /logout для выхода из системы"
    )

    await bot_manager.send_answer(
        text=help_text,
        event=message,
        message_type=MessageType.COMMAND_ACTION_INFO,
        delete_by_type=MessageActionType.COMMAND_ACTION_CLEANUP,
        parse_mode="Markdown",
    )


# ============================================================
# КОМАНДА /id
# ============================================================


@router.message(Command("id"))
@log_exceptions(bot_logger)
async def cmd_id(message: Message, state: FSMContext) -> None:
    """Команда для получения ID пользователя и чата."""
    bot_manager = get_bot_manager()

    if not message.from_user:
        await bot_manager.send_answer(
            text="❌ Не удалось определить пользователя.",
            event=message,
            message_type=MessageType.COMMAND_ACTION_INFO,
            delete_by_type=MessageActionType.COMMAND_ACTION_CLEANUP,
        )
        return

    user = message.from_user
    text = f"🆔 **Информация о пользователе**\n\n👤 ID: `{user.id}`\n📝 Имя: {user.first_name or 'Не указано'}\n"

    if user.last_name:
        text += f"📝 Фамилия: {user.last_name}\n"
    if user.username:
        text += f"🔗 Username: @{user.username}\n"
    text += f"🤖 Бот: {'Да' if user.is_bot else 'Нет'}\n\n"
    text += f"💬 Chat ID: `{message.chat.id}`\n"

    await bot_manager.send_answer(
        text=text,
        event=message,
        message_type=MessageType.COMMAND_ACTION_INFO,
        delete_by_type=MessageActionType.COMMAND_ACTION_CLEANUP,
        parse_mode="Markdown",
    )


# ============================================================
# КОМАНДА /msg
# ============================================================


@router.message(Command("msg"))
@log_exceptions(bot_logger)
async def cmd_msg(message: Message, state: FSMContext) -> None:
    """Команда для открытия контекстного меню сообщения по ID."""
    bot_manager = get_bot_manager()

    if not message.from_user:
        await bot_manager.send_answer(
            text="❌ Не удалось определить пользователя.",
            event=message,
            message_type=MessageType.COMMAND_AUTH,
            delete_by_type=MessageActionType.COMMAND_AUTH_CLEANUP,
        )
        return

    command_text = message.text or ""
    parts = command_text.split()

    if len(parts) < 2:
        await bot_manager.send_answer(
            text="❌ **Использование:** `/msg <id_сообщения>`\n\n"
            "Например: `/msg 12345`\n"
            "Чтобы узнать ID сообщения, используйте `/id`",
            event=message,
            message_type=MessageType.COMMAND_ACTION_INFO,
            delete_by_type=MessageActionType.COMMAND_ACTION_CLEANUP,
            parse_mode="Markdown",
        )
        return

    try:
        message_id = int(parts[1])
    except ValueError:
        await bot_manager.send_answer(
            text="❌ Неверный ID сообщения. Используйте число.",
            event=message,
            message_type=MessageType.COMMAND_ACTION_INFO,
            delete_by_type=MessageActionType.COMMAND_ACTION_CLEANUP,
        )
        return

    try:
        async with db_manager.get_session() as session:
            repo = MessageRepository()
            db_message = await repo.get_message_by_id(session, message_id)

            if not db_message:
                await bot_manager.send_answer(
                    text=f"❌ Сообщение с ID `{message_id}` не найдено.",
                    event=message,
                    message_type=MessageType.COMMAND_ACTION_INFO,
                    delete_by_type=MessageActionType.COMMAND_ACTION_CLEANUP,
                    parse_mode="Markdown",
                )
                return

            from app.bot.handlers.aiogram.custom.chat_message_menu import show_message_context_menu

            await show_message_context_menu(
                event=message,
                state=state,
                message_id=message_id,
                chat_id=db_message.FK_Chat,
                edit_original=False,
            )

            await bot_manager.delete_message_by_link(message)

    except ImportError:
        bot_logger.error("❌ chat_message_menu module not found")
        await bot_manager.send_answer(
            text="❌ Функция временно недоступна. Попробуйте позже.",
            event=message,
            message_type=MessageType.COMMAND_ACTION_INFO,
            delete_by_type=MessageActionType.COMMAND_ACTION_CLEANUP,
        )
    except Exception as e:
        bot_logger.error(f"❌ Error in cmd_msg: {e}", exc_info=True)
        await bot_manager.send_answer(
            text="❌ Ошибка при обработке команды. Попробуйте позже.",
            event=message,
            message_type=MessageType.COMMAND_ACTION_INFO,
            delete_by_type=MessageActionType.COMMAND_ACTION_CLEANUP,
        )


# ============================================================
# КОМАНДА /find
# ============================================================


@router.message(Command("find"))
@log_exceptions(bot_logger)
async def cmd_find(message: Message, state: FSMContext) -> None:
    """Команда для поиска сообщения по ID."""
    bot_manager = get_bot_manager()

    if not message.from_user:
        await bot_manager.send_answer(
            text="❌ Не удалось определить пользователя.",
            event=message,
            message_type=MessageType.COMMAND_ACTION_INFO,
            delete_by_type=MessageActionType.COMMAND_ACTION_CLEANUP,
        )
        return

    command_text = message.text or ""
    parts = command_text.split()

    if len(parts) < 2:
        await bot_manager.send_answer(
            text="❌ **Использование:** `/find <id_сообщения>`\n\nНапример: `/find 12345`",
            event=message,
            message_type=MessageType.COMMAND_ACTION_INFO,
            delete_by_type=MessageActionType.COMMAND_ACTION_CLEANUP,
            parse_mode="Markdown",
        )
        return

    try:
        message_id = int(parts[1])
    except ValueError:
        await bot_manager.send_answer(
            text="❌ Неверный ID сообщения. Используйте число.",
            event=message,
            message_type=MessageType.COMMAND_ACTION_INFO,
            delete_by_type=MessageActionType.COMMAND_ACTION_CLEANUP,
        )
        return

    try:
        async with db_manager.get_session() as session:
            repo = MessageRepository()
            db_message = await repo.get_message_by_id(session, message_id)

            if not db_message:
                await bot_manager.send_answer(
                    text=f"❌ Сообщение с ID `{message_id}` не найдено.",
                    event=message,
                    message_type=MessageType.COMMAND_ACTION_INFO,
                    delete_by_type=MessageActionType.COMMAND_ACTION_CLEANUP,
                    parse_mode="Markdown",
                )
                return

            text = (
                f"🔍 **Найдено сообщение #{message_id}**\n\n"
                f"💬 Чат: `{db_message.FK_Chat}`\n"
                f"📅 Дата: {db_message.FDateSent.strftime('%d.%m.%Y %H:%M') if db_message.FDateSent else 'неизвестно'}\n\n"
            )
            if db_message.FText:
                text += f"📝 {db_message.FText}\n\n"
            text += f"🔗 Используйте `/msg {message_id}` для открытия меню действий"

            await bot_manager.send_answer(
                text=text,
                event=message,
                message_type=MessageType.COMMAND_ACTION_INFO,
                delete_by_type=MessageActionType.COMMAND_ACTION_CLEANUP,
                parse_mode="Markdown",
            )

            await bot_manager.delete_message_by_link(message)

    except ImportError:
        bot_logger.error("❌ MessageRepository not found")
        await bot_manager.send_answer(
            text="❌ Функция временно недоступна. Попробуйте позже.",
            event=message,
            message_type=MessageType.COMMAND_ACTION_INFO,
            delete_by_type=MessageActionType.COMMAND_ACTION_CLEANUP,
        )
    except Exception as e:
        bot_logger.error(f"❌ Error in cmd_find: {e}", exc_info=True)
        await bot_manager.send_answer(
            text="❌ Ошибка при обработке команды. Попробуйте позже.",
            event=message,
            message_type=MessageType.COMMAND_ACTION_INFO,
            delete_by_type=MessageActionType.COMMAND_ACTION_CLEANUP,
        )


__all__ = [
    "router",
]
