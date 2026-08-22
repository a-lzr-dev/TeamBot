"""
Модуль авторизации пользователей в Telegram боте.

Отвечает за:
1. Аутентификацию пользователей по номеру телефона
2. Проверку пользователей через хранимую процедуру Avanpost
3. Сохранение данных пользователей в БД
4. Управление сессиями и кешем авторизации
5. Обновление команд для авторизованных пользователей
6. Фоновую синхронизацию данных пользователя
7. Middleware для проверки авторизации
8. Deep Linking для перехода к сообщениям
"""

import asyncio
import re
from collections.abc import Awaitable, Callable
from typing import Any

from aiogram import F, Router
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, Message, ReplyKeyboardRemove, TelegramObject

from ....config import settings
from ....db import db_manager
from ....db.repositories import AvanpostRepository, AvanpostUserRepository, UserRepository
from ....logger import bot_logger
from ....models.base import ErrorCategory, MessageActionType, MessageType
from ....services.error_service import error_service
from ....utils.decorators import log_exceptions
from ...dependencies import get_bot_manager
from ...keyboards import AuthKeyboard

# Создание роутера для обработки команд и callback-запросов
router = Router(name="aiogram_auth")

# Репозитории (создаем один раз на уровне модуля для переиспользования)
_user_repo = UserRepository()  # Репозиторий для работы с пользователями
_avanpost_repo = AvanpostRepository()  # Репозиторий для работы с Avanpost
_avanpost_user_repo = AvanpostUserRepository()  # Репозиторий для работы с пользователями Avanpost


class AuthStates(StatesGroup):
    """
    Состояния для аутентификации пользователя.

    Используются в FSM (Finite State Machine) для отслеживания
    текущего этапа авторизации.
    """

    waiting_for_contact = State()  # Ожидание контакта от пользователя
    authenticated = State()  # Пользователь авторизован


# Хранилище для временного хранения данных авторизации
# Ключ: ID пользователя в Telegram
# Значение: словарь с данными авторизации (user_id, group_id, phone)
_auth_cache: dict[int, dict[str, Any]] = {}


async def is_user_authenticated(user_id: int) -> bool:
    """
    Проверка, авторизован ли пользователь.

    Проверяет наличие связи с AvanpostUser в базе данных.

    Args:
        user_id: ID пользователя в Telegram

    Returns:
        bool: True если пользователь авторизован, иначе False
    """
    try:
        async with db_manager.get_session() as session:
            result = await _user_repo.is_user_authenticated(session, user_id)
            return bool(result)
    except Exception as e:
        bot_logger.error(f"❌ Failed to check authentication: {e}")
        return False


async def _get_message_by_id(message_id: int) -> dict[str, Any] | None:
    """
    Получение сообщения по ID через AvanpostUserRepository.

    Args:
        message_id: ID сообщения

    Returns:
        dict | None: Данные сообщения или None
    """
    try:
        async with db_manager.get_session() as session:
            return await _avanpost_user_repo.get_message_by_id(session, message_id)  # type: ignore[no-any-return]
    except Exception as e:
        bot_logger.error(f"❌ Failed to get message {message_id}: {e}")
        return None


async def _handle_deep_link_message(
    event: Message | CallbackQuery,
    state: FSMContext,
    msg_id: int,
    bot_manager: Any,
) -> bool:
    """
    Обработка перехода к сообщению по Deep Linking.

    Args:
        event: Сообщение или CallbackQuery от пользователя
        state: Состояние FSM
        msg_id: ID сообщения
        bot_manager: Менеджер бота

    Returns:
        bool: True если сообщение найдено и обработано, иначе False
    """
    try:
        # Получение сообщения из БД через AvanpostUserRepository
        message_data = await _get_message_by_id(msg_id)

        if message_data:
            from .chat_message_menu import show_message_context_menu
            from .lists.chat_details import chat_details_handler

            # ============================================================
            # ИСПРАВЛЕНИЕ 1: Сохраняем информацию о чате и странице
            # ============================================================
            state_data = await state.get_data()
            chat_details_page = state_data.get("chat_details_page", 0)
            selected_chat_id = state_data.get("selected_chat_id")
            avanpost_user_id = state_data.get("avanpost_user_id")
            parent_item_id = state_data.get("parent_item_id")
            group_id = state_data.get("group_id")

            # Если есть контекст чата - сохраняем для возврата
            if selected_chat_id and avanpost_user_id:
                await state.update_data(
                    return_to_chat_id=selected_chat_id,
                    return_to_page=chat_details_page,
                    return_avanpost_user_id=avanpost_user_id,
                    return_parent_item_id=parent_item_id,
                    return_group_id=group_id,
                )

            # Форматирование сообщения
            formatted = chat_details_handler.format_single_message(message_data)

            # Определение chat_id
            chat_id = event.chat.id if isinstance(event, Message) else event.message.chat.id if event.message else 0

            # Объединение информации о сообщении и контекстном меню
            title = f"🔗 **Переход к сообщению #{msg_id}**\n\n{formatted}"

            # ============================================================
            # ИСПРАВЛЕНИЕ 2: Добавляем кнопку "Назад к чату" в меню
            # ============================================================
            await show_message_context_menu(
                event=event,
                state=state,
                message_id=msg_id,
                chat_id=chat_id,
                custom_text=title,
                edit_original=True,
                show_back_to_chat=bool(selected_chat_id and avanpost_user_id),
            )

            # ============================================================
            # ИСПРАВЛЕНИЕ 3: Удаляем команду /start
            # ============================================================
            if isinstance(event, Message):
                try:
                    await bot_manager.delete_message_by_link(event)
                except Exception as e:
                    bot_logger.debug(f"ℹ️ Could not delete start command: {e}")

            # Очистка payload
            await state.update_data(deep_link_payload=None)
            await state.set_state(AuthStates.authenticated)
            return True
        else:
            await bot_manager.send_answer(
                text=f"❌ Сообщение #{msg_id} не найдено.",
                event=event,
                message_type=MessageType.COMMAND_ACTION_INFO,
                delete_by_type=MessageActionType.COMMAND_ACTION_CLEANUP,
            )
            return False

    except ValueError:
        await bot_manager.send_answer(
            text="❌ Неверный формат ссылки.",
            event=event,
            message_type=MessageType.COMMAND_ACTION_INFO,
            delete_by_type=MessageActionType.COMMAND_ACTION_CLEANUP,
        )
        return False
    except Exception as e:
        bot_logger.error(f"❌ Failed to process deep link: {e}", exc_info=True)
        await bot_manager.send_answer(
            text="❌ Ошибка при переходе к сообщению.",
            event=event,
            message_type=MessageType.COMMAND_ACTION_INFO,
            delete_by_type=MessageActionType.COMMAND_ACTION_CLEANUP,
        )
        return False


@router.message(Command("start"))
@log_exceptions(bot_logger)
async def cmd_start(message: Message, state: FSMContext) -> None:
    """
    Обработчик команды /start - запрос верификации.

    Поддерживает Deep Linking:
    - /start msg_123 - перейти к сообщению после авторизации
    - /start - обычная авторизация

    Args:
        message: Сообщение от пользователя
        state: Состояние FSM
    """
    # Проверка наличия пользователя
    if not message.from_user:
        await message.answer("❌ Не удалось определить пользователя.")
        return

    telegram_user_id = message.from_user.id
    bot_manager = get_bot_manager()

    # ============================================================
    # ОБРАБОТКА DEEP LINKING (параметр после /start)
    # ============================================================
    payload = None
    if message.text and " " in message.text:
        payload = message.text.split(" ", 1)[1]

    # Сохранение payload в состояние, чтобы обработать после авторизации
    if payload and payload.startswith("msg_"):
        await state.update_data(deep_link_payload=payload)

    # Проверка, авторизован ли пользователь в БД
    is_authenticated_db = await is_user_authenticated(telegram_user_id)

    # Проверка, есть ли пользователь в кеше команд
    is_in_cache = bot_manager.is_user_in_cache(telegram_user_id)

    # Очистка кеша, если пользователь разлогинился
    if is_in_cache and not is_authenticated_db:
        bot_manager.clear_user_cache(telegram_user_id)
        _auth_cache.pop(telegram_user_id, None)
        bot_logger.debug(f"🧹 Cleared stale cache for user {telegram_user_id} during /start")

    if await is_user_authenticated(telegram_user_id):
        # Обновление команды для авторизованного пользователя
        is_admin = telegram_user_id in settings.ADMIN_IDS
        try:
            await bot_manager.update_user_commands(telegram_user_id, is_admin)
        except Exception as e:
            bot_logger.warning(f"⚠️ Failed to update commands: {e}")

        # ============================================================
        # ЕСЛИ ЕСТЬ PAYLOAD - ОБРАБАТЫВАЕМ ПЕРЕХОД К СООБЩЕНИЮ
        # ============================================================
        if payload and payload.startswith("msg_"):
            try:
                msg_id = int(payload.replace("msg_", ""))
                handled = await _handle_deep_link_message(message, state, msg_id, bot_manager)
                if handled:
                    # Обновление времени последней активности
                    async with db_manager.get_session() as session:
                        await _user_repo.update_last_activity(session, telegram_user_id)
                    return
            except ValueError:
                await bot_manager.send_answer(
                    text="❌ Неверный формат ссылки.",
                    event=message,
                    message_type=MessageType.COMMAND_ACTION_INFO,
                    delete_by_type=MessageActionType.COMMAND_ACTION_CLEANUP,
                )

        # Если payload нет или обработка не удалась — обычное приветствие
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
            await _user_repo.update_last_activity(session, telegram_user_id)
        return

    # Если пользователь не авторизован - запрос контакта
    keyboard = AuthKeyboard.get_auth_request_keyboard()

    await state.set_state(AuthStates.waiting_for_contact)

    # Если есть payload, показываем его в сообщении
    payload_text = ""
    if payload and payload.startswith("msg_"):
        try:
            msg_id = int(payload.replace("msg_", ""))
            payload_text = f"\n\n🔗 После авторизации вы будете перенаправлены к сообщению #{msg_id}."
        except ValueError:
            pass

    # Отправка сообщения с запросом контакта
    result = await bot_manager.send_message(
        chat_id=message.chat.id,
        text="🔐 **Верификация по номеру телефона**\n\n"
        "Для идентификации необходимо подтвердить ваш номер телефона.\n\n"
        "⚠️ **Важно:** Бот использует ваш номер телефона только для "
        "авторизации и не передает его третьим лицам."
        f"{payload_text}\n\n"
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
    """
    Отмена авторизации через текстовую кнопку.

    Args:
        message: Сообщение от пользователя
        state: Состояние FSM
    """
    bot_manager = get_bot_manager()
    current_state = await state.get_state()

    if current_state == AuthStates.waiting_for_contact:
        # Отмена авторизации
        await state.clear()
        await bot_manager.send_answer(
            text="❌ Верификация отменена.\n\nДля повторной попытки используйте /start",
            event=message,
            message_type=MessageType.COMMAND_AUTH,
            delete_by_type=MessageActionType.COMMAND_AUTH_CLEANUP,
            reply_markup=ReplyKeyboardRemove(),
        )
    else:
        # Нет активной авторизации
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
    """
    Обработка полученного контакта от пользователя.

    Выполняет проверку номера телефона через хранимую процедуру Avanpost,
    сохраняет данные пользователя в БД и выполняет авторизацию.

    Args:
        message: Сообщение с контактом
        state: Состояние FSM
    """
    bot_manager = get_bot_manager()

    # Проверка наличия пользователя
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

    # Отображение toast-уведомления о начале проверки
    await bot_manager.send_toast(text="⏳ Проверка данных...", message=message)

    # Проверка наличия номера телефона
    if not contact or not contact.phone_number:
        await bot_manager.send_answer(
            text="❌ Не удалось получить номер телефона. Попробуйте еще раз.",
            event=message,
            message_type=MessageType.COMMAND_AUTH,
            delete_by_type=MessageActionType.COMMAND_AUTH_CLEANUP,
        )
        return

    # Проверка, что пользователь отправляет свой собственный контакт
    if contact.user_id != telegram_user_id:
        await bot_manager.send_answer(
            text="⚠️ Пожалуйста, отправьте свой собственный контакт.\n\n"
            "Нажмите кнопку 'Поделиться контактом' и подтвердите отправку.",
            event=message,
            message_type=MessageType.COMMAND_AUTH,
            delete_by_type=MessageActionType.COMMAND_AUTH_CLEANUP,
        )
        return

    # Нормализация номера телефона
    phone_number = normalize_phone(contact.phone_number)
    bot_logger.info(f"📱 Received contact from user {telegram_user_id}: {phone_number}")

    try:
        # 1. Проверка пользователя через хранимую процедуру Avanpost
        async with db_manager.get_session("avanpost") as avanpost_session:
            avanpost_user_id, menu_group_id, fk_contact = await _avanpost_repo.check_user_by_phone(
                session=avanpost_session,
                phone_number=phone_number,
            )

        # Если пользователь не найден в системе Avanpost
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
            user = await _user_repo.save_user(
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
            success, avanpost_user = await _user_repo.create_or_update_avanpost_user_upsert(
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
        _auth_cache[telegram_user_id] = {
            "user_id": avanpost_user_id,
            "group_id": menu_group_id,
            "phone": phone_number,
        }

        # Установка состояния "авторизован"
        await state.set_state(AuthStates.authenticated)

        # 4. Запуск синхронизации пользовательских данных в фоне
        asyncio.create_task(
            _sync_user_in_background(
                telegram_user_id=telegram_user_id,
                avanpost_user_id=avanpost_user_id,
            )
        )

        # 5. Обновление команд для пользователя
        is_admin = telegram_user_id in settings.ADMIN_IDS
        try:
            await bot_manager.update_user_commands(telegram_user_id, is_admin)
            bot_logger.info(f"✅ Commands updated for user {telegram_user_id}")
        except Exception as e:
            bot_logger.warning(f"⚠️ Failed to update commands: {e}")

        # ============================================================
        # 6. ОБРАБОТКА DEEP LINKING ПОСЛЕ АВТОРИЗАЦИИ
        # ============================================================
        state_data = await state.get_data()
        deep_link_payload = state_data.get("deep_link_payload")

        # Формирование приветственного сообщения
        if deep_link_payload and deep_link_payload.startswith("msg_"):
            try:
                msg_id = int(deep_link_payload.replace("msg_", ""))

                # Получаем сообщение из БД через AvanpostUserRepository
                message_data = await _get_message_by_id(msg_id)

                if message_data:
                    from .chat_message_menu import show_message_context_menu
                    from .lists.chat_details import chat_details_handler

                    # ============================================================
                    # ИСПРАВЛЕНИЕ: Используем format_single_message
                    # ============================================================
                    formatted = chat_details_handler.format_single_message(message_data)

                    # Формируем приветствие с сообщением
                    welcome_text = f"✅ **Авторизация успешна!**\n\n🔗 **Переход к сообщению #{msg_id}**\n\n{formatted}"

                    # Отправляем приветствие с контекстным меню
                    await show_message_context_menu(
                        event=message,
                        state=state,
                        message_id=msg_id,
                        chat_id=message.chat.id,
                        custom_text=welcome_text,
                        edit_original=False,
                    )

                    # Очищаем payload
                    await state.update_data(deep_link_payload=None)
                    await state.set_state(AuthStates.authenticated)
                    return
                else:
                    # Сообщение не найдено, показываем обычное приветствие
                    await bot_manager.send_answer(
                        text="❌ Сообщение не найдено, но вы успешно авторизованы!\n\n"
                        + _build_welcome_message(avanpost_user_id, menu_group_id, is_admin),
                        event=message,
                        message_type=MessageType.COMMAND_AUTH,
                        delete_by_type=MessageActionType.COMMAND_AUTH_CLEANUP,
                        parse_mode="Markdown",
                    )
                    await state.set_state(AuthStates.authenticated)
                    return

            except (ValueError, Exception) as e:
                bot_logger.error(f"❌ Failed to process deep link after auth: {e}")
                # В случае ошибки показываем обычное приветствие

        # 7. Отправка обычного приветственного сообщения (если нет payload)
        welcome_text = _build_welcome_message(avanpost_user_id, menu_group_id, is_admin)

        await bot_manager.send_answer(
            text=welcome_text,
            event=message,
            message_type=MessageType.COMMAND_AUTH,
            delete_by_type=MessageActionType.COMMAND_AUTH_CLEANUP,
            parse_mode="Markdown",
        )
        await state.set_state(AuthStates.authenticated)

    except Exception as e:
        # Обработка ошибок авторизации
        bot_logger.error(f"❌ Authentication error: {e}", exc_info=True)

        # Логирование ошибки через error_service
        await error_service.log_error(
            error=e,
            component="auth",
            category=ErrorCategory.SYSTEM,
        )

        # Отправка сообщения об ошибке пользователю
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
    """
    Команда для выхода из системы.

    Выполняет выход пользователя, очищает кеш и сбрасывает команды.

    Args:
        message: Сообщение от пользователя
        state: Состояние FSM
    """
    bot_manager = get_bot_manager()

    # Проверка наличия пользователя
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
        # Выход пользователя через репозиторий
        async with db_manager.get_session() as session:
            success = await _user_repo.logout_user(session, user_id)

            if success:
                await session.commit()
                bot_logger.info(f"✅ User {user_id} logged out")
            else:
                bot_logger.warning(f"⚠️ User {user_id} not found for logout")

        # Очистка кеша авторизации
        _auth_cache.pop(user_id, None)
        bot_manager.clear_user_cache(user_id)

        # Сброс команд пользователя
        try:
            await bot_manager.reset_user_commands(user_id)
            bot_logger.info(f"✅ Commands reset for user {user_id}")
        except Exception as e:
            bot_logger.warning(f"⚠️ Failed to reset commands: {e}")

        # Очистка состояния FSM
        await state.clear()

        # Отправка сообщения об успешном выходе
        await bot_manager.send_answer(
            text="👋 Вы вышли из системы.\n\nДля повторной авторизации используйте /start",
            event=message,
            message_type=MessageType.COMMAND_AUTH,
            delete_by_type=MessageActionType.COMMAND_AUTH_CLEANUP,
        )

    except Exception as e:
        # Обработка ошибок выхода
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
    """
    Команда /actions с использованием group_id из авторизации.

    Проверяет авторизацию пользователя и передает управление
    обработчику команды /actions с переданным group_id.

    Args:
        message: Сообщение от пользователя
        state: Состояние FSM
    """
    # Отложенный импорт для избежания циклических зависимостей
    from .actions import cmd_actions

    bot_manager = get_bot_manager()

    # Проверка наличия пользователя
    if not message.from_user:
        await bot_manager.send_answer(
            text="❌ Не удалось определить пользователя.",
            event=message,
            message_type=MessageType.COMMAND_AUTH,
            delete_by_type=MessageActionType.COMMAND_AUTH_CLEANUP,
        )
        return

    user_id = message.from_user.id

    # Проверка авторизации пользователя
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

    # Получение group_id из кеша авторизации
    user_data = _auth_cache.get(user_id)

    if user_data and user_data.get("group_id"):
        await state.update_data(use_group_id=user_data.get("group_id"))

    # Вызов обработчика команды /actions
    await cmd_actions(message, state)


# ============ МИДЛВАР ДЛЯ ПРОВЕРКИ АВТОРИЗАЦИИ ============


async def auth_middleware(
    handler: Callable[[TelegramObject, dict[str, Any]], Awaitable[Any]],
    event: TelegramObject,
    data: dict[str, Any],
) -> Any:
    """
    Middleware для проверки авторизации пользователя.

    Проверяет авторизацию для всех команд (кроме /start, /help, /logout).
    Если пользователь не авторизован, отправляет сообщение с требованием
    авторизации и прерывает выполнение команды.

    Args:
        handler: Обработчик события
        event: Событие от пользователя
        data: Данные события

    Returns:
        Any: Результат выполнения обработчика или None при ошибке
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

            # Если пользователь не авторизован
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

    # Если все проверки пройдены - выполнение обработчика
    return await handler(event, data)


# ============ ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ ============


def normalize_phone(phone: str) -> str:
    """
    Нормализация номера телефона к формату +XXXXXXXXXXX.

    Выполняет:
    - Удаление всех нецифровых символов
    - Замену '8' на '7' в начале номера (для российских номеров)
    - Добавление '+' перед номером

    Args:
        phone: Исходный номер телефона

    Returns:
        str: Нормализованный номер телефона
    """
    # Удаление всех нецифровых символов
    digits = re.sub(r"\D", "", phone)

    # Замена '8' на '7' в начале номера
    if digits.startswith("8"):
        digits = "7" + digits[1:]

    # Если номер начинается с '7' - добавляем '+'
    if digits.startswith("7"):
        return "+" + digits

    # Если номер уже начинается с '+7' - возвращаем как есть
    if phone.startswith("+7"):
        return phone

    # Если номер уже начинается с '+' - возвращаем как есть
    if phone.startswith("+"):
        return phone

    # Возвращение исходного номера
    return phone


async def check_user_by_phone_avanpost(phone_number: str) -> tuple[int | None, int | None, int | None]:
    """
    Проверка пользователя через хранимую процедуру Avanpost.

    Args:
        phone_number: Номер телефона для проверки

    Returns:
        tuple[int | None, int | None, int | None]:
            (avanpost_user_id, menu_group_id, fk_contact) или (None, None, None) при ошибке
    """
    try:
        # Нормализация номера телефона
        normalized_phone = normalize_phone(phone_number)

        # Вызов хранимой процедуры
        async with db_manager.get_session("avanpost") as session:
            result = await _avanpost_repo.check_user_by_phone(
                session=session,
                phone_number=normalized_phone,
            )
            # Явное приведение типов для mypy
            return (
                int(result[0]) if result[0] is not None else None,
                int(result[1]) if result[1] is not None else None,
                int(result[2]) if result[2] is not None else None,
            )
    except Exception as e:
        bot_logger.error(f"❌ Failed to check user in Avanpost: {e}", exc_info=True)
        return None, None, None


async def get_user_group_id(user_id: int) -> int | None:
    """
    Получение ID группы действий для пользователя.

    Поддерживает как Telegram ID, так и Avanpost ID.
    Использует репозиторий вместо прямого доступа к модели.

    Args:
        user_id: ID пользователя (Telegram или Avanpost)

    Returns:
        int | None: ID группы действий или None
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
            # Поиск по Telegram ID
            result = await _user_repo.get_user_group_id(session, user_id)
            if result is not None:
                # Явное приведение к int для mypy
                return int(result) if isinstance(result, int) else None

            # Если не нашли по Telegram ID, пробуем как Avanpost ID
            avanpost_user_data = await _user_repo.get_avanpost_user_data(session, user_id)
            if avanpost_user_data:
                group_id = avanpost_user_data.get("FK_MenuGroup")
                if group_id is not None and isinstance(group_id, int):
                    return int(group_id)

            return None
    except Exception as e:
        bot_logger.error(f"❌ Failed to get user group: {e}")
        return None


async def _sync_user_in_background(
    telegram_user_id: int,
    avanpost_user_id: int,
) -> None:
    """
    Фоновая синхронизация пользовательских данных из Avanpost.

    Запускается после успешной авторизации пользователя для
    загрузки всех связанных данных (чаты, заказы, транспорт и т.д.)

    Args:
        telegram_user_id: ID пользователя в Telegram
        avanpost_user_id: ID пользователя в Avanpost
    """
    try:
        from ....services import avanpost_sync_service

        bot_logger.info(f"🔄 Background sync started for user {avanpost_user_id} (telegram: {telegram_user_id})")
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
    """
    Формирование приветственного сообщения для авторизованного пользователя.

    Args:
        avanpost_user_id: ID пользователя в Avanpost
        menu_group_id: ID группы меню
        is_admin: Является ли пользователь администратором

    Returns:
        str: Текст приветственного сообщения в формате Markdown
    """
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
