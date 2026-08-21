"""
Модуль обработчиков AIogram для действий и меню.

Этот модуль предоставляет обработчики команд, колбэков и действий
для работы с меню действий Avanpost.

Основные компоненты:
    - Команда /actions для открытия меню действий
    - Обработка колбэков меню (навигация, выбор действий)
    - Выполнение действий по типам (открытие заказов, чатов, транспорта)
    - Обработка выбора чата для просмотра сообщений

Типы действий:
    - FK_Type=1: Отправка данных на сервер
    - FK_Type=2: Открытие файла
    - FK_Type=4: Открытие маршрута перевозки
    - FK_Type=5: Открытие точки маршрута
    - FK_Type=6: Открытие списка контактов
    - FK_Type=7: Открытие контактной информации
    - FK_Type=8: Открытие списка заказов заказчика
    - FK_Type=9: Открытие списка чатов
    - FK_Type=10: Открытие списка транспорта
    - FK_Type=11: Открытие списка заказов перевозчика
"""

import contextlib
from typing import Any

from aiogram import F, Router
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message

from ....config import settings
from ....db import db_manager
from ....db.repositories import AvanpostActionRepository, AvanpostUserRepository, UserRepository
from ....logger import bot_logger
from ....models import MessageActionType, MessageType
from ....utils.decorators import log_exceptions
from ...dependencies import get_bot_manager
from .auth import _auth_cache, get_user_group_id, is_user_authenticated
from .common import back_to_users, show_menu
from .lists.chat_details import show_chat_details
from .states import ActionStates, ChatDetailsStates, SubMenuStates

# Создание роутера для действий
router = Router(name="aiogram_actions")

# Репозитории для работы с данными
_actions_repo = AvanpostActionRepository()
_avanpost_user_repo = AvanpostUserRepository()
_user_repo = UserRepository()

# Константы из настроек
BUTTONS_PER_ROW = getattr(settings, "KEYBOARD_BUTTONS_PER_ROW", 3)


def _get_chat_id(event: Message | CallbackQuery) -> int:
    """
    Получение ID чата из события.

    Args:
        event: Сообщение или CallbackQuery

    Returns:
        int: ID чата
    """
    if isinstance(event, Message):
        chat_id = event.chat.id
        return int(chat_id) if chat_id is not None else 0
    if isinstance(event, CallbackQuery) and event.message:
        chat_id = event.message.chat.id
        return int(chat_id) if chat_id is not None else 0
    return 0


# ============ КОМАНДА /actions ============


@router.message(Command("actions"))
@log_exceptions(bot_logger)
async def cmd_actions(message: Message, state: FSMContext) -> None:
    """
    Команда для вызова меню действий.

    Открывает меню действий для текущего пользователя или
    для выбранного через /users пользователя.

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

    async with db_manager.get_session() as session:
        await _cmd_actions_impl(message, state, session, user_id)


async def _cmd_actions_impl(
    message: Message,
    state: FSMContext,
    session: Any,
    user_id: int,
) -> None:
    """
    Реализация команды /actions с переданной сессией.

    Args:
        message: Сообщение от пользователя
        state: Состояние FSM
        session: Сессия БД
        user_id: ID пользователя Telegram
    """
    bot_manager = get_bot_manager()

    # Получение данных о выбранном пользователе
    state_data = await state.get_data()
    selected_user_id = state_data.get("selected_user_id")
    selected_user_name = state_data.get("selected_user_name")

    # Если выбран конкретный пользователь через /users
    if selected_user_id and selected_user_id != user_id:
        user_id = selected_user_id
        bot_logger.debug(f"✅ Using selected user ID from state: {user_id} ({selected_user_name})")

        # Проверка наличия пользователя в Avanpost
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

        # Сохранение данных в состоянии
        is_admin = user_id in settings.ADMIN_IDS
        await state.update_data(
            user_id=user_id,
            is_admin=is_admin,
            selected_user_id=user_id,
            selected_user_name=selected_user_name,
        )

        # Получение группы действий пользователя
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

        # Показ меню для выбранного пользователя
        await state.set_state(ActionStates.viewing_menu)
        await bot_manager.delete_message_by_link(message)
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
    # Проверка авторизации
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

    # Получение группы действий пользователя
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

    # Показ меню для текущего пользователя
    await state.set_state(ActionStates.viewing_menu)
    await bot_manager.delete_message_by_link(message)
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
    Обработка колбэков действий через универсальный обработчик.

    Обрабатывает все колбэки меню действий:
    - action_<id>: Выбор действия
    - action_back_<id>: Возврат на уровень назад
    - action_home: Возврат в главное меню
    - back_to_users: Возврат к списку пользователей

    Args:
        callback: CallbackQuery от пользователя
        state: Состояние FSM
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

    # Обработка специального колбэка "назад к пользователям"
    if callback_data == "back_to_users":
        await back_to_users(callback, state)
        return

    # Получение группы действий для пользователя
    async with db_manager.get_session() as session:
        state_data = await state.get_data()
        selected_user_id = state_data.get("selected_user_id")
        selected_user_name = state_data.get("selected_user_name")

        # Определение group_id
        group_id = await _get_group_id_for_user(telegram_user_id, selected_user_id, session)

        if not group_id:
            await bot_manager.send_toast(
                text="❌ Не удалось определить группу действий.",
                event=callback,
            )
            return

        # Сохранение в состоянии
        await state.update_data(group_id=group_id)

        # Использование универсального обработчика
        from ...callbacks import action_callback_handler

        # Подготовка данных для обработчика
        await action_callback_handler.handle(
            callback=callback,
            state=state,
            session=session,
            group_id=group_id,
            user_display_name=selected_user_name,
        )


async def _get_group_id_for_user(
    telegram_user_id: int,
    selected_user_id: int | None,
    session: Any,
) -> int | None:
    """
    Получение group_id для пользователя.

    Args:
        telegram_user_id: ID пользователя в Telegram
        selected_user_id: ID выбранного пользователя (опционально)
        session: Сессия БД

    Returns:
        int | None: ID группы действий или None
    """
    # Если выбран конкретный пользователь
    if selected_user_id:
        # Получение из кеша
        cache_data = _auth_cache.get(telegram_user_id)
        if cache_data:
            group_id_raw = cache_data.get("group_id")
            if group_id_raw is not None:
                return int(group_id_raw) if isinstance(group_id_raw, int) else None

        # Получение из БД
        avanpost_user_data = await UserRepository.get_avanpost_user_data(session, selected_user_id)
        if avanpost_user_data:
            group_id_raw = avanpost_user_data.get("FK_MenuGroup")
            if group_id_raw is not None:
                return int(group_id_raw) if isinstance(group_id_raw, int) else None

    # Для текущего пользователя
    return await get_user_group_id(telegram_user_id)


# ============ ВЫПОЛНЕНИЕ ДЕЙСТВИЯ ============


async def execute_action(callback: CallbackQuery, action_id: int, state: FSMContext) -> None:
    """
    Выполнение действия при выборе конечного пункта меню.

    Определяет тип действия по FK_Type и вызывает соответствующий обработчик.

    Args:
        callback: CallbackQuery от пользователя
        action_id: ID выбранного действия
        state: Состояние FSM
    """
    bot_manager = get_bot_manager()
    bot_logger.info(f"🎯 [execute_action] START: action_id={action_id}")

    try:
        # Получение данных из состояния
        state_data = await state.get_data()
        await state.update_data(parent_item_id=action_id)

        group_id = state_data.get("group_id")
        selected_user_id = state_data.get("selected_user_id")

        if selected_user_id:
            group_id = await get_user_group_id(selected_user_id)

        if not group_id:
            group_id = await get_user_group_id(callback.from_user.id)

        if not group_id:
            await bot_manager.send_toast(text="❌ Не удалось определить группу действий", event=callback)
            return

        # Получение информации о действии
        async with db_manager.get_session("main") as session:
            action_info = await AvanpostActionRepository.get_action_info_with_names(
                action_id=action_id,
                session=session,
            )

            if not action_info:
                await bot_manager.send_toast(
                    text=f"❌ Информация о действии #{action_id} не найдена.",
                    event=callback,
                )
                return

            fk_type = action_info["fk_type"]
            scenario_fid = action_info["scenario_fid"]
            type_name = action_info["type_name"]
            scenario_name = action_info["scenario_name"]

            # Обработка типа 11 (Открытие списка заказов перевозчика)
            if fk_type == 11:
                await _handle_open_orders(
                    callback=callback, bot_manager=bot_manager, action_id=action_id, state=state, order_type="carrier"
                )
                return

            # Обработка по типу действия
            await _handle_action_by_type(
                fk_type=fk_type,
                scenario_fid=scenario_fid,
                action_id=action_id,
                type_name=type_name,
                scenario_name=scenario_name,
                callback=callback,
                bot_manager=bot_manager,
                state=state,
            )

    except Exception as e:
        bot_logger.error(f"❌ [execute_action] Failed: {e}", exc_info=True)
        with contextlib.suppress(Exception):
            await bot_manager.send_toast(
                text="❌ Ошибка выполнения действия. Попробуйте позже.",
                event=callback,
            )


# ============ ОБРАБОТЧИКИ ПО ТИПАМ ДЕЙСТВИЙ ============


async def _handle_action_by_type(
    fk_type: int,
    scenario_fid: int,
    action_id: int,
    type_name: str,
    scenario_name: str,
    callback: CallbackQuery,
    bot_manager: Any,
    state: FSMContext,
) -> None:
    """
    Обработка действия на основе его типа (FK_Type).

    Группировка по FK_Type:
        1 - Отправка данных на сервер
        2 - Открытие файла
        4 - Открытие маршрута перевозки
        5 - Открытие точки маршрута перевозки
        6 - Открытие списка контактов
        7 - Открытие контактной информации
        8 - Открытие списка заказов заказчика
        9 - Открытие списка чатов
        10 - Открытие списка транспорта
        11 - Открытие списка заказов перевозчика

    Args:
        fk_type: Тип действия
        scenario_fid: ID сценария (для типа 1)
        action_id: ID действия
        type_name: Название типа
        scenario_name: Название сценария
        callback: CallbackQuery от пользователя
        bot_manager: Экземпляр BotManager
        state: Состояние FSM
    """
    if fk_type == 1:
        await _handle_send_data(
            scenario_fid=scenario_fid,
            scenario_name=scenario_name,
            action_id=action_id,
            callback=callback,
            bot_manager=bot_manager,
        )
    elif fk_type == 2:
        await bot_manager.send_toast(
            text=f"📂 Открытие файла. Действие #{action_id}",
            event=callback,
        )
    elif fk_type == 4:
        await bot_manager.send_toast(
            text=f"🗺️ Открытие маршрута перевозки. Действие #{action_id}",
            event=callback,
        )
    elif fk_type == 5:
        await bot_manager.send_toast(
            text=f"📍 Открытие точки маршрута. Действие #{action_id}",
            event=callback,
        )
    elif fk_type == 6:
        await bot_manager.send_toast(
            text=f"👥 Открытие списка контактов. Действие #{action_id}",
            event=callback,
        )
    elif fk_type == 7:
        await bot_manager.send_toast(
            text=f"ℹ️ Открытие контактной информации. Действие #{action_id}",
            event=callback,
        )
    elif fk_type == 8:
        await _handle_open_orders(callback, bot_manager, action_id, state, order_type="customer")
    elif fk_type == 9:
        await _handle_open_chats(callback, bot_manager, action_id, state)
    elif fk_type == 10:
        await _handle_open_vehicles(callback, bot_manager, action_id, state)
    elif fk_type == 11:
        await _handle_open_orders(callback, bot_manager, action_id, state, order_type="carrier")
    else:
        await bot_manager.send_toast(
            text=f"🚧 Неизвестный тип действия: {type_name} (ID: {fk_type})",
            event=callback,
        )


# ============ ОБРАБОТЧИК: ОТКРЫТИЕ ЗАКАЗОВ ============


async def _handle_open_orders(
    callback: CallbackQuery,
    bot_manager: Any,
    action_id: int,
    state: FSMContext,
    order_type: str = "customer",
) -> None:
    """
    Обработчик открытия списка заказов.

    Args:
        callback: CallbackQuery от пользователя
        bot_manager: Экземпляр BotManager
        action_id: ID действия
        state: Состояние FSM
        order_type: "customer" - заказы заказчика (FK_Type=8)
                   "carrier"  - заказы перевозчика (FK_Type=11)
    """
    if order_type == "customer":
        await bot_manager.send_toast(text="📋 Загрузка списка заказов заказчика...", event=callback)
    else:
        await bot_manager.send_toast(text="🚚 Загрузка списка заказов перевозчика...", event=callback)

    try:
        state_data = await state.get_data()
        avanpost_user_id = state_data.get("user_id") or state_data.get("selected_user_id")

        if not avanpost_user_id:
            await bot_manager.send_toast(text="❌ Не удалось определить пользователя.", event=callback)
            return

        # Установка состояния
        from .states import CarrierOrderStates

        await state.set_state(CarrierOrderStates.viewing_orders)
        await state.update_data(
            orders_page=0,
            orders_search_query=None,
            parent_item_id=action_id,
            avanpost_user_id=avanpost_user_id,
            orders_type=order_type,
        )

        if order_type == "customer":
            # Заказы заказчика
            from .lists.orders import show_orders_list

            await show_orders_list(
                event=callback,
                state=state,
                avanpost_user_id=avanpost_user_id,
                page=0,
            )
        else:
            # Заказы перевозчика
            from .lists.carrier_orders import show_carrier_orders_list

            await show_carrier_orders_list(
                event=callback,
                state=state,
                avanpost_user_id=avanpost_user_id,
                page=0,
            )

    except Exception as e:
        bot_logger.error(f"❌ Failed to load orders ({order_type}): {e}", exc_info=True)
        await bot_manager.send_toast(text=f"❌ Ошибка загрузки заказов: {str(e)[:100]}", event=callback)


# ============ ОБРАБОТЧИК: ОТКРЫТИЕ ЧАТОВ ============


async def _handle_open_chats(
    callback: CallbackQuery,
    bot_manager: Any,
    action_id: int,
    state: FSMContext,
) -> None:
    """
    Обработчик: Открытие списка чатов (FK_Type=9).

    Args:
        callback: CallbackQuery от пользователя
        bot_manager: Экземпляр BotManager
        action_id: ID действия
        state: Состояние FSM
    """
    await bot_manager.send_toast(text="💬 Загрузка списка чатов...", event=callback)

    try:
        state_data = await state.get_data()
        avanpost_user_id = state_data.get("user_id") or state_data.get("selected_user_id")

        if not avanpost_user_id:
            await bot_manager.send_toast(text="❌ Не удалось определить пользователя.", event=callback)
            return

        # Добавление текущего пункта в историю
        history = state_data.get("menu_history", [])
        history.append(action_id)
        await state.update_data(menu_history=history)

        await state.set_state(SubMenuStates.viewing_chats)
        await state.update_data(
            chats_page=0,
            chats_search_query=None,
            parent_item_id=action_id,
            avanpost_user_id=avanpost_user_id,
        )

        from .lists.chats import show_chats_list

        await show_chats_list(
            event=callback,
            state=state,
            avanpost_user_id=avanpost_user_id,
            page=0,
        )

    except Exception as e:
        bot_logger.error(f"❌ Failed to load chats: {e}", exc_info=True)
        await bot_manager.send_toast(text=f"❌ Ошибка загрузки чатов: {str(e)[:100]}", event=callback)


# ============ ОБРАБОТЧИК: ОТКРЫТИЕ ТРАНСПОРТА ============


async def _handle_open_vehicles(
    callback: CallbackQuery,
    bot_manager: Any,
    action_id: int,
    state: FSMContext,
) -> None:
    """
    Обработчик: Открытие списка транспорта (FK_Type=10).

    Args:
        callback: CallbackQuery от пользователя
        bot_manager: Экземпляр BotManager
        action_id: ID действия
        state: Состояние FSM
    """
    await bot_manager.send_toast(text="🚗 Загрузка списка транспорта...", event=callback)

    try:
        state_data = await state.get_data()
        avanpost_user_id = state_data.get("user_id") or state_data.get("selected_user_id")

        if not avanpost_user_id:
            await bot_manager.send_toast(text="❌ Не удалось определить пользователя.", event=callback)
            return

        await state.set_state(SubMenuStates.viewing_vehicles)
        await state.update_data(
            vehicles_page=0,
            vehicles_search_query=None,
            parent_item_id=action_id,
            avanpost_user_id=avanpost_user_id,
        )

        from .lists.vehicles import show_vehicles_list

        await show_vehicles_list(
            event=callback,
            state=state,
            avanpost_user_id=avanpost_user_id,
            page=0,
        )

    except Exception as e:
        bot_logger.error(f"❌ Failed to load vehicles: {e}", exc_info=True)
        await bot_manager.send_toast(text=f"❌ Ошибка загрузки транспорта: {str(e)[:100]}", event=callback)


# ============ ОБРАБОТЧИК: ОТПРАВКА ДАННЫХ ============


async def _handle_send_data(
    scenario_fid: int,
    scenario_name: str,
    action_id: int,
    callback: CallbackQuery,
    bot_manager: Any,
) -> None:
    """
    Обработка действий типа "Отправка данных на сервер" (FK_Type=1).

    Args:
        scenario_fid: ID сценария
        scenario_name: Название сценария
        action_id: ID действия
        callback: CallbackQuery от пользователя
        bot_manager: Экземпляр BotManager
    """
    scenario_handlers = {
        1: "📤 Отправка данных (по умолчанию)",
        6: "📍 Отправка местоположения",
        7: "⛽ Отправка данных о заправке",
        8: "💰 Отправка данных о расходах",
        10: "✏️ Ввод данных вручную",
        11: "⏱️ Отправка данных сейчас",
        12: "📦 Загрузка груза (общее)",
        13: "🌡️ Загрузка груза (температура)",
        14: "📄 Загрузка груза (документы)",
        15: "⚠️ Разгрузка груза (проблема с грузом)",
        16: "📄 Разгрузка груза (документы)",
        17: "🚗 Прием авто и ТМЦ",
    }

    handler = scenario_handlers.get(scenario_fid)
    if handler:
        await bot_manager.send_toast(
            text=f"{handler}. Действие #{action_id}",
            event=callback,
        )
    else:
        await bot_manager.send_toast(
            text=f"🚧 Отправка данных: {scenario_name} (Сценарий {scenario_fid})",
            event=callback,
        )


# ============ ОБРАБОТЧИК ДЛЯ ВЫБОРА ЧАТА (ОТКРЫТИЕ СООБЩЕНИЙ) ============


@router.callback_query(F.data.startswith("chat_select_"))
@log_exceptions(bot_logger)
async def handle_chat_selection(callback: CallbackQuery, state: FSMContext) -> None:
    """
    Обработка выбора чата для просмотра сообщений.

    Args:
        callback: CallbackQuery от пользователя
        state: Состояние FSM
    """
    bot_manager = get_bot_manager()
    await bot_manager.send_toast(text="💬 Загрузка сообщений чата...", event=callback)

    try:
        # Извлечение ID чата из callback_data
        chat_id = int(callback.data.split("_")[-1])

        state_data = await state.get_data()
        avanpost_user_id = (
            state_data.get("avanpost_user_id") or state_data.get("user_id") or state_data.get("selected_user_id")
        )
        parent_item_id = state_data.get("parent_item_id")

        if not avanpost_user_id:
            await bot_manager.send_toast(text="❌ Не удалось определить пользователя.", event=callback)
            return

        # Сохранение в состояние
        await state.update_data(
            selected_chat_id=chat_id,
            chat_details_page=0,
            parent_item_id=parent_item_id,
        )
        await state.set_state(ChatDetailsStates.viewing_messages)

        # Показ сообщений чата
        await show_chat_details(
            event=callback,
            state=state,
            avanpost_user_id=avanpost_user_id,
            chat_id=chat_id,
            page=0,
        )

    except ValueError as e:
        bot_logger.error(f"❌ Invalid chat ID in callback: {callback.data}, error: {e}")
        await bot_manager.send_toast(text="❌ Неверный ID чата.", event=callback)
    except Exception as e:
        bot_logger.error(f"❌ Failed to load chat messages: {e}", exc_info=True)
        await bot_manager.send_toast(text=f"❌ Ошибка загрузки сообщений: {str(e)[:100]}", event=callback)


__all__ = [
    "router",
    "ActionStates",
    "cmd_actions",
    "execute_action",
    "show_menu",
]
