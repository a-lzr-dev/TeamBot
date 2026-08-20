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
from ...keyboards import UserKeyboard, get_search_cancel_keyboard
from .auth import _auth_cache, is_user_authenticated

router = Router(name="aiogram_users")


class UserStates(StatesGroup):
    """Состояния для работы с пользователями"""

    viewing_users = State()
    searching_users = State()  # Состояние поиска


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
# ПОЛУЧЕНИЕ СПИСКА ПОЛЬЗОВАТЕЛЕЙ С ПАГИНАЦИЕЙ И ПОИСКОМ
# ============================================================


async def get_users_page(
    session: Any,
    page: int = 0,
    page_size: int = 10,
    search_query: str | None = None,
) -> dict[str, Any]:
    """
    Получение списка пользователей с пагинацией и поддержкой поиска.

    Args:
        session: Сессия БД
        page: Номер страницы (начиная с 0)
        page_size: Количество пользователей на странице
        search_query: Поисковый запрос (имя, фамилия, телефон)

    Returns:
        dict: {
            "users": list[dict],
            "total": int,
            "page": int,
            "total_pages": int,
            "has_prev": bool,
            "has_next": bool,
            "search_query": str | None
        }
    """
    try:
        from sqlalchemy import func, or_, select
        from sqlalchemy.orm import selectinload

        from app.models import AvanpostUserLinkModel, AvanpostUserModel, UserModel

        # Базовый запрос с подгрузкой связанных моделей
        stmt = (
            select(AvanpostUserModel)
            .options(selectinload(AvanpostUserModel.user_link).selectinload(AvanpostUserLinkModel.telegram_user))
            .order_by(AvanpostUserModel.FID)
        )

        # Применение поискового фильтра при его наличии
        if search_query and len(search_query) >= 2:
            search_pattern = f"%{search_query}%"

            # Построение условия для поиска по AvanpostUser
            conditions = [
                AvanpostUserModel.FName.ilike(search_pattern),
                AvanpostUserModel.FPhone.ilike(search_pattern),
            ]

            # Поиск по связанному Telegram пользователю через подзапрос
            # Использование явного JOIN с AvanpostUserLinkModel для доступа к FK_Link
            subquery = (
                select(AvanpostUserLinkModel.FK_Parent)
                .join(UserModel, AvanpostUserLinkModel.FK_Link == UserModel.FID)
                .where(
                    or_(
                        UserModel.FFirstName.ilike(search_pattern),
                        UserModel.FLastName.ilike(search_pattern),
                        UserModel.FUserName.ilike(search_pattern),
                    )
                )
                .scalar_subquery()
            )

            # Добавление условия: AvanpostUser.FID IN (subquery)
            conditions.append(AvanpostUserModel.FID.in_(subquery))

            stmt = stmt.where(or_(*conditions))

        # Общий подсчет (с учетом фильтра)
        count_stmt = select(func.count()).select_from(AvanpostUserModel)

        if search_query and len(search_query) >= 2:
            search_pattern = f"%{search_query}%"
            conditions = [
                AvanpostUserModel.FName.ilike(search_pattern),
                AvanpostUserModel.FPhone.ilike(search_pattern),
            ]

            subquery = (
                select(AvanpostUserLinkModel.FK_Parent)
                .join(UserModel, AvanpostUserLinkModel.FK_Link == UserModel.FID)
                .where(
                    or_(
                        UserModel.FFirstName.ilike(search_pattern),
                        UserModel.FLastName.ilike(search_pattern),
                        UserModel.FUserName.ilike(search_pattern),
                    )
                )
                .scalar_subquery()
            )
            conditions.append(AvanpostUserModel.FID.in_(subquery))
            count_stmt = count_stmt.where(or_(*conditions))

        total_result = await session.execute(count_stmt)
        total = total_result.scalar() or 0

        total_pages = (total + page_size - 1) // page_size

        # Пагинация
        offset = page * page_size
        stmt = stmt.offset(offset).limit(page_size)

        result = await session.execute(stmt)
        users = result.scalars().all()

        # Форматирование пользователей
        users_data = []
        for user in users:
            # Получение Telegram пользователя через user_link (если есть)
            telegram_user = None
            if user.user_link and user.user_link.telegram_user:
                telegram_user = user.user_link.telegram_user

            # Безопасное получение fk_user
            fk_user = user.user_link.FK_Link if user.user_link else None

            users_data.append(
                {
                    "id": user.FID,
                    "name": user.FName or f"User #{user.FID}",
                    "phone": user.FPhone or "Не указан",
                    "group_id": user.FK_MenuGroup,
                    "telegram_id": fk_user,
                    "telegram_name": telegram_user.fullname if telegram_user else None,
                    "is_authorized": fk_user is not None,
                }
            )

        return {
            "users": users_data,
            "total": total,
            "page": page,
            "total_pages": total_pages,
            "has_prev": page > 0,
            "has_next": page < total_pages - 1,
            "search_query": search_query,
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
            "search_query": search_query,
            "error": str(e),
        }


# ============================================================
# ОТОБРАЖЕНИЕ СПИСКА ПОЛЬЗОВАТЕЛЕЙ
# ============================================================


async def show_users(
    event: Message | CallbackQuery,
    state: FSMContext,
    page: int = 0,
    search_query: str | None = None,
    chat_id: int | None = None,
) -> None:
    """Отображение списка пользователей с пагинацией и поиском"""
    bot_manager = get_bot_manager()

    if chat_id is None:
        if isinstance(event, Message):
            chat_id = event.chat.id
        elif isinstance(event, CallbackQuery) and event.message:
            chat_id = event.message.chat.id
        else:
            bot_logger.error("❌ Cannot determine chat_id for show_users")
            return

    if isinstance(event, CallbackQuery):
        await event.answer()

    if search_query is None:
        data = await state.get_data()
        search_query = data.get("search_query")

    try:
        async with db_manager.get_session() as session:
            # Получение данных с учетом поиска
            data = await get_users_page(
                session=session,
                page=page,
                page_size=10,
                search_query=search_query,
            )

        if data.get("error"):
            error_text = f"❌ Ошибка загрузки пользователей: {data['error']}"
            await bot_manager.send_message(
                chat_id=chat_id,
                text=error_text,
                message_type=MessageType.COMMAND_ACTION_INFO,
                delete_by_type=MessageActionType.COMMAND_ACTION_CLEANUP,
                parse_mode="Markdown",
                reply_markup=UserKeyboard.get_close_keyboard(),
            )
            return

        users = data["users"]
        total = data["total"]
        current_page = data["page"]
        total_pages = data["total_pages"]
        has_prev = data["has_prev"]
        has_next = data["has_next"]
        current_search = data.get("search_query")

        # Сохранение текущей страницы и поискового запроса в состояние
        await state.update_data(users_page=current_page, search_query=current_search)

        # Формирование текста
        if total == 0:
            empty_text = "📋 Нет пользователей в системе Avanpost."
            if current_search:
                empty_text = f"🔍 По запросу '{current_search}' пользователи не найдены."

            await bot_manager.send_message(
                chat_id=chat_id,  # Используем переданный chat_id
                text=empty_text,
                message_type=MessageType.COMMAND_ACTION_INFO,
                delete_by_type=MessageActionType.COMMAND_ACTION_CLEANUP,
                parse_mode="Markdown",
                reply_markup=UserKeyboard.get_close_keyboard(),
            )
            return

        # Заголовок с информацией о странице и поиске
        start_item = current_page * 10 + 1
        end_item = min(start_item + 9, total)

        header_text = "👥 **СПИСОК ПОЛЬЗОВАТЕЛЕЙ**\n\n"

        if current_search:
            header_text += f"🔍 **Поиск:** `{current_search}`\n"

        header_text += f"📊 Показаны: {start_item}-{end_item} из {total}\n"
        header_text += f"📄 Страница {current_page + 1} из {total_pages}\n\n"
        header_text += "Выберите пользователя для запуска меню действий:\n"

        # Создание клавиатуры (с учетом поиска)
        keyboard = UserKeyboard.get_users_keyboard(
            users=users,
            current_page=current_page,
            total_pages=total_pages,
            has_prev=has_prev,
            has_next=has_next,
            search_query=current_search,
        )

        result = await bot_manager.send_message(
            chat_id=chat_id,
            text=header_text,
            message_type=MessageType.COMMAND_ACTION,
            delete_by_type=MessageActionType.COMMAND_ACTION_CLEANUP,
            parse_mode="Markdown",
            reply_markup=keyboard,
        )

        # Если это callback, обновляем ID сообщения в состоянии
        if isinstance(event, CallbackQuery) and result.get("success"):
            await state.update_data(last_users_message_id=result.get("message_id"))

    except Exception as e:
        bot_logger.error(f"❌ Failed to show users: {e}", exc_info=True)
        await error_service.log_error(
            error=e,
            component="users",
            category=ErrorCategory.SYSTEM,
        )

        error_text = "❌ Произошла ошибка при загрузке пользователей. Попробуйте позже."
        await bot_manager.send_message(
            chat_id=chat_id,
            text=error_text,
            message_type=MessageType.COMMAND_ACTION_INFO,
            delete_by_type=MessageActionType.COMMAND_ACTION_CLEANUP,
            parse_mode="Markdown",
            reply_markup=UserKeyboard.get_close_keyboard(),
        )


# ============================================================
# ОБРАБОТЧИК КОМАНДЫ /users
# ============================================================


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

    # Установка состояния просмотра и очистки поиска
    await state.set_state(UserStates.viewing_users)
    await state.update_data(search_query=None, users_page=0)

    # Удаление сообщения с командой
    await bot_manager.delete_message_by_link(message)

    # Очистка состояния перед показом списка
    await _clear_user_selection(state)

    # Отображение списка пользователей (страница 0)
    await show_users(event=message, state=state, page=0)


# ============================================================
# ОБРАБОТЧИК ПОИСКА
# ============================================================


@router.message(UserStates.searching_users)
@log_exceptions(bot_logger)
async def handle_user_search_query(message: Message, state: FSMContext) -> None:
    """Обработка поискового запроса (текст)"""
    bot_manager = get_bot_manager()

    # Проверка прав администратора
    if not message.from_user or message.from_user.id not in settings.ADMIN_IDS:
        await bot_manager.send_answer(
            text="⛔ У вас нет прав для этой команды.",
            event=message,
            message_type=MessageType.COMMAND_ACTION_INFO,
            delete_by_type=MessageActionType.COMMAND_ACTION_CLEANUP,
        )
        await state.set_state(UserStates.viewing_users)
        return

    query = message.text.strip() if message.text else ""

    # Если поисковый запрос пустой или слишком короткий
    if not query or len(query) < 2:
        await bot_manager.send_answer(
            text="ℹ️ Введите минимум 2 символа для поиска.",
            event=message,
            message_type=MessageType.COMMAND_ACTION_INFO,
            delete_by_type=MessageActionType.COMMAND_ACTION_CLEANUP,
        )
        return

    # Сохранение поискового запроса
    await state.update_data(search_query=query)

    # Удаление сообщения с поисковым запросом
    await bot_manager.delete_message_by_link(message)

    # Отображение результата поиска
    await show_users(event=message, state=state, page=0, search_query=query)


# ============================================================
# ОБРАБОТЧИК КНОПКИ ПОИСКА
# ============================================================


@router.callback_query(F.data == "users_search")
@log_exceptions(bot_logger)
async def handle_users_search_button(callback: CallbackQuery, state: FSMContext) -> None:
    """Обработка кнопки поиска пользователей"""
    bot_manager = get_bot_manager()

    # Проверка прав администратора
    if not callback.from_user or callback.from_user.id not in settings.ADMIN_IDS:
        await callback.answer("⛔ У вас нет прав.", show_alert=True)
        return

    await callback.answer("🔍 Введите поисковый запрос", show_alert=False)

    # Перевод в состояние поиска
    await state.set_state(UserStates.searching_users)

    # Сохранение текущей страницы, чтобы вернуться к ней при отмене
    data = await state.get_data()
    current_page = data.get("users_page", 0)
    await state.update_data(users_page_before_search=current_page)

    # Удаление текущего сообщения со списком пользователей
    if callback.message:
        try:
            await callback.message.delete()
            bot_logger.debug("🗑️ Deleted users list before search")
        except Exception as e:
            bot_logger.warning(f"⚠️ Could not delete message: {e}")

    # Отправка сообщения с просьбой ввести поисковый запрос
    await bot_manager.send_answer(
        text="🔍 **Поиск пользователей**\n\n"
        "Введите имя, фамилию или номер телефона для поиска.\n"
        "Минимум 2 символа.\n\n"
        "Используйте кнопку ниже для отмены:",
        event=callback,
        message_type=MessageType.COMMAND_ACTION_INFO,
        delete_by_type=MessageActionType.COMMAND_ACTION_CLEANUP,
        parse_mode="Markdown",
        reply_markup=get_search_cancel_keyboard(),
    )


# ============================================================
# ОБРАБОТЧИК ОТМЕНЫ ПОИСКА (ЧЕРЕЗ CALLBACK)
# ============================================================


@router.callback_query(F.data == "users_cancel_search")
@log_exceptions(bot_logger)
async def handle_cancel_search(callback: CallbackQuery, state: FSMContext) -> None:
    """Отмена поиска через callback - возврат к списку пользователей"""
    # Проверка прав администратора
    if not callback.from_user or callback.from_user.id not in settings.ADMIN_IDS:
        await callback.answer("⛔ У вас нет прав.", show_alert=True)
        return

    await callback.answer("👥 Возврат к списку пользователей", show_alert=False)

    # Сброс состояния поиска
    await state.set_state(None)

    # Получение сохраненной страницы
    data = await state.get_data()
    page = data.get("users_page_before_search", 0)

    # Очистка временных переменных
    await state.update_data(
        users_page_before_search=0,
        search_query=None,
    )

    # Удаление сообщения с поиском
    if callback.message:
        try:
            await callback.message.delete()
            bot_logger.debug("🗑️ Deleted search message")
        except Exception as e:
            bot_logger.warning(f"⚠️ Could not delete message: {e}")

    # Отправка нового сообщения со списком пользователей
    await show_users(
        event=callback,
        state=state,
        page=page,
        search_query=None,
        chat_id=callback.message.chat.id if callback.message else None,
    )

    bot_logger.info("✅ Search cancelled, returned to users list")


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
# ФУНКЦИЯ ВЫБОРА ПОЛЬЗОВАТЕЛЯ
# ============================================================


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

        # Сохранение в кеш
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

        # Сохранение в состояние
        await state.update_data(
            selected_user_id=user_id,
            selected_user_name=user_name,
            selected_user_group_id=group_id,
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

    # Очистка состояния от выбранного пользователя
    await _clear_user_selection(state)

    # Получение страницы и поискового запроса из состояния
    state_data = await state.get_data()
    page = state_data.get("users_page", 0)
    search_query = state_data.get("search_query")

    await bot_manager.send_toast(
        text="👥 Возврат к списку пользователей",
        event=callback,
    )

    # Отображение списка пользователей
    await show_users(event=callback, state=state, page=page, search_query=search_query)


# ============================================================
# ФУНКЦИЯ ДЛЯ ЗАКРЫТИЯ СПИСКА ПОЛЬЗОВАТЕЛЕЙ
# ============================================================


async def close_users_list(callback: CallbackQuery, state: FSMContext) -> None:
    """Закрытие списка пользователей и очистка состояния"""
    bot_manager = get_bot_manager()

    # Очистка состояния
    await _clear_user_selection(state)
    await state.update_data(users_page=0, search_query=None)
    await state.set_state(None)  # Сбрасываем состояние

    # Удаление сообщения
    if callback.message:
        try:
            await callback.message.delete()
            bot_logger.debug("🗑️ Users list closed")
        except Exception as e:
            bot_logger.warning(f"⚠️ Could not delete message: {e}")

    # Отправка уведомления
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
    "handle_users_search_button",
    "UserStates",
]
