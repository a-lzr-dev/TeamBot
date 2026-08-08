import re
from collections.abc import Awaitable, Callable
from typing import Any

from aiogram import F, Router
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, Contact, Message, ReplyKeyboardRemove, TelegramObject, Update

from ....config import settings
from ....db import AvanpostRepository, UserRepository, db_manager
from ....exceptions import log_exceptions
from ....logger import tg_logger
from ....models import ErrorCategory, MessageActionType, MessageType, datetime_now
from ....services.error_service import error_service
from ....tg.dependencies import get_tg_manager
from ...keyboards import AuthKeyboard

router = Router(name="aiogram_auth")


class AuthStates(StatesGroup):
    """Состояния для аутентификации"""

    waiting_for_contact = State()
    authenticated = State()


# Хранилище для временного хранения данных авторизации
_auth_cache: dict[int, dict[str, Any]] = {}


async def is_user_authenticated(user_id: int) -> bool:
    """Проверка, авторизован ли пользователь"""
    try:
        async with db_manager.get_session() as session:
            user = await UserRepository.get_user_by_id(session, user_id)

            if user and user.FK_Avanpost:
                user.FDateLastActivity = datetime_now()
                await session.commit()
                return True
            return False
    except Exception as e:
        tg_logger.error(f"❌ Failed to check authentication: {e}")
        return False


@router.message(Command("start"))
@log_exceptions(tg_logger)
async def cmd_start(message: Message, state: FSMContext) -> None:
    """Обработчик команды /start - запрос верификации"""
    user_id = message.from_user.id
    tg_manager = get_tg_manager()

    # Проверка, авторизован ли пользователь в БД
    is_authenticated_db = await is_user_authenticated(user_id)

    # Проверка, есть ли пользователь в кеше команд
    is_in_cache = tg_manager.is_user_in_cache(user_id)

    # Очистка кеша
    if is_in_cache and not is_authenticated_db:
        tg_manager.clear_user_cache(user_id)
        tg_logger.debug(f"🧹 Cleared stale cache for user {user_id} during /start")

    # Проверка, авторизован ли пользователь уже
    if await is_user_authenticated(user_id):
        # Обновление команды для авторизованного пользователя
        is_admin = user_id in settings.ADMIN_IDS
        try:
            await tg_manager.update_user_commands(user_id, is_admin)
        except Exception as e:
            tg_logger.warning(f"⚠️ Failed to update commands: {e}")

        await tg_manager.send_answer(
            text="👋 Добро пожаловать!\n\n"
            "✅ Вы уже авторизованы в системе.\n"
            "Используйте /help для получения списка команд.\n\n"
            "📌 Для выхода из системы используйте /logout",
            event=message,
            message_type=MessageType.COMMAND_AUTH,
            delete_by_type=MessageActionType.COMMAND_AUTH_CLEANUP,
        )
        await state.set_state(AuthStates.authenticated)

        # Обновление времеми последней активности
        async with db_manager.get_session() as session:
            user = await UserRepository.get_user_by_id(session, user_id)
            if user:
                user.FDateLastActivity = datetime_now()
                await session.commit()
        return

    # Запрос контакта
    keyboard = AuthKeyboard.get_auth_request_keyboard()

    await state.set_state(AuthStates.waiting_for_contact)

    # Отправка сообщения с запросом контакта
    result = await tg_manager.send_message(
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
@log_exceptions(tg_logger)
async def handle_cancel_auth(message: Message, state: FSMContext) -> None:
    """Отмена авторизации через текстовую кнопку"""
    tg_manager = get_tg_manager()
    current_state = await state.get_state()

    if current_state == AuthStates.waiting_for_contact:
        await state.clear()
        await tg_manager.send_answer(
            text="❌ Верификация отменена.\n\nДля повторной попытки используйте /start",
            event=message,
            message_type=MessageType.COMMAND_AUTH,
            delete_by_type=MessageActionType.COMMAND_AUTH_CLEANUP,
            reply_markup=ReplyKeyboardRemove(),
        )
    else:
        await tg_manager.send_answer(
            text="❌ Нет активной авторизации.",
            event=message,
            message_type=MessageType.COMMAND_AUTH,
            delete_by_type=MessageActionType.COMMAND_AUTH_CLEANUP,
            reply_markup=ReplyKeyboardRemove(),
        )


@router.message(F.contact)
@log_exceptions(tg_logger)
async def handle_contact(message: Message, state: FSMContext) -> None:
    """Обработка полученного контакта"""
    tg_manager = get_tg_manager()
    contact: Contact = message.contact

    # Удаление сообщения с контактом
    #    await tg_manager.delete_message_by_link(message)

    # Получение ID сообщения с запросом авторизации
    #    data = await state.get_data()
    #    auth_message_id = data.get("auth_message_id")

    # Удаление сообщения с запросом авторизации
    #    if auth_message_id:
    #        await tg_manager.delete_message_by_id(
    #            chat_id=message.chat.id,
    #           message_id=auth_message_id
    #        )

    await tg_manager.send_toast(text="⏳ Проверка данных...", message=message)

    if not contact or not contact.phone_number:
        await tg_manager.send_answer(
            text="❌ Не удалось получить номер телефона. Попробуйте еще раз.",
            event=message,
            message_type=MessageType.COMMAND_AUTH,
            delete_by_type=MessageActionType.COMMAND_AUTH_CLEANUP,
        )
        return

    if contact.user_id != message.from_user.id:
        await tg_manager.send_answer(
            text="⚠️ Пожалуйста, отправьте свой собственный контакт.\n\n"
            "Нажмите кнопку 'Поделиться контактом' и подтвердите отправку.",
            event=message,
            message_type=MessageType.COMMAND_AUTH,
            delete_by_type=MessageActionType.COMMAND_AUTH_CLEANUP,
        )
        return

    phone_number = normalize_phone(contact.phone_number)
    tg_logger.info(f"📱 Received contact from user {message.from_user.id}: {phone_number}")

    try:
        # Проверка пользователя через хранимую процедуру Avanpost
        user_id_avanpost, group_id = await check_user_by_phone_avanpost(phone_number)

        # Удаление сообщений о проверке
        # if loading_result.get("success"):
        #     await tg_manager.delete_message_by_id(
        #         chat_id=message.chat.id,
        #         message_id=loading_result.get("message_id")
        #     )

        if not user_id_avanpost:
            keyboard = AuthKeyboard.get_auth_request_keyboard()

            # Отправка сообщения об ошибке
            await tg_manager.send_answer(
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

        async with db_manager.get_session() as session:
            user = await UserRepository.save_user(
                session=session,
                user_id=message.from_user.id,
                chat_id=message.chat.id,
                avanpost_id=user_id_avanpost,
                avanpost_group_id=group_id,
            )

        if not user:
            await tg_manager.send_answer(
                text="❌ Ошибка при сохранении данных пользователя.\n\n"
                "Пожалуйста, попробуйте позже или обратитесь к администратору.",
                event=message,
                message_type=MessageType.COMMAND_AUTH,
                delete_by_type=MessageActionType.COMMAND_AUTH_CLEANUP,
            )
            return

        # Сохранение ID группы в кеш
        _auth_cache[message.from_user.id] = {"user_id": user_id_avanpost, "group_id": group_id, "phone": phone_number}

        await state.set_state(AuthStates.authenticated)

        # Обновление команды для пользователя
        is_admin = message.from_user.id in settings.ADMIN_IDS
        try:
            await tg_manager.update_user_commands(message.from_user.id, is_admin)
            tg_logger.info(f"✅ Commands updated for user {message.from_user.id}")
        except Exception as e:
            tg_logger.warning(f"⚠️ Failed to update commands: {e}")

        # Формирование приветственного сообщения
        welcome_text = (
            f"✅ **Авторизация успешна!**\n\n"
            f"👋 Добро пожаловать!\n\n"
            f"📱 Ваш номер телефона подтвержден.\n"
            f"🆔 ID пользователя: `{user_id_avanpost}`\n"
        )

        if group_id:
            welcome_text += f"📂 Группа действий: `{group_id}`\n\n"
        else:
            welcome_text += "\n"

        welcome_text += "**Доступные команды:**\n• /help - Помощь\n• /actions - Меню действий\n• /stats - Статистика\n"

        if user_id_avanpost in settings.ADMIN_IDS:
            welcome_text += "• /groups - Группы действий (админ)\n"
            welcome_text += "• /sync - Синхронизация (админ)\n"

        welcome_text += "\n📌 Используйте /logout для выхода из системы."

        # Отправка финального сообщения
        await tg_manager.send_answer(
            text=welcome_text,
            event=message,
            message_type=MessageType.COMMAND_AUTH,
            delete_by_type=MessageActionType.COMMAND_AUTH_CLEANUP,
            parse_mode="Markdown",
        )

    except Exception as e:
        tg_logger.error(f"❌ Authentication error: {e}", exc_info=True)

        await error_service.log_error(
            error=e,
            component="auth",
            category=ErrorCategory.SYSTEM,
            session=session,
        )

        await tg_manager.send_answer(
            text="❌ Произошла ошибка при авторизации.\n\n"
            "Пожалуйста, попробуйте позже или обратитесь к администратору.",
            event=message,
            message_type=MessageType.COMMAND_AUTH,
            delete_by_type=MessageActionType.COMMAND_AUTH_CLEANUP,
            clear_previous=True,
        )


@router.message(Command("logout"))
@log_exceptions(tg_logger)
async def cmd_logout(message: Message, state: FSMContext) -> None:
    """Команда для выхода из системы"""
    tg_manager = get_tg_manager()

    try:
        async with db_manager.get_session() as session:
            user = await UserRepository.get_user_by_id(session, message.from_user.id)

            if user:
                user.FK_Avanpost = None
                user.FK_Chat = None
                await session.commit()
                tg_logger.info(f"✅ User {user.FID} logged out")

        _auth_cache.pop(message.from_user.id, None)

        # Очистка кеша команд пользователя
        tg_manager.clear_user_cache(message.from_user.id)

        # Сброс команды пользователя до базовых
        try:
            await tg_manager.reset_user_commands(message.from_user.id)
            tg_logger.info(f"✅ Commands reset for user {message.from_user.id}")
        except Exception as e:
            tg_logger.warning(f"⚠️ Failed to reset commands: {e}")

        await state.clear()

        # Отправка и сохранение сообщения о выходе
        await tg_manager.send_answer(
            text="👋 Вы вышли из системы.\n\nДля повторной авторизации используйте /start",
            event=message,
            message_type=MessageType.COMMAND_AUTH,
            delete_by_type=MessageActionType.COMMAND_AUTH_CLEANUP,
        )

    except Exception as e:
        tg_logger.error(f"❌ Logout error: {e}", exc_info=True)

        await tg_manager.send_answer(
            text="❌ Ошибка при выходе из системы.",
            event=message,
            message_type=MessageType.COMMAND_AUTH,
            delete_by_type=MessageActionType.COMMAND_AUTH_CLEANUP,
        )


@router.message(Command("actions"))
@log_exceptions(tg_logger)
async def cmd_actions_with_auth(message: Message, state: FSMContext) -> None:
    """Команда /actions с использованием group_id из авторизации"""
    from .actions import cmd_actions

    tg_manager = get_tg_manager()

    if not await is_user_authenticated(message.from_user.id):
        await tg_manager.send_answer(
            text="🔐 **Требуется авторизация**\n\n"
            "Для доступа к действиям необходимо авторизоваться.\n"
            "Используйте /start для начала авторизации.",
            event=message,
            message_type=MessageType.COMMAND_AUTH,
            delete_by_type=MessageActionType.COMMAND_AUTH_CLEANUP,
        )
        return

    user_data = _auth_cache.get(message.from_user.id)

    if user_data and user_data.get("group_id"):
        await state.update_data(use_group_id=user_data.get("group_id"))

    await cmd_actions(message, state)


# ============ МИДЛВАР ДЛЯ ПРОВЕРКИ АВТОРИЗАЦИИ ============


async def auth_middleware(
    handler: Callable[[TelegramObject, dict[str, Any]], Awaitable[Any]],
    event: Message | CallbackQuery | Update,
    data: dict[str, Any],
) -> Any:
    """
    Мидлвар для проверки авторизации пользователя.
    Проверяет авторизацию для всех команд (кроме /start, /help, /logout).
    """
    tg_manager = get_tg_manager()

    # Проверка, является ли событие сообщением с командой
    if isinstance(event, Message) and event.text:
        command = event.text.split()[0] if event.text else None

        # Пропуск без проверки публичные команды
        if command and command.startswith("/"):
            if command in ["/start", "/help", "/logout"]:
                return await handler(event, data)

            # Проверка авторизации для остальных команд
            user_id = event.from_user.id if event.from_user else None
            if not user_id:
                return await handler(event, data)

            if not await is_user_authenticated(user_id):
                tg_manager = get_tg_manager()
                keyboard = AuthKeyboard.get_auth_needed_keyboard()

                await tg_manager.send_answer(
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
        user_id = event.from_user.id if event.from_user else None
        if user_id and not await is_user_authenticated(user_id):
            await tg_manager.send_toast(callback="🔐 Требуется авторизация", message=event)
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


async def check_user_by_phone_avanpost(phone_number: str) -> tuple[int | None, int | None]:
    """Проверка пользователя через хранимую процедуру Avanpost"""
    try:
        normalized_phone = normalize_phone(phone_number)

        async with db_manager.get_session("avanpost") as session:
            return await AvanpostRepository.check_user_by_phone(
                session=session,
                phone_number=normalized_phone,
            )
    except Exception as e:
        tg_logger.error(f"❌ Failed to check user in Avanpost: {e}", exc_info=True)
        return None, None


async def get_user_group_id(user_id: int) -> int | None:
    """Получение ID группы действий для пользователя."""
    # Проверка кеша
    user_data = _auth_cache.get(user_id)
    if user_data:
        return user_data.get("group_id")

    try:
        async with db_manager.get_session() as session:
            user = await UserRepository.get_user_by_id(session, user_id)
            if user:
                group_id = user.FK_AvanpostGroup
                if group_id is not None:
                    return int(group_id)
                return None
    except Exception as e:
        tg_logger.error(f"❌ Failed to get user group: {e}")

    return None


__all__ = [
    "router",
    "get_user_group_id",
    "is_user_authenticated",
    "auth_middleware",
    "cmd_start",
    "_auth_cache",
]
