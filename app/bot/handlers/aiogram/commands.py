"""Модуль обработчиков основных команд Telegram бота.

Этот модуль предоставляет обработчики для базовых команд, доступных
всем пользователям, а также дополнительные утилиты для работы с сообщениями.

Содержит команды:
    1. /help   - Динамическая справка с учетом прав пользователя
    2. /id     - Получение ID пользователя и чата
    3. /msg    - Открытие контекстного меню сообщения по ID

Логика работы команд:
    - /help: Анализирует статус пользователя (неавторизован/авторизован/админ)
             и показывает только доступные команды.
    - /id:   Выводит техническую информацию о пользователе и чате.
    - /msg:  Принимает ID сообщения и открывает контекстное меню для него.

Примечания:
    - Все команды используют единый механизм очистки старых сообщений.
    - Для работы /msg требуется доступ к базе данных Avanpost.
"""

from aiogram import Router
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.types import Message

from ....bot.dependencies import get_bot_manager
from ....config import settings
from ....db import db_manager
from ....logger import bot_logger
from ....models import MessageActionType, MessageType
from ....utils.decorators import log_exceptions
from .auth import is_user_authenticated

# Создание роутера для команд
router = Router(name="aiogram_commands")


# ============================================================
# 1. КОМАНДА /help - ДИНАМИЧЕСКАЯ СПРАВКА
# ============================================================


@router.message(Command("help"))
@log_exceptions(bot_logger)
async def cmd_help(message: Message, state: FSMContext) -> None:
    """Команда /help — динамическая справка по доступным командам.

    Анализирует статус пользователя и показывает только те команды,
    которые доступны в текущем контексте.

    Логика вывода:
        1. Базовые команды (всегда):
           - /start, /help

        2. Команды для авторизованных пользователей:
           - /actions, /automation, /stats, /id, /msg, /logout

        3. Административные команды (только для админов):
           - /users, /bc, /bc_send, /bc_del
           - /sync*, /admins, /add_admin, /remove_admin

        4. Инструкции для неавторизованных пользователей:
           - Предложение авторизоваться через /start

    Args:
        message: Сообщение от пользователя
        state: Состояние FSM
    """
    bot_manager = get_bot_manager()

    if not message.from_user:
        await bot_manager.send_answer(
            text="❌ Не удалось определить пользователя.",
            event=message,
            message_type=MessageType.COMMAND_ACTION_INFO,
            delete_by_type=MessageActionType.COMMAND_ACTION_CLEANUP,
        )
        return

    user_id = message.from_user.id
    is_admin = user_id in settings.ADMIN_IDS
    is_auth = await is_user_authenticated(user_id)

    help_text = "🤖 **TeamBot - Помощь**\n\n"

    # --- 1. Базовые команды (доступны всегда) ---
    help_text += "**📋 Основные команды:**\n"
    help_text += "🚀 /start - Начать работу / Авторизация\n"
    help_text += "❓ /help - Эта справка\n"

    # --- 2. Команды, требующие авторизации ---
    if is_auth:
        help_text += (
            "\n**🔐 Команды для авторизованных пользователей:**\n"
            "📋 /actions - Меню действий\n"
            "🤖 /automation - Меню автоматизации\n"
            "📊 /stats - Меню статистики\n"
            "🆔 /id - Мой ID\n"
            "💬 /msg <id> - Контекстное меню сообщения\n"
            "🚪 /logout - Выйти из системы\n"
        )
    else:
        help_text += "\n🔐 **Для доступа к расширенным командам**\nиспользуйте `/start` для авторизации.\n"

    # --- 3. Административные команды (только для админов) ---
    if is_admin:
        help_text += (
            "\n**👑 Административные команды:**\n"
            "👥 /users - Список пользователей\n"
            "📢 /bc - Меню рассылки\n"
            "📤 /bc_send - Создать рассылку\n"
            "🗑️ /bc_del - Отменить рассылку\n"
            "🔄 /sync - Меню синхронизации\n"
            "💬 /sync_chats - Синхр. чатов\n"
            "📚 /sync_base - Синхр. справочников\n"
            "📇 /sync_contacts - Синхр. контактов\n"
            "👤 /sync_user <id> - Синхр. пользователя\n"
            "👥 /sync_all_users - Синхр. всех пользователей\n"
            "⚡ /sync_light - Стандартная синхр.\n"
            "💪 /sync_force - Полная синхр. Force\n"
            "👑 /admins - Список админов\n"
            "➕ /add_admin <id> - Добавить админа\n"
            "➖ /remove_admin <id> - Удалить админа\n"
        )

    # --- 4. Инструкции для неавторизованных ---
    if not is_auth:
        help_text += (
            "\n📌 **Что делать?**\n"
            "1️⃣ Используйте `/start` для авторизации по номеру телефона.\n"
            "2️⃣ После авторизации вам станут доступны команды для работы.\n"
        )
    else:
        help_text += "\n📌 Используйте `/logout` для выхода из системы."

    await bot_manager.send_answer(
        text=help_text,
        event=message,
        message_type=MessageType.COMMAND_ACTION_INFO,
        delete_by_type=MessageActionType.COMMAND_ACTION_CLEANUP,
        parse_mode="Markdown",
    )


# ============================================================
# 2. КОМАНДА /id - ИНФОРМАЦИЯ О ПОЛЬЗОВАТЕЛЕ
# ============================================================


@router.message(Command("id"))
@log_exceptions(bot_logger)
async def cmd_id(message: Message, state: FSMContext) -> None:
    """Команда /id — получение ID пользователя и чата.

    Выводит техническую информацию:
        - ID пользователя в Telegram
        - Имя, фамилию, username
        - Является ли пользователь ботом
        - ID текущего чата

    Args:
        message: Сообщение от пользователя
        state: Состояние FSM (не используется)
    """
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
# 3. КОМАНДА /msg - КОНТЕКСТНОЕ МЕНЮ СООБЩЕНИЯ
# ============================================================


@router.message(Command("msg"))
@log_exceptions(bot_logger)
async def cmd_msg(message: Message, state: FSMContext) -> None:
    """Команда /msg — открытие контекстного меню для сообщения по ID.

    Позволяет выполнять действия с сообщением:
        - Ответить на сообщение
        - Просмотреть вложения
        - Скопировать ID
        - Найти в чате
        - Удалить сообщение (только для админов)

    Формат: `/msg <id_сообщения>`

    Пример: `/msg 12345`

    Args:
        message: Сообщение от пользователя
        state: Состояние FSM
    """
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
        from ....db.repositories import AvanpostUserRepository

        async with db_manager.get_session() as session:
            repo = AvanpostUserRepository()
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

            from .custom.chat_message_menu import show_message_context_menu

            chat_id = message.chat.id if message.chat else 0

            await show_message_context_menu(
                event=message,
                state=state,
                message_id=message_id,
                chat_id=chat_id,
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


__all__ = [
    "router",
]
