import contextlib
from typing import Any

from aiogram import F, Router
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message

from app.bot.dependencies import get_bot_manager
from app.bot.keyboards import ActionKeyboard
from app.config import settings
from app.db import db_manager
from app.db.repositories.avanpost_actions import AvanpostActionsRepository
from app.db.repositories.users import UserRepository
from app.exceptions import log_exceptions
from app.logger import bot_logger
from app.models import ErrorCategory, MessageActionType, MessageType
from app.services import error_service

from .auth import _auth_cache, get_user_group_id, is_user_authenticated
from .users import back_to_users

router = Router(name="aiogram_actions")

# Репозиторий для работы с меню
_actions_repo = AvanpostActionsRepository()


class ActionStates(StatesGroup):
    """Состояния для работы с действиями"""

    viewing_menu = State()


# ============ ОБРАБОТЧИКИ ============


@router.message(Command("actions"))
@log_exceptions(bot_logger)
async def cmd_actions(message: Message, state: FSMContext) -> None:
    """Команда для вызова меню действий"""
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

    async with db_manager.get_session() as session:
        await _cmd_actions_impl(message, state, session, user_id)


async def _cmd_actions_impl(
    message: Message,
    state: FSMContext,
    session: Any,
    user_id: int,
) -> None:
    """Реализация команды /actions с переданной сессией"""
    bot_manager = get_bot_manager()

    # Проверка на выбранного пользователя через /users
    state_data = await state.get_data()
    selected_user_id = state_data.get("selected_user_id")
    selected_user_name = state_data.get("selected_user_name")

    # Если выбран конкретный пользователь через /users
    if selected_user_id and selected_user_id != user_id:
        user_id = selected_user_id
        bot_logger.debug(f"✅ Using selected user ID from state: {user_id} ({selected_user_name})")

        # Проверка, что пользователь существует в Avanpost
        avanpost_user_data = await UserRepository.get_avanpost_user_data(session, user_id)
        if not avanpost_user_data:
            await bot_manager.send_answer(
                text=f"❌ **Пользователь не найден**\n\nПользователь с ID `{user_id}` не найден в системе Avanpost.",
                event=message,
                message_type=MessageType.COMMAND_ACTION_INFO,
                delete_by_type=MessageActionType.COMMAND_ACTION_CLEANUP,
                parse_mode="Markdown",
            )
            return

        # Обновление is_admin
        is_admin = user_id in settings.ADMIN_IDS
        await state.update_data(
            user_id=user_id,
            is_admin=is_admin,
            selected_user_id=user_id,
            selected_user_name=selected_user_name,
        )

        # Получение group_id для выбранного пользователя
        group_id = await get_user_group_id(user_id)
        if not group_id:
            await bot_manager.send_answer(
                text="❌ **Группа действий не найдена**\n\n"
                f"У пользователя `{selected_user_name or user_id}` не назначена группа действий в системе.\n"
                "Обратитесь к администратору для настройки прав.",
                event=message,
                message_type=MessageType.COMMAND_ACTION_INFO,
                delete_by_type=MessageActionType.COMMAND_ACTION_CLEANUP,
                parse_mode="Markdown",
            )
            return

        await state.set_state(ActionStates.viewing_menu)
        await bot_manager.delete_message_by_link(message)

        # Очистка истории при входе в меню
        await state.update_data(menu_history=[])

        await show_menu(
            event=message,
            group_id=group_id,
            state=state,
            session=session,
            _is_new=True,
            user_display_name=selected_user_name or f"User #{user_id}",
        )
        return

    # Стандартная логика для текущего пользователя
    if not await is_user_authenticated(user_id):
        await bot_manager.send_answer(
            text="🔐 **Требуется авторизация**\n\n"
            "Для доступа к действиям необходимо авторизоваться.\n"
            "Используйте /start для начала авторизации.",
            event=message,
            message_type=MessageType.COMMAND_ACTION_INFO,
            delete_by_type=MessageActionType.COMMAND_ACTION_CLEANUP,
            parse_mode="Markdown",
        )
        return

    group_id = await get_user_group_id(user_id)

    if not group_id:
        await bot_manager.send_answer(
            text="❌ **Группа действий не найдена**\n\n"
            "У вас не назначена группа действий в системе.\n"
            "Обратитесь к администратору для настройки прав.",
            event=message,
            message_type=MessageType.COMMAND_ACTION_INFO,
            delete_by_type=MessageActionType.COMMAND_ACTION_CLEANUP,
            parse_mode="Markdown",
        )
        return

    await state.set_state(ActionStates.viewing_menu)
    await bot_manager.delete_message_by_link(message)

    # Очистка истории при входе в меню
    await state.update_data(menu_history=[])

    await show_menu(
        event=message,
        group_id=group_id,
        state=state,
        session=session,
        _is_new=True,
    )


# ============ ОБРАБОТЧИКИ КОЛБЭКОВ ============


@router.callback_query(
    F.data.startswith("action_")
    | F.data.startswith("action_back_")
    | (F.data == "action_home")
    | (F.data == "back_to_users")
)
@log_exceptions(bot_logger)
async def handle_action_callback(callback: CallbackQuery, state: FSMContext) -> None:
    """
    Обработка колбэков действий.

    Поддерживает:
    - action_<id> - выбор действия
    - action_back_<parent_id> - возврат на уровень назад
    - action_home - возврат в главное меню
    - back_to_groups - переход к списку групп (админ)
    - back_to_users - переход к списку пользователей
    """
    bot_manager = get_bot_manager()

    if not callback.from_user:
        await bot_manager.send_toast(text="❌ Не удалось определить пользователя.", event=callback)
        return

    telegram_user_id = callback.from_user.id
    callback_data = callback.data

    if not callback_data:
        await bot_manager.send_toast(text="❌ Пустой callback.", event=callback)
        return

    # Обработка возврата к списку пользователей
    if callback_data == "back_to_users":
        await back_to_users(callback, state)
        return

    bot_logger.debug(f"✅ Callback from REAL user: {telegram_user_id}")
    bot_logger.debug(f"✅ Callback data: {callback.data}")

    async with db_manager.get_session() as session:
        await _handle_action_callback_impl(callback, state, session, telegram_user_id)


async def _handle_action_callback_impl(
    callback: CallbackQuery,
    state: FSMContext,
    session: Any,
    telegram_user_id: int,
) -> None:
    """Реализация обработки колбэка с переданной сессией"""
    bot_manager = get_bot_manager()
    callback_data = callback.data

    # Получение состояния
    state_data = await state.get_data()
    selected_user_id = state_data.get("selected_user_id")
    selected_user_name = state_data.get("selected_user_name")
    selected_user_group_id = state_data.get("selected_user_group_id")

    # ============================================================
    # БЛОК 1: ОБРАБОТКА ВЫБРАННОГО ПОЛЬЗОВАТЕЛЯ (через /users)
    # ============================================================
    if selected_user_id and selected_user_id != telegram_user_id:
        bot_logger.debug(f"✅ Using selected user ID from state in callback: {selected_user_id} ({selected_user_name})")

        # 1. Получаем group_id из состояния (сохранен в select_user)
        group_id = selected_user_group_id

        # 2. Если в состоянии нет, пробуем из кеша
        if not group_id:
            cache_data = _auth_cache.get(telegram_user_id)
            if cache_data:
                group_id = cache_data.get("group_id")
                bot_logger.debug(f"✅ Found group_id in cache: {group_id}")

        # 3. Если всё еще нет — пробуем получить из БД
        if not group_id:
            avanpost_user_data = await UserRepository.get_avanpost_user_data(session, selected_user_id)
            if avanpost_user_data:
                group_id = avanpost_user_data.get("FK_MenuGroup")
                bot_logger.debug(f"✅ Found group_id in DB: {group_id}")
            else:
                await bot_manager.send_toast(
                    text=f"❌ Пользователь {selected_user_name or selected_user_id} не найден в системе Avanpost.",
                    event=callback,
                )
                return

        if not group_id:
            await bot_manager.send_toast(
                text=f"❌ У пользователя {selected_user_name or selected_user_id} не назначена группа действий.",
                event=callback,
            )
            return

        # 4. Проверка, что пользователь существует в Avanpost
        avanpost_user_data = await UserRepository.get_avanpost_user_data(session, selected_user_id)
        if not avanpost_user_data:
            await bot_manager.send_toast(
                text=f"❌ Пользователь {selected_user_id} не найден в системе Avanpost.",
                event=callback,
            )
            return

        # 5. Обновление состояния и кеша
        is_admin = telegram_user_id in settings.ADMIN_IDS
        await state.update_data(
            user_id=selected_user_id,
            is_admin=is_admin,
            selected_user_id=selected_user_id,
            selected_user_name=selected_user_name,
            selected_user_group_id=group_id,
            use_group_id=group_id,
        )

        # Обновляем кеш с данными выбранного пользователя
        _auth_cache[telegram_user_id] = {
            "avanpost_user_id": selected_user_id,
            "group_id": group_id,
            "phone": avanpost_user_data.get("FPhone") if avanpost_user_data else None,
            "telegram_user_id": telegram_user_id,
        }
        bot_logger.debug(f"✅ Updated _auth_cache for telegram user {telegram_user_id} with group_id={group_id}")

        # ============================================================
        # ОБРАБОТКА ВЫБОРА ДЕЙСТВИЯ
        # ============================================================
        if callback_data.startswith("action_") and not callback_data.startswith("action_back_"):
            try:
                action_id = int(callback_data.split("_")[1])

                has_children = await _actions_repo.has_subitems(
                    session=session,
                    group_id=group_id,
                    item_id=action_id,
                )

                if has_children:
                    await bot_manager.send_toast(event=callback)

                    # Сохранение истории переходов
                    history = state_data.get("menu_history", [])
                    history.append(action_id)
                    await state.update_data(menu_history=history)
                    bot_logger.debug(f"📜 Added {action_id} to history: {history}")

                    await show_menu(
                        event=callback,
                        group_id=group_id,
                        parent_item_id=action_id,
                        state=state,
                        session=session,
                        is_callback=True,
                        user_display_name=selected_user_name or f"User #{selected_user_id}",
                    )
                else:
                    await execute_action(callback=callback, action_id=action_id, state=state)
                return

            except (ValueError, IndexError):
                bot_logger.warning(f"⚠️ Invalid action ID in callback: {callback.data}")

        # Обработка остальных колбэков (action_back_, action_home)
        from ...callbacks import action_callback_handler

        await action_callback_handler.handle(callback, state)
        return

    # ============================================================
    # БЛОК 2: СТАНДАРТНАЯ ЛОГИКА ДЛЯ ТЕКУЩЕГО ПОЛЬЗОВАТЕЛЯ
    # ============================================================
    await state.update_data(
        user_id=telegram_user_id,
        is_admin=telegram_user_id in settings.ADMIN_IDS,
    )

    # Обработка выбора действия (не "Назад" и не "В главное меню")
    if callback_data.startswith("action_") and not callback_data.startswith("action_back_"):
        try:
            action_id = int(callback_data.split("_")[1])

            group_id = await get_user_group_id(telegram_user_id)

            if group_id:
                has_children = await _actions_repo.has_subitems(
                    session=session,
                    group_id=group_id,
                    item_id=action_id,
                )

                if has_children:
                    await bot_manager.send_toast(event=callback)

                    # Сохранение истории переходов
                    history = state_data.get("menu_history", [])
                    history.append(action_id)
                    await state.update_data(menu_history=history)
                    bot_logger.debug(f"📜 Added {action_id} to history: {history}")

                    await show_menu(
                        event=callback,
                        group_id=group_id,
                        parent_item_id=action_id,
                        state=state,
                        session=session,
                        is_callback=True,
                    )
                else:
                    await execute_action(callback=callback, action_id=action_id, state=state)
            else:
                await bot_manager.send_toast(
                    text="❌ Не удалось определить группу действий для пользователя.",
                    event=callback,
                )
            return

        except (ValueError, IndexError):
            bot_logger.warning(f"⚠️ Invalid action ID in callback: {callback.data}")

    # Обработка остальных колбэков (action_back_, action_home, back_to_groups)
    from ...callbacks import action_callback_handler

    await action_callback_handler.handle(callback, state)


# ============ ФУНКЦИЯ SHOW_MENU ============


@log_exceptions(bot_logger)
async def show_menu(
    *,
    event: Message | CallbackQuery,
    group_id: int,
    state: FSMContext,
    session: Any,
    parent_item_id: int | None = None,
    is_callback: bool = False,
    _is_new: bool = False,
    user_display_name: str | None = None,
) -> None:
    """
    Отображение меню действий с горизонтальным расположением кнопок.

    Использует репозиторий AvanpostActionsRepository.
    """
    bot_manager = get_bot_manager()

    user_id = None
    is_admin = False

    try:
        state_data = await state.get_data()
        user_id = state_data.get("user_id")

        # Проверка на выбранного пользователя
        selected_user_id = state_data.get("selected_user_id")

        if selected_user_id and not user_id:
            user_id = selected_user_id
            bot_logger.debug(f"✅ Using selected user ID from state in show_menu: {user_id}")

        if user_id:
            bot_logger.debug(f"✅ Using user_id from state: {user_id}")
            is_admin = state_data.get("is_admin", user_id in settings.ADMIN_IDS)
        else:
            if isinstance(event, CallbackQuery):
                if event.from_user:
                    user_id = event.from_user.id
                    bot_logger.debug(f"✅ Callback from user: {user_id}")
                    is_callback = True

            elif isinstance(event, Message):
                if event.from_user and not event.from_user.is_bot:
                    user_id = event.from_user.id
                    bot_logger.debug(f"✅ Message from user: {user_id}")
                elif event.from_user:
                    bot_logger.debug("⚠️ Message from bot, trying to find real user...")

                    if event.reply_to_message and event.reply_to_message.from_user:
                        user_id = event.reply_to_message.from_user.id
                        bot_logger.debug(f"✅ Found user from reply: {user_id}")
                    elif event.forward_from:
                        user_id = event.forward_from.id
                        bot_logger.debug(f"✅ Found user from forward: {user_id}")
                    elif event.sender_chat:
                        user_id = event.sender_chat.id
                        bot_logger.debug(f"✅ Found user from sender_chat: {user_id}")
                else:
                    bot_logger.debug("⚠️ No from_user in message")

            if user_id:
                is_admin = user_id in settings.ADMIN_IDS
                await state.update_data(user_id=user_id, is_admin=is_admin, last_activity="show_menu")
                bot_logger.debug(f"✅ Saved user {user_id} to state")

        if not user_id:
            error_msg = "❌ Не удалось определить пользователя"
            bot_logger.error(error_msg)
            await bot_manager.send_toast(text=error_msg, event=event)
            return

        is_admin = user_id in settings.ADMIN_IDS
        bot_logger.debug(f"🔍 User ID: {user_id}")
        bot_logger.debug(f"🔍 Is admin: {is_admin}")

        # Используем репозиторий с переданной сессией
        lang_code = "ru"  # TODO: Получать из настроек пользователя

        menu_data = await _actions_repo.get_menu_items_with_parent(
            session=session,
            group_id=group_id,
            parent_item_id=parent_item_id,
            lang_code=lang_code,
        )

        menu_items = menu_data.get("items", [])
        parent_name = menu_data.get("parent_name")
        parent_id = menu_data.get("parent_id")

        bot_logger.debug(f"📊 Menu items count: {len(menu_items)}, parent: {parent_name} (ID: {parent_id})")

        if not menu_items:
            empty_text = "📋 Нет доступных действий."

            keyboard = None
            if parent_item_id is not None:
                keyboard = InlineKeyboardMarkup(
                    inline_keyboard=[
                        [InlineKeyboardButton(text="🔙 Назад", callback_data=f"action_back_{parent_item_id}")]
                    ]
                )
            elif state_data.get("selected_user_id"):
                keyboard = InlineKeyboardMarkup(
                    inline_keyboard=[[InlineKeyboardButton(text="👥 К пользователям", callback_data="back_to_users")]]
                )

            if is_callback and isinstance(event, CallbackQuery):
                if event.message:
                    await bot_manager.delete_message_by_link(event.message)
                    await bot_manager.send_message(
                        chat_id=event.message.chat.id,
                        text=empty_text,
                        message_type=MessageType.COMMAND_ACTION_INFO,
                        delete_by_type=MessageActionType.COMMAND_ACTION_CLEANUP,
                        parse_mode="Markdown",
                        reply_markup=keyboard,
                    )
            else:
                if isinstance(event, Message):
                    await bot_manager.send_message(
                        chat_id=event.chat.id,
                        text=empty_text,
                        message_type=MessageType.COMMAND_ACTION_INFO,
                        delete_by_type=MessageActionType.COMMAND_ACTION_CLEANUP,
                        parse_mode="Markdown",
                        reply_markup=keyboard,
                    )
                elif isinstance(event, CallbackQuery) and event.message:
                    await bot_manager.send_message(
                        chat_id=event.message.chat.id,
                        text=empty_text,
                        message_type=MessageType.COMMAND_ACTION_INFO,
                        delete_by_type=MessageActionType.COMMAND_ACTION_CLEANUP,
                        parse_mode="Markdown",
                        reply_markup=keyboard,
                    )
            return

        # Формирование текста с красивым оформлением
        header_text = "✨ 📋 **МЕНЮ ДЕЙСТВИЙ**"

        # Добавляем информацию о выбранном пользователе
        display_name = user_display_name or state_data.get("selected_user_name")
        if display_name:
            header_text += f" 👤 {display_name}"

        if parent_item_id is not None:
            if parent_name:
                header_text += f" • 📂 {parent_name} ✨\n"
            else:
                header_text += " • 📂 Подменю ✨\n"
        else:
            header_text += " ✨\n"

        header_text += "\n"

        # Создание клавиатуры
        keyboard = ActionKeyboard.get_action_menu_keyboard(
            items=menu_items,
            parent_id=parent_id,
            is_admin=is_admin,
            is_root_menu=(parent_item_id is None),
            show_back_to_users=bool(state_data.get("selected_user_id")),
        )

        if is_callback and isinstance(event, CallbackQuery):
            try:
                if event.message:
                    await bot_manager.delete_message_by_link(event.message)
                    bot_logger.debug(f"🗑️ Deleted old message {event.message.message_id}")
            except Exception as e:
                bot_logger.warning(f"⚠️ Failed to delete old message: {e}")

            # Отправка нового сообщения
            if event.message:
                result = await bot_manager.send_message(
                    chat_id=event.message.chat.id,
                    text=header_text,
                    message_type=MessageType.COMMAND_ACTION,
                    delete_by_type=MessageActionType.COMMAND_ACTION_CLEANUP,
                    parse_mode="Markdown",
                    reply_markup=keyboard,
                )

                if result.get("success"):
                    await state.update_data(last_action_message_id=result.get("message_id"))
                    bot_logger.debug(f"✅ Sent new message {result.get('message_id')}")

        else:
            if isinstance(event, Message):
                await bot_manager.send_message(
                    chat_id=event.chat.id,
                    text=header_text,
                    message_type=MessageType.COMMAND_ACTION,
                    delete_by_type=MessageActionType.COMMAND_ACTION_CLEANUP,
                    parse_mode="Markdown",
                    reply_markup=keyboard,
                )
            elif isinstance(event, CallbackQuery) and event.message:
                await bot_manager.send_message(
                    chat_id=event.message.chat.id,
                    text=header_text,
                    message_type=MessageType.COMMAND_ACTION,
                    delete_by_type=MessageActionType.COMMAND_ACTION_CLEANUP,
                    parse_mode="Markdown",
                    reply_markup=keyboard,
                )

    except Exception as e:
        if "message is not modified" not in str(e):
            bot_logger.error(f"❌ Failed to show menu: {e}", exc_info=True)

            await error_service.log_error(
                error=e,
                component="actions",
                category=ErrorCategory.SYSTEM,
                context={
                    "parent_id": parent_item_id,
                    "group_id": group_id,
                    "user_id": user_id if user_id else None,
                    "is_admin": is_admin,
                    "message_or_callback_type": type(event).__name__,
                },
            )

            error_text = "❌ Произошла ошибка при загрузке меню. Попробуйте позже."

            if is_callback and isinstance(event, CallbackQuery):
                with contextlib.suppress(Exception):
                    if event.message:
                        await bot_manager.delete_message_by_link(event.message)
                        await bot_manager.send_message(
                            chat_id=event.message.chat.id,
                            text=error_text,
                            message_type=MessageType.COMMAND_ACTION_INFO,
                            delete_by_type=MessageActionType.COMMAND_ACTION_CLEANUP,
                            parse_mode="Markdown",
                        )
            else:
                with contextlib.suppress(Exception):
                    if isinstance(event, Message):
                        await bot_manager.send_message(
                            chat_id=event.chat.id,
                            text=error_text,
                            message_type=MessageType.COMMAND_ACTION_INFO,
                            delete_by_type=MessageActionType.COMMAND_ACTION_CLEANUP,
                            parse_mode="Markdown",
                        )
                    elif isinstance(event, CallbackQuery) and event.message:
                        await bot_manager.send_message(
                            chat_id=event.message.chat.id,
                            text=error_text,
                            message_type=MessageType.COMMAND_ACTION_INFO,
                            delete_by_type=MessageActionType.COMMAND_ACTION_CLEANUP,
                            parse_mode="Markdown",
                        )


# ============ ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ ============


async def execute_action(callback: CallbackQuery, action_id: int, state: FSMContext) -> None:
    """Выполнение действия при выборе конечного пункта меню"""
    bot_manager = get_bot_manager()
    try:
        state_data = await state.get_data()
        group_id = state_data.get("group_id")

        # Проверка на выбранного пользователя
        selected_user_id = state_data.get("selected_user_id")
        if selected_user_id:
            group_id = await get_user_group_id(selected_user_id)

        if not group_id:
            group_id = await get_user_group_id(callback.from_user.id)

        if not group_id:
            await bot_manager.send_toast(text="❌ Не удалось определить группу действий", event=callback)
            return

        # Получение информации о действии через репозиторий
        async with db_manager.get_session() as session:
            action_info = await _actions_repo.get_menu_item_by_id(
                session=session,
                item_id=action_id,
                lang_code="ru",
            )

        if action_info:
            action_name = action_info.get("name", "Без названия")
            toast_text = f"🚧️ {action_name}. Функционал в разработке..."
        else:
            toast_text = f"🚧 Действие #{action_id}. Функционал в разработке..."

        await bot_manager.send_toast(text=toast_text[:200], event=callback)
        bot_logger.debug(f"✅ Toast shown for action {action_id}: {toast_text}")

    except Exception as e:
        bot_logger.error(f"❌ Failed to execute action: {e}", exc_info=True)
        with contextlib.suppress(Exception):
            await bot_manager.send_toast(text="❌ Ошибка выполнения", event=callback)


__all__ = [
    "router",
    "ActionStates",
    "show_menu",
    "cmd_actions",
    "execute_action",
]
