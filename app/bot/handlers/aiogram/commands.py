import asyncio
from typing import Any

from aiogram import Router
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.types import (
    BotCommand,
    BotCommandScopeAllPrivateChats,
    CallbackQuery,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Message,
)

from app.bot.dependencies import get_bot_manager
from app.config import settings
from app.db import db_manager
from app.db.repositories import StatsRepository, UserRepository
from app.exceptions import log_exceptions
from app.logger import bot_logger
from app.models import MessageActionType, MessageType

from .users import UserStates

router = Router(name="aiogram_commands")


# ============================================================
# ОСНОВНЫЕ КОМАНДЫ
# ============================================================


@router.message(Command("help"))
@log_exceptions(bot_logger)
async def cmd_help(message: Message) -> None:
    """Обработчик команды /help"""
    bot_manager = get_bot_manager()

    await bot_manager.delete_message_by_link(message)

    user_id = message.from_user.id if message.from_user else None
    is_admin = user_id is not None and user_id in settings.ADMIN_IDS

    help_lines = [
        "🤖 **Помощь по боту**",
        "",
        "**📋 Команды:**",
        "/start - Начать работу с ботом",
        "/help - Показать эту справку",
        "/stats - Показать статистику",
        "/id - Показать мой ID",
        "/actions - Меню действий",
        "/automation - Меню автоматизации",
    ]

    if is_admin:
        help_lines.extend(
            [
                "/groups - Группы действий (админ)",
                "/sync - Синхронизации (админ)",
                "/broadcast - Рассылка (админ)",
                "/delete - Удалить сообщение (админ)",
                "/admins - Список администраторов (админ)",
                "/add_admin - Добавить администратора (админ)",
                "/remove_admin - Удалить администратора (админ)",
            ]
        )

    help_lines.extend(
        [
            "",
            "**⚙️ Функции:**",
            "• Отслеживание добавления/удаления бота из чатов",
            "• Отслеживание присоединения/выхода участников",
            "• Ведение базы данных чатов и участников",
            "• Приветствие новых участников",
            "",
            "**📊 Статистика:**",
            "Бот отслеживает:",
            "• Количество чатов, где он присутствует",
            "• Количество участников в каждом чате",
            "• Активность пользователей",
            "",
            "**💡 Советы:**",
            "• Добавьте бота в группу с правами администратора",
            "• Бот будет автоматически отслеживать всех участников",
            "• Для получения статистики используйте /stats",
        ]
    )

    await bot_manager.send_answer(
        text="\n".join(help_lines),
        event=message,
        message_type=MessageType.COMMAND,
        delete_by_type=MessageActionType.COMMAND_CLEANUP,
        parse_mode="Markdown",
    )


# ============================================================
# ОТЛАДОЧНЫЕ КОМАНДЫ
# ============================================================


@router.message(Command("debug_commands"))
@log_exceptions(bot_logger)
async def cmd_debug_commands(message: Message) -> None:
    """
    Отладочная команда для проверки состояния команд пользователя.

    Показывает:
    - Статус авторизации в БД
    - Статус в кеше команд
    - Список команд в кеше
    - Информацию о пользователе
    - Статистику кеша
    """
    bot_manager = get_bot_manager()
    if not message.from_user:
        await bot_manager.send_answer(
            text="❌ Не удалось определить пользователя.",
            event=message,
            message_type=MessageType.COMMAND,
            delete_by_type=MessageActionType.COMMAND_CLEANUP,
        )
        return

    user_id = message.from_user.id

    await bot_manager.delete_message_by_link(message)

    # 1. Проверка авторизации в БД
    is_authorized_db = await bot_manager.is_user_authorized(user_id)

    # 2. Проверка в кеше команд
    is_in_cache = bot_manager.is_user_in_cache(user_id)

    # 3. Получение кешированных команд
    cached_commands = bot_manager.get_user_commands(user_id)

    # 4. Проверка, является ли пользователь администратором
    is_admin = user_id in getattr(settings, "ADMIN_IDS", [])

    # 5. Получение информации о пользователе из БД через репозиторий
    user_info = None
    async with db_manager.get_session() as session:
        user = await UserRepository.get_user_by_id(session, user_id)
        if user:
            user_info = {
                "id": user.FID,
                "username": user.FUserName,
                "first_name": user.FFirstName,
                "last_name": user.FLastName,
                "is_bot": user.FFlagBot,
                "phone": user.FPhone,
                "is_authenticated": user.is_authenticated,
                "avanpost_id": user.avanpost_id,
                "avanpost_group_id": user.avanpost_group_id,
                "last_activity": user.FDateLastActivity.isoformat() if user.FDateLastActivity else None,
            }

    # 6. Статистика кеша
    cache_stats = bot_manager.get_cache_stats()

    # 7. Информация о настройках
    admin_ids = getattr(settings, "ADMIN_IDS", [])

    # Формирование отладочного сообщения
    debug_info = _build_debug_message(
        user_id=user_id,
        is_authorized_db=is_authorized_db,
        is_in_cache=is_in_cache,
        cached_commands=cached_commands,
        is_admin=is_admin,
        user_info=user_info,
        cache_stats=cache_stats,
        admin_ids=admin_ids,
    )

    # Отправка сообщения
    await bot_manager.send_answer(
        text=debug_info,
        event=message,
        message_type=MessageType.COMMAND,
        delete_by_type=MessageActionType.COMMAND_CLEANUP,
        parse_mode="Markdown",
    )

    bot_logger.info(f"🔍 Debug commands requested by user {user_id}")


@router.message(Command("refresh_commands"))
@log_exceptions(bot_logger)
async def cmd_refresh_commands(message: Message) -> None:
    """
    Принудительное обновление команд пользователя.

    Обновляет команды в локальном кеше бота.
    """
    bot_manager = get_bot_manager()
    if not message.from_user:
        await bot_manager.send_answer(
            text="❌ Не удалось определить пользователя.",
            event=message,
            message_type=MessageType.COMMAND,
            delete_by_type=MessageActionType.COMMAND_CLEANUP,
        )
        return

    user_id = message.from_user.id

    await bot_manager.delete_message_by_link(message)

    # Проверка авторизации
    is_authorized = await bot_manager.is_user_authorized(user_id)
    is_admin = user_id in getattr(settings, "ADMIN_IDS", [])

    if not is_authorized and not is_admin:
        await bot_manager.send_answer(
            text="❌ **Вы не авторизованы!**\n\nИспользуйте `/start` для авторизации.",
            event=message,
            message_type=MessageType.COMMAND,
            delete_by_type=MessageActionType.COMMAND_CLEANUP,
            parse_mode="Markdown",
        )
        return

    # Обновление команды
    await bot_manager.update_user_commands(user_id, is_admin)

    # Получение обновленного списка
    cached_commands = bot_manager.get_user_commands(user_id)

    # Формирование ответа
    response_lines = [
        "✅ **Команды обновлены!**",
        "",
        f"Обновлено команд: `{len(cached_commands) if cached_commands else 0}`",
        "",
        "📋 **Доступные команды:**",
    ]

    if cached_commands:
        for cmd in cached_commands:
            response_lines.append(f"• `{cmd['command']}` - {cmd['description']}")
    else:
        response_lines.append("❌ Команды не загружены")

    await bot_manager.send_answer(
        text="\n".join(response_lines),
        event=message,
        message_type=MessageType.COMMAND,
        delete_by_type=MessageActionType.COMMAND_CLEANUP,
        parse_mode="Markdown",
    )

    bot_logger.info(f"🔄 Commands refreshed for user {user_id}")


@router.message(Command("force_set_commands"))
@log_exceptions(bot_logger)
async def cmd_force_set_commands(message: Message) -> None:
    """
    Принудительная установка команд в Telegram API.

    Эта команда:
    1. Формирует полный список команд для пользователя
    2. Отправляет их в Telegram API через set_my_commands()
    3. Обновляет локальный кеш
    4. Показывает результат

    Используется, когда команды есть в кеше бота, но не отображаются в Telegram.
    """
    bot_manager = get_bot_manager()
    if not message.from_user:
        await bot_manager.send_answer(
            text="❌ Не удалось определить пользователя.",
            event=message,
            message_type=MessageType.COMMAND_ADMIN,
            delete_by_type=MessageActionType.COMMAND_ADMIN_CLEANUP,
        )
        return

    user_id = message.from_user.id

    # Удаление сообщения с командой (для чистоты)
    await bot_manager.delete_message_by_link(message)

    # 1. Проверка прав
    if user_id not in settings.ADMIN_IDS:
        await bot_manager.send_answer(
            text="⛔ **Доступ запрещен**\n\nЭта команда доступна только администраторам.",
            event=message,
            message_type=MessageType.COMMAND_ADMIN,
            delete_by_type=MessageActionType.COMMAND_ADMIN_CLEANUP,
            parse_mode="Markdown",
        )
        return

    # 2. Проверка бота
    bot = bot_manager.aiogram_client.bot
    if not bot:
        await bot_manager.send_answer(
            text="❌ **Бот не инициализирован**\n\nНе удалось получить доступ к Telegram API.",
            event=message,
            message_type=MessageType.COMMAND_ADMIN,
            delete_by_type=MessageActionType.COMMAND_ADMIN_CLEANUP,
            parse_mode="Markdown",
        )
        return

    # 3. Получение списка команд

    # Определение права пользователя
    is_admin = user_id in settings.ADMIN_IDS
    is_authorized = await bot_manager.is_user_authorized(user_id)

    # Формирование списка команд в правильном порядке
    commands = []

    # 1. Публичные команды (доступны всем)
    commands.extend(bot_manager.get_public_commands())

    # 2. Команды для авторизованных пользователей
    if is_authorized or is_admin:
        commands.extend(bot_manager.get_auth_commands())

    # 3. Административные команды
    if is_admin:
        commands.extend(bot_manager.get_admin_commands())

    # Удаление дубликатов (если есть)
    seen = set()
    unique_commands = []
    for cmd in commands:
        if cmd["command"] not in seen:
            seen.add(cmd["command"])
            unique_commands.append(cmd)
    commands = unique_commands

    # 4. Отправка в Telegram API
    try:
        # Преобразование в формат BotCommand
        bot_commands = [
            BotCommand(
                command=cmd["command"].lstrip("/"),  # Убираем / для API
                description=cmd["description"],
            )
            for cmd in commands
        ]

        # Установка команды в Telegram
        await bot.set_my_commands(bot_commands)

        # 5. Обновление кеша

        # Обновление кеша для текущего пользователя
        await bot_manager.update_user_commands(user_id, is_admin)

        # Обновление для всех администраторов
        for admin_id in settings.ADMIN_IDS:
            if admin_id != user_id:
                try:
                    await bot_manager.update_user_commands(admin_id, is_admin=True)
                except Exception as e:
                    bot_logger.warning(f"Failed to update commands for admin {admin_id}: {e}")

        # 6. Формирование ответа
        response_lines = [
            "✅ **КОМАНДЫ УСПЕШНО УСТАНОВЛЕНЫ!**",
            "",
            f"📊 Установлено команд: `{len(bot_commands)}`",
            "",
            "📋 **Список установленных команд:**",
            "",
        ]

        # Группировка команд для удобства
        public_cmds = [c for c in commands if c in bot_manager.get_public_commands()]
        auth_cmds = [c for c in commands if c in bot_manager.get_auth_commands()]
        admin_cmds = [c for c in commands if c in bot_manager.get_admin_commands()]

        if public_cmds:
            response_lines.append("**🔓 Публичные:**")
            for cmd in public_cmds:
                response_lines.append(f"  • `{cmd['command']}` - {cmd['description']}")
            response_lines.append("")

        if auth_cmds:
            response_lines.append("**🔐 Авторизованные:**")
            for cmd in auth_cmds:
                response_lines.append(f"  • `{cmd['command']}` - {cmd['description']}")
            response_lines.append("")

        if admin_cmds:
            response_lines.append("**👑 Административные:**")
            for cmd in admin_cmds:
                response_lines.append(f"  • `{cmd['command']}` - {cmd['description']}")
            response_lines.append("")

        # 7. Дополнительная информация
        response_lines.extend(
            [
                "⏳ **Важно:**",
                "• Telegram может кешировать команды до 5-10 минут",
                "• Если команды не отображаются сразу:",
                "  - Перезапустите Telegram",
                "  - Напишите `/` и подождите",
                "  - Используйте `/debug_commands` для проверки",
                "",
                "📌 **Проверка:** Используйте `/debug_commands` для проверки состояния",
            ]
        )

        # Отправка результата
        await bot_manager.send_answer(
            text="\n".join(response_lines),
            event=message,
            message_type=MessageType.COMMAND_ADMIN,
            delete_by_type=MessageActionType.COMMAND_ADMIN_CLEANUP,
            parse_mode="Markdown",
        )

        bot_logger.info(f"✅ Commands force-set for user {user_id} ({len(bot_commands)} commands)")

    except Exception as e:
        bot_logger.error(f"❌ Failed to force set commands: {e}", exc_info=True)

        error_lines = [
            "❌ **Ошибка при установке команд**",
            "",
            f"```\n{str(e)}\n```",
            "",
            "Попробуйте:",
            "• Перезапустить бота",
            "• Проверить токен бота",
            "• Использовать `/refresh_commands`",
        ]

        await bot_manager.send_answer(
            text="\n".join(error_lines),
            event=message,
            message_type=MessageType.COMMAND_ADMIN,
            delete_by_type=MessageActionType.COMMAND_ADMIN_CLEANUP,
            parse_mode="Markdown",
        )


@router.message(Command("force_set_commands_all"))
@log_exceptions(bot_logger)
async def cmd_force_set_commands_all(message: Message) -> None:
    """Принудительная установка команд для ВСЕХ пользователей"""
    bot_manager = get_bot_manager()
    if not message.from_user:
        await bot_manager.send_answer(
            text="❌ Не удалось определить пользователя.",
            event=message,
            message_type=MessageType.COMMAND_ADMIN,
            delete_by_type=MessageActionType.COMMAND_ADMIN_CLEANUP,
        )
        return

    user_id = message.from_user.id

    await bot_manager.delete_message_by_link(message)

    # Проверка прав
    if user_id not in settings.ADMIN_IDS:
        await bot_manager.send_answer(
            text="⛔ **Доступ запрещен**\n\nЭта команда доступна только администраторам.",
            event=message,
            message_type=MessageType.COMMAND_ADMIN,
            delete_by_type=MessageActionType.COMMAND_ADMIN_CLEANUP,
            parse_mode="Markdown",
        )
        return

    # Отправка сообщения о начале
    result = await bot_manager.send_answer(
        text="🔄 **Начинаю обновление команд для всех пользователей...**\n\nЭто может занять некоторое время.",
        event=message,
        message_type=MessageType.COMMAND_ADMIN,
        delete_by_type=MessageActionType.COMMAND_ADMIN_CLEANUP,
        parse_mode="Markdown",
    )

    progress_msg = result.get("message")
    if not progress_msg:
        # Если не удалось получить message, отправляем обычное сообщение
        progress_msg = await message.answer(
            "🔄 **Начинаю обновление команд для всех пользователей...**\n\nЭто может занять некоторое время.",
            parse_mode="Markdown",
        )

    try:
        # Получение всех авторизованных пользователей через репозиторий
        async with db_manager.get_session() as session:
            users = await UserRepository.get_authorized_users(session)

        total_users = len(users)
        updated = 0
        errors = 0

        # Обновление команды для каждого пользователя
        for idx, user in enumerate(users, 1):
            try:
                is_admin = user.FID in settings.ADMIN_IDS
                await bot_manager.update_user_commands(user.FID, is_admin)
                updated += 1

                # Отображение прогресса каждых 5 пользователей
                if (idx % 5 == 0 or idx == total_users) and hasattr(progress_msg, "edit_text"):
                    await progress_msg.edit_text(
                        f"🔄 **Обновление команд...**\n\n"
                        f"Обработано: `{idx}/{total_users}`\n"
                        f"Успешно: `{updated}`\n"
                        f"Ошибок: `{errors}`",
                        parse_mode="Markdown",
                    )

                # Небольшая пауза, чтобы не превысить лимиты Telegram
                await asyncio.sleep(0.1)

            except Exception as e:
                errors += 1
                bot_logger.error(f"Failed to update commands for user {user.FID}: {e}")

        # Финальный отчет
        result_lines = [
            "✅ **ОБНОВЛЕНИЕ КОМАНД ЗАВЕРШЕНО!**",
            "",
            "📊 **Статистика:**",
            f"• Всего пользователей: `{total_users}`",
            f"• Обновлено: `{updated}`",
            f"• Ошибок: `{errors}`",
            "",
            "💡 **Рекомендации:**",
            "• Если команды не отображаются, подождите 5-10 минут",
            "• Используйте `/debug_commands` для проверки",
            "• Используйте `/force_set_commands` для текущего пользователя",
        ]

        # Проверка, что progress_msg имеет метод edit_text
        if hasattr(progress_msg, "edit_text"):
            await progress_msg.edit_text(text="\n".join(result_lines), parse_mode="Markdown")
        else:
            # Если не можем редактировать, отправляем новое сообщение
            await message.answer(text="\n".join(result_lines), parse_mode="Markdown")

        bot_logger.info(f"✅ Force-set commands for {updated} users (errors: {errors})")

    except Exception as e:
        bot_logger.error(f"❌ Failed to force set commands for all users: {e}", exc_info=True)

        error_text = f"❌ **Ошибка:**\n\n```\n{str(e)}\n```"
        if hasattr(progress_msg, "edit_text"):
            await progress_msg.edit_text(text=error_text, parse_mode="Markdown")
        else:
            await message.answer(text=error_text, parse_mode="Markdown")


@router.message(Command("debug_telegram_commands"))
@log_exceptions(bot_logger)
async def cmd_debug_telegram_commands(message: Message) -> None:
    """Проверка, какие команды реально установлены в Telegram API"""
    bot_manager = get_bot_manager()
    if not message.from_user:
        await bot_manager.send_answer(
            text="❌ Не удалось определить пользователя.",
            event=message,
            message_type=MessageType.COMMAND_ADMIN,
            delete_by_type=MessageActionType.COMMAND_ADMIN_CLEANUP,
        )
        return

    user_id = message.from_user.id

    await bot_manager.delete_message_by_link(message)

    # Проверка прав
    if user_id not in settings.ADMIN_IDS:
        await bot_manager.send_answer(
            text="⛔ **Доступ запрещен**\n\nЭта команда доступна только администраторам.",
            event=message,
            message_type=MessageType.COMMAND_ADMIN,
            delete_by_type=MessageActionType.COMMAND_ADMIN_CLEANUP,
            parse_mode="Markdown",
        )
        return

    try:
        bot = bot_manager.aiogram_client.bot
        if not bot:
            await message.answer("❌ Бот не инициализирован")
            return

        # Получение команд для текущего пользователя
        bot_commands = await bot.get_my_commands()

        # Проверка также скоупа для приватных чатов - используем правильный тип
        private_commands = await bot.get_my_commands(scope=BotCommandScopeAllPrivateChats())

        response_lines = [
            "🔍 **КОМАНДЫ В TELEGRAM API**",
            "=" * 30,
            "",
            "**📋 Default Scope:**",
        ]

        if bot_commands:
            response_lines.append(f"Всего: `{len(bot_commands)}` команд")
            response_lines.append("")
            for cmd in bot_commands:
                response_lines.append(f"  • `/{cmd.command}` - {cmd.description}")
        else:
            response_lines.append("❌ **Нет команд в default scope!**")

        response_lines.extend(
            [
                "",
                "**📋 Private Chats Scope:**",
            ]
        )

        if private_commands:
            response_lines.append(f"Всего: `{len(private_commands)}` команд")
            response_lines.append("")
            for cmd in private_commands:
                response_lines.append(f"  • `/{cmd.command}` - {cmd.description}")
        else:
            response_lines.append("❌ **Нет команд в private chats scope!**")

        # Сравнение с кешем
        cached_commands = bot_manager.get_user_commands(user_id)
        if cached_commands:
            response_lines.extend(
                [
                    "",
                    "**📊 Сравнение с кешем бота:**",
                    f"• В кеше: `{len(cached_commands)}` команд",
                    f"• В Telegram (default): `{len(bot_commands)}` команд",
                ]
            )

            if len(bot_commands) != len(cached_commands):
                response_lines.extend(
                    [
                        "",
                        "⚠️ **Количество команд НЕ совпадает!**",
                        "Используйте `/force_set_commands` для синхронизации.",
                    ]
                )
            else:
                response_lines.extend(
                    [
                        "",
                        "✅ **Количество команд совпадает!**",
                        "Если команды не отображаются, попробуйте:",
                        "1. Перезапустить Telegram",
                        "2. Подождать 5-10 минут (кеширование)",
                    ]
                )

        await bot_manager.send_answer(
            text="\n".join(response_lines),
            event=message,
            message_type=MessageType.COMMAND_ADMIN,
            delete_by_type=MessageActionType.COMMAND_ADMIN_CLEANUP,
            parse_mode="Markdown",
        )

    except Exception as e:
        bot_logger.error(f"❌ Failed to debug telegram commands: {e}", exc_info=True)
        await message.answer(f"❌ Ошибка: {e}")


@router.message(Command("debug_scopes"))
@log_exceptions(bot_logger)
async def cmd_debug_scopes(message: Message) -> None:
    """Проверяет, для каких скоупов установлены команды"""
    bot_manager = get_bot_manager()
    if not message.from_user:
        await bot_manager.send_answer(
            text="❌ Не удалось определить пользователя.",
            event=message,
            message_type=MessageType.COMMAND_ADMIN,
            delete_by_type=MessageActionType.COMMAND_ADMIN_CLEANUP,
        )
        return

    user_id = message.from_user.id

    await bot_manager.delete_message_by_link(message)

    # Проверка прав
    if user_id not in settings.ADMIN_IDS:
        await bot_manager.send_answer(
            text="⛔ **Доступ запрещен**\n\nЭта команда доступна только администраторам.",
            event=message,
            message_type=MessageType.COMMAND_ADMIN,
            delete_by_type=MessageActionType.COMMAND_ADMIN_CLEANUP,
            parse_mode="Markdown",
        )
        return

    try:
        bot = bot_manager.aiogram_client.bot
        if not bot:
            await message.answer("❌ Бот не инициализирован")
            return

        from aiogram.types import (
            BotCommandScopeAllChatAdministrators,
            BotCommandScopeAllGroupChats,
            BotCommandScopeAllPrivateChats,
            BotCommandScopeDefault,
        )

        response_lines = [
            "🔍 **ПРОВЕРКА СКОУПОВ КОМАНД**",
            "=" * 30,
            "",
        ]

        # Проверка разных скоупов
        scopes = {
            "Default": BotCommandScopeDefault(),
            "All Private Chats": BotCommandScopeAllPrivateChats(),
            "All Group Chats": BotCommandScopeAllGroupChats(),
            "All Chat Administrators": BotCommandScopeAllChatAdministrators(),
        }

        for scope_name, _scope in scopes.items():
            try:
                if scope_name == "Default":
                    commands = await bot.get_my_commands(scope=BotCommandScopeDefault())
                elif scope_name == "All Private Chats":
                    commands = await bot.get_my_commands(scope=BotCommandScopeAllPrivateChats())
                elif scope_name == "All Group Chats":
                    commands = await bot.get_my_commands(scope=BotCommandScopeAllGroupChats())
                elif scope_name == "All Chat Administrators":
                    commands = await bot.get_my_commands(scope=BotCommandScopeAllChatAdministrators())
                else:
                    commands = await bot.get_my_commands()
                response_lines.append(f"**{scope_name}:** {len(commands)} команд")
                if commands:
                    for cmd in commands[:5]:
                        response_lines.append(f"  • /{cmd.command}")
                    if len(commands) > 5:
                        response_lines.append(f"  • ... и еще {len(commands) - 5}")
                else:
                    response_lines.append("  • (пусто)")
                response_lines.append("")
            except Exception as e:
                response_lines.append(f"**{scope_name}:** ❌ Ошибка - {e}")
                response_lines.append("")

        await bot_manager.send_answer(
            text="\n".join(response_lines),
            event=message,
            message_type=MessageType.COMMAND_ADMIN,
            delete_by_type=MessageActionType.COMMAND_ADMIN_CLEANUP,
            parse_mode="Markdown",
        )

    except Exception as e:
        await message.answer(f"❌ Ошибка: {e}")


# ============================================================
# СТАНДАРТНЫЕ КОМАНДЫ
# ============================================================


@router.message(Command("stats"))
@log_exceptions(bot_logger)
async def cmd_stats(message: Message) -> None:
    """Обработчик команды /stats - статистика"""
    bot_manager = get_bot_manager()

    if not message.from_user:
        await bot_manager.send_answer(
            text="❌ Не удалось определить пользователя.",
            event=message,
            message_type=MessageType.COMMAND,
            delete_by_type=MessageActionType.COMMAND_CLEANUP,
        )
        return

    user_id = message.from_user.id

    if user_id not in settings.ADMIN_IDS:
        await bot_manager.send_answer(
            text="⛔ У вас нет прав для этой команды.",
            event=message,
            message_type=MessageType.COMMAND,
            delete_by_type=MessageActionType.COMMAND_CLEANUP,
        )
        return

    await bot_manager.delete_message_by_link(message)

    async with db_manager.get_session() as session:
        stats_data = await StatsRepository.get_full_stats(session)

        # Извлечение данных из результата
        total_chats = stats_data.get("chats", {}).get("total", 0)
        active_chats = stats_data.get("chats", {}).get("active", 0)
        total_users = stats_data.get("users", {}).get("total", 0)
        active_members = 0  # В StatsRepository нет отдельного поля для активных участников

        # Получение топ-чатов из статистики
        top_chats = stats_data.get("top_chats", [])

    stats_lines = [
        "📊 **Статистика бота**",
        "",
        "**Чаты:**",
        f"• Всего: {total_chats}",
        f"• Активные: {active_chats}",
        f"• Неактивные: {total_chats - active_chats}",
        "",
        "**Пользователи:**",
        f"• Всего: {total_users}",
        f"• Активных участников: {active_members}",
        "",
        "**Топ-10 чатов по участникам:**",
    ]

    if top_chats:
        for chat in top_chats[:10]:
            chat_title = chat.get("title", f"Chat {chat.get('chat_id', 'unknown')}")
            message_count = chat.get("message_count", 0)
            stats_lines.append(f"• {chat_title}: {message_count} сообщений")
    else:
        stats_lines.append("• Нет данных")

    await bot_manager.send_answer(
        text="\n".join(stats_lines),
        event=message,
        message_type=MessageType.COMMAND,
        delete_by_type=MessageActionType.COMMAND_CLEANUP,
        parse_mode="Markdown",
    )
    bot_logger.info(f"✅ Stats sent to user {user_id}")


# ============================================================
# НОВОЕ МЕНЮ СИНХРОНИЗАЦИИ (вместо старой команды /sync)
# ============================================================


@router.message(Command("sync"))
@log_exceptions(bot_logger)
async def cmd_sync_menu(message: Message) -> None:
    """Меню синхронизации Avanpost (вместо старой команды /sync)"""
    bot_manager = get_bot_manager()

    if not message.from_user:
        await bot_manager.send_answer(
            text="❌ Не удалось определить пользователя.",
            event=message,
            message_type=MessageType.COMMAND_ADMIN,
            delete_by_type=MessageActionType.COMMAND_ADMIN_CLEANUP,
        )
        return

    user_id = message.from_user.id

    if user_id not in settings.ADMIN_IDS:
        await bot_manager.send_answer(
            text="⛔ У вас нет прав для этой команды.",
            event=message,
            message_type=MessageType.COMMAND_ADMIN,
            delete_by_type=MessageActionType.COMMAND_ADMIN_CLEANUP,
        )
        return

    await bot_manager.delete_message_by_link(message)

    keyboard = InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="🔄 Стандартная", callback_data="sync_light"),
                InlineKeyboardButton(text="⚡ Полная (force)", callback_data="sync_force"),
            ],
            [
                InlineKeyboardButton(text="📋 Справочники", callback_data="sync_base"),
                InlineKeyboardButton(text="📇 Контакты", callback_data="sync_contacts"),
            ],
            [
                InlineKeyboardButton(text="🧑 Пользователь", callback_data="sync_user"),
                InlineKeyboardButton(text="👥 Все пользователи", callback_data="sync_all_users"),
            ],
            [
                InlineKeyboardButton(text="💬 Синхр. чатов", callback_data="sync_chats"),
            ],
            [
                InlineKeyboardButton(text="❌ Закрыть", callback_data="sync_close"),
            ],
        ]
    )

    await bot_manager.send_answer(
        text="🔄 **Меню синхронизации Avanpost**\n\n"
        "Выберите действие:\n\n"
        "📌 **Стандартная синхронизация**\n"
        "• /sync_light — Обычная синхронизация (только изменения)\n\n"
        "⚡ **Полная синхронизация**\n"
        "• /sync_force — Полная синхронизация (принудительная)\n\n"
        "📚 **Справочники**\n"
        "• /sync_base — Синхронизация справочников\n\n"
        "👥 **Контакты**\n"
        "• /sync_contacts — Синхронизация контактов\n\n"
        "👤 **Пользователи**\n"
        "• /sync_user — Синхронизация данных пользователя\n"
        "• /sync_all_users — Синхронизация всех пользователей\n\n"
        "💬 **Чаты**\n"
        "• /sync_chats — Синхронизация чатов (Telegram)",
        event=message,
        message_type=MessageType.COMMAND_ADMIN,
        delete_by_type=MessageActionType.COMMAND_ADMIN_CLEANUP,
        parse_mode="Markdown",
        reply_markup=keyboard,
    )


# ============================================================
# СТАРАЯ КОМАНДА СИНХРОНИЗАЦИИ ЧАТОВ (ПЕРЕИМЕНОВАНА)
# ============================================================


@router.message(Command("sync_chats"))
@log_exceptions(bot_logger)
async def cmd_sync_chats(message: Message) -> None:
    """Синхронизация чатов Telegram (бывшая /sync)"""
    bot_manager = get_bot_manager()

    if not message.from_user:
        await bot_manager.send_answer(
            text="❌ Не удалось определить пользователя.",
            event=message,
            message_type=MessageType.COMMAND,
            delete_by_type=MessageActionType.COMMAND_CLEANUP,
        )
        return

    user_id = message.from_user.id

    if user_id not in settings.ADMIN_IDS:
        await bot_manager.send_answer(
            text="⛔ У вас нет прав для этой команды.",
            event=message,
            message_type=MessageType.COMMAND,
            delete_by_type=MessageActionType.COMMAND_CLEANUP,
        )
        return

    await bot_manager.delete_message_by_link(message)

    try:
        status = await bot_manager.get_status()

        # Проверка статуса Telethon
        telethon_status = status.get("telethon", {})
        if not telethon_status.get("connected", False):
            await bot_manager.send_answer(
                text="❌ Telethon клиент не доступен.",
                event=message,
                message_type=MessageType.COMMAND,
                delete_by_type=MessageActionType.COMMAND_CLEANUP,
            )
            return

        await bot_manager.send_toast(text="🔄 Начинаю синхронизацию всех чатов...", message=message)

        result = await bot_manager.sync_all_chats(force=True)

        if result.get("error"):
            await bot_manager.send_answer(
                text=f"❌ Ошибка синхронизации: {result['error']}",
                event=message,
                message_type=MessageType.COMMAND,
                delete_by_type=MessageActionType.COMMAND_CLEANUP,
            )
            return

        # Формирование отчета о синхронизации
        if "processed" in result:
            report_lines = [
                "✅ Синхронизация чатов завершена!",
                "",
                "📊 **Статистика:**",
                f"• Обработано чатов: {result.get('processed', {}).get('chats', 0)}",
                f"• Обработано участников: {result.get('processed', {}).get('members', 0)}",
                f"• Добавлено чатов: {result.get('added', {}).get('chats', 0)}",
                f"• Добавлено участников: {result.get('added', {}).get('members', 0)}",
                f"• Деактивировано чатов: {result.get('deactivated', {}).get('chats', 0)}",
                f"• Деактивировано участников: {result.get('deactivated', {}).get('members', 0)}",
                f"• Ошибок: {result.get('errors', {}).get('chats', 0)} чатов, "
                f"{result.get('errors', {}).get('members', 0)} участников",
            ]
            await bot_manager.send_answer(
                text="\n".join(report_lines),
                event=message,
                message_type=MessageType.COMMAND,
                delete_by_type=MessageActionType.COMMAND_CLEANUP,
                parse_mode="Markdown",
            )
        else:
            await bot_manager.send_answer(
                text="✅ Синхронизация всех чатов завершена!",
                event=message,
                message_type=MessageType.COMMAND,
                delete_by_type=MessageActionType.COMMAND_CLEANUP,
            )

        bot_logger.info(f"✅ Sync chats completed by user {user_id}")

    except Exception as err:
        bot_logger.error(f"❌ Sync chats command failed: {err}", exc_info=True)
        await bot_manager.send_answer(
            text=f"❌ Ошибка синхронизации: {str(err)}",
            event=message,
            message_type=MessageType.COMMAND,
            delete_by_type=MessageActionType.COMMAND_CLEANUP,
        )


# ============================================================
# ОБРАБОТЧИКИ КОЛБЭКОВ ДЛЯ МЕНЮ СИНХРОНИЗАЦИИ
# ============================================================


@router.callback_query(lambda c: c.data.startswith("sync_"))
@log_exceptions(bot_logger)
async def handle_sync_callback(callback: CallbackQuery, _state: FSMContext) -> None:
    """Обработка колбэков меню синхронизации"""
    bot_manager = get_bot_manager()

    if not callback.from_user:
        await bot_manager.send_toast(text="❌ Не удалось определить пользователя.", event=callback)
        return

    user_id = callback.from_user.id
    action = callback.data

    # Проверка прав
    if user_id not in settings.ADMIN_IDS:
        await bot_manager.send_toast(text="⛔ У вас нет прав.", event=callback)
        return

    await bot_manager.send_toast(event=callback)

    # Закрытие меню
    if action == "sync_close":
        if callback.message and hasattr(callback.message, "delete"):
            await callback.message.delete()
        return

    # Создание заглушки для выполнения команд
    class MockMessage:
        def __init__(self, chat_id: int, from_user: Any) -> None:
            self.chat = type("obj", (object,), {"id": chat_id})()
            self.from_user = from_user
            self.text = f"/{action}"

    mock_message = MockMessage(
        chat_id=callback.message.chat.id if callback.message else 0, from_user=callback.from_user
    )

    # Выполнение соответствующей команды
    if action == "sync_light":
        from .admin import cmd_sync_light

        await cmd_sync_light(mock_message)
    elif action == "sync_force":
        from .admin import cmd_sync_force

        await cmd_sync_force(mock_message)
    elif action == "sync_base":
        from .admin import cmd_sync_base

        await cmd_sync_base(mock_message)
    elif action == "sync_contacts":
        from .admin import cmd_sync_contacts

        await cmd_sync_contacts(mock_message)
    elif action == "sync_user":
        from .admin import cmd_sync_user

        await cmd_sync_user(mock_message)
    elif action == "sync_all_users":
        from .admin import cmd_sync_all_users

        await cmd_sync_all_users(mock_message)
    elif action == "sync_chats":
        await cmd_sync_chats(mock_message)


@router.message(Command("id"))
@log_exceptions(bot_logger)
async def cmd_id(message: Message) -> None:
    """Получение ID чата и пользователя"""
    bot_manager = get_bot_manager()

    await bot_manager.delete_message_by_link(message)

    user_id = message.from_user.id if message.from_user else None
    chat_id = message.chat.id
    chat_type = message.chat.type

    response_lines = [
        "📌 **Информация об ID**",
        "",
        f"• Ваш ID: `{user_id}`",
        f"• ID чата: `{chat_id}`",
        f"• Тип чата: `{chat_type}`",
    ]

    if message.chat.title:
        response_lines.append(f"• Название чата: `{message.chat.title}`")

    if message.from_user and message.from_user.username:
        response_lines.append(f"• Username: @{message.from_user.username}")

    is_admin = user_id is not None and user_id in settings.ADMIN_IDS
    response_lines.append(f"\n• Администратор: {'✅ Да' if is_admin else '❌ Нет'}")

    await bot_manager.send_answer(
        text="\n".join(response_lines),
        event=message,
        message_type=MessageType.COMMAND,
        delete_by_type=MessageActionType.COMMAND_CLEANUP,
        parse_mode="Markdown",
    )


@router.message(Command("cancel"))
@log_exceptions(bot_logger)
async def cmd_cancel(message: Message, state: FSMContext) -> None:
    """Отмена текущей операции"""
    bot_manager = get_bot_manager()

    # Получение текущего состояния
    current_state = await state.get_state()

    # ================ Специальная обработка для постояния поиска пользователей ================
    if current_state == "UserStates:searching_users":
        # Возвращение к списку пользователей
        from .users import show_users

        # Получение сохраненной страницу
        data = await state.get_data()
        page = data.get("users_page_before_search", 0)

        # Сброс состояния поиска
        await state.set_state(UserStates.viewing_users)
        await state.update_data(
            users_page_before_search=0,
            search_query=None,
        )

        # Удаление сообщение с командой
        await bot_manager.delete_message_by_link(message)

        # Отправка toast
        await bot_manager.send_toast(
            text="👥 Возврат к списку пользователей",
            event=message,
            duration=0,
        )

        # Отображение списка пользователей
        await show_users(event=message, state=state, page=page, search_query=None)
        return

    # Стандартная обработка для других состояний
    if current_state is None:
        await bot_manager.send_answer(
            text="❌ Нет активных операций для отмены.",
            event=message,
            message_type=MessageType.COMMAND,
            delete_by_type=MessageActionType.COMMAND_CLEANUP,
        )
        return

    await state.clear()
    await bot_manager.send_answer(
        text="✅ Операция отменена.",
        event=message,
        message_type=MessageType.COMMAND,
        delete_by_type=MessageActionType.COMMAND_CLEANUP,
    )


# ============================================================
# ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ
# ============================================================


def _build_debug_message(
    user_id: int,
    is_authorized_db: bool,
    is_in_cache: bool,
    cached_commands: list[dict[str, str]] | None,
    is_admin: bool,
    user_info: dict | None,
    cache_stats: dict,
    admin_ids: list[int],
) -> str:
    """Формирование отладочного сообщения"""

    lines = [
        "🔍 **ОТЛАДКА КОМАНД**",
        "=" * 30,
        "",
        "**👤 ПОЛЬЗОВАТЕЛЬ:**",
        f"• ID: `{user_id}`",
    ]

    if user_info:
        lines.extend(
            [
                f"• Username: @{user_info.get('username', 'Не указан')}",
                f"• Имя: {user_info.get('first_name', 'Не указано')}",
            ]
        )
        if user_info.get("last_name"):
            lines.append(f"• Фамилия: {user_info.get('last_name')}")
        lines.extend(
            [
                f"• Телефон: `{user_info.get('phone', 'Не указан')}`",
                f"• Avanpost ID: `{user_info.get('avanpost_id', 'Не указан')}`",
                f"• Группа действий: `{user_info.get('avanpost_group_id', 'Не указана')}`",
            ]
        )
        if user_info.get("last_activity"):
            lines.append(f"• Последняя активность: {user_info['last_activity']}")
    else:
        lines.append("• ❌ **Пользователь не найден в БД**")

    lines.extend(
        [
            "",
            "**🔐 СТАТУС АВТОРИЗАЦИИ:**",
            f"• В БД: {'✅ ДА' if is_authorized_db else '❌ НЕТ'}",
            f"• В кеше команд: {'✅ ДА' if is_in_cache else '❌ НЕТ'}",
            f"• Администратор: {'✅ ДА' if is_admin else '❌ НЕТ'}",
        ]
    )

    if not is_authorized_db:
        lines.extend(
            [
                "",
                "⚠️ **Пользователь НЕ авторизован в системе!**",
                "Для авторизации используйте `/start`",
            ]
        )
    elif not is_in_cache:
        lines.extend(
            [
                "",
                "⚠️ **Пользователь авторизован, но НЕ в кеше команд!**",
                "Команды не обновились. Попробуйте:",
                "1. Отправить любое сообщение (сработает middleware)",
                "2. Использовать `/refresh_commands`",
                "3. Использовать `/force_set_commands`",
            ]
        )

    lines.extend(
        [
            "",
            "**📋 КОМАНДЫ В КЕШЕ:**",
        ]
    )

    if cached_commands:
        lines.append(f"• Всего: `{len(cached_commands)}` команд")
        lines.append("")
        lines.append("**Список команд:**")
        for cmd in cached_commands:
            lines.append(f"  • `{cmd['command']}` - {cmd['description']}")
    else:
        lines.extend(
            [
                "❌ **Команды НЕ найдены в кеше!**",
                "",
                "Возможные причины:",
                "1. Пользователь не авторизован",
                "2. `update_user_commands()` не вызывался",
                "3. Ошибка в middleware",
            ]
        )

    lines.extend(
        [
            "",
            "**📊 СТАТИСТИКА КЕША:**",
            f"• Всего пользователей в кеше: `{cache_stats.get('total_users', 0)}`",
        ]
    )

    if cache_stats.get("user_ids"):
        lines.append(f"• ID пользователей: `{cache_stats['user_ids']}`")

    lines.extend(
        [
            "",
            "**👑 АДМИНИСТРАТОРЫ:**",
            f"• Всего: `{len(admin_ids)}`",
        ]
    )

    if admin_ids:
        admin_list = ", ".join([f"`{aid}`" for aid in admin_ids])
        lines.append(f"• ID: {admin_list}")
        if user_id in admin_ids:
            lines.append("• ✅ Вы в списке администраторов")
        else:
            lines.append("• ❌ Вы НЕ в списке администраторов")

    lines.extend(
        [
            "",
            "**🎯 ОЖИДАЕМЫЕ КОМАНДЫ:**",
            "• Публичные: `/start`, `/help`",
        ]
    )

    if is_authorized_db or is_admin:
        lines.append("• Авторизованные: `/actions`, `/automation`, `/stats`, `/id`, `/logout`")

    if is_admin:
        lines.append(
            "• Админские: `/sync`, `/sync_chats`, `/broadcast`, `/delete`, `/admins`, `/add_admin`, `/remove_admin`, `/groups`"
        )

    lines.extend(
        [
            "",
            "**💡 РЕКОМЕНДАЦИИ:**",
        ]
    )

    if not is_authorized_db:
        lines.append("1. Используйте `/start` для авторизации")
    elif not is_in_cache:
        lines.extend(
            [
                "1. Используйте `/refresh_commands` для обновления кеша",
                "2. Используйте `/force_set_commands` для принудительной установки в Telegram",
            ]
        )
    else:
        lines.extend(
            [
                "✅ Все работает корректно!",
                "Если команды все равно не видны:",
                "1. Используйте `/force_set_commands` для принудительной установки",
                "2. Перезапустите Telegram",
                "3. Подождите 5-10 минут (кеширование Telegram)",
            ]
        )

    lines.extend(
        [
            "",
            "=" * 30,
            "📌 Для принудительной установки команд используйте `/force_set_commands`",
        ]
    )

    return "\n".join(lines)


__all__ = [
    "router",
    "cmd_sync_menu",
    "cmd_sync_chats",
    "handle_sync_callback",
]
