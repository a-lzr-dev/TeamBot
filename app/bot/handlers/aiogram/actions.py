import contextlib
from typing import Any

from aiogram import F, Router
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, Message

from ....bot.dependencies import get_bot_manager
from ....config import settings
from ....db import AvanpostRepository, db_manager
from ....db.repositories import UserRepository
from ....exceptions import log_exceptions
from ....logger import bot_logger
from ....models import ErrorCategory, MessageActionType, MessageType
from ....services import error_service
from ...keyboards import ActionKeyboard
from .auth import _auth_cache, get_user_group_id, is_user_authenticated
from .users import back_to_users

router = Router(name="aiogram_actions")


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

    # Проверка, не является ли пользователь выбранным через /users
    state_data = await state.get_data()
    selected_user_id = state_data.get("selected_user_id")
    selected_user_name = state_data.get("selected_user_name")

    # Если выбран конкретный пользователь через /users
    if selected_user_id and selected_user_id != user_id:
        # Использование выбранного пользователя
        user_id = selected_user_id
        bot_logger.debug(f"✅ Using selected user ID from state: {user_id} ({selected_user_name})")

        # Проверка, что пользователь существует в Avanpost
        async with db_manager.get_session() as session:
            avanpost_user = await UserRepository.get_avanpost_user_data(session, user_id)
            if not avanpost_user:
                await bot_manager.send_answer(
                    text="❌ **Пользователь не найден**\n\n"
                    f"Пользователь с ID `{user_id}` не найден в системе Avanpost.",
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

    await show_menu(event=message, group_id=group_id, state=state, _is_new=True)


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

        # 3. Если всё еще нет — пробуем получить из БД напрямую по Avanpost ID
        if not group_id:
            async with db_manager.get_session() as session:
                from app.models.avanpost import AvanpostUserModel

                avanpost_user = await session.get(AvanpostUserModel, selected_user_id)
                if avanpost_user:
                    group_id = avanpost_user.FK_MenuGroup
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
        async with db_manager.get_session() as session:
            from app.models.avanpost import AvanpostUserModel

            avanpost_user = await session.get(AvanpostUserModel, selected_user_id)
            if not avanpost_user:
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
            "phone": avanpost_user.FPhone,
            "telegram_user_id": telegram_user_id,
        }
        bot_logger.debug(f"✅ Updated _auth_cache for telegram user {telegram_user_id} with group_id={group_id}")

        # ============================================================
        # ОБРАБОТКА ВЫБОРА ДЕЙСТВИЯ
        # ============================================================
        if callback_data.startswith("action_") and not callback_data.startswith("action_back_"):
            try:
                action_id = int(callback_data.split("_")[1])

                async with db_manager.get_session("avanpost") as session:
                    has_children = await AvanpostRepository.has_subitems(
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
                async with db_manager.get_session("avanpost") as session:
                    has_children = await AvanpostRepository.has_subitems(
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
    parent_item_id: int | None = None,
    is_callback: bool = False,
    _is_new: bool = False,
    user_display_name: str | None = None,
) -> None:
    """
    Отображение меню действий с горизонтальным расположением кнопок.
    """
    bot_manager = get_bot_manager()

    user_id = None
    is_admin = False

    try:
        state_data = await state.get_data()
        user_id = state_data.get("user_id")

        # Проверка на выбранного пользователя
        selected_user_id = state_data.get("selected_user_id")
        # selected_user_name = state_data.get("selected_user_name")

        if selected_user_id and not user_id:
            user_id = selected_user_id
            bot_logger.debug(f"✅ Using selected user ID from state in show_menu: {user_id}")

        if user_id:
            bot_logger.debug(f"✅ Using user_id from state: {user_id}")
            is_admin = state_data.get("is_admin", user_id in settings.ADMIN_IDS)
        else:
            if isinstance(event, CallbackQuery):
                # Для CallbackQuery - ВСЕГДА берем from_user у callback
                if event.from_user:
                    user_id = event.from_user.id
                    bot_logger.debug(f"✅ Callback from user: {user_id}")
                    bot_logger.debug(f"✅ Callback data: {event.data}")
                    is_callback = True

            elif isinstance(event, Message):
                # Для обычного сообщения
                if event.from_user and not event.from_user.is_bot:
                    # Реальный пользователь отправил сообщение
                    user_id = event.from_user.id
                    bot_logger.debug(f"✅ Message from user: {user_id}")
                elif event.from_user:
                    # Сообщение от бота - ищем реального пользователя
                    bot_logger.debug("⚠️ Message from bot, trying to find real user...")

                    # 1. Проверяем reply_to_message
                    if event.reply_to_message and event.reply_to_message.from_user:
                        user_id = event.reply_to_message.from_user.id
                        bot_logger.debug(f"✅ Found user from reply: {user_id}")
                    # 2. Проверяем forward_from
                    elif event.forward_from:
                        user_id = event.forward_from.id
                        bot_logger.debug(f"✅ Found user from forward: {user_id}")
                    # 3. Проверяем sender_chat (для каналов)
                    elif event.sender_chat:
                        user_id = event.sender_chat.id
                        bot_logger.debug(f"✅ Found user from sender_chat: {user_id}")
                else:
                    bot_logger.debug("⚠️ No from_user in message")

            # Если удалось определить пользователя - сохраняем в состояние
            if user_id:
                is_admin = user_id in settings.ADMIN_IDS
                await state.update_data(user_id=user_id, is_admin=is_admin, last_activity="show_menu")
                bot_logger.debug(f"✅ Saved user {user_id} to state")

        # Если не удалось определить пользователя - ошибка
        if not user_id:
            error_msg = "❌ Не удалось определить пользователя"
            bot_logger.error(error_msg)
            await bot_manager.send_toast(text=error_msg, event=event)
            return

        # Проверка прав администратора
        is_admin = user_id in settings.ADMIN_IDS
        bot_logger.debug(f"🔍 User ID: {user_id}")
        bot_logger.debug(f"🔍 Is admin: {is_admin}")
        bot_logger.debug(f"🔍 Admin list: {settings.ADMIN_IDS}")

        # Получение меню из БД
        menu_data = await get_menu_items_with_parent(group_id, parent_item_id)
        menu_items = menu_data.get("items", [])
        parent_name = menu_data.get("parent_name")
        parent_id = menu_data.get("parent_id")

        bot_logger.debug(f"📊 Menu items count: {len(menu_items)}, parent: {parent_name} (ID: {parent_id})")
        bot_logger.debug(f"📊 First item: {menu_items[0] if menu_items else 'None'}")

        # Формирование текста
        if not menu_items:
            empty_text = "📋 Нет доступных действий."

            if is_callback and isinstance(event, CallbackQuery):
                if event.message:
                    await bot_manager.delete_message_by_link(event.message)
                    await bot_manager.send_message(
                        chat_id=event.message.chat.id,
                        text=empty_text,
                        message_type=MessageType.COMMAND_ACTION_INFO,
                        delete_by_type=MessageActionType.COMMAND_ACTION_CLEANUP,
                        parse_mode="Markdown",
                    )
            else:
                if isinstance(event, Message):
                    await bot_manager.send_message(
                        chat_id=event.chat.id,
                        text=empty_text,
                        message_type=MessageType.COMMAND_ACTION_INFO,
                        delete_by_type=MessageActionType.COMMAND_ACTION_CLEANUP,
                        parse_mode="Markdown",
                    )
                elif isinstance(event, CallbackQuery) and event.message:
                    await bot_manager.send_message(
                        chat_id=event.message.chat.id,
                        text=empty_text,
                        message_type=MessageType.COMMAND_ACTION_INFO,
                        delete_by_type=MessageActionType.COMMAND_ACTION_CLEANUP,
                        parse_mode="Markdown",
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
    """
    Выполнение действия при выборе конечного пункта меню.
    Показывает Toast (уведомление вверху экрана) вместо всплывающего окна.
    """
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

        # Получение информации о действии
        action_info = None
        async with db_manager.get_session("avanpost") as session:
            items = await AvanpostRepository.get_menu_items(
                session=session,
                group_id=group_id,
                parent_item_id=None,
            )

            for item in items:
                if item.get("id") == action_id:
                    action_info = item
                    break

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


async def get_menu_items_with_parent(group_id: int, parent_item_id: int | None = None) -> dict[str, Any]:
    """
    Получение пунктов меню и информации о родителе из базы данных Avanpost.
    Использует AvanpostRepository.get_menu_items().
    """
    try:
        async with db_manager.get_session("avanpost") as session:
            items = await AvanpostRepository.get_menu_items(
                session=session,
                group_id=group_id,
                parent_item_id=parent_item_id,
            )

            parent_name = None
            parent_id = parent_item_id

            if parent_item_id is not None:
                all_items = await AvanpostRepository.get_menu_items(
                    session=session,
                    group_id=group_id,
                    parent_item_id=None,
                )
                for item in all_items:
                    if item.get("id") == parent_item_id:
                        parent_name = item.get("name")
                        break

            return {
                "items": items,
                "parent_name": parent_name,
                "parent_id": parent_id,
            }

    except Exception as e:
        bot_logger.error(f"❌ Failed to get menu items with parent: {e}", exc_info=True)
        return {"items": [], "parent_name": None, "parent_id": None}


async def get_menu_items(group_id: int, parent_item_id: int | None = None) -> list[dict[str, Any]]:
    """Получение пунктов меню из базы данных Avanpost (для обратной совместимости)"""
    data = await get_menu_items_with_parent(group_id, parent_item_id)
    items = data.get("items")
    if items is None:
        return []
    if not isinstance(items, list):
        return []
    return items


# ============ ФОНОВАЯ ЗАДАЧА ДЛЯ ОЧИСТКИ ============


async def start_cleanup_scheduler() -> None:
    """Запуск фоновой задачи для периодической очистки просроченных сообщений"""
    import asyncio

    bot_logger.info("🔄 Starting cleanup scheduler for bot messages")

    while True:
        try:
            await asyncio.sleep(60)
        except asyncio.CancelledError:
            bot_logger.info("⏹️ Cleanup scheduler stopped")
            break
        except Exception as e:
            bot_logger.error(f"❌ Cleanup scheduler error: {e}", exc_info=True)
            await asyncio.sleep(60)


__all__ = [
    "router",
    "start_cleanup_scheduler",
    "show_menu",
    "cmd_actions",
    "execute_action",
    "get_menu_items_with_parent",
    "get_menu_items",
]
