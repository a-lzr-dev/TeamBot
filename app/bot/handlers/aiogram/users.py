import contextlib
from typing import Any

from aiogram import F, Router
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, Message

from ....bot.dependencies import get_bot_manager
from ....config import settings
from ....db import UserRepository, db_manager
from ....exceptions import log_exceptions
from ....logger import bot_logger
from ....models import ErrorCategory, MessageActionType, MessageType
from ....services import error_service
from ...callbacks import users_callback_handler
from ...keyboards import UserKeyboard
from .auth import _auth_cache, is_user_authenticated

router = Router(name="aiogram_users")


class UserStates(StatesGroup):
    """Состояния для работы с пользователями"""

    viewing_users = State()


@router.message(Command("users"))
@log_exceptions(bot_logger)
async def cmd_users(message: Message, state: FSMContext) -> None:
    """Команда для вызова списка пользователей"""
    bot_manager = get_bot_manager()

    # Проверка прав администратора
    if not message.from_user or message.from_user.id not in settings.ADMIN_IDS:
        await bot_manager.send_answer(
            text="⛔ У вас нет прав для этой команды.",
            event=message,
            message_type=MessageType.COMMAND_ACTION_INFO,
            delete_by_type=MessageActionType.COMMAND_ACTION_CLEANUP,
        )
        return

    # Проверка авторизации
    if not await is_user_authenticated(message.from_user.id):
        await bot_manager.send_answer(
            text="🔐 **Требуется авторизация**\n\n"
            "Для доступа к списку пользователей необходимо авторизоваться.\n"
            "Используйте /start для начала авторизации.",
            event=message,
            message_type=MessageType.COMMAND_ACTION_INFO,
            delete_by_type=MessageActionType.COMMAND_ACTION_CLEANUP,
        )
        return

    await state.set_state(UserStates.viewing_users)

    # Удаление сообщения с командой
    await bot_manager.delete_message_by_link(message)

    # Очищаем состояние перед показом списка
    await _clear_user_selection(state)

    # Отображение списка пользователей (страница 0)
    await show_users(event=message, state=state, page=0)


# ============================================================
# ВСПОМОГАТЕЛЬНАЯ ФУНКЦИЯ ДЛЯ ОЧИСТКИ СОСТОЯНИЯ
# ============================================================


async def _clear_user_selection(state: FSMContext) -> None:
    """Очистка состояния от выбранного пользователя"""
    await state.update_data(
        selected_user_id=None,
        selected_user_name=None,
        selected_user_group_id=None,
        use_group_id=None,
        user_id=None,
        menu_history=[],
        is_admin=False,
    )
    bot_logger.debug("🧹 User selection cleared from state")


# ============================================================
# ОБРАБОТЧИКИ КОЛБЭКОВ
# ============================================================


@router.callback_query(F.data.startswith("users_"))
@log_exceptions(bot_logger)
async def handle_users_callback(callback: CallbackQuery, state: FSMContext) -> None:
    """
    Обработка колбэков списка пользователей.
    Делегирует логику в UsersCallbackHandler.
    """
    await users_callback_handler.handle(callback, state)


# ============================================================
# ФУНКЦИИ ДЛЯ РАБОТЫ С ПОЛЬЗОВАТЕЛЯМИ
# ============================================================


async def get_users_page(page: int = 0, page_size: int = 10) -> dict[str, Any]:
    """
    Получение списка пользователей с пагинацией.

    Args:
        page: Номер страницы (начиная с 0)
        page_size: Количество пользователей на странице

    Returns:
        dict: {
            "users": list[dict],
            "total": int,
            "page": int,
            "total_pages": int,
            "has_prev": bool,
            "has_next": bool
        }
    """
    try:
        async with db_manager.get_session() as session:
            # Получение всех пользователей Avanpost
            users = await UserRepository.get_all_avanpost_users(
                session=session,
                limit=page_size,
                offset=page * page_size,
            )

            # Получение общего количества пользователей
            from sqlalchemy import func, select

            from app.models import AvanpostUserModel

            total_result = await session.execute(select(func.count()).select_from(AvanpostUserModel))
            total = total_result.scalar() or 0

            total_pages = (total + page_size - 1) // page_size

            # Форматирование пользователей
            users_data = []
            for user in users:
                # Попытка найти Telegram пользователя
                telegram_user = None
                if user.fk_user:
                    telegram_user = await UserRepository.get_user_by_id(session, user.fk_user)

                users_data.append(
                    {
                        "id": user.FID,
                        "name": user.FName or f"User #{user.FID}",
                        "phone": user.FPhone or "Не указан",
                        "group_id": user.FK_MenuGroup,
                        "telegram_id": user.fk_user,
                        "telegram_name": telegram_user.fullname if telegram_user else None,
                        "is_authorized": user.fk_user is not None,
                    }
                )

            return {
                "users": users_data,
                "total": total,
                "page": page,
                "total_pages": total_pages,
                "has_prev": page > 0,
                "has_next": page < total_pages - 1,
            }

    except Exception as e:
        bot_logger.error(f"❌ Failed to get users: {e}", exc_info=True)
        return {
            "users": [],
            "total": 0,
            "page": 0,
            "total_pages": 0,
            "has_prev": False,
            "has_next": False,
            "error": str(e),
        }


async def show_users(
    event: Message | CallbackQuery,
    state: FSMContext,
    page: int = 0,
) -> None:
    """
    Отображение списка пользователей с пагинацией.

    Args:
        event: Message или CallbackQuery объект
        state: FSM состояние
        page: Номер страницы (начиная с 0)
    """
    bot_manager = get_bot_manager()

    # Ответ на callback, чтобы убрать "часики"
    if isinstance(event, CallbackQuery):
        await event.answer()

    try:
        # Получение данных
        data = await get_users_page(page)

        if data.get("error"):
            error_text = f"❌ Ошибка загрузки пользователей: {data['error']}"
            if isinstance(event, CallbackQuery):
                await bot_manager.edit_callback_message(
                    text=error_text,
                    callback=event,
                    parse_mode="Markdown",
                )
            else:
                await bot_manager.send_answer(
                    text=error_text,
                    event=event,
                    message_type=MessageType.COMMAND_ACTION_INFO,
                    delete_by_type=MessageActionType.COMMAND_ACTION_CLEANUP,
                    parse_mode="Markdown",
                )
            return

        users = data["users"]
        total = data["total"]
        current_page = data["page"]
        total_pages = data["total_pages"]
        has_prev = data["has_prev"]
        has_next = data["has_next"]

        # Сохранение текущей страницы в состояние
        await state.update_data(users_page=current_page)

        # Формирование текста
        if total == 0:
            empty_text = "📋 Нет пользователей в системе Avanpost."
            if isinstance(event, CallbackQuery):
                await bot_manager.edit_callback_message(
                    text=empty_text,
                    callback=event,
                    parse_mode="Markdown",
                    reply_markup=UserKeyboard.get_close_keyboard(),
                )
            else:
                await bot_manager.send_answer(
                    text=empty_text,
                    event=event,
                    message_type=MessageType.COMMAND_ACTION_INFO,
                    delete_by_type=MessageActionType.COMMAND_ACTION_CLEANUP,
                    parse_mode="Markdown",
                    reply_markup=UserKeyboard.get_close_keyboard(),
                )
            return

        # Заголовок с информацией о странице
        start_item = current_page * 10 + 1
        end_item = min(start_item + 9, total)

        header_text = (
            f"👥 **СПИСОК ПОЛЬЗОВАТЕЛЕЙ**\n\n"
            f"📊 Показаны: {start_item}-{end_item} из {total}\n"
            f"📄 Страница {current_page + 1} из {total_pages}\n\n"
            f"Выберите пользователя для запуска меню действий:\n"
        )

        # Создание клавиатуры
        keyboard = UserKeyboard.get_users_keyboard(
            users=users,
            current_page=current_page,
            total_pages=total_pages,
            has_prev=has_prev,
            has_next=has_next,
        )

        if isinstance(event, CallbackQuery):
            await bot_manager.edit_callback_message(
                text=header_text,
                callback=event,
                parse_mode="Markdown",
                reply_markup=keyboard,
            )
        else:
            await bot_manager.send_answer(
                text=header_text,
                event=event,
                message_type=MessageType.COMMAND_ACTION,
                delete_by_type=MessageActionType.COMMAND_ACTION_CLEANUP,
                parse_mode="Markdown",
                reply_markup=keyboard,
            )

    except Exception as e:
        bot_logger.error(f"❌ Failed to show users: {e}", exc_info=True)
        await error_service.log_error(
            error=e,
            component="users",
            category=ErrorCategory.SYSTEM,
        )

        error_text = "❌ Произошла ошибка при загрузке пользователей. Попробуйте позже."

        if isinstance(event, CallbackQuery):
            with contextlib.suppress(Exception):
                await bot_manager.edit_callback_message(
                    text=error_text,
                    callback=event,
                    parse_mode="Markdown",
                    reply_markup=UserKeyboard.get_close_keyboard(),
                )
        else:
            await bot_manager.send_answer(
                text=error_text,
                event=event,
                message_type=MessageType.COMMAND_ACTION_INFO,
                delete_by_type=MessageActionType.COMMAND_ACTION_CLEANUP,
                parse_mode="Markdown",
                reply_markup=UserKeyboard.get_close_keyboard(),
            )


async def select_user(callback: CallbackQuery, state: FSMContext, user_id: int) -> None:
    """
    Обработка выбора пользователя.
    Запускает /actions для выбранного пользователя.
    """
    bot_manager = get_bot_manager()

    try:
        # Получение информации о пользователе
        async with db_manager.get_session() as session:
            user = await UserRepository.get_avanpost_user_data(session, user_id)

        if not user:
            await bot_manager.send_toast(
                text=f"❌ Пользователь {user_id} не найден.",
                event=callback,
            )
            return

        user_name = user.get("FName") or f"User #{user_id}"
        group_id = user.get("FK_MenuGroup")

        # Проверка, что у пользователя есть группа действий
        if not group_id:
            await bot_manager.send_toast(
                text=f"❌ У пользователя {user_name} не назначена группа действий.",
                event=callback,
                show_alert=True,
            )
            return

        telegram_user_id = callback.from_user.id

        # ============================================================
        # СОХРАНЯЕМ В КЕШ
        # ============================================================
        _auth_cache[telegram_user_id] = {
            "avanpost_user_id": user_id,
            "group_id": group_id,
            "phone": user.get("FPhone"),
            "telegram_user_id": telegram_user_id,
        }
        bot_logger.debug(
            f"✅ Updated _auth_cache for telegram user {telegram_user_id}: "
            f"avanpost_user_id={user_id}, group_id={group_id}"
        )

        # ============================================================
        # СОХРАНЯЕМ В СОСТОЯНИЕ
        # ============================================================
        await state.update_data(
            selected_user_id=user_id,
            selected_user_name=user_name,
            selected_user_group_id=group_id,  # Явно сохраняем group_id
            use_group_id=group_id,
            user_id=user_id,
            is_admin=telegram_user_id in settings.ADMIN_IDS,
        )

        await bot_manager.send_toast(
            text=f"✅ Выбран пользователь: {user_name}",
            event=callback,
        )

        # Импорт функции из actions.py
        from .actions import show_menu

        # Удаление текущего сообщения
        if callback.message:
            await bot_manager.delete_message_by_link(callback.message)

        # Отображение меню действий для выбранного пользователя
        await show_menu(
            event=callback,
            group_id=group_id,
            state=state,
            is_callback=True,
            _is_new=True,
            user_display_name=user_name,
        )

        bot_logger.info(f"✅ User {user_id} selected, showing actions menu with group {group_id}")

    except Exception as e:
        bot_logger.error(f"❌ Failed to select user: {e}", exc_info=True)
        await bot_manager.send_toast(
            text=f"❌ Ошибка при выборе пользователя: {str(e)[:100]}",
            event=callback,
            show_alert=True,
        )


# ============================================================
# ФУНКЦИЯ ДЛЯ ВОЗВРАТА К СПИСКУ ПОЛЬЗОВАТЕЛЕЙ (из actions)
# ============================================================


async def back_to_users(callback: CallbackQuery, state: FSMContext) -> None:
    """
    Возврат к списку пользователей из меню действий.
    Используется для обработки кнопки "К пользователям".

    ВАЖНО: Очищает состояние перед показом списка!
    """
    bot_manager = get_bot_manager()

    # Очищаем состояние от выбранного пользователя
    await _clear_user_selection(state)

    # Получаем страницу из состояния (если есть)
    state_data = await state.get_data()
    page = state_data.get("users_page", 0)

    # Отправляем toast
    await bot_manager.send_toast(
        text="👥 Возврат к списку пользователей",
        event=callback,
    )

    # Показываем список пользователей
    await show_users(event=callback, state=state, page=page)


# ============================================================
# ФУНКЦИЯ ДЛЯ ЗАКРЫТИЯ СПИСКА ПОЛЬЗОВАТЕЛЕЙ
# ============================================================


async def close_users_list(callback: CallbackQuery, state: FSMContext) -> None:
    """
    Закрытие списка пользователей и очистка состояния.
    """
    bot_manager = get_bot_manager()

    # Очищаем состояние
    await _clear_user_selection(state)
    await state.update_data(users_page=0)

    # Удаляем сообщение
    if callback.message:
        try:
            await callback.message.delete()
            bot_logger.debug("🗑️ Users list closed")
        except Exception as e:
            bot_logger.warning(f"⚠️ Could not delete message: {e}")

    # Отправляем уведомление
    await bot_manager.send_toast(
        text="👥 Список пользователей закрыт",
        event=callback,
    )


__all__ = [
    "router",
    "show_users",
    "cmd_users",
    "get_users_page",
    "select_user",
    "back_to_users",
    "close_users_list",
    "_clear_user_selection",
]
