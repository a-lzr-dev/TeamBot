"""
Модуль для контекстного меню сообщений.

Позволяет выполнять действия с сообщениями:
- Ответить на сообщение
- Просмотреть вложения
- Скопировать ID
- Найти в чате
- Удалить сообщение

Поддерживает вызов через:
- Команду /msg <id>
- Callback-запросы из списка сообщений
"""

import contextlib

from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message

from ....config import settings
from ....db import db_manager
from ....db.repositories import MessageRepository
from ....logger import bot_logger
from ....models import MessageActionType, MessageType
from ....utils.decorators import log_exceptions
from ...dependencies import get_bot_manager

# Создание роутера для контекстного меню
router = Router(name="chat_message_menu")


class ReplyStates(StatesGroup):
    """Состояния для ответа на сообщение."""

    waiting_for_reply_text = State()


async def show_message_context_menu(
    event: Message | CallbackQuery,
    state: FSMContext,
    message_id: int,
    chat_id: int,
    custom_text: str | None = None,
    edit_original: bool = True,
    show_back_to_chat: bool = False,
) -> None:
    """
    Отображение контекстного меню для сообщения.

    Args:
        event: Событие (Message или CallbackQuery)
        state: Состояние FSM
        message_id: ID сообщения
        chat_id: ID чата
        custom_text: Кастомный текст вместо стандартного заголовка (опционально)
        edit_original: Редактировать оригинальное сообщение (для callback)
        show_back_to_chat: Показывать кнопку "Назад к чату"
    """
    bot_manager = get_bot_manager()

    title = "📌 **Действия с сообщением**\n\n"
    if custom_text:
        title = custom_text
    else:
        # Получение информации о сообщении
        async with db_manager.get_session() as session:
            repo = MessageRepository()
            db_message = await repo.get_message_by_id(session, message_id)

            # Формирование заголовка
            title += f"🆔 ID: `{message_id}`\n"
            title += f"💬 Чат: `{chat_id}`\n"

            if db_message:
                if db_message.FText:
                    text_preview = db_message.FText[:100] + "..." if len(db_message.FText) > 100 else db_message.FText
                    title += f"📝 Текст: {text_preview}\n"
                if db_message.FDateSent:
                    title += f"📅 Дата: {db_message.FDateSent.strftime('%d.%m.%Y %H:%M')}\n"
            else:
                title += "⚠️ Сообщение не найдено в базе данных\n"

            title += "\nВыберите действие:"

    # Формирование клавиатуры с действиями
    keyboard_buttons = [
        [
            InlineKeyboardButton(text="📝 Ответить", callback_data=f"msg_reply_{message_id}"),
            InlineKeyboardButton(text="📎 Вложения", callback_data=f"msg_attachments_{message_id}"),
        ],
        [
            InlineKeyboardButton(text="📋 Копировать ID", callback_data=f"msg_copy_id_{message_id}"),
            InlineKeyboardButton(text="🔍 Найти в чате", callback_data=f"msg_find_{message_id}"),
        ],
        [
            InlineKeyboardButton(text="🗑️ Удалить", callback_data=f"msg_delete_{message_id}"),
        ],
    ]

    # Добавление кнопки "Назад к чату" если нужно
    if show_back_to_chat:
        keyboard_buttons.append(
            [
                InlineKeyboardButton(
                    text="🔙 Назад к чату",
                    callback_data=f"msg_back_to_chat_{message_id}",
                )
            ]
        )

    keyboard_buttons.append(
        [
            InlineKeyboardButton(text="❌ Закрыть", callback_data="msg_close_menu"),
        ]
    )

    keyboard = InlineKeyboardMarkup(inline_keyboard=keyboard_buttons)

    # Сохранение ID сообщения в состояние
    await state.update_data(context_message_id=message_id, context_chat_id=chat_id)

    # Отправка или редактирование сообщения с меню
    if isinstance(event, CallbackQuery) and edit_original:
        # Если это callback - редактируем текущее сообщение
        try:
            await bot_manager.edit_callback_message(
                callback=event,
                text=title,
                parse_mode="Markdown",
                reply_markup=keyboard,
            )
            return
        except Exception as e:
            bot_logger.warning(f"⚠️ Could not edit callback message: {e}")

    # Отправка нового, если не удалеось отредактировать
    chat_id_for_send = event.message.chat.id if isinstance(event, CallbackQuery) and event.message else chat_id

    await bot_manager.send_message(
        chat_id=chat_id_for_send,
        text=title,
        message_type=MessageType.COMMAND_ACTION,
        delete_by_type=MessageActionType.COMMAND_ACTION_CLEANUP,
        parse_mode="Markdown",
        reply_markup=keyboard,
    )


# ============================================================
# ОБРАБОТЧИКИ КОЛБЭКОВ КОНТЕКСТНОГО МЕНЮ
# ============================================================


@router.callback_query(F.data.startswith("msg_reply_"))
@log_exceptions(bot_logger)
async def handle_msg_reply(callback: CallbackQuery, state: FSMContext) -> None:
    """Ответить на сообщение."""
    bot_manager = get_bot_manager()
    message_id = int(callback.data.split("_")[-1])

    # Получение информации о сообщении
    async with db_manager.get_session() as session:
        repo = MessageRepository()
        db_message = await repo.get_message_by_id(session, message_id)

        if not db_message:
            await bot_manager.send_toast(text="❌ Сообщение не найдено.", event=callback)
            return

    # Сохранение ID сообщения для ответа
    await state.update_data(reply_to_message_id=message_id, reply_chat_id=db_message.FK_Chat)
    await state.set_state(ReplyStates.waiting_for_reply_text)

    await bot_manager.edit_callback_message(
        callback=callback,
        text=f"📝 **Ответ на сообщение #{message_id}**\n\nВведите текст ответа:\n(для отмены отправьте /cancel)",
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup(
            inline_keyboard=[[InlineKeyboardButton(text="❌ Отмена", callback_data="msg_cancel_reply")]]
        ),
    )


@router.callback_query(F.data.startswith("msg_attachments_"))
@log_exceptions(bot_logger)
async def handle_msg_attachments(callback: CallbackQuery, state: FSMContext) -> None:
    """Отобржаение вложения сообщения."""
    bot_manager = get_bot_manager()
    message_id = int(callback.data.split("_")[-1])

    await bot_manager.send_toast(
        text=f"📎 Загрузка вложений для сообщения #{message_id}...",
        event=callback,
    )

    # TODO: Реализовать получение вложений из базы данных
    await bot_manager.edit_callback_message(
        callback=callback,
        text=f"📎 **Вложения сообщения #{message_id}**\n\n🔍 Функция в разработке.\n\nID сообщения: `{message_id}`",
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup(
            inline_keyboard=[[InlineKeyboardButton(text="🔙 Назад", callback_data=f"msg_back_{message_id}")]]
        ),
    )


@router.callback_query(F.data.startswith("msg_copy_id_"))
@log_exceptions(bot_logger)
async def handle_msg_copy_id(callback: CallbackQuery, state: FSMContext) -> None:
    """Скопировать ID сообщения."""
    bot_manager = get_bot_manager()
    message_id = int(callback.data.split("_")[-1])

    # В Telegram боте нельзя скопировать в буфер обмена напрямую
    # Отправляем ID как текст
    await bot_manager.send_answer(
        text=f"🆔 **ID сообщения:** `{message_id}`\n\n"
        f"Вы можете скопировать его вручную или использовать команду `/msg {message_id}`\n"
        f"Для просмотра контекста сообщения используйте `/find {message_id}`",
        event=callback,
        message_type=MessageType.COMMAND_ACTION,
        parse_mode="Markdown",
        delete_by_type=MessageActionType.COMMAND_ACTION_CLEANUP,
    )

    await callback.answer("✅ ID скопирован в буфер обмена (если поддерживается)", show_alert=False)


@router.callback_query(F.data.startswith("msg_find_"))
@log_exceptions(bot_logger)
async def handle_msg_find(callback: CallbackQuery, state: FSMContext) -> None:
    """Найти сообщение в чате."""
    bot_manager = get_bot_manager()
    message_id = int(callback.data.split("_")[-1])

    # Получение информации о сообщении
    async with db_manager.get_session() as session:
        repo = MessageRepository()
        db_message = await repo.get_message_by_id(session, message_id)

        if not db_message:
            await bot_manager.send_toast(text="❌ Сообщение не найдено.", event=callback)
            return

        # Отображение сообщения
        text = f"🔍 **Найдено сообщение #{message_id}**\n\n"
        text += f"💬 Чат: `{db_message.FK_Chat}`\n"
        text += (
            f"📅 Дата: {db_message.FDateSent.strftime('%d.%m.%Y %H:%M') if db_message.FDateSent else 'неизвестно'}\n\n"
        )
        if db_message.FText:
            text += f"📝 {db_message.FText}\n\n"
        text += f"🔗 Используйте `/msg {message_id}` для повторного открытия меню"

        await bot_manager.edit_callback_message(
            callback=callback,
            text=text,
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup(
                inline_keyboard=[
                    [InlineKeyboardButton(text="📝 Ответить", callback_data=f"msg_reply_{message_id}")],
                    [InlineKeyboardButton(text="🔙 Назад", callback_data=f"msg_back_{message_id}")],
                ]
            ),
        )


@router.callback_query(F.data.startswith("msg_delete_"))
@log_exceptions(bot_logger)
async def handle_msg_delete(callback: CallbackQuery, state: FSMContext) -> None:
    """Удалить сообщение."""
    bot_manager = get_bot_manager()
    message_id = int(callback.data.split("_")[-1])

    # Запрашивание подтверждения
    keyboard = InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="✅ Да, удалить", callback_data=f"msg_confirm_delete_{message_id}"),
                InlineKeyboardButton(text="❌ Отмена", callback_data=f"msg_back_{message_id}"),
            ]
        ]
    )

    await bot_manager.edit_callback_message(
        callback=callback,
        text=f"⚠️ **Подтверждение удаления**\n\n"
        f"Вы уверены, что хотите удалить сообщение #{message_id}?\n\n"
        f"⚠️ Это действие необратимо.",
        parse_mode="Markdown",
        reply_markup=keyboard,
    )


@router.callback_query(F.data.startswith("msg_confirm_delete_"))
@log_exceptions(bot_logger)
async def handle_msg_confirm_delete(callback: CallbackQuery, state: FSMContext) -> None:
    """Подтверждение удаления сообщения."""
    bot_manager = get_bot_manager()
    message_id = int(callback.data.split("_")[-1])

    # Получение информации о сообщении
    async with db_manager.get_session() as session:
        repo = MessageRepository()
        db_message = await repo.get_message_by_id(session, message_id)

        if not db_message:
            await bot_manager.send_toast(text="❌ Сообщение не найдено.", event=callback)
            return

        # Проверка прав (только администраторы могут удалять)
        if callback.from_user and callback.from_user.id not in settings.ADMIN_IDS:
            await bot_manager.send_toast(
                text="⛔ У вас нет прав на удаление сообщений.", event=callback, show_alert=True
            )
            return

        # Удаление сообщения
        result = await bot_manager.delete_message_by_id(
            chat_id=db_message.FK_Chat,
            message_id=message_id,
        )

        if result.get("success"):
            await bot_manager.send_toast(
                text=f"✅ Сообщение #{message_id} удалено.",
                event=callback,
            )
            # Закрытие меню
            with contextlib.suppress(Exception):
                await callback.message.delete()
        else:
            await bot_manager.send_toast(
                text=f"❌ Ошибка при удалении: {result.get('error', 'неизвестная ошибка')}",
                event=callback,
                show_alert=True,
            )


@router.callback_query(F.data.startswith("msg_back_to_chat_"))
@log_exceptions(bot_logger)
async def handle_back_to_chat(callback: CallbackQuery, state: FSMContext) -> None:
    """
    Возврат к детализации чата на ту же страницу.
    """
    bot_manager = get_bot_manager()
    await bot_manager.send_toast(text="🔙 Возврат к чату...", event=callback)

    # Получение сохранённого контекста
    state_data = await state.get_data()
    chat_id = state_data.get("return_to_chat_id")
    page = state_data.get("return_to_page", 0)
    avanpost_user_id = state_data.get("return_avanpost_user_id")
    parent_item_id = state_data.get("return_parent_item_id")
    group_id = state_data.get("return_group_id")

    if not chat_id or not avanpost_user_id:
        await bot_manager.send_toast(
            text="❌ Не удалось определить чат для возврата.",
            event=callback,
            show_alert=True,
        )
        return

    # Восстановление состояния
    from .lists.chat_details import ChatDetailsStates, show_chat_details

    await state.update_data(
        selected_chat_id=chat_id,
        chat_details_page=page,
        avanpost_user_id=avanpost_user_id,
        parent_item_id=parent_item_id,
        group_id=group_id,
    )
    await state.set_state(ChatDetailsStates.viewing_messages)

    # Удаление текущего сообщения с меню
    if callback.message:
        try:
            await callback.message.delete()
        except Exception as e:
            bot_logger.warning(f"⚠️ Could not delete message: {e}")

    # Отображение чата на той же странице
    await show_chat_details(
        event=callback,
        state=state,
        avanpost_user_id=avanpost_user_id,
        chat_id=chat_id,
        page=page,
    )


@router.callback_query(F.data.startswith("msg_back_"))
@log_exceptions(bot_logger)
async def handle_msg_back(callback: CallbackQuery, state: FSMContext) -> None:
    """Возврат к сообщению."""
    message_id = int(callback.data.split("_")[-1])
    await show_message_context_menu(
        event=callback,
        state=state,
        message_id=message_id,
        chat_id=callback.message.chat.id if callback.message else 0,
        edit_original=True,
    )


@router.callback_query(F.data == "msg_close_menu")
@log_exceptions(bot_logger)
async def handle_msg_close_menu(callback: CallbackQuery, state: FSMContext) -> None:
    """Закрытие контекстного меню."""
    bot_manager = get_bot_manager()
    await bot_manager.send_toast(text="❌ Меню закрыто.", event=callback)

    # Очистка временных данных
    await state.update_data(
        return_to_chat_id=None,
        return_to_page=None,
        return_avanpost_user_id=None,
        return_parent_item_id=None,
        return_group_id=None,
    )

    with contextlib.suppress(Exception):
        await callback.message.delete()

    await state.clear()


@router.callback_query(F.data == "msg_cancel_reply")
@log_exceptions(bot_logger)
async def handle_msg_cancel_reply(callback: CallbackQuery, state: FSMContext) -> None:
    """Отмена ответа на сообщение."""
    bot_manager = get_bot_manager()
    await state.clear()
    await bot_manager.send_toast(text="❌ Ответ отменен.", event=callback)

    with contextlib.suppress(Exception):
        await callback.message.delete()


# ============================================================
# ОБРАБОТЧИК ТЕКСТОВЫХ ОТВЕТОВ
# ============================================================


@router.message(ReplyStates.waiting_for_reply_text)
@log_exceptions(bot_logger)
async def handle_reply_text(message: Message, state: FSMContext) -> None:
    """
    Обработка текста ответа на сообщение.

    Args:
        message: Сообщение с текстом ответа
        state: Состояние FSM
    """
    bot_manager = get_bot_manager()

    # Проверка отмены
    if message.text and message.text.lower() in ["/cancel", "отмена", "cancel"]:
        await state.clear()
        await bot_manager.send_answer(
            text="❌ Ответ отменен.",
            event=message,
            message_type=MessageType.COMMAND_ACTION_INFO,
            delete_by_type=MessageActionType.COMMAND_ACTION_CLEANUP,
        )
        return

    data = await state.get_data()
    reply_to_message_id = data.get("reply_to_message_id")
    reply_chat_id = data.get("reply_chat_id")

    if not reply_to_message_id or not reply_chat_id:
        await state.clear()
        await bot_manager.send_answer(
            text="❌ Не найден ID сообщения для ответа.",
            event=message,
            message_type=MessageType.COMMAND_ACTION_INFO,
            delete_by_type=MessageActionType.COMMAND_ACTION_CLEANUP,
        )
        return

    if not message.text or not message.text.strip():
        await bot_manager.send_answer(
            text="❌ Текст ответа не может быть пустым.\n\nВведите текст или /cancel для отмены.",
            event=message,
            message_type=MessageType.COMMAND_ACTION_INFO,
            delete_by_type=MessageActionType.COMMAND_ACTION_CLEANUP,
        )
        return

    # Получение информации о сообщении
    async with db_manager.get_session() as session:
        repo = MessageRepository()
        db_message = await repo.get_message_by_id(session, reply_to_message_id)

        if not db_message:
            await state.clear()
            await bot_manager.send_answer(
                text="❌ Исходное сообщение не найдено.",
                event=message,
                message_type=MessageType.COMMAND_ACTION_INFO,
                delete_by_type=MessageActionType.COMMAND_ACTION_CLEANUP,
            )
            return

        # Отправка ответа
        result = await bot_manager.send_message(
            chat_id=reply_chat_id,
            text=f"📝 **Ответ на сообщение #{reply_to_message_id}**\n\n{message.text}",
            message_type=MessageType.BOT_RESPONSE,
            parse_mode="Markdown",
            reply_to_message_id=reply_to_message_id,
            user_id=message.from_user.id if message.from_user else None,
            user_first_name=message.from_user.first_name if message.from_user else None,
            user_username=message.from_user.username if message.from_user else None,
        )

        if result.get("success"):
            await bot_manager.send_answer(
                text="✅ Ответ отправлен!",
                event=message,
                message_type=MessageType.COMMAND_ACTION_INFO,
                delete_by_type=MessageActionType.COMMAND_ACTION_CLEANUP,
            )
            await bot_manager.delete_message_by_link(message)
        else:
            await bot_manager.send_answer(
                text=f"❌ Ошибка при отправке ответа: {result.get('error', 'неизвестная ошибка')}",
                event=message,
                message_type=MessageType.COMMAND_ACTION_INFO,
                delete_by_type=MessageActionType.COMMAND_ACTION_CLEANUP,
            )

    await state.clear()


# ============================================================
# КОМАНДА /msg (обработчик сообщений)
# ============================================================


@router.message(lambda msg: msg.text and msg.text.startswith("/msg"))
@log_exceptions(bot_logger)
async def cmd_msg(message: Message, state: FSMContext) -> None:
    """
    Команда для открытия контекстного меню сообщения по ID.
    """
    bot_manager = get_bot_manager()

    # Проверка существования пользователя
    if not message.from_user:
        await bot_manager.send_answer(
            text="❌ Не удалось определить пользователя.",
            event=message,
            message_type=MessageType.COMMAND_AUTH,
            delete_by_type=MessageActionType.COMMAND_AUTH_CLEANUP,
        )
        return

    # Разбор аргументов команды
    command_text = message.text or ""
    parts = command_text.split()

    if len(parts) < 2:
        await bot_manager.send_answer(
            text="❌ **Использование:** `/msg <id_сообщения>`\n\n"
            "Например: `/msg 12345`\n"
            "Чтобы узнать ID сообщения, используйте `/id`",
            event=message,
            message_type=MessageType.COMMAND_ACTION_INFO,
            delete_by_type=MessageActionType.COMMAND_ACTION_CLEANUP,
            parse_mode="Markdown",
        )
        return

    try:
        message_id = int(parts[1])
    except ValueError:
        await bot_manager.send_answer(
            text="❌ Неверный ID сообщения. Используйте число.",
            event=message,
            message_type=MessageType.COMMAND_ACTION_INFO,
            delete_by_type=MessageActionType.COMMAND_ACTION_CLEANUP,
        )
        return

    # Проверка, есть ли сообщение в базе данных
    try:
        async with db_manager.get_session() as session:
            repo = MessageRepository()
            db_message = await repo.get_message_by_id(session, message_id)

            if not db_message:
                await bot_manager.send_answer(
                    text=f"❌ Сообщение с ID `{message_id}` не найдено.",
                    event=message,
                    message_type=MessageType.COMMAND_ACTION_INFO,
                    delete_by_type=MessageActionType.COMMAND_ACTION_CLEANUP,
                    parse_mode="Markdown",
                )
                return

            # Открытие контекстного меню для сообщения
            await show_message_context_menu(
                event=message,
                state=state,
                message_id=message_id,
                chat_id=db_message.FK_Chat,
                edit_original=False,
            )

            # Удаление команды
            await bot_manager.delete_message_by_link(message)

    except Exception as e:
        bot_logger.error(f"❌ Error in cmd_msg: {e}", exc_info=True)
        await bot_manager.send_answer(
            text="❌ Ошибка при обработке команды. Попробуйте позже.",
            event=message,
            message_type=MessageType.COMMAND_ACTION_INFO,
            delete_by_type=MessageActionType.COMMAND_ACTION_CLEANUP,
        )


__all__ = [
    "router",
    "show_message_context_menu",
    "handle_reply_text",
    "ReplyStates",
]
