import contextlib
from typing import TYPE_CHECKING, Any

from aiogram import F, Router
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, Message
from sqlalchemy import text

from ....config import settings
from ....db import AvanpostRepository, db_manager
from ....exceptions import log_exceptions
from ....logger import tg_logger
from ....models import ErrorCategory, MessageActionType, MessageType
from ....services import error_service
from ...keyboards import ActionKeyboard
from .auth import get_user_group_id, is_user_authenticated

if TYPE_CHECKING:
    from ....tg import TelegramManager

router = Router(name="aiogram_actions")


class ActionStates(StatesGroup):
    """Состояния для работы с действиями"""

    viewing_menu = State()


def get_tg_manager() -> "TelegramManager":
    """Получение глобального tg_manager"""
    from ....tg import tg_manager

    return tg_manager


# ============ ФУНКЦИИ ДЛЯ РАБОТЫ С БД ============


async def create_chat_actions_table() -> None:
    """Создание таблицы для хранения сообщений бота (если не существует)"""
    try:
        async with db_manager.get_session() as session:
            from sqlalchemy import text

            try:
                await session.execute(text("SELECT 1 FROM TChatsActions LIMIT 1"))
                tg_logger.debug("ℹ️ Table TChatsActions already exists")
            except Exception:
                from ....models import BaseModel

                await session.run_sync(BaseModel.metadata.create_all)
                tg_logger.info("✅ Table TChatsActions created successfully")
    except Exception as e:
        tg_logger.error(f"❌ Failed to create TChatsActions table: {e}", exc_info=True)


# ============ ОБРАБОТЧИКИ ============


@router.message(Command("actions"))
@log_exceptions(tg_logger)
async def cmd_actions(message: Message, state: FSMContext) -> None:
    """Команда для вызова меню действий"""
    tg_manager = get_tg_manager()

    if not await is_user_authenticated(message.from_user.id):
        await tg_manager.send_answer(
            text="🔐 **Требуется авторизация**\n\nДля доступа к действиям необходимо авторизоваться.\nИспользуйте /start для начала авторизации.",
            event=message,
            message_type=MessageType.COMMAND_ACTION_INFO,
            delete_by_type=MessageActionType.COMMAND_ACTION_CLEANUP,
            parse_mode="Markdown",
        )
        return

    group_id = await get_user_group_id(message.from_user.id)

    if not group_id:
        await tg_manager.send_answer(
            text="❌ **Группа действий не найдена**\n\nУ вас не назначена группа действий в системе.\nОбратитесь к администратору для настройки прав.",
            event=message,
            message_type=MessageType.COMMAND_ACTION_INFO,
            delete_by_type=MessageActionType.COMMAND_ACTION_CLEANUP,
            parse_mode="Markdown",
        )
        return

    await state.set_state(ActionStates.viewing_menu)

    await tg_manager.delete_message_by_link(message)

    # Очищаем историю при входе в меню
    await state.update_data(menu_history=[])

    await show_menu(event=message, group_id=group_id, state=state, is_new=True)


# ============ ОБРАБОТЧИКИ КОЛБЭКОВ ============


@router.callback_query(
    F.data.startswith("action_")
    | F.data.startswith("action_back_")
    | (F.data == "action_home")
    | (F.data == "back_to_groups")
)
@log_exceptions(tg_logger)
async def handle_action_callback(callback: CallbackQuery, state: FSMContext) -> None:
    """Обработка колбэков действий"""
    tg_manager = get_tg_manager()

    user_id = callback.from_user.id

    tg_logger.debug(f"✅ Callback from REAL user: {user_id}")
    tg_logger.debug(f"✅ Callback data: {callback.data}")

    await state.update_data(user_id=user_id, is_admin=user_id in settings.ADMIN_IDS)

    # Обработка выбора действия (не "Назад" и не "В главное меню")
    if callback.data.startswith("action_") and not callback.data.startswith("action_back_"):
        try:
            action_id = int(callback.data.split("_")[1])

            group_id = await get_user_group_id(user_id)
            if group_id:
                has_children = await check_has_subitems(group_id, action_id)

                if has_children:
                    await tg_manager.send_toast(event=callback)

                    # Сохраняем историю переходов
                    state_data = await state.get_data()
                    history = state_data.get("menu_history", [])
                    history.append(action_id)
                    await state.update_data(menu_history=history)
                    tg_logger.debug(f"📜 Added {action_id} to history: {history}")

                    await show_menu(
                        event=callback,
                        group_id=group_id,
                        parent_item_id=action_id,
                        state=state,
                        is_callback=True,
                    )
                else:
                    await execute_action(callback=callback, action_id=action_id, state=state)
            return
        except (ValueError, IndexError):
            tg_logger.warning(f"⚠️ Invalid action ID in callback: {callback.data}")

    # Обработка остальных колбэков (action_back_, action_home, back_to_groups)
    from ...callbacks import action_callback_handler

    await action_callback_handler.handle(callback, state)


# ============ ФУНКЦИЯ SHOW_MENU ============


@log_exceptions(tg_logger)
async def show_menu(
    *,
    event: Message | CallbackQuery,
    group_id: int,
    state: FSMContext,
    parent_item_id: int | None = None,
    is_callback: bool = False,
    is_new: bool = False,
) -> None:
    """
    Отображение меню действий с горизонтальным расположением кнопок.

    Args:
        event: Message или CallbackQuery объект
        group_id: ID группы действий
        parent_item_id: ID родительского элемента (None для корневого меню)
        state: FSM состояние
        is_callback: Вызвано из callback или из message
        is_new: Отправлять новое сообщение или редактировать существующее
    """
    tg_manager = get_tg_manager()

    user_id = None
    is_admin = False

    try:
        state_data = await state.get_data()
        user_id = state_data.get("user_id")

        if user_id:
            tg_logger.debug(f"✅ Using user_id from state: {user_id}")
            is_admin = state_data.get("is_admin", user_id in settings.ADMIN_IDS)
        else:
            if isinstance(event, CallbackQuery):
                # Для CallbackQuery - ВСЕГДА берем from_user у callback
                user_id = event.from_user.id
                tg_logger.debug(f"✅ Callback from user: {user_id}")
                tg_logger.debug(f"✅ Callback data: {event.data}")
                is_callback = True

            elif isinstance(event, Message):
                # Для обычного сообщения
                if event.from_user:
                    # Проверяем, не бот ли это
                    if not event.from_user.is_bot:
                        # Реальный пользователь отправил сообщение
                        user_id = event.from_user.id
                        tg_logger.debug(f"✅ Message from user: {user_id}")
                    else:
                        # Сообщение от бота - ищем реального пользователя
                        tg_logger.debug("⚠️ Message from bot, trying to find real user...")

                        # 1. Проверяем reply_to_message
                        if event.reply_to_message and event.reply_to_message.from_user:
                            user_id = event.reply_to_message.from_user.id
                            tg_logger.debug(f"✅ Found user from reply: {user_id}")

                        # 2. Проверяем forward_from
                        elif event.forward_from:
                            user_id = event.forward_from.id
                            tg_logger.debug(f"✅ Found user from forward: {user_id}")

                        # 3. Проверяем sender_chat (для каналов)
                        elif event.sender_chat:
                            user_id = event.sender_chat.id
                            tg_logger.debug(f"✅ Found user from sender_chat: {user_id}")

            # Если удалось определить пользователя - сохраняем в состояние
            if user_id:
                is_admin = user_id in settings.ADMIN_IDS
                await state.update_data(user_id=user_id, is_admin=is_admin, last_activity="show_menu")
                tg_logger.debug(f"✅ Saved user {user_id} to state")

        # Если не удалось определить пользователя - ошибка
        if not user_id:
            error_msg = "❌ Не удалось определить пользователя"
            tg_logger.error(error_msg)
            await tg_manager.send_toast(text=error_msg, event=event)
            return

        # Проверка прав администратора
        is_admin = user_id in settings.ADMIN_IDS
        tg_logger.debug(f"🔍 User ID: {user_id}")
        tg_logger.debug(f"🔍 Is admin: {is_admin}")
        tg_logger.debug(f"🔍 Admin list: {settings.ADMIN_IDS}")

        # Получение меню из БД
        menu_data = await get_menu_items_with_parent(group_id, parent_item_id)
        menu_items = menu_data.get("items", [])
        parent_name = menu_data.get("parent_name")
        parent_id = menu_data.get("parent_id")

        tg_logger.debug(f"📊 Menu items count: {len(menu_items)}, parent: {parent_name} (ID: {parent_id})")
        tg_logger.debug(f"📊 First item: {menu_items[0] if menu_items else 'None'}")

        # Формирование текста
        if not menu_items:
            empty_text = "📋 Нет доступных действий."

            if is_callback and isinstance(event, CallbackQuery):
                await tg_manager.delete_message_by_link(event.message)
                await tg_manager.send_message(
                    chat_id=event.message.chat.id,
                    text=empty_text,
                    message_type=MessageType.COMMAND_ACTION_INFO,
                    delete_by_type=MessageActionType.COMMAND_ACTION_CLEANUP,
                    parse_mode="Markdown",
                )
            else:
                await tg_manager.send_message(
                    chat_id=event.chat.id,
                    text=empty_text,
                    message_type=MessageType.COMMAND_ACTION_INFO,
                    delete_by_type=MessageActionType.COMMAND_ACTION_CLEANUP,
                    parse_mode="Markdown",
                )
            return

        # Формирование текста с красивым оформлением
        header_text = "✨ 📋 **МЕНЮ ДЕЙСТВИЙ**"

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
            items=menu_items, parent_id=parent_id, is_admin=is_admin, is_root_menu=(parent_item_id is None)
        )

        # Для callback ВСЕГДА удаляем и отправляем новое
        if is_callback and isinstance(event, CallbackQuery):
            # Удаляем старое сообщение
            try:
                await tg_manager.delete_message_by_link(event.message)
                tg_logger.debug(f"🗑️ Deleted old message {event.message.message_id}")
            except Exception as e:
                tg_logger.warning(f"⚠️ Failed to delete old message: {e}")

            # Отправляем новое сообщение
            result = await tg_manager.send_message(
                chat_id=event.message.chat.id,
                text=header_text,
                message_type=MessageType.COMMAND_ACTION,
                delete_by_type=MessageActionType.COMMAND_ACTION_CLEANUP,
                parse_mode="Markdown",
                reply_markup=keyboard,
            )

            if result.get("success"):
                await state.update_data(last_action_message_id=result.get("message_id"))
                tg_logger.debug(f"✅ Sent new message {result.get('message_id')}")

        else:
            # Для обычных сообщений (не callback) - отправляем как обычно
            await tg_manager.send_message(
                chat_id=event.chat.id,
                text=header_text,
                message_type=MessageType.COMMAND_ACTION,
                delete_by_type=MessageActionType.COMMAND_ACTION_CLEANUP,
                parse_mode="Markdown",
                reply_markup=keyboard,
            )

    except Exception as e:
        if "message is not modified" not in str(e):
            tg_logger.error(f"❌ Failed to show menu: {e}", exc_info=True)

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
                    await tg_manager.delete_message_by_link(event.message)
                    await tg_manager.send_message(
                        chat_id=event.message.chat.id,
                        text=error_text,
                        message_type=MessageType.COMMAND_ACTION_INFO,
                        delete_by_type=MessageActionType.COMMAND_ACTION_CLEANUP,
                        parse_mode="Markdown",
                    )
            else:
                with contextlib.suppress(Exception):
                    await tg_manager.send_message(
                        chat_id=event.chat.id,
                        text=error_text,
                        message_type=MessageType.COMMAND_ACTION_INFO,
                        delete_by_type=MessageActionType.COMMAND_ACTION_CLEANUP,
                        parse_mode="Markdown",
                    )


# ============ ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ ============


async def check_has_subitems(group_id: int, item_id: int) -> bool:
    """Проверка, есть ли у пункта дочерние элементы"""
    try:
        async with db_manager.get_session("avanpost") as session:
            sql = """
                EXEC ext.PA_avp_RSAppScenariosGroupsItems_Load
                    @GroupID = :group_id,
                    @ParentItemID = :item_id
            """

            result = await session.execute(text(sql), {"group_id": group_id, "item_id": item_id})

            rows = result.fetchall()
            return len(rows) > 0

    except Exception as e:
        tg_logger.error(f"❌ Failed to check subitems: {e}", exc_info=True)
        return False


async def execute_action(callback: CallbackQuery, action_id: int, state: FSMContext) -> None:
    """
    Выполнение действия при выборе конечного пункта меню.
    Показывает Toast (уведомление вверху экрана) вместо всплывающего окна.
    """
    tg_manager = get_tg_manager()
    try:
        # Получаем информацию о действии из БД
        action_info = None
        try:
            async with db_manager.get_session("avanpost") as session:
                # Получаем все пункты меню для группы
                # Используем group_id=1 или получаем из состояния
                group_id = 1  # TODO: Получать из контекста пользователя

                items = await AvanpostRepository.get_menu_items(
                    session=session,
                    group_id=group_id,
                    parent_item_id=None,  # Получаем все пункты корневого меню
                )

                # Ищем нужное действие
                for item in items:
                    if item.get("id") == action_id:
                        action_info = item
                        break

        except Exception as e:
            tg_logger.warning(f"⚠️ Could not get action info: {e}")

        # Формируем текст Toast
        if action_info:
            action_name = action_info.get("name", "Без названия")
            toast_text = f"🚧️ {action_name}. Функционал в разработке..."
        else:
            toast_text = f"🚧 Действие #{action_id}. Функционал в разработке..."

        await tg_manager.send_toast(text=toast_text[:200], event=callback)
        tg_logger.debug(f"✅ Toast shown for action {action_id}: {toast_text}")

    except Exception as e:
        tg_logger.error(f"❌ Failed to execute action: {e}", exc_info=True)
        with contextlib.suppress(Exception):
            await tg_manager.send_toast(text="❌ Ошибка выполнения")


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
        tg_logger.error(f"❌ Failed to get menu items with parent: {e}", exc_info=True)
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

    tg_logger.info("🔄 Starting cleanup scheduler for bot messages")

    while True:
        try:
            await asyncio.sleep(60)
        except asyncio.CancelledError:
            tg_logger.info("⏹️ Cleanup scheduler stopped")
            break
        except Exception as e:
            tg_logger.error(f"❌ Cleanup scheduler error: {e}", exc_info=True)
            await asyncio.sleep(60)


# ============ ЭКСПОРТ ФУНКЦИЙ ============

__all__ = [
    "router",
    "start_cleanup_scheduler",
    "show_menu",
    "cmd_actions",
    "check_has_subitems",
    "execute_action",
    "get_menu_items_with_parent",
    "get_menu_items",
]
