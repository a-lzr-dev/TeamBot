"""Модуль обработчиков для управления массовыми рассылками (Broadcast).

Этот модуль предоставляет полный функционал для работы с рассылками в Telegram боте:

1. ГЛАВНОЕ МЕНЮ РАССЫЛОК (/bc)
   - Отображение меню с доступными действиями
   - Работает как с Message, так и с CallbackQuery

2. СОЗДАНИЕ РАССЫЛКИ (/bc_send)
   - Ввод текста сообщения
   - Подтверждение перед отправкой
   - Отправка во все активные чаты
   - Сохранение истории рассылки в БД
   - Отчет о результате

3. ОТМЕНА РАССЫЛКИ (/bc_del)
   - Выбор рассылки из списка активных
   - Подтверждение отмены
   - Удаление всех сообщений рассылки из Telegram и БД

4. ИСТОРИЯ РАССЫЛОК
   - Просмотр последних 10 рассылок
   - Информация о статусе и статистике

Состояния FSM:
    BroadcastStates:
        - waiting_for_text: Ожидание текста сообщения
        - waiting_for_confirmation: Ожидание подтверждения отправки

    BroadcastCancelStates:
        - selecting: Выбор рассылки для отмены
        - confirming: Подтверждение отмены

Примечания:
    - Все команды доступны только администраторам (проверка через _is_admin)
    - Рассылка сохраняется в БД с полной историей отправленных сообщений
    - Отмена рассылки удаляет все связанные сообщения из Telegram
    - Поддерживается HTML разметка в тексте сообщения
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

# ============================================================
# РОУТЕР И РЕПОЗИТОРИИ
# ============================================================

router = Router(name="aiogram_broadcast")

_broadcast_repo = BroadcastRepository()
_chat_repo = ChatRepository()
_message_repo = MessageRepository()


# ============================================================
# СОСТОЯНИЯ FSM
# ============================================================


class BroadcastStates(StatesGroup):
    """Состояния для создания рассылки."""

    waiting_for_text = State()  # Ожидание текста сообщения
    waiting_for_confirmation = State()  # Ожидание подтверждения отправки


class BroadcastCancelStates(StatesGroup):
    """Состояния для отмены рассылки."""

    selecting = State()  # Выбор рассылки для отмены
    confirming = State()  # Подтверждение отмены


# ============================================================
# ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ
# ============================================================


def _is_admin(user_id: int) -> bool:
    """Проверка, является ли пользователь администратором."""
    return user_id in settings.ADMIN_IDS


async def _broadcast_progress(current: int, total: int) -> None:
    """Callback для отслеживания прогресса рассылки."""
    if current % 10 == 0 or current == total:
        db_logger.debug(f"📊 Broadcast progress: {current}/{total}")


async def _show_no_broadcasts_message(event: Message | CallbackQuery, state: FSMContext) -> None:
    """Показать сообщение "Нет активных рассылок для отмены" с кнопкой "Отмена".

    Работает как с Message, так и с CallbackQuery.
    """
    from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

    bot_manager = get_bot_manager()

    keyboard = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="❌ Отмена", callback_data="bc_menu")]])

    if isinstance(event, Message):
        await bot_manager.send_answer(
            text="📋 Нет активных рассылок для отмены.",
            event=event,
            message_type=MessageType.COMMAND_ADMIN,
            delete_by_type=MessageActionType.COMMAND_ADMIN_CLEANUP,
            reply_markup=keyboard,
        )
    else:  # CallbackQuery
        await bot_manager.edit_callback_message(
            callback=event,
            text="📋 Нет активных рассылок для отмены.",
            reply_markup=keyboard,
        )

    await state.clear()


# ============================================================
# 1. ГЛАВНОЕ МЕНЮ РАССЫЛОК
# ============================================================


async def show_broadcast_menu(event: Message | CallbackQuery) -> None:
    """Отображение главного меню управления рассылками.

    Работает как с Message (команда /bc), так и с CallbackQuery (кнопка "Назад").

    Args:
        event: Message или CallbackQuery
    """
    bot_manager = get_bot_manager()

    # Определение user_id из события
    user_id = (event.from_user.id if event.from_user else 0) if isinstance(event, Message) else event.from_user.id

    if not _is_admin(user_id):
        await bot_manager.send_toast(
            text="⛔ У вас нет прав для этой команды.",
            event=event,
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

    text = (
        "📢 **Управление рассылками**\n\n"
        "Выберите действие:\n"
        "• 📤 **Создать рассылку** — отправить сообщение во все чаты\n"
        "• 🗑️ **Отменить рассылку** — отменить активную рассылку\n"
        "• 📋 **История** — просмотр последних рассылок"
    )

    if isinstance(event, Message):
        await bot_manager.send_answer(
            text=text,
            event=event,
            message_type=MessageType.COMMAND_ADMIN,
            delete_by_type=MessageActionType.COMMAND_ADMIN_CLEANUP,
            parse_mode="Markdown",
            reply_markup=keyboard,
        )
    else:  # CallbackQuery
        if event.message:
            await bot_manager.edit_callback_message(
                callback=event,
                text=text,
                parse_mode="Markdown",
                reply_markup=keyboard,
            )


@router.message(Command("bc"))
@log_exceptions(bot_logger)
async def cmd_bc_menu(message: Message) -> None:
    """Команда /bc — открытие меню управления рассылками."""
    await show_broadcast_menu(message)


# ============================================================
# 2. СОЗДАНИЕ РАССЫЛКИ (/bc_send)
# ============================================================


@router.message(Command("bc_send"))
@log_exceptions(bot_logger)
async def cmd_bc_send(message: Message, state: FSMContext) -> None:
    """Команда /bc_send — начало процесса создания рассылки."""
    bot_manager = get_bot_manager()

    if not message.from_user or not _is_admin(message.from_user.id):
        await bot_manager.send_answer(
            text="⛔ У вас нет прав для этой команды.",
            event=message,
            message_type=MessageType.COMMAND_ADMIN,
            delete_by_type=MessageActionType.COMMAND_ADMIN_CLEANUP,
        )
        return

    await state.set_state(BroadcastStates.waiting_for_text)

    keyboard = InlineKeyboardMarkup(
        inline_keyboard=[[InlineKeyboardButton(text="❌ Отмена", callback_data="bc_cancel_send")]]
    )

    await bot_manager.send_answer(
        text="📤 **Создание рассылки**\n\nОтправьте текст для рассылки во все чаты.\nПоддерживается HTML разметка.",
        event=message,
        message_type=MessageType.COMMAND_ADMIN,
        delete_by_type=MessageActionType.COMMAND_ADMIN_CLEANUP,
        parse_mode="Markdown",
        reply_markup=keyboard,
    )


@router.message(BroadcastStates.waiting_for_text)
@log_exceptions(bot_logger)
async def broadcast_get_text(message: Message, state: FSMContext) -> None:
    """Получение текста для рассылки.

    Ожидает текстовое сообщение от пользователя, проверяет его, подсчитывает количество чатов и переходит к
    подтверждению.
    """
    bot_manager = get_bot_manager()

    if not message.from_user:
        return

    # Обработка отмены через текстовую команду
    if message.text and message.text.lower() in ["/cancel", "отмена", "cancel"]:
        await state.clear()
        await bot_manager.send_answer(
            text="❌ Рассылка отменена.",
            event=message,
            message_type=MessageType.COMMAND_ADMIN,
            delete_by_type=MessageActionType.COMMAND_ADMIN_CLEANUP,
        )
        return

    # Проверка наличия текста
    if not message.text or not message.text.strip():
        await bot_manager.send_answer(
            text="❌ Текст сообщения не может быть пустым.\nПожалуйста, отправьте текст для рассылки.",
            event=message,
            message_type=MessageType.COMMAND_ADMIN,
            delete_by_type=MessageActionType.COMMAND_ADMIN_CLEANUP,
        )
        return

    # Подсчёт активных чатов
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

    # Сохранение данных в состояние
    await state.update_data(
        text=message.text,
        parse_mode="HTML",
        sender_user_id=message.from_user.id,
        sender_first_name=message.from_user.first_name,
        sender_username=message.from_user.username,
    )

    await state.set_state(BroadcastStates.waiting_for_confirmation)

    # Клавиатура подтверждения
    keyboard = InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="✅ Да, отправить", callback_data="bc_confirm"),
                InlineKeyboardButton(text="❌ Нет", callback_data="bc_cancel_send"),
            ]
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
    """Подтверждение отправки рассылки.

    Создает запись в БД, выполняет рассылку, сохраняет связи и показывает результат.
    """
    bot_manager = get_bot_manager()
    await callback.answer()

    # Получение данных из состояния
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

    # 1. Создание записи о рассылке в БД
    async with db_manager.get_session() as session:
        chats = await _chat_repo.get_chats(session, is_active=True)
        chat_count = len(chats)

        broadcast = await _broadcast_repo.create_broadcast(
            session=session,
            user_id=sender_user_id or callback.from_user.id,
            title=text[:100] + ("..." if len(text) > 100 else ""),
            text=text,
            parse_mode=parse_mode,
            total_chats=chat_count,
        )

        await session.commit()

    # 2. Запуск рассылки
    await bot_manager.edit_callback_message(
        callback=callback,
        text="🔄 Начинаю рассылку...",
    )

    result = await bot_manager.broadcast_message(
        text=text,
        parse_mode=parse_mode,
        disable_web_page_preview=True,
        sender_user_id=sender_user_id,
        sender_first_name=sender_first_name,
        sender_username=sender_username,
        progress_callback=_broadcast_progress,
        broadcast_id=broadcast.FID,  # <-- связи сохраняются здесь
    )

    # 3. Обновление статуса рассылки (НЕ СОХРАНЯЕМ СВЯЗИ ПОВТОРНО!)
    async with db_manager.get_session() as session:
        await _broadcast_repo.update_broadcast_status(
            session=session,
            broadcast_id=broadcast.FID,
            status="sent" if result.get("success") else "failed",
            success_count=result.get("successful", 0),
            failed_count=result.get("failed", 0),
        )
        await session.commit()

    # 4. Отчет о результате
    report = (
        f"📊 **Результат рассылки**\n\n"
        f"• ✅ Успешно отправлено: {result['successful']}\n"
        f"• ❌ Ошибок: {result['failed']}\n"
        f"• 📊 Всего чатов: {result['total']}\n"
        f"• 📈 Успешность: {result['successful'] * 100 // result['total'] if result['total'] > 0 else 0}%\n"
        f"• 🆔 ID рассылки: `{broadcast.FID}`"
    )

    result_keyboard = InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="📂 Назад в меню", callback_data="bc_menu"),
                InlineKeyboardButton(text="❌ Закрыть", callback_data="bc_close"),
            ]
        ]
    )

    await bot_manager.edit_callback_message(
        callback=callback,
        text=report,
        parse_mode="Markdown",
        reply_markup=result_keyboard,
    )

    await state.clear()


@router.callback_query(F.data == "bc_cancel_send")
@log_exceptions(bot_logger)
async def bc_cancel_send(callback: CallbackQuery, state: FSMContext) -> None:
    """Отмена создания рассылки — возврат в главное меню."""
    await callback.answer("❌ Рассылка отменена")
    await state.clear()
    await show_broadcast_menu(callback)


# ============================================================
# 3. ОТМЕНА РАССЫЛКИ (/bc_del)
# ============================================================


@router.message(Command("bc_del"))
@log_exceptions(bot_logger)
async def cmd_bc_del(message: Message, state: FSMContext) -> None:
    """Команда /bc_del — отмена существующей рассылки."""
    bot_manager = get_bot_manager()

    if not message.from_user or not _is_admin(message.from_user.id):
        await bot_manager.send_answer(
            text="⛔ У вас нет прав для этой команды.",
            event=message,
            message_type=MessageType.COMMAND_ADMIN,
            delete_by_type=MessageActionType.COMMAND_ADMIN_CLEANUP,
        )
        return

    await state.set_state(BroadcastCancelStates.selecting)

    async with db_manager.get_session() as session:
        broadcasts = await _broadcast_repo.get_recent_broadcasts(
            session=session,
            limit=10,
            include_cancelled=False,
        )

    if not broadcasts:
        await _show_no_broadcasts_message(message, state)
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
    """Подтверждение отмены рассылки с удалением всех сообщений."""
    from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

    bot_manager = get_bot_manager()
    await callback.answer("🔄 Отмена рассылки...")

    broadcast_id = int(callback.data.split("_")[3])

    async with db_manager.get_session() as session:
        broadcast = await _broadcast_repo.get_broadcast_by_id(session, broadcast_id)

        if not broadcast:
            await bot_manager.send_toast(
                text="❌ Рассылка не найдена.",
                event=callback,
            )
            return

        # Если уже отменена
        if broadcast.FStatus == "cancelled":
            keyboard = InlineKeyboardMarkup(
                inline_keyboard=[
                    [
                        InlineKeyboardButton(text="📂 Назад в меню", callback_data="bc_menu"),
                        InlineKeyboardButton(text="❌ Закрыть", callback_data="bc_close"),
                    ]
                ]
            )
            await bot_manager.edit_callback_message(
                callback=callback,
                text=f"ℹ️ **Рассылка #{broadcast_id} уже была отменена.**",
                parse_mode="Markdown",
                reply_markup=keyboard,
            )
            await state.clear()
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

        await _broadcast_repo.force_cancel_broadcast(
            session=session,
            broadcast_id=broadcast_id,
            cancelled_by=callback.from_user.id,
        )

        await session.commit()

    # Клавиатура с кнопками
    keyboard = InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="📂 Назад в меню", callback_data="bc_menu"),
                InlineKeyboardButton(text="❌ Закрыть", callback_data="bc_close"),
            ]
        ]
    )

    await bot_manager.edit_callback_message(
        callback=callback,
        text=f"✅ **Рассылка #{broadcast_id} отменена!**\n\n"
        f"🗑️ Удалено сообщений: {deleted_count}\n"
        f"📊 Всего было отправлено: {broadcast.FSuccessCount}",
        parse_mode="Markdown",
        reply_markup=keyboard,
    )

    await state.clear()


@router.callback_query(F.data == "bc_cancel_list")
@log_exceptions(bot_logger)
async def bc_cancel_list(callback: CallbackQuery, state: FSMContext) -> None:
    """Возврат в меню рассылок (отмена выбора)."""
    await callback.answer("❌ Отмена")
    await state.clear()
    await show_broadcast_menu(callback)


# ============================================================
# 4. ИСТОРИЯ РАССЫЛОК
# ============================================================


@router.callback_query(F.data == "bc_history")
@log_exceptions(bot_logger)
async def bc_history(callback: CallbackQuery) -> None:
    """Просмотр истории последних 10 рассылок."""
    bot_manager = get_bot_manager()
    await callback.answer()

    if not _is_admin(callback.from_user.id):
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

    # Клавиатура навигации (всегда показывается)
    keyboard = InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="📂 Назад в меню", callback_data="bc_menu"),
                InlineKeyboardButton(text="❌ Закрыть", callback_data="bc_close"),
            ]
        ]
    )

    if not broadcasts:
        await bot_manager.edit_callback_message(
            callback=callback,
            text="📋 История рассылок пуста.",
            reply_markup=keyboard,
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

    await bot_manager.edit_callback_message(
        callback=callback,
        text=text,
        parse_mode="Markdown",
        reply_markup=keyboard,
    )


# ============================================================
# 5. ОБЩИЕ ОБРАБОТЧИКИ (переходы из меню)
# ============================================================


@router.callback_query(F.data == "bc_menu")
@log_exceptions(bot_logger)
async def bc_menu_callback(callback: CallbackQuery, state: FSMContext) -> None:
    """Возврат в главное меню рассылок (из колбэка)."""
    await callback.answer()
    await state.clear()
    await show_broadcast_menu(callback)


@router.callback_query(F.data == "bc_create")
@log_exceptions(bot_logger)
async def bc_create_callback(callback: CallbackQuery, state: FSMContext) -> None:
    """Переход к созданию рассылки из меню."""
    bot_manager = get_bot_manager()
    await callback.answer()

    if not _is_admin(callback.from_user.id):
        await bot_manager.send_toast(
            text="⛔ У вас нет прав.",
            event=callback,
        )
        return

    await state.set_state(BroadcastStates.waiting_for_text)

    keyboard = InlineKeyboardMarkup(
        inline_keyboard=[[InlineKeyboardButton(text="❌ Отмена", callback_data="bc_cancel_send")]]
    )

    await bot_manager.edit_callback_message(
        callback=callback,
        text="📤 **Создание рассылки**\n\nОтправьте текст для рассылки во все чаты.\nПоддерживается HTML разметка.",
        parse_mode="Markdown",
        reply_markup=keyboard,
    )


@router.callback_query(F.data == "bc_cancel")
@log_exceptions(bot_logger)
async def bc_cancel_callback(callback: CallbackQuery, state: FSMContext) -> None:
    """Переход к отмене рассылки из меню."""
    bot_manager = get_bot_manager()
    await callback.answer()

    if not _is_admin(callback.from_user.id):
        await bot_manager.send_toast(
            text="⛔ У вас нет прав.",
            event=callback,
        )
        return

    await state.set_state(BroadcastCancelStates.selecting)

    async with db_manager.get_session() as session:
        broadcasts = await _broadcast_repo.get_recent_broadcasts(
            session=session,
            limit=10,
            include_cancelled=False,
        )

    if not broadcasts:
        await _show_no_broadcasts_message(callback, state)
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

    buttons.append([InlineKeyboardButton(text="❌ Отмена", callback_data="bc_cancel_list")])
    keyboard = InlineKeyboardMarkup(inline_keyboard=buttons)

    await bot_manager.edit_callback_message(
        callback=callback,
        text="🗑️ **Отмена рассылки**\n\n"
        "Выберите рассылку для отмены:\n"
        "🟢 — выполнена, 🔵 — в процессе\n\n"
        "⚠️ **Внимание:** Отмена удалит все сообщения этой рассылки из чатов!",
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
