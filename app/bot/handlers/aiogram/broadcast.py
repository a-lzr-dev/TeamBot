"""
Модуль обработчиков для управления рассылками.
"""

from aiogram import F, Router
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message

from ....bot.dependencies import get_bot_manager
from ....config import settings
from ....db import db_manager
from ....db.repositories import BroadcastRepository, ChatRepository, MessageRepository
from ....logger import bot_logger, db_logger
from ....models import MessageActionType, MessageType
from ....utils.decorators import log_exceptions

router = Router(name="aiogram_broadcast")

# Репозитории
_broadcast_repo = BroadcastRepository()
_chat_repo = ChatRepository()
_message_repo = MessageRepository()


class BroadcastStates(StatesGroup):
    """Состояния для создания рассылки."""

    waiting_for_text = State()
    waiting_for_confirmation = State()


class BroadcastCancelStates(StatesGroup):
    """Состояния для отмены рассылки."""

    selecting = State()
    confirming = State()


# Вспомогательная функция для прогресса
async def _broadcast_progress(current: int, total: int) -> None:
    """Функция обратного вызова для отслеживания прогресса рассылки."""
    if current % 10 == 0 or current == total:
        db_logger.debug(f"📊 Broadcast progress: {current}/{total}")


# ============================================================
# КОМАНДА /bc — МЕНЮ РАССЫЛКИ
# ============================================================


@router.message(Command("bc"))
@log_exceptions(bot_logger)
async def cmd_bc_menu(message: Message) -> None:
    """Меню управления рассылками."""
    bot_manager = get_bot_manager()

    if not message.from_user or message.from_user.id not in settings.ADMIN_IDS:
        await bot_manager.send_answer(
            text="⛔ У вас нет прав для этой команды.",
            event=message,
            message_type=MessageType.COMMAND_ADMIN,
            delete_by_type=MessageActionType.COMMAND_ADMIN_CLEANUP,
        )
        return

    keyboard = InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="📤 Создать рассылку", callback_data="bc_create")],
            [InlineKeyboardButton(text="🗑️ Отменить рассылку", callback_data="bc_cancel")],
            [InlineKeyboardButton(text="📋 История рассылок", callback_data="bc_history")],
            [InlineKeyboardButton(text="❌ Закрыть", callback_data="bc_close")],
        ]
    )

    await bot_manager.send_answer(
        text="📢 **Управление рассылками**\n\n"
        "Выберите действие:\n"
        "• 📤 **Создать рассылку** — отправить сообщение во все чаты\n"
        "• 🗑️ **Отменить рассылку** — отменить активную рассылку\n"
        "• 📋 **История** — просмотр последних рассылок",
        event=message,
        message_type=MessageType.COMMAND_ADMIN,
        delete_by_type=MessageActionType.COMMAND_ADMIN_CLEANUP,
        parse_mode="Markdown",
        reply_markup=keyboard,
    )


# ============================================================
# КОМАНДА /bc_send — СОЗДАНИЕ РАССЫЛКИ
# ============================================================


@router.message(Command("bc_send"))
@log_exceptions(bot_logger)
async def cmd_bc_send(message: Message, state: FSMContext) -> None:
    """Создание новой рассылки."""
    bot_manager = get_bot_manager()

    if not message.from_user or message.from_user.id not in settings.ADMIN_IDS:
        await bot_manager.send_answer(
            text="⛔ У вас нет прав для этой команды.",
            event=message,
            message_type=MessageType.COMMAND_ADMIN,
            delete_by_type=MessageActionType.COMMAND_ADMIN_CLEANUP,
        )
        return

    await state.set_state(BroadcastStates.waiting_for_text)

    await bot_manager.send_answer(
        text="📤 **Создание рассылки**\n\n"
        "Отправьте текст для рассылки во все чаты.\n"
        "Поддерживается HTML разметка.\n\n"
        "Для отмены используйте /cancel",
        event=message,
        message_type=MessageType.COMMAND_ADMIN,
        delete_by_type=MessageActionType.COMMAND_ADMIN_CLEANUP,
        parse_mode="Markdown",
    )


@router.message(BroadcastStates.waiting_for_text)
@log_exceptions(bot_logger)
async def broadcast_get_text(message: Message, state: FSMContext) -> None:
    """Получение текста для рассылки."""
    bot_manager = get_bot_manager()

    if not message.from_user:
        return

    if message.text and message.text.lower() in ["/cancel", "отмена", "cancel"]:
        await state.clear()
        await bot_manager.send_answer(
            text="❌ Рассылка отменена.",
            event=message,
            message_type=MessageType.COMMAND_ADMIN,
            delete_by_type=MessageActionType.COMMAND_ADMIN_CLEANUP,
        )
        return

    if not message.text or not message.text.strip():
        await bot_manager.send_answer(
            text="❌ Текст сообщения не может быть пустым.\nПожалуйста, отправьте текст для рассылки.",
            event=message,
            message_type=MessageType.COMMAND_ADMIN,
            delete_by_type=MessageActionType.COMMAND_ADMIN_CLEANUP,
        )
        return

    # Подсчёт чатов
    async with db_manager.get_session() as session:
        chats = await _chat_repo.get_chats(session, is_active=True)
        chat_count = len(chats)

    if chat_count == 0:
        await state.clear()
        await bot_manager.send_answer(
            text="❌ Нет активных чатов для рассылки.",
            event=message,
            message_type=MessageType.COMMAND_ADMIN,
            delete_by_type=MessageActionType.COMMAND_ADMIN_CLEANUP,
        )
        return

    # Сохранение данных
    await state.update_data(
        text=message.text,
        parse_mode="HTML",
        sender_user_id=message.from_user.id,
        sender_first_name=message.from_user.first_name,
        sender_username=message.from_user.username,
    )

    await state.set_state(BroadcastStates.waiting_for_confirmation)

    keyboard = InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="✅ Да, отправить", callback_data="bc_confirm")],
            [InlineKeyboardButton(text="❌ Отмена", callback_data="bc_cancel_send")],
        ]
    )

    await bot_manager.send_answer(
        text=f"📊 **Подтверждение рассылки**\n\n"
        f"Текст будет отправлен в **{chat_count}** чатов.\n\n"
        f"Текст сообщения:\n"
        f"```\n{message.text[:200]}{'...' if len(message.text) > 200 else ''}\n```\n\n"
        f"Отправить?",
        event=message,
        message_type=MessageType.COMMAND_ADMIN,
        delete_by_type=MessageActionType.COMMAND_ADMIN_CLEANUP,
        parse_mode="Markdown",
        reply_markup=keyboard,
    )


@router.callback_query(F.data == "bc_confirm")
@log_exceptions(bot_logger)
async def bc_confirm_send(callback: CallbackQuery, state: FSMContext) -> None:
    """Подтверждение отправки рассылки."""
    bot_manager = get_bot_manager()
    await callback.answer()

    data = await state.get_data()
    text = data.get("text")
    parse_mode = data.get("parse_mode", "HTML")
    sender_user_id = data.get("sender_user_id")
    sender_first_name = data.get("sender_first_name")
    sender_username = data.get("sender_username")

    if not text:
        await bot_manager.edit_callback_message(
            callback=callback,
            text="❌ Текст сообщения не найден.",
        )
        await state.clear()
        return

    # Создание записи о рассылке в БД
    async with db_manager.get_session() as session:
        # Подсчёт чатов
        chats = await _chat_repo.get_chats(session, is_active=True)
        chat_count = len(chats)

        # Создание рассылки
        broadcast = await _broadcast_repo.create_broadcast(
            session=session,
            user_id=sender_user_id or callback.from_user.id,
            title=text[:100] + ("..." if len(text) > 100 else ""),
            text=text,
            parse_mode=parse_mode,
            total_chats=chat_count,
        )

        await session.commit()

    # Обновление сообщения
    await bot_manager.edit_callback_message(
        callback=callback,
        text="🔄 Начинаю рассылку...",
    )

    # Выполнение рассылки
    result = await bot_manager.broadcast_message(
        text=text,
        parse_mode=parse_mode,
        disable_web_page_preview=True,
        sender_user_id=sender_user_id,
        sender_first_name=sender_first_name,
        sender_username=sender_username,
        progress_callback=_broadcast_progress,
    )

    # Сохранение связей с сообщениями
    async with db_manager.get_session() as session:
        # Обновление статуса рассылки
        await _broadcast_repo.update_broadcast_status(
            session=session,
            broadcast_id=broadcast.FID,
            status="sent",
            success_count=result.get("successful", 0),
            failed_count=result.get("failed", 0),
        )

        # Получение ID сообщений из результата (нужно модифицировать broadcast_message)
        # Для каждого успешного чата нужно сохранить связь
        # Это требует модификации broadcast_message для возврата message_ids

        await session.commit()

    # Формирование отчета
    report = (
        f"📊 **Результат рассылки**\n\n"
        f"• ✅ Успешно отправлено: {result['successful']}\n"
        f"• ❌ Ошибок: {result['failed']}\n"
        f"• 📊 Всего чатов: {result['total']}\n"
        f"• 📈 Успешность: {result['successful'] * 100 // result['total'] if result['total'] > 0 else 0}%\n"
        f"• 🆔 ID рассылки: `{broadcast.FID}`"
    )

    await bot_manager.edit_callback_message(
        callback=callback,
        text=report,
        parse_mode="Markdown",
    )

    await state.clear()


@router.callback_query(F.data == "bc_cancel_send")
@log_exceptions(bot_logger)
async def bc_cancel_send(callback: CallbackQuery, state: FSMContext) -> None:
    """Отмена создания рассылки."""
    await callback.answer("❌ Рассылка отменена")
    await state.clear()
    await callback.message.delete()


# ============================================================
# КОМАНДА /bc_del — ОТМЕНА РАССЫЛКИ
# ============================================================


@router.message(Command("bc_del"))
@log_exceptions(bot_logger)
async def cmd_bc_del(message: Message, state: FSMContext) -> None:
    """Отмена рассылки."""
    bot_manager = get_bot_manager()

    if not message.from_user or message.from_user.id not in settings.ADMIN_IDS:
        await bot_manager.send_answer(
            text="⛔ У вас нет прав для этой команды.",
            event=message,
            message_type=MessageType.COMMAND_ADMIN,
            delete_by_type=MessageActionType.COMMAND_ADMIN_CLEANUP,
        )
        return

    await state.set_state(BroadcastCancelStates.selecting)

    # Получение последних рассылок
    async with db_manager.get_session() as session:
        broadcasts = await _broadcast_repo.get_recent_broadcasts(
            session=session,
            limit=10,
            include_cancelled=False,
        )

    if not broadcasts:
        await bot_manager.send_answer(
            text="📋 Нет активных рассылок для отмены.",
            event=message,
            message_type=MessageType.COMMAND_ADMIN,
            delete_by_type=MessageActionType.COMMAND_ADMIN_CLEANUP,
        )
        await state.clear()
        return

    # Формирование клавиатуры со списком рассылок
    buttons = []
    for bc in broadcasts:
        status_emoji = "✅" if bc.FStatus == "sent" else "⏳"
        buttons.append(
            [
                InlineKeyboardButton(
                    text=f"{status_emoji} #{bc.FID} — {bc.FTitle[:30]} ({bc.FSuccessCount}/{bc.FTotalChats})",
                    callback_data=f"bc_select_{bc.FID}",
                )
            ]
        )

    buttons.append([InlineKeyboardButton(text="❌ Отмена", callback_data="bc_cancel_list")])

    keyboard = InlineKeyboardMarkup(inline_keyboard=buttons)

    await bot_manager.send_answer(
        text="🗑️ **Отмена рассылки**\n\n"
        "Выберите рассылку для отмены:\n"
        "🟢 — выполнена, 🔵 — в процессе\n\n"
        "⚠️ **Внимание:** Отмена удалит все сообщения этой рассылки из чатов!",
        event=message,
        message_type=MessageType.COMMAND_ADMIN,
        delete_by_type=MessageActionType.COMMAND_ADMIN_CLEANUP,
        parse_mode="Markdown",
        reply_markup=keyboard,
    )


@router.callback_query(F.data.startswith("bc_select_"))
@log_exceptions(bot_logger)
async def bc_select_broadcast(callback: CallbackQuery, state: FSMContext) -> None:
    """Выбор рассылки для отмены."""
    bot_manager = get_bot_manager()
    await callback.answer()

    broadcast_id = int(callback.data.split("_")[2])

    # Получение информации о рассылке
    async with db_manager.get_session() as session:
        broadcast = await _broadcast_repo.get_broadcast_by_id(session, broadcast_id)
        if not broadcast:
            await bot_manager.send_toast(
                text="❌ Рассылка не найдена.",
                event=callback,
            )
            return

        messages = await _broadcast_repo.get_broadcast_messages(session, broadcast_id)

    # Запрос подтверждения
    keyboard = InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="✅ Да, отменить",
                    callback_data=f"bc_confirm_cancel_{broadcast_id}",
                ),
                InlineKeyboardButton(
                    text="❌ Нет",
                    callback_data="bc_cancel_list",
                ),
            ]
        ]
    )

    await bot_manager.edit_callback_message(
        callback=callback,
        text=f"⚠️ **Подтверждение отмены рассылки #{broadcast_id}**\n\n"
        f"📝 **Тема:** {broadcast.FTitle}\n"
        f"📊 **Отправлено:** {broadcast.FSuccessCount}/{broadcast.FTotalChats} чатов\n"
        f"📨 **Сообщений:** {len(messages)}\n\n"
        f"⚠️ **Это действие необратимо!**\n"
        f"Все сообщения этой рассылки будут удалены из чатов.",
        parse_mode="Markdown",
        reply_markup=keyboard,
    )


@router.callback_query(F.data.startswith("bc_confirm_cancel_"))
@log_exceptions(bot_logger)
async def bc_confirm_cancel(callback: CallbackQuery, state: FSMContext) -> None:
    """Подтверждение отмены рассылки."""
    bot_manager = get_bot_manager()
    await callback.answer("🔄 Отмена рассылки...")

    broadcast_id = int(callback.data.split("_")[3])

    async with db_manager.get_session() as session:
        # Получение рассылки
        broadcast = await _broadcast_repo.get_broadcast_by_id(session, broadcast_id)
        if not broadcast:
            await bot_manager.send_toast(
                text="❌ Рассылка не найдена.",
                event=callback,
            )
            return

        # Получение всех связанных сообщений
        links = await _broadcast_repo.get_broadcast_messages(session, broadcast_id)

        # Удаление сообщений из Telegram
        deleted_count = 0
        for link in links:
            try:
                result = await bot_manager.delete_message_by_id(
                    chat_id=link.FK_Chat,
                    message_id=link.FK_Message,
                )
                if result.get("success"):
                    deleted_count += 1
            except Exception as e:
                bot_logger.warning(f"⚠️ Failed to delete message {link.FK_Message}: {e}")

        # Отметка сообщений как удалённых в БД
        await _broadcast_repo.mark_messages_deleted(session, broadcast_id)

        # Отмена рассылки
        await _broadcast_repo.cancel_broadcast(
            session=session,
            broadcast_id=broadcast_id,
            cancelled_by=callback.from_user.id,
        )

        await session.commit()

    await bot_manager.edit_callback_message(
        callback=callback,
        text=f"✅ **Рассылка #{broadcast_id} отменена!**\n\n"
        f"🗑️ Удалено сообщений: {deleted_count}\n"
        f"📊 Всего было отправлено: {broadcast.FSuccessCount}",
        parse_mode="Markdown",
    )

    await state.clear()


@router.callback_query(F.data == "bc_cancel_list")
@log_exceptions(bot_logger)
async def bc_cancel_list(callback: CallbackQuery, state: FSMContext) -> None:
    """Возврат к списку рассылок."""
    bot_manager = get_bot_manager()
    await callback.answer()

    await state.set_state(BroadcastCancelStates.selecting)

    # Повторный показ списка
    async with db_manager.get_session() as session:
        broadcasts = await _broadcast_repo.get_recent_broadcasts(
            session=session,
            limit=10,
            include_cancelled=False,
        )

    if not broadcasts:
        await bot_manager.edit_callback_message(
            callback=callback,
            text="📋 Нет активных рассылок для отмены.",
        )
        await state.clear()
        return

    buttons = []
    for bc in broadcasts:
        status_emoji = "✅" if bc.FStatus == "sent" else "⏳"
        buttons.append(
            [
                InlineKeyboardButton(
                    text=f"{status_emoji} #{bc.FID} — {bc.FTitle[:30]} ({bc.FSuccessCount}/{bc.FTotalChats})",
                    callback_data=f"bc_select_{bc.FID}",
                )
            ]
        )

    buttons.append([InlineKeyboardButton(text="❌ Закрыть", callback_data="bc_close")])
    keyboard = InlineKeyboardMarkup(inline_keyboard=buttons)

    await bot_manager.edit_callback_message(
        callback=callback,
        text="🗑️ **Отмена рассылки**\n\nВыберите рассылку для отмены:",
        parse_mode="Markdown",
        reply_markup=keyboard,
    )


# ============================================================
# ОБЩИЕ ОБРАБОТЧИКИ
# ============================================================


@router.callback_query(F.data == "bc_create")
@log_exceptions(bot_logger)
async def bc_create_callback(callback: CallbackQuery, state: FSMContext) -> None:
    """Создание рассылки через меню."""
    bot_manager = get_bot_manager()
    await callback.answer()

    # Проверка прав
    if callback.from_user.id not in settings.ADMIN_IDS:
        await bot_manager.send_toast(
            text="⛔ У вас нет прав.",
            event=callback,
        )
        return

    # Переход в режим создания рассылки
    await state.set_state(BroadcastStates.waiting_for_text)

    await bot_manager.edit_callback_message(
        callback=callback,
        text="📤 **Создание рассылки**\n\n"
        "Отправьте текст для рассылки во все чаты.\n"
        "Поддерживается HTML разметка.\n\n"
        "Для отмены используйте /cancel",
        parse_mode="Markdown",
    )


@router.callback_query(F.data == "bc_history")
@log_exceptions(bot_logger)
async def bc_history(callback: CallbackQuery) -> None:
    """История рассылок."""
    bot_manager = get_bot_manager()
    await callback.answer()

    if callback.from_user.id not in settings.ADMIN_IDS:
        await bot_manager.send_toast(
            text="⛔ У вас нет прав.",
            event=callback,
        )
        return

    async with db_manager.get_session() as session:
        broadcasts = await _broadcast_repo.get_recent_broadcasts(
            session=session,
            limit=10,
            include_cancelled=True,
        )

    if not broadcasts:
        await bot_manager.edit_callback_message(
            callback=callback,
            text="📋 История рассылок пуста.",
        )
        return

    text = "📋 **История рассылок**\n\n"
    for bc in broadcasts:
        status_emoji = {
            "pending": "⏳",
            "sent": "✅",
            "cancelled": "❌",
            "failed": "⚠️",
        }.get(bc.FStatus, "❓")

        text += (
            f"{status_emoji} **#{bc.FID}** — {bc.FTitle}\n"
            f"   📅 {bc.FCreatedAt.strftime('%d.%m.%Y %H:%M')}\n"
            f"   📊 {bc.FSuccessCount}/{bc.FTotalChats} чатов\n"
            f"   📌 Статус: {bc.FStatus.upper()}\n\n"
        )

    keyboard = InlineKeyboardMarkup(
        inline_keyboard=[[InlineKeyboardButton(text="❌ Закрыть", callback_data="bc_close")]]
    )

    await bot_manager.edit_callback_message(
        callback=callback,
        text=text,
        parse_mode="Markdown",
        reply_markup=keyboard,
    )


@router.callback_query(F.data == "bc_close")
@log_exceptions(bot_logger)
async def bc_close(callback: CallbackQuery, state: FSMContext) -> None:
    """Закрытие меню рассылок."""
    await callback.answer("❌ Меню закрыто")
    await state.clear()
    await callback.message.delete()


__all__ = [
    "router",
]
