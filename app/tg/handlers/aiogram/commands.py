import asyncio

from aiogram import Router
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.types import BotCommand, BotCommandScopeAllPrivateChats, Message
from sqlalchemy import func, select

from ....config import settings
from ....db import db_manager
from ....db.repositories import UserRepository
from ....exceptions import log_exceptions
from ....logger import tg_logger
from ....models import ChatMemberModel, ChatModel, MessageActionType, MessageType, UserModel
from ....tg.dependencies import get_tg_manager

router = Router(name="aiogram_commands")


# ============================================================
# ОСНОВНЫЕ КОМАНДЫ
# ============================================================


@router.message(Command("help"))
@log_exceptions(tg_logger)
async def cmd_help(message: Message) -> None:
    """Обработчик команды /help"""
    tg_manager = get_tg_manager()

    await tg_manager.delete_message_by_link(message)

    is_admin = message.from_user and message.from_user.id in settings.ADMIN_IDS

    help_lines = [
        "🤖 **Помощь по боту**",
        "",
        "**📋 Команды:**",
        "/start - Начать работу с ботом",
        "/help - Показать эту справку",
        "/stats - Показать статистику (админ)",
        "/sync - Синхронизировать чаты (админ)",
        "/id - Показать мой ID",
        "/actions - Меню действий",
        "/add_admin - Добавить администратора (админ)",
        "/remove_admin - Удалить администратора (админ)",
        "/admins - Список администраторов (админ)",
        "/debug_commands - 🔍 Отладка команд",
        "/refresh_commands - 🔄 Обновить команды",
        "/force_set_commands - ⚡ Принудительно установить команды (админ)",
    ]

    if is_admin:
        help_lines.append("/groups - Группы действий (админ)")

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

    await tg_manager.send_answer(
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
@log_exceptions(tg_logger)
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
    tg_manager = get_tg_manager()
    user_id = message.from_user.id

    await tg_manager.delete_message_by_link(message)

    # 1. Проверка авторизации в БД
    is_authorized_db = await tg_manager.is_user_authorized(user_id)

    # 2. Проверка в кеше команд
    is_in_cache = tg_manager.is_user_in_cache(user_id)

    # 3. Получение кешированных команд
    cached_commands = tg_manager.get_user_commands(user_id)

    # 4. Проверка, является ли пользователь администратором
    is_admin = user_id in getattr(settings, "ADMIN_IDS", [])

    # 5. Получение информации о пользователе из БД
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
                "avanpost_id": user.FK_Avanpost,
                "avanpost_group": user.FK_AvanpostGroup,
                "is_authenticated": user.is_authenticated,
                "last_activity": user.FDateLastActivity.isoformat() if user.FDateLastActivity else None,
            }

    # 6. Статистика кеша
    cache_stats = tg_manager.get_cache_stats()

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

    # Отправляем сообщение
    await tg_manager.send_answer(
        text=debug_info,
        event=message,
        message_type=MessageType.COMMAND,
        delete_by_type=MessageActionType.COMMAND_CLEANUP,
        parse_mode="Markdown",
    )

    tg_logger.info(f"🔍 Debug commands requested by user {user_id}")


@router.message(Command("refresh_commands"))
@log_exceptions(tg_logger)
async def cmd_refresh_commands(message: Message) -> None:
    """
    Принудительное обновление команд пользователя.

    Обновляет команды в локальном кеше бота.
    """
    tg_manager = get_tg_manager()
    user_id = message.from_user.id

    await tg_manager.delete_message_by_link(message)

    # Проверка авторизации
    is_authorized = await tg_manager.is_user_authorized(user_id)
    is_admin = user_id in getattr(settings, "ADMIN_IDS", [])

    if not is_authorized and not is_admin:
        await tg_manager.send_answer(
            text="❌ **Вы не авторизованы!**\n\nИспользуйте `/start` для авторизации.",
            event=message,
            message_type=MessageType.COMMAND,
            delete_by_type=MessageActionType.COMMAND_CLEANUP,
            parse_mode="Markdown",
        )
        return

    # Обновление команды
    await tg_manager.update_user_commands(user_id, is_admin)

    # Получение обновленного списка
    cached_commands = tg_manager.get_user_commands(user_id)

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

    await tg_manager.send_answer(
        text="\n".join(response_lines),
        event=message,
        message_type=MessageType.COMMAND,
        delete_by_type=MessageActionType.COMMAND_CLEANUP,
        parse_mode="Markdown",
    )

    tg_logger.info(f"🔄 Commands refreshed for user {user_id}")


@router.message(Command("force_set_commands"))
@log_exceptions(tg_logger)
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
    tg_manager = get_tg_manager()
    user_id = message.from_user.id

    # Удаление сообщения с командой (для чистоты)
    await tg_manager.delete_message_by_link(message)

    # ============================================================
    # ШАГ 1: ПРОВЕРКА ПРАВ
    # ============================================================
    if user_id not in settings.ADMIN_IDS:
        await tg_manager.send_answer(
            text="⛔ **Доступ запрещен**\n\nЭта команда доступна только администраторам.",
            event=message,
            message_type=MessageType.COMMAND_ADMIN,
            delete_by_type=MessageActionType.COMMAND_ADMIN_CLEANUP,
            parse_mode="Markdown",
        )
        return

    # ============================================================
    # ШАГ 2: ПРОВЕРКА БОТА
    # ============================================================
    bot = tg_manager.aiogram_client.bot
    if not bot:
        await tg_manager.send_answer(
            text="❌ **Бот не инициализирован**\n\nНе удалось получить доступ к Telegram API.",
            event=message,
            message_type=MessageType.COMMAND_ADMIN,
            delete_by_type=MessageActionType.COMMAND_ADMIN_CLEANUP,
            parse_mode="Markdown",
        )
        return

    # ============================================================
    # ШАГ 3: ПОЛУЧЕНИЕ СПИСКА КОМАНД
    # ============================================================
    # Определение права пользователя
    is_admin = user_id in settings.ADMIN_IDS
    is_authorized = await tg_manager.is_user_authorized(user_id)

    # Формирование списка команд в правильном порядке
    commands = []

    # 1. Публичные команды (доступны всем)
    commands.extend(tg_manager.get_public_commands())

    # 2. Команды для авторизованных пользователей
    if is_authorized or is_admin:
        commands.extend(tg_manager.get_auth_commands())

    # 3. Административные команды
    if is_admin:
        commands.extend(tg_manager.get_admin_commands())

    # Удаление дубликатов (если есть)
    seen = set()
    unique_commands = []
    for cmd in commands:
        if cmd["command"] not in seen:
            seen.add(cmd["command"])
            unique_commands.append(cmd)
    commands = unique_commands

    # ============================================================
    # ШАГ 4: ОТПРАВКА В TELEGRAM API
    # ============================================================
    try:
        # Преобразование в формат BotCommand
        bot_commands = [
            BotCommand(
                command=cmd["command"].lstrip("/"),  # Убираем / для API
                description=cmd["description"],
            )
            for cmd in commands
        ]

        # Устанавливание команды в Telegram
        await bot.set_my_commands(bot_commands)

        # ============================================================
        # ШАГ 5: ОБНОВЛЕНИЕ КЕША
        # ============================================================
        # Обновление кеша для текущего пользователя
        await tg_manager.update_user_commands(user_id, is_admin)

        # Обновление для всех администраторов
        for admin_id in settings.ADMIN_IDS:
            if admin_id != user_id:
                try:
                    await tg_manager.update_user_commands(admin_id, is_admin=True)
                except Exception as e:
                    tg_logger.warning(f"Failed to update commands for admin {admin_id}: {e}")

        # ============================================================
        # ШАГ 6: ФОРМИРОВАНИЕ ОТВЕТА
        # ============================================================
        response_lines = [
            "✅ **КОМАНДЫ УСПЕШНО УСТАНОВЛЕНЫ!**",
            "",
            f"📊 Установлено команд: `{len(bot_commands)}`",
            "",
            "📋 **Список установленных команд:**",
            "",
        ]

        # Группировка команд для удобства
        public_cmds = [c for c in commands if c in tg_manager.get_public_commands()]
        auth_cmds = [c for c in commands if c in tg_manager.get_auth_commands()]
        admin_cmds = [c for c in commands if c in tg_manager.get_admin_commands()]

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

        # ============================================================
        # ШАГ 7: ДОПОЛНИТЕЛЬНАЯ ИНФОРМАЦИЯ
        # ============================================================
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
        await tg_manager.send_answer(
            text="\n".join(response_lines),
            event=message,
            message_type=MessageType.COMMAND_ADMIN,
            delete_by_type=MessageActionType.COMMAND_ADMIN_CLEANUP,
            parse_mode="Markdown",
        )

        tg_logger.info(f"✅ Commands force-set for user {user_id} ({len(bot_commands)} commands)")

    except Exception as e:
        tg_logger.error(f"❌ Failed to force set commands: {e}", exc_info=True)

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

        await tg_manager.send_answer(
            text="\n".join(error_lines),
            event=message,
            message_type=MessageType.COMMAND_ADMIN,
            delete_by_type=MessageActionType.COMMAND_ADMIN_CLEANUP,
            parse_mode="Markdown",
        )


router.message(Command("force_set_commands_all"))


@log_exceptions(tg_logger)
async def cmd_force_set_commands_all(message: Message) -> None:
    """
    Принудительная установка команд для ВСЕХ пользователей.

    Эта команда:
    1. Получает всех авторизованных пользователей из БД
    2. Для каждого формирует правильный список команд
    3. Устанавливает команды в Telegram API
    4. Обновляет кеш

    Используется, когда нужно массово обновить команды для всех.
    """
    tg_manager = get_tg_manager()
    user_id = message.from_user.id

    await tg_manager.delete_message_by_link(message)

    # Проверка прав
    if user_id not in settings.ADMIN_IDS:
        await tg_manager.send_answer(
            text="⛔ **Доступ запрещен**\n\nЭта команда доступна только администраторам.",
            event=message,
            message_type=MessageType.COMMAND_ADMIN,
            delete_by_type=MessageActionType.COMMAND_ADMIN_CLEANUP,
            parse_mode="Markdown",
        )
        return

    # Отправка сообщения о начале и сохранение объекта Message
    progress_result = await tg_manager.send_answer(
        text="🔄 **Начинаю обновление команд для всех пользователей...**\n\nЭто может занять некоторое время.",
        event=message,
        message_type=MessageType.COMMAND_ADMIN,
        delete_by_type=MessageActionType.COMMAND_ADMIN_CLEANUP,
        parse_mode="Markdown",
    )

    # Получаем объект Message из результата
    progress_msg = progress_result.get("message")
    if not progress_msg:
        # Если не удалось получить message, отправляем обычное сообщение
        progress_msg = await message.answer(
            "🔄 **Начинаю обновление команд для всех пользователей...**\n\nЭто может занять некоторое время.",
            parse_mode="Markdown",
        )

    try:
        # Получение всех авторизованных пользователей
        async with db_manager.get_session() as session:
            stmt = select(UserModel).where(UserModel.FK_Avanpost.is_not(None))
            result = await session.execute(stmt)
            users = result.scalars().all()

        total_users = len(users)
        updated = 0
        errors = 0

        # Обновление команды для каждого пользователя
        for idx, user in enumerate(users, 1):
            try:
                is_admin = user.FID in settings.ADMIN_IDS
                await tg_manager.update_user_commands(user.FID, is_admin)
                updated += 1

                # Отображение прогресса каждых 5 пользователей
                if idx % 5 == 0 or idx == total_users:
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
                tg_logger.error(f"Failed to update commands for user {user.FID}: {e}")

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

        await progress_msg.edit_text(text="\n".join(result_lines), parse_mode="Markdown")

        tg_logger.info(f"✅ Force-set commands for {updated} users (errors: {errors})")

    except Exception as e:
        tg_logger.error(f"❌ Failed to force set commands for all users: {e}", exc_info=True)

        await progress_msg.edit_text(text=f"❌ **Ошибка:**\n\n```\n{str(e)}\n```", parse_mode="Markdown")


@router.message(Command("debug_telegram_commands"))
@log_exceptions(tg_logger)
async def cmd_debug_telegram_commands(message: Message) -> None:
    """
    Проверяет, какие команды реально установлены в Telegram API.
    """
    tg_manager = get_tg_manager()
    user_id = message.from_user.id

    await tg_manager.delete_message_by_link(message)

    # Проверка прав
    if user_id not in settings.ADMIN_IDS:
        await tg_manager.send_answer(
            text="⛔ **Доступ запрещен**\n\nЭта команда доступна только администраторам.",
            event=message,
            message_type=MessageType.COMMAND_ADMIN,
            delete_by_type=MessageActionType.COMMAND_ADMIN_CLEANUP,
            parse_mode="Markdown",
        )
        return

    try:
        bot = tg_manager.aiogram_client.bot
        if not bot:
            await message.answer("❌ Бот не инициализирован")
            return

        # Получение команд для текущего пользователя
        bot_commands = await bot.get_my_commands()

        # Проверка также скоупа для приватных чатов
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
        cached_commands = tg_manager.get_user_commands(user_id)
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

        await tg_manager.send_answer(
            text="\n".join(response_lines),
            event=message,
            message_type=MessageType.COMMAND_ADMIN,
            delete_by_type=MessageActionType.COMMAND_ADMIN_CLEANUP,
            parse_mode="Markdown",
        )

    except Exception as e:
        tg_logger.error(f"❌ Failed to debug telegram commands: {e}", exc_info=True)
        await message.answer(f"❌ Ошибка: {e}")


@router.message(Command("debug_scopes"))
@log_exceptions(tg_logger)
async def cmd_debug_scopes(message: Message) -> None:
    """
    Проверяет, для каких скоупов установлены команды.
    """
    tg_manager = get_tg_manager()
    user_id = message.from_user.id

    await tg_manager.delete_message_by_link(message)

    # Проверка прав
    if user_id not in settings.ADMIN_IDS:
        await tg_manager.send_answer(
            text="⛔ **Доступ запрещен**\n\nЭта команда доступна только администраторам.",
            event=message,
            message_type=MessageType.COMMAND_ADMIN,
            delete_by_type=MessageActionType.COMMAND_ADMIN_CLEANUP,
            parse_mode="Markdown",
        )
        return

    try:
        bot = tg_manager.aiogram_client.bot
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

        for scope_name, scope in scopes.items():
            try:
                commands = await bot.get_my_commands(scope=scope)
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

        await tg_manager.send_answer(
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

    for chat in top_chats:
        chat_title = chat.FTitle or f"Chat {chat.FID}"
        stats_lines.append(f"• {chat_title}: {chat.members_count} участников")

    await tg_manager.send_answer(
        text="\n".join(stats_lines),
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
            report_lines = [
                "✅ Синхронизация завершена!",
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
            await tg_manager.send_answer(
                text="\n".join(report_lines),
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

    is_admin = message.from_user and message.from_user.id in settings.ADMIN_IDS
    response_lines.append(f"\n• Администратор: {'✅ Да' if is_admin else '❌ Нет'}")

    await tg_manager.send_answer(
        text="\n".join(response_lines),
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

    admin_list = [f"• `{admin_id}`" for admin_id in settings.ADMIN_IDS]

    response_lines = [
        "👑 **Список администраторов**",
        "",
        *admin_list,
        "",
        "Для добавления администратора используйте /add_admin <user_id>",
    ]

    await tg_manager.send_answer(
        text="\n".join(response_lines),
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
                f"• Группа действий: `{user_info.get('avanpost_group', 'Не указана')}`",
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
            "• Админские: `/sync`, `/broadcast`, `/delete`, `/admins`, `/add_admin`, `/remove_admin`, `/groups`"
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
]
