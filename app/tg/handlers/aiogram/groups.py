import contextlib

from aiogram import F, Router
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, Message

from ....config import settings
from ....db import AvanpostRepository, db_manager
from ....exceptions import log_exceptions
from ....logger import tg_logger
from ....models import ErrorCategory, MessageActionType, MessageType
from ....services import error_service
from ....tg.dependencies import get_tg_manager
from ...keyboards import GroupKeyboard
from .auth import is_user_authenticated

router = Router(name="aiogram_groups")


class GroupStates(StatesGroup):
    """Состояния для работы с группами"""

    viewing_groups = State()


@router.message(Command("groups"))
@log_exceptions(tg_logger)
async def cmd_groups(message: Message, state: FSMContext) -> None:
    """Команда для вызова списка групп действий"""
    tg_manager = get_tg_manager()

    # Проверка прав администратора
    if not message.from_user or message.from_user.id not in settings.ADMIN_IDS:
        await tg_manager.send_answer(
            text="⛔ У вас нет прав для этой команды.",
            event=message,
            message_type=MessageType.COMMAND_ACTION_INFO,
            delete_by_type=MessageActionType.COMMAND_ACTION_CLEANUP,
        )
        return

    # Проверка авторизации
    if not await is_user_authenticated(message.from_user.id):
        await tg_manager.send_answer(
            text="🔐 **Требуется авторизация**\n\n"
            "Для доступа к группам действий необходимо авторизоваться.\n"
            "Используйте /start для начала авторизации.",
            event=message,
            message_type=MessageType.COMMAND_ACTION_INFO,
            delete_by_type=MessageActionType.COMMAND_ACTION_CLEANUP,
        )
        return

    await state.set_state(GroupStates.viewing_groups)

    # Удаление сообщения с командой
    await tg_manager.delete_message_by_link(message)

    # Отображение списка групп
    await show_groups(event=message, state=state)


# ============ ОБРАБОТЧИКИ КОЛБЭКОВ ============


@router.callback_query(F.data.startswith("group_"))
@log_exceptions(tg_logger)
async def handle_group_callback(callback: CallbackQuery, state: FSMContext) -> None:
    """Обработка выбора группы"""
    from ...callbacks.groups import group_callback_handler

    await group_callback_handler.handle(callback, state)


@router.callback_query(F.data == "back_to_groups")
@log_exceptions(tg_logger)
async def handle_back_to_groups(callback: CallbackQuery, state: FSMContext) -> None:
    """Возврат к списку групп"""
    from ...callbacks.groups import group_callback_handler

    await group_callback_handler.handle(callback, state)


# ============ ФУНКЦИИ ДЛЯ РАБОТЫ С ГРУППАМИ ============


async def show_groups(
    event: Message | CallbackQuery,
    state: FSMContext,
) -> None:
    """
    Отображение списка групп действий.

    Args:
        event: Message или CallbackQuery объект
        state: FSM состояние
    """
    tg_manager = get_tg_manager()

    # Ответ на callback, чтобы убрать "часики"
    if isinstance(event, CallbackQuery):
        await event.answer()

    try:
        # Получение списка групп из БД
        async with db_manager.get_session("avanpost") as session:
            groups = await AvanpostRepository.get_groups(session=session)

        # Формирование текста
        if not groups:
            empty_text = "📋 Нет доступных групп действий."

            if isinstance(event, CallbackQuery):
                await tg_manager.edit_callback_message(
                    text=empty_text,
                    callback=event,
                    parse_mode="Markdown",
                )
            else:
                await tg_manager.send_answer(
                    text=empty_text,
                    event=event,
                    message_type=MessageType.COMMAND_ACTION_INFO,
                    delete_by_type=MessageActionType.COMMAND_ACTION_CLEANUP,
                    parse_mode="Markdown",
                )
            return

        header_text = "✨ 📋 **ГРУППЫ ДЕЙСТВИЙ** ✨\n\n"

        keyboard = GroupKeyboard.get_groups_keyboard(groups=groups, is_root_menu=True)

        if isinstance(event, CallbackQuery):
            await tg_manager.edit_callback_message(
                text=header_text,
                callback=event,
                parse_mode="Markdown",
                reply_markup=keyboard,
            )
        else:
            await tg_manager.send_answer(
                text=header_text,
                event=event,
                message_type=MessageType.COMMAND_ACTION,
                delete_by_type=MessageActionType.COMMAND_ACTION_CLEANUP,
                parse_mode="Markdown",
                reply_markup=keyboard,
            )

    except Exception as e:
        tg_logger.error(f"❌ Failed to show groups: {e}", exc_info=True)
        await error_service.log_error(
            error=e,
            component="groups",
            category=ErrorCategory.SYSTEM,
            session=session,
        )

        error_text = "❌ Произошла ошибка при загрузке групп. Попробуйте позже."

        if isinstance(event, CallbackQuery):
            with contextlib.suppress(Exception):
                await tg_manager.edit_callback_message(
                    text=error_text,
                    callback=event,
                    parse_mode="Markdown",
                )
        else:
            await tg_manager.send_answer(
                text=error_text,
                event=event,
                message_type=MessageType.COMMAND_ACTION_INFO,
                delete_by_type=MessageActionType.COMMAND_ACTION_CLEANUP,
                parse_mode="Markdown",
            )


__all__ = [
    "router",
    "show_groups",
]
