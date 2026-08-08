from aiogram import Router
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.types import Message
from sqlalchemy import func, select

from ....config import settings
from ....db import db_manager
from ....exceptions import log_exceptions
from ....logger import tg_logger
from ....models import ChatMemberModel, ChatModel, MessageActionType, MessageType, UserModel
from ....tg.dependencies import get_tg_manager

router = Router(name="aiogram_commands")


@router.message(Command("help"))
@log_exceptions(tg_logger)
async def cmd_help(message: Message) -> None:
    """Обработчик команды /help"""
    tg_manager = get_tg_manager()

    await tg_manager.delete_message_by_link(message)

    is_admin = message.from_user and message.from_user.id in settings.ADMIN_IDS

    help_text = (
        "🤖 **Помощь по боту**\n\n"
        "**📋 Команды:**\n"
        "/start - Начать работу с ботом\n"
        "/help - Показать эту справку\n"
        "/stats - Показать статистику (админ)\n"
        "/sync - Синхронизировать чаты (админ)\n"
        "/id - Показать мой ID\n"
        "/actions - Меню действий\n"
        "/add_admin - Добавить администратора (админ)\n"
        "/remove_admin - Удалить администратора (админ)\n"
        "/admins - Список администраторов (админ)\n"
    )

    if is_admin:
        help_text += "/groups - Группы действий (админ)\n"

    help_text += (
        "\n**⚙️ Функции:**\n"
        "• Отслеживание добавления/удаления бота из чатов\n"
        "• Отслеживание присоединения/выхода участников\n"
        "• Ведение базы данных чатов и участников\n"
        "• Приветствие новых участников\n\n"
        "**📊 Статистика:**\n"
        "Бот отслеживает:\n"
        "• Количество чатов, где он присутствует\n"
        "• Количество участников в каждом чате\n"
        "• Активность пользователей\n\n"
        "**💡 Советы:**\n"
        "• Добавьте бота в группу с правами администратора\n"
        "• Бот будет автоматически отслеживать всех участников\n"
        "• Для получения статистики используйте /stats"
    )

    await tg_manager.send_answer(
        text=help_text,
        event=message,
        message_type=MessageType.COMMAND,
        delete_by_type=MessageActionType.COMMAND_CLEANUP,
        parse_mode="Markdown",
    )


@router.message(Command("stats"))
@log_exceptions(tg_logger)
async def cmd_stats(message: Message) -> None:
    """Обработчик команды /stats - статистика"""
    tg_manager = get_tg_manager()

    if not message.from_user or message.from_user.id not in settings.ADMIN_IDS:
        await tg_manager.send_answer(
            text="⛔ У вас нет прав для этой команды.",
            event=message,
            message_type=MessageType.COMMAND,
            delete_by_type=MessageActionType.COMMAND_CLEANUP,
        )
        return

    await tg_manager.delete_message_by_link(message)

    async with db_manager.get_session() as session:
        total_chats = await session.scalar(select(func.count()).select_from(ChatModel)) or 0

        active_chats = (
            await session.scalar(select(func.count()).select_from(ChatModel).where(ChatModel.FFlagActive)) or 0
        )

        total_users = await session.scalar(select(func.count()).select_from(UserModel)) or 0

        active_members = (
            await session.scalar(select(func.count()).select_from(ChatMemberModel).where(ChatMemberModel.FFlagActive))
            or 0
        )

        stmt = (
            select(ChatModel.FID, ChatModel.FTitle, func.count(ChatMemberModel.FID).label("members_count"))
            .outerjoin(ChatMemberModel, ChatMemberModel.FK_Chat == ChatModel.FID)
            .where(ChatModel.FFlagActive)
            .group_by(ChatModel.FID, ChatModel.FTitle)
            .limit(10)
        )
        result = await session.execute(stmt)
        top_chats = result.all()

    stats_text = (
        f"📊 **Статистика бота**\n\n"
        f"**Чаты:**\n"
        f"• Всего: {total_chats}\n"
        f"• Активные: {active_chats}\n"
        f"• Неактивные: {total_chats - active_chats}\n\n"
        f"**Пользователи:**\n"
        f"• Всего: {total_users}\n"
        f"• Активных участников: {active_members}\n\n"
        f"**Топ-10 чатов по участникам:**\n"
    )

    for chat in top_chats:
        chat_title = chat.FTitle or f"Chat {chat.FID}"
        stats_text += f"• {chat_title}: {chat.members_count} участников\n"

    await tg_manager.send_answer(
        text=stats_text,
        event=message,
        message_type=MessageType.COMMAND,
        delete_by_type=MessageActionType.COMMAND_CLEANUP,
        parse_mode="Markdown",
    )
    tg_logger.info(f"✅ Stats sent to user {message.from_user.id}")


@router.message(Command("sync"))
@log_exceptions(tg_logger)
async def cmd_sync(message: Message) -> None:
    """Принудительная синхронизация чатов"""
    tg_manager = get_tg_manager()

    if not message.from_user or message.from_user.id not in settings.ADMIN_IDS:
        await tg_manager.send_answer(
            text="⛔ У вас нет прав для этой команды.",
            event=message,
            message_type=MessageType.COMMAND,
            delete_by_type=MessageActionType.COMMAND_CLEANUP,
        )
        return

    await tg_manager.delete_message_by_link(message)

    try:
        status = await tg_manager.get_status()

        # Проверка статуса Telethon
        telethon_status = status.get("telethon", {})
        if not telethon_status.get("connected", False):
            await tg_manager.send_answer(
                text="❌ Telethon клиент не доступен.",
                event=message,
                message_type=MessageType.COMMAND,
                delete_by_type=MessageActionType.COMMAND_CLEANUP,
            )
            return

        await tg_manager.send_toast(text="🔄 Начинаю синхронизацию всех чатов...", message=message)

        result = await tg_manager.sync_all_chats(force=True)

        if result.get("error"):
            await tg_manager.send_answer(
                text=f"❌ Ошибка синхронизации: {result['error']}",
                event=message,
                message_type=MessageType.COMMAND,
                delete_by_type=MessageActionType.COMMAND_CLEANUP,
            )
            return

        # Формирование отчета о синхронизации
        if "processed" in result:
            report = (
                f"✅ Синхронизация завершена!\n\n"
                f"📊 **Статистика:**\n"
                f"• Обработано чатов: {result.get('processed', {}).get('chats', 0)}\n"
                f"• Обработано участников: {result.get('processed', {}).get('members', 0)}\n"
                f"• Добавлено чатов: {result.get('added', {}).get('chats', 0)}\n"
                f"• Добавлено участников: {result.get('added', {}).get('members', 0)}\n"
                f"• Деактивировано чатов: {result.get('deactivated', {}).get('chats', 0)}\n"
                f"• Деактивировано участников: {result.get('deactivated', {}).get('members', 0)}\n"
                f"• Ошибок: {result.get('errors', {}).get('chats', 0)} чатов, "
                f"{result.get('errors', {}).get('members', 0)} участников"
            )
            await tg_manager.send_answer(
                text=report,
                event=message,
                message_type=MessageType.COMMAND,
                delete_by_type=MessageActionType.COMMAND_CLEANUP,
                parse_mode="Markdown",
            )
        else:
            await tg_manager.send_answer(
                text="✅ Синхронизация всех чатов завершена!",
                event=message,
                message_type=MessageType.COMMAND,
                delete_by_type=MessageActionType.COMMAND_CLEANUP,
            )

        tg_logger.info(f"✅ Sync completed by user {message.from_user.id}")

    except Exception as err:
        tg_logger.error(f"❌ Sync command failed: {err}", exc_info=True)
        await tg_manager.send_answer(
            text=f"❌ Ошибка синхронизации: {str(err)}",
            event=message,
            message_type=MessageType.COMMAND,
            delete_by_type=MessageActionType.COMMAND_CLEANUP,
        )


@router.message(Command("id"))
@log_exceptions(tg_logger)
async def cmd_id(message: Message) -> None:
    """Получение ID чата и пользователя"""
    tg_manager = get_tg_manager()

    await tg_manager.delete_message_by_link(message)

    user_id = message.from_user.id if message.from_user else None
    chat_id = message.chat.id
    chat_type = message.chat.type

    response = f"📌 **Информация об ID**\n\n• Ваш ID: `{user_id}`\n• ID чата: `{chat_id}`\n• Тип чата: `{chat_type}`\n"

    if message.chat.title:
        response += f"• Название чата: `{message.chat.title}`\n"

    if message.from_user and message.from_user.username:
        response += f"• Username: @{message.from_user.username}\n"

    is_admin = message.from_user and message.from_user.id in settings.ADMIN_IDS
    response += f"\n• Администратор: {'✅ Да' if is_admin else '❌ Нет'}"

    await tg_manager.send_answer(
        text=response,
        event=message,
        message_type=MessageType.COMMAND,
        delete_by_type=MessageActionType.COMMAND_CLEANUP,
        parse_mode="Markdown",
    )


@router.message(Command("cancel"))
@log_exceptions(tg_logger)
async def cmd_cancel(message: Message, state: FSMContext) -> None:
    """Отмена текущей операции"""
    tg_manager = get_tg_manager()

    await tg_manager.delete_message_by_link(message)

    current_state = await state.get_state()
    if current_state is None:
        await tg_manager.send_answer(
            text="❌ Нет активных операций для отмены.",
            event=message,
            message_type=MessageType.COMMAND,
            delete_by_type=MessageActionType.COMMAND_CLEANUP,
        )
        return

    await state.clear()
    await tg_manager.send_answer(
        text="✅ Операция отменена.",
        event=message,
        message_type=MessageType.COMMAND,
        delete_by_type=MessageActionType.COMMAND_CLEANUP,
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
            message_type=MessageType.COMMAND,
            delete_by_type=MessageActionType.COMMAND_CLEANUP,
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
        message_type=MessageType.COMMAND,
        delete_by_type=MessageActionType.COMMAND_CLEANUP,
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
            message_type=MessageType.COMMAND,
            delete_by_type=MessageActionType.COMMAND_CLEANUP,
        )
        return

    args = message.text.split()
    if len(args) < 2:
        await tg_manager.send_answer(
            text="❌ Использование: /add_admin <user_id>\n"
            "Например: /add_admin 123456789\n\n"
            "💡 Чтобы узнать свой ID, используйте /id",
            event=message,
            message_type=MessageType.COMMAND,
            delete_by_type=MessageActionType.COMMAND_CLEANUP,
        )
        return

    try:
        new_admin_id = int(args[1])

        if new_admin_id in settings.ADMIN_IDS:
            await tg_manager.send_answer(
                text=f"ℹ️ Пользователь {new_admin_id} уже является администратором.",
                event=message,
                message_type=MessageType.COMMAND,
                delete_by_type=MessageActionType.COMMAND_CLEANUP,
            )
            return

        settings.ADMIN_IDS.append(new_admin_id)

        await tg_manager.send_answer(
            text=f"✅ Пользователь {new_admin_id} добавлен в админы!\n\n"
            f"⚠️ **Важно:** Для постоянного добавления обновите `ADMIN_IDS` в файле `.env`.\n"
            f"Текущий список админов: {settings.ADMIN_IDS}",
            event=message,
            message_type=MessageType.COMMAND,
            delete_by_type=MessageActionType.COMMAND_CLEANUP,
        )
        tg_logger.info(f"✅ User {new_admin_id} added to admins by {message.from_user.id}")

    except ValueError:
        await tg_manager.send_answer(
            text="❌ Неверный формат ID. Используйте число.",
            event=message,
            message_type=MessageType.COMMAND,
            delete_by_type=MessageActionType.COMMAND_CLEANUP,
        )
    except Exception as err:
        tg_logger.error(f"❌ Failed to add admin: {err}")
        await tg_manager.send_answer(
            text=f"❌ Ошибка: {err}",
            event=message,
            message_type=MessageType.COMMAND,
            delete_by_type=MessageActionType.COMMAND_CLEANUP,
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
            message_type=MessageType.COMMAND,
            delete_by_type=MessageActionType.COMMAND_CLEANUP,
        )
        return

    if len(settings.ADMIN_IDS) <= 1:
        await tg_manager.send_answer(
            text="⚠️ Нельзя удалить единственного администратора.",
            event=message,
            message_type=MessageType.COMMAND,
            delete_by_type=MessageActionType.COMMAND_CLEANUP,
        )
        return

    args = message.text.split()
    if len(args) < 2:
        await tg_manager.send_answer(
            text="❌ Использование: /remove_admin <user_id>\nНапример: /remove_admin 123456789",
            event=message,
            message_type=MessageType.COMMAND,
            delete_by_type=MessageActionType.COMMAND_CLEANUP,
        )
        return

    try:
        admin_id = int(args[1])

        if admin_id not in settings.ADMIN_IDS:
            await tg_manager.send_answer(
                text=f"ℹ️ Пользователь {admin_id} не является администратором.",
                event=message,
                message_type=MessageType.COMMAND,
                delete_by_type=MessageActionType.COMMAND_CLEANUP,
            )
            return

        if admin_id == message.from_user.id:
            await tg_manager.send_answer(
                text="⚠️ Вы не можете удалить сами себя из списка админов.",
                event=message,
                message_type=MessageType.COMMAND,
                delete_by_type=MessageActionType.COMMAND_CLEANUP,
            )
            return

        settings.ADMIN_IDS.remove(admin_id)

        await tg_manager.send_answer(
            text=f"✅ Пользователь {admin_id} удален из админов!\n\n"
            f"⚠️ **Важно:** Для постоянного удаления обновите `ADMIN_IDS` в файле `.env`.\n"
            f"Текущий список админов: {settings.ADMIN_IDS}",
            event=message,
            message_type=MessageType.COMMAND,
            delete_by_type=MessageActionType.COMMAND_CLEANUP,
        )
        tg_logger.info(f"✅ User {admin_id} removed from admins by {message.from_user.id}")

    except ValueError:
        await tg_manager.send_answer(
            text="❌ Неверный формат ID. Используйте число.",
            event=message,
            message_type=MessageType.COMMAND,
            delete_by_type=MessageActionType.COMMAND_CLEANUP,
        )
    except Exception as err:
        tg_logger.error(f"❌ Failed to remove admin: {err}")
        await tg_manager.send_answer(
            text=f"❌ Ошибка: {err}",
            event=message,
            message_type=MessageType.COMMAND,
            delete_by_type=MessageActionType.COMMAND_CLEANUP,
        )


__all__ = [
    "router",
]
