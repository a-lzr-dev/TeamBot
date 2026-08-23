"""
Модуль административных обработчиков Aiogram.

Этот модуль предоставляет обработчики для административных команд,
сгруппированные по функциональным областям:

1. ОТМЕНА ОПЕРАЦИЙ
   - /cancel - Отмена текущей операции FSM

2. УПРАВЛЕНИЕ АДМИНИСТРАТОРАМИ
   - /admins - Просмотр списка администраторов
   - /add_admin <id> - Добавление администратора
   - /remove_admin <id> - Удаление администратора

3. ОБРАБОТЧИКИ КОЛБЭКОВ
   - delete_confirm / delete_cancel - Подтверждение/отмена удаления

Примечания:
- Все команды доступны только администраторам (проверка по settings.ADMIN_IDS)
- Колбэки удаления обрабатываются через admin_callback_handler
"""

from aiogram import Router
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message

from ....bot.dependencies import get_bot_manager
from ....config import settings
from ....logger import bot_logger
from ....models import MessageActionType, MessageType
from ....utils.decorators import log_exceptions

# ============================================================
# РОУТЕР
# ============================================================

router = Router(name="aiogram_admin")


# ============================================================
# 1. ОТМЕНА ОПЕРАЦИЙ
# ============================================================


@router.message(Command("cancel"))
@log_exceptions(bot_logger)
async def cmd_cancel(message: Message, state: FSMContext) -> None:
    """
    Отмена текущей операции FSM.

    Args:
        message: Сообщение от пользователя
        state: Состояние FSM
    """
    bot_manager = get_bot_manager()

    current_state = await state.get_state()
    if current_state is None:
        await bot_manager.send_answer(
            text="❌ Нет активных операций для отмены.",
            event=message,
            message_type=MessageType.COMMAND_ADMIN,
            delete_by_type=MessageActionType.COMMAND_ADMIN_CLEANUP,
        )
        return

    await state.clear()
    await bot_manager.send_answer(
        text="✅ Операция отменена.",
        event=message,
        message_type=MessageType.COMMAND_ADMIN,
        delete_by_type=MessageActionType.COMMAND_ADMIN_CLEANUP,
    )


# ============================================================
# 2. УПРАВЛЕНИЕ АДМИНИСТРАТОРАМИ
# ============================================================


@router.message(Command("admins"))
@log_exceptions(bot_logger)
async def cmd_admins(message: Message) -> None:
    """
    Просмотр списка администраторов.

    Args:
        message: Сообщение от пользователя
    """
    bot_manager = get_bot_manager()

    if not message.from_user or message.from_user.id not in settings.ADMIN_IDS:
        await bot_manager.send_answer(
            text="⛔ У вас нет прав для этой команды.",
            event=message,
            message_type=MessageType.COMMAND_ADMIN,
            delete_by_type=MessageActionType.COMMAND_ADMIN_CLEANUP,
        )
        return

    admin_list = [f"• `{admin_id}`" for admin_id in settings.ADMIN_IDS]

    response = (
        "👑 **Список администраторов**\n\n"
        f"{chr(10).join(admin_list) if admin_list else 'Нет администраторов'}\n\n"
        "Для добавления администратора используйте /add_admin <user_id>"
    )

    await bot_manager.send_answer(
        text=response,
        event=message,
        message_type=MessageType.COMMAND_ADMIN,
        delete_by_type=MessageActionType.COMMAND_ADMIN_CLEANUP,
        parse_mode="Markdown",
    )


@router.message(Command("add_admin"))
@log_exceptions(bot_logger)
async def cmd_add_admin(message: Message) -> None:
    """
    Добавление администратора.

    Формат: /add_admin <user_id>

    Args:
        message: Сообщение от пользователя
    """
    bot_manager = get_bot_manager()

    if not message.from_user or message.from_user.id not in settings.ADMIN_IDS:
        await bot_manager.send_answer(
            text="⛔ У вас нет прав для этой команды.",
            event=message,
            message_type=MessageType.COMMAND_ADMIN,
            delete_by_type=MessageActionType.COMMAND_ADMIN_CLEANUP,
        )
        return

    command_text = message.text or ""
    args = command_text.split()

    if len(args) < 2:
        await bot_manager.send_answer(
            text="❌ Использование: /add_admin <user_id>\n"
            "Например: /add_admin 123456789\n\n"
            "💡 Чтобы узнать свой ID, используйте /id",
            event=message,
            message_type=MessageType.COMMAND_ADMIN,
            delete_by_type=MessageActionType.COMMAND_ADMIN_CLEANUP,
        )
        return

    try:
        new_admin_id = int(args[1])

        if new_admin_id in settings.ADMIN_IDS:
            await bot_manager.send_answer(
                text=f"ℹ️ Пользователь {new_admin_id} уже является администратором.",
                event=message,
                message_type=MessageType.COMMAND_ADMIN,
                delete_by_type=MessageActionType.COMMAND_ADMIN_CLEANUP,
            )
            return

        settings.ADMIN_IDS.append(new_admin_id)

        await bot_manager.send_answer(
            text=f"✅ Пользователь {new_admin_id} добавлен в админы!\n\n"
            f"⚠️ **Важно:** Для постоянного добавления обновите `ADMIN_IDS` в файле `.env`.\n"
            f"Текущий список админов: {settings.ADMIN_IDS}",
            event=message,
            message_type=MessageType.COMMAND_ADMIN,
            delete_by_type=MessageActionType.COMMAND_ADMIN_CLEANUP,
        )
        bot_logger.info(f"✅ User {new_admin_id} added to admins by {message.from_user.id}")

    except ValueError:
        await bot_manager.send_answer(
            text="❌ Неверный формат ID. Используйте число.",
            event=message,
            message_type=MessageType.COMMAND_ADMIN,
            delete_by_type=MessageActionType.COMMAND_ADMIN_CLEANUP,
        )
    except Exception as err:
        bot_logger.error(f"❌ Failed to add admin: {err}")
        await bot_manager.send_answer(
            text=f"❌ Ошибка: {err}",
            event=message,
            message_type=MessageType.COMMAND_ADMIN,
            delete_by_type=MessageActionType.COMMAND_ADMIN_CLEANUP,
        )


@router.message(Command("remove_admin"))
@log_exceptions(bot_logger)
async def cmd_remove_admin(message: Message) -> None:
    """
    Удаление администратора.

    Формат: /remove_admin <user_id>

    Args:
        message: Сообщение от пользователя
    """
    bot_manager = get_bot_manager()

    if not message.from_user or message.from_user.id not in settings.ADMIN_IDS:
        await bot_manager.send_answer(
            text="⛔ У вас нет прав для этой команды.",
            event=message,
            message_type=MessageType.COMMAND_ADMIN,
            delete_by_type=MessageActionType.COMMAND_ADMIN_CLEANUP,
        )
        return

    if len(settings.ADMIN_IDS) <= 1:
        await bot_manager.send_answer(
            text="⚠️ Нельзя удалить единственного администратора.",
            event=message,
            message_type=MessageType.COMMAND_ADMIN,
            delete_by_type=MessageActionType.COMMAND_ADMIN_CLEANUP,
        )
        return

    command_text = message.text or ""
    args = command_text.split()

    if len(args) < 2:
        await bot_manager.send_answer(
            text="❌ Использование: /remove_admin <user_id>\nНапример: /remove_admin 123456789",
            event=message,
            message_type=MessageType.COMMAND_ADMIN,
            delete_by_type=MessageActionType.COMMAND_ADMIN_CLEANUP,
        )
        return

    try:
        admin_id = int(args[1])

        if admin_id not in settings.ADMIN_IDS:
            await bot_manager.send_answer(
                text=f"ℹ️ Пользователь {admin_id} не является администратором.",
                event=message,
                message_type=MessageType.COMMAND_ADMIN,
                delete_by_type=MessageActionType.COMMAND_ADMIN_CLEANUP,
            )
            return

        if admin_id == message.from_user.id:
            await bot_manager.send_answer(
                text="⚠️ Вы не можете удалить сами себя из списка админов.",
                event=message,
                message_type=MessageType.COMMAND_ADMIN,
                delete_by_type=MessageActionType.COMMAND_ADMIN_CLEANUP,
            )
            return

        settings.ADMIN_IDS.remove(admin_id)

        await bot_manager.send_answer(
            text=f"✅ Пользователь {admin_id} удален из админов!\n\n"
            f"⚠️ **Важно:** Для постоянного удаления обновите `ADMIN_IDS` в файле `.env`.\n"
            f"Текущий список админов: {settings.ADMIN_IDS}",
            event=message,
            message_type=MessageType.COMMAND_ADMIN,
            delete_by_type=MessageActionType.COMMAND_ADMIN_CLEANUP,
        )
        bot_logger.info(f"✅ User {admin_id} removed from admins by {message.from_user.id}")

    except ValueError:
        await bot_manager.send_answer(
            text="❌ Неверный формат ID. Используйте число.",
            event=message,
            message_type=MessageType.COMMAND_ADMIN,
            delete_by_type=MessageActionType.COMMAND_ADMIN_CLEANUP,
        )
    except Exception as err:
        bot_logger.error(f"❌ Failed to remove admin: {err}")
        await bot_manager.send_answer(
            text=f"❌ Ошибка: {err}",
            event=message,
            message_type=MessageType.COMMAND_ADMIN,
            delete_by_type=MessageActionType.COMMAND_ADMIN_CLEANUP,
        )


# ============================================================
# 3. ОБРАБОТЧИКИ КОЛБЭКОВ
# ============================================================


@router.callback_query(lambda c: c.data in ["delete_confirm", "delete_cancel"])
@log_exceptions(bot_logger)
async def handle_delete_callback(callback: CallbackQuery, state: FSMContext) -> None:
    """
    Обработка колбэков для подтверждения/отмены удаления сообщения.

    Args:
        callback: CallbackQuery от пользователя
        state: Состояние FSM
    """
    from ...callbacks.admin import admin_callback_handler

    await admin_callback_handler.handle(callback, state)


__all__ = [
    "router",
    "cmd_cancel",
    "cmd_admins",
    "cmd_add_admin",
    "cmd_remove_admin",
]
