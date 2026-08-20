import asyncio
import re
from collections.abc import Awaitable, Callable
from typing import Any

from aiogram import F, Router
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, Message, ReplyKeyboardRemove, TelegramObject

from app.bot.dependencies import get_bot_manager
from app.bot.keyboards import AuthKeyboard
from app.config import settings
from app.db import db_manager
from app.db.repositories import AvanpostRepository, UserRepository
from app.exceptions import log_exceptions
from app.logger import bot_logger
from app.models.base import ErrorCategory, MessageActionType, MessageType, datetime_now
from app.services.error_service import error_service

router = Router(name="aiogram_auth")


class AuthStates(StatesGroup):
    """Состояния для аутентификации"""

    waiting_for_contact = State()
    authenticated = State()


# Хранилище для временного хранения данных авторизации
_auth_cache: dict[int, dict[str, Any]] = {}


async def is_user_authenticated(user_id: int) -> bool:
    """Проверка, авторизован ли пользователь (есть ли связь с AvanpostUser)"""
    try:
        async with db_manager.get_session() as session:
            return await UserRepository.is_user_authenticated(session, user_id)
    except Exception as e:
        bot_logger.error(f"❌ Failed to check authentication: {e}")
        return False


@router.message(Command("start"))
@log_exceptions(bot_logger)
async def cmd_start(message: Message, state: FSMContext) -> None:
    """Обработчик команды /start - запрос верификации"""
    if not message.from_user:
        await message.answer("❌ Не удалось определить пользователя.")
        return

    telegram_user_id = message.from_user.id
    bot_manager = get_bot_manager()

    # Проверка, авторизован ли пользователь в БД
    is_authenticated_db = await is_user_authenticated(telegram_user_id)

    # Проверка, есть ли пользователь в кеше команд
    is_in_cache = bot_manager.is_user_in_cache(telegram_user_id)

    # Очистка кеша, если пользователь разлогинился
    if is_in_cache and not is_authenticated_db:
        bot_manager.clear_user_cache(telegram_user_id)
        # Очищаем и глобальный кэш авторизации
        _auth_cache.pop(telegram_user_id, None)
        bot_logger.debug(f"🧹 Cleared stale cache for user {telegram_user_id} during /start")

    if await is_user_authenticated(telegram_user_id):
        # Обновление команды для авторизованного пользователя
        is_admin = telegram_user_id in settings.ADMIN_IDS
        try:
            await bot_manager.update_user_commands(telegram_user_id, is_admin)
        except Exception as e:
            bot_logger.warning(f"⚠️ Failed to update commands: {e}")

        await bot_manager.send_answer(
            text="👋 Добро пожаловать!\n\n"
            "✅ Вы уже авторизованы в системе.\n"
            "Используйте /help для получения списка команд.\n\n"
            "📌 Для выхода из системы используйте /logout",
            event=message,
            message_type=MessageType.COMMAND_AUTH,
            delete_by_type=MessageActionType.COMMAND_AUTH_CLEANUP,
        )
        await state.set_state(AuthStates.authenticated)

        # Обновление времени последней активности
        async with db_manager.get_session() as session:
            user = await UserRepository.get_user_by_id(session, telegram_user_id)
            if user:
                user.FDateLastActivity = datetime_now()
                await session.commit()
        return

    # Запрос контакта
    keyboard = AuthKeyboard.get_auth_request_keyboard()

    await state.set_state(AuthStates.waiting_for_contact)

    # Отправка сообщения с запросом контакта
    result = await bot_manager.send_message(
        chat_id=message.chat.id,
        text="🔐 **Верификация по номеру телефона**\n\n"
        "Для идентификации необходимо подтвердить ваш номер телефона.\n\n"
        "⚠️ **Важно:** Бот использует ваш номер телефона только для "
        "авторизации и не передает его третьим лицам.\n\n"
        "Нажмите кнопку ниже, чтобы поделиться контактом:",
        message_type=MessageType.COMMAND_AUTH,
        delete_message_id=message.message_id,
        delete_by_type=MessageActionType.COMMAND_AUTH_CLEANUP,
        parse_mode="Markdown",
        reply_markup=keyboard,
    )

    # Сохранение ID сообщения с запросом для последующего удаления
    if result.get("success"):
        await state.update_data(auth_message_id=result.get("message_id"))


@router.message(F.text == "❌ Отмена")
@log_exceptions(bot_logger)
async def handle_cancel_auth(message: Message, state: FSMContext) -> None:
    """Отмена авторизации через текстовую кнопку"""
    bot_manager = get_bot_manager()
    current_state = await state.get_state()

    if current_state == AuthStates.waiting_for_contact:
        await state.clear()
        await bot_manager.send_answer(
            text="❌ Верификация отменена.\n\nДля повторной попытки используйте /start",
            event=message,
            message_type=MessageType.COMMAND_AUTH,
            delete_by_type=MessageActionType.COMMAND_AUTH_CLEANUP,
            reply_markup=ReplyKeyboardRemove(),
        )
    else:
        await bot_manager.send_answer(
            text="❌ Нет активной авторизации.",
            event=message,
            message_type=MessageType.COMMAND_AUTH,
            delete_by_type=MessageActionType.COMMAND_AUTH_CLEANUP,
            reply_markup=ReplyKeyboardRemove(),
        )


@router.message(F.contact)
@log_exceptions(bot_logger)
async def handle_contact(message: Message, state: FSMContext) -> None:
    """Обработка полученного контакта"""
    bot_manager = get_bot_manager()

    if not message.from_user:
        await bot_manager.send_answer(
            text="❌ Не удалось определить пользователя.",
            event=message,
            message_type=MessageType.COMMAND_AUTH,
            delete_by_type=MessageActionType.COMMAND_AUTH_CLEANUP,
        )
        return

    telegram_user_id = message.from_user.id
    contact = message.contact

    await bot_manager.send_toast(text="⏳ Проверка данных...", message=message)

    if not contact or not contact.phone_number:
        await bot_manager.send_answer(
            text="❌ Не удалось получить номер телефона. Попробуйте еще раз.",
            event=message,
            message_type=MessageType.COMMAND_AUTH,
            delete_by_type=MessageActionType.COMMAND_AUTH_CLEANUP,
        )
        return

    if contact.user_id != telegram_user_id:
        await bot_manager.send_answer(
            text="⚠️ Пожалуйста, отправьте свой собственный контакт.\n\n"
            "Нажмите кнопку 'Поделиться контактом' и подтвердите отправку.",
            event=message,
            message_type=MessageType.COMMAND_AUTH,
            delete_by_type=MessageActionType.COMMAND_AUTH_CLEANUP,
        )
        return

    phone_number = normalize_phone(contact.phone_number)
    bot_logger.info(f"📱 Received contact from user {telegram_user_id}: {phone_number}")

    try:
        # 1. Проверка пользователя через хранимую процедуру Avanpost
        avanpost_user_id, menu_group_id, fk_contact = await check_user_by_phone_avanpost(phone_number)

        if not avanpost_user_id:
            keyboard = AuthKeyboard.get_auth_request_keyboard()

            await bot_manager.send_answer(
                text="❌ **Пользователь не найден**\n\n"
                f"Номер телефона `{phone_number}` не зарегистрирован в системе.\n\n"
                "⚠️ Если вы уверены, что номер правильный, обратитесь к администратору.\n\n"
                "Вы можете попробовать еще раз:",
                event=message,
                message_type=MessageType.COMMAND_AUTH,
                delete_by_type=MessageActionType.COMMAND_AUTH_CLEANUP,
                parse_mode="Markdown",
                reply_markup=keyboard,
            )
            return

        # 2. Сохранение информации о пользователе в БД
        async with db_manager.get_session("main") as session:
            # Сохранение пользователя
            user = await UserRepository.save_user(
                session=session,
                user_id=telegram_user_id,
                chat_id=message.chat.id,
                first_name=contact.first_name or message.from_user.first_name,
                last_name=contact.last_name or message.from_user.last_name,
                username=message.from_user.username,
                is_bot=message.from_user.is_bot,
                phone=phone_number,
            )

            if not user:
                await bot_manager.send_answer(
                    text="❌ Ошибка при сохранении данных пользователя.\n\n"
                    "Пожалуйста, попробуйте позже или обратитесь к администратору.",
                    event=message,
                    message_type=MessageType.COMMAND_AUTH,
                    delete_by_type=MessageActionType.COMMAND_AUTH_CLEANUP,
                )
                return

            # Создание или обновление связи с AvanpostUser
            success, avanpost_user = await UserRepository.create_or_update_avanpost_user_upsert(
                session=session,
                telegram_user_id=telegram_user_id,
                avanpost_user_id=avanpost_user_id,
                fk_contact=fk_contact,
                fk_menugroup=menu_group_id,
                fphone=phone_number,
            )

            if not success or not avanpost_user:
                await bot_manager.send_answer(
                    text="❌ Ошибка при создании пользователя в системе.\n\n"
                    "Пожалуйста, попробуйте позже или обратитесь к администратору.",
                    event=message,
                    message_type=MessageType.COMMAND_AUTH,
                    delete_by_type=MessageActionType.COMMAND_AUTH_CLEANUP,
                )
                return

            await session.commit()

        # 3. Обновление кеша авторизации
        # ВАЖНО! Используем Telegram ID как ключ
        _auth_cache[telegram_user_id] = {
            "user_id": avanpost_user_id,
            "group_id": menu_group_id,
            "phone": phone_number,
        }

        await state.set_state(AuthStates.authenticated)

        # 4. Запуск синхронизации пользовательских данных в фоне
        asyncio.create_task(
            _sync_user_in_background(
                telegram_user_id=telegram_user_id,
                avanpost_user_id=avanpost_user_id,
            )
        )

        # 5. Обновление команды для пользователя
        is_admin = telegram_user_id in settings.ADMIN_IDS
        try:
            await bot_manager.update_user_commands(telegram_user_id, is_admin)
            bot_logger.info(f"✅ Commands updated for user {telegram_user_id}")
        except Exception as e:
            bot_logger.warning(f"⚠️ Failed to update commands: {e}")

        # 6. Формирование приветственного сообщения
        welcome_text = _build_welcome_message(avanpost_user_id, menu_group_id, is_admin)

        # 7. Отправка финального сообщения
        await bot_manager.send_answer(
            text=welcome_text,
            event=message,
            message_type=MessageType.COMMAND_AUTH,
            delete_by_type=MessageActionType.COMMAND_AUTH_CLEANUP,
            parse_mode="Markdown",
        )

    except Exception as e:
        bot_logger.error(f"❌ Authentication error: {e}", exc_info=True)

        await error_service.log_error(
            error=e,
            component="auth",
            category=ErrorCategory.SYSTEM,
        )

        await bot_manager.send_answer(
            text="❌ Произошла ошибка при авторизации.\n\n"
            "Пожалуйста, попробуйте позже или обратитесь к администратору.",
            event=message,
            message_type=MessageType.COMMAND_AUTH,
            delete_by_type=MessageActionType.COMMAND_AUTH_CLEANUP,
            clear_previous=True,
        )


@router.message(Command("logout"))
@log_exceptions(bot_logger)
async def cmd_logout(message: Message, state: FSMContext) -> None:
    """Команда для выхода из системы"""
    bot_manager = get_bot_manager()

    if not message.from_user:
        await bot_manager.send_answer(
            text="❌ Не удалось определить пользователя.",
            event=message,
            message_type=MessageType.COMMAND_AUTH,
            delete_by_type=MessageActionType.COMMAND_AUTH_CLEANUP,
        )
        return

    user_id = message.from_user.id

    try:
        async with db_manager.get_session() as session:
            success = await UserRepository.logout_user(session, user_id)

            if success:
                await session.commit()
                bot_logger.info(f"✅ User {user_id} logged out")
            else:
                bot_logger.warning(f"⚠️ User {user_id} not found for logout")

        # Очистка кешиа
        _auth_cache.pop(user_id, None)
        bot_manager.clear_user_cache(user_id)

        # Сброс команд
        try:
            await bot_manager.reset_user_commands(user_id)
            bot_logger.info(f"✅ Commands reset for user {user_id}")
        except Exception as e:
            bot_logger.warning(f"⚠️ Failed to reset commands: {e}")

        await state.clear()

        await bot_manager.send_answer(
            text="👋 Вы вышли из системы.\n\nДля повторной авторизации используйте /start",
            event=message,
            message_type=MessageType.COMMAND_AUTH,
            delete_by_type=MessageActionType.COMMAND_AUTH_CLEANUP,
        )

    except Exception as e:
        bot_logger.error(f"❌ Logout error: {e}", exc_info=True)

        await bot_manager.send_answer(
            text="❌ Ошибка при выходе из системы.",
            event=message,
            message_type=MessageType.COMMAND_AUTH,
            delete_by_type=MessageActionType.COMMAND_AUTH_CLEANUP,
        )


@router.message(Command("actions"))
@log_exceptions(bot_logger)
async def cmd_actions_with_auth(message: Message, state: FSMContext) -> None:
    """Команда /actions с использованием group_id из авторизации"""
    from .actions import cmd_actions

    bot_manager = get_bot_manager()

    if not message.from_user:
        await bot_manager.send_answer(
            text="❌ Не удалось определить пользователя.",
            event=message,
            message_type=MessageType.COMMAND_AUTH,
            delete_by_type=MessageActionType.COMMAND_AUTH_CLEANUP,
        )
        return

    user_id = message.from_user.id

    if not await is_user_authenticated(user_id):
        await bot_manager.send_answer(
            text="🔐 **Требуется авторизация**\n\n"
            "Для доступа к действиям необходимо авторизоваться.\n"
            "Используйте /start для начала авторизации.",
            event=message,
            message_type=MessageType.COMMAND_AUTH,
            delete_by_type=MessageActionType.COMMAND_AUTH_CLEANUP,
        )
        return

    user_data = _auth_cache.get(user_id)

    if user_data and user_data.get("group_id"):
        await state.update_data(use_group_id=user_data.get("group_id"))

    await cmd_actions(message, state)


# ============ МИДЛВАР ДЛЯ ПРОВЕРКИ АВТОРИЗАЦИИ ============


async def auth_middleware(
    handler: Callable[[TelegramObject, dict[str, Any]], Awaitable[Any]],
    event: TelegramObject,
    data: dict[str, Any],
) -> Any:
    """
    Мидлвар для проверки авторизации пользователя.
    Проверяет авторизацию для всех команд (кроме /start, /help, /logout).
    """
    bot_manager = get_bot_manager()

    # Проверка, является ли событие сообщением с командой
    if isinstance(event, Message) and event.text:
        command = event.text.split()[0] if event.text else None

        # Пропуск без проверки публичные команды
        if command and command.startswith("/"):
            if command in ["/start", "/help", "/logout"]:
                return await handler(event, data)

            # Проверка авторизации для остальных команд
            user = event.from_user
            if not user:
                return await handler(event, data)

            user_id = user.id

            if not await is_user_authenticated(user_id):
                bot_manager = get_bot_manager()
                keyboard = AuthKeyboard.get_auth_needed_keyboard()

                await bot_manager.send_answer(
                    text="🔐 **Требуется авторизация**\n\n"
                    "Для доступа к этой команде необходимо авторизоваться.\n"
                    "Используйте /start для начала авторизации.",
                    event=event,
                    message_type=MessageType.COMMAND_AUTH,
                    delete_by_type=MessageActionType.COMMAND_AUTH_CLEANUP,
                    parse_mode="Markdown",
                    reply_markup=keyboard,
                )
                return None

    # Проверка авторизации для callback_query
    if isinstance(event, CallbackQuery):
        user = event.from_user
        if user:
            user_id = user.id
            if not await is_user_authenticated(user_id):
                await bot_manager.send_toast(text="🔐 Требуется авторизация", event=event)
                return None

    return await handler(event, data)


# ============ ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ ============


def normalize_phone(phone: str) -> str:
    """Нормализация номера телефона к формату +XXXXXXXXXXX"""
    digits = re.sub(r"\D", "", phone)

    if digits.startswith("8"):
        digits = "7" + digits[1:]

    if digits.startswith("7"):
        return "+" + digits

    if phone.startswith("+7"):
        return phone

    if phone.startswith("+"):
        return phone

    return phone


async def check_user_by_phone_avanpost(phone_number: str) -> tuple[int | None, int | None, int | None]:
    """
    Проверка пользователя через хранимую процедуру Avanpost.

    Returns:
        tuple[int | None, int | None, int | None]: (avanpost_user_id, menu_group_id, fk_contact)
    """
    try:
        normalized_phone = normalize_phone(phone_number)

        async with db_manager.get_session("avanpost") as session:
            return await AvanpostRepository.check_user_by_phone(
                session=session,
                phone_number=normalized_phone,
            )
    except Exception as e:
        bot_logger.error(f"❌ Failed to check user in Avanpost: {e}", exc_info=True)
        return None, None, None


async def get_user_group_id(user_id: int) -> int | None:
    """
    Получение ID группы действий для пользователя.

    Поддерживает как Telegram ID, так и Avanpost ID.
    """
    # Проверка кеша по Telegram ID
    user_data = _auth_cache.get(user_id)
    if user_data:
        group_id = user_data.get("group_id")
        if group_id is not None:
            if isinstance(group_id, int):
                return group_id
            try:
                return int(group_id)
            except (ValueError, TypeError):
                pass

    try:
        async with db_manager.get_session() as session:
            # Сначала пробуем как Telegram ID
            result = await UserRepository.get_user_group_id(session, user_id)
            if result is not None:
                return result

            # Если не нашли, пробуем как Avanpost ID
            from app.models.avanpost import AvanpostUserModel

            avanpost_user = await session.get(AvanpostUserModel, user_id)
            if avanpost_user:
                fk_menu_group = avanpost_user.FK_MenuGroup
                if fk_menu_group is None:
                    return None
                if isinstance(fk_menu_group, int):
                    return fk_menu_group
                try:
                    return int(fk_menu_group)
                except (ValueError, TypeError):
                    return None

            return None
    except Exception as e:
        bot_logger.error(f"❌ Failed to get user group: {e}")

    return None


async def _sync_user_in_background(avanpost_user_id: int, **_kwargs: Any) -> None:
    """Фоновая синхронизация пользовательских данных из Avanpost"""
    try:
        from ....services import avanpost_sync_service

        bot_logger.info(f"🔄 Background sync started for user {avanpost_user_id}")
        await avanpost_sync_service.initialize()
        stats = await avanpost_sync_service.sync_user_data(avanpost_user_id, force=False)

        if hasattr(stats, "to_dict"):
            stats_dict = stats.to_dict()
            bot_logger.info(
                f"✅ Background sync completed for user {avanpost_user_id}: "
                f"inserted={stats_dict.get('total_inserted', 0)}, "
                f"updated={stats_dict.get('total_updated', 0)}, "
                f"deleted={stats_dict.get('total_deleted', 0)}"
            )
        else:
            bot_logger.info(f"✅ Background sync completed for user {avanpost_user_id}: {stats}")

    except Exception as e:
        bot_logger.error(f"❌ Background sync failed for user {avanpost_user_id}: {e}", exc_info=True)


def _build_welcome_message(avanpost_user_id: int, menu_group_id: int | None, is_admin: bool) -> str:
    """Формирование приветственного сообщения"""
    welcome_text = (
        f"✅ **Авторизация успешна!**\n\n"
        f"👋 Добро пожаловать!\n\n"
        f"📱 Ваш номер телефона подтвержден.\n"
        f"🆔 ID пользователя в Avanpost: `{avanpost_user_id}`\n"
    )

    if menu_group_id:
        welcome_text += f"📂 Группа действий: `{menu_group_id}`\n\n"
    else:
        welcome_text += "\n"

    welcome_text += "**Доступные команды:**\n"
    welcome_text += "• /help - Помощь\n"
    welcome_text += "• /actions - Меню действий\n"
    welcome_text += "• /stats - Статистика\n"

    if is_admin:
        welcome_text += "• /sync - Синхронизации (админ)\n"
        welcome_text += "• /groups - Группы действий (админ)\n"

    welcome_text += "\n📌 Используйте /logout для выхода из системы."

    return welcome_text


__all__ = [
    "router",
    "get_user_group_id",
    "is_user_authenticated",
    "auth_middleware",
    "cmd_start",
    "_auth_cache",
]
