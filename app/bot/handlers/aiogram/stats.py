"""
Модуль обработчика команды /stats для бота.

Предоставляет интерактивное меню статистики с подкомандами:

Доступные виды статистики (для всех авторизованных пользователей):
- 📊 /stats_full - Полная статистика системы
- 💬 /stats_chats - Статистика чатов
- 👤 /stats_users - Статистика пользователей
- 💬 /stats_messages - Статистика сообщений

Доступно только для администраторов:
- 🚨 /stats_errors - Статистика ошибок
- ⏰ /stats_reminders - Статистика напоминаний
- 🤖 /stats_automation - Статистика заявок на автоматизацию
- 💻 /stats_system - Системная статистика
- 🗄️ /stats_db - Статистика таблиц БД (количество записей)

Команда /stats открывает интерактивное меню, где пользователь может выбрать
нужный вид статистики. Для администраторов в меню отображаются дополнительные пункты.
"""

from typing import Any

from aiogram import Router
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message

from ....bot.dependencies import get_bot_manager
from ....bot.manager import BotManager
from ....config import settings
from ....db import db_manager
from ....db.repositories import StatsRepository
from ....logger import bot_logger
from ....models import MessageActionType, MessageType, datetime_now
from ....utils.decorators import log_exceptions
from .auth import is_user_authenticated

# ============================================================
# РОУТЕР И РЕПОЗИТОРИЙ
# ============================================================

router = Router(name="aiogram_stats")
_stats_repo = StatsRepository()


# ============================================================
# СОСТОЯНИЯ FSM
# ============================================================


class StatsStates(StatesGroup):
    """Состояния для меню статистики."""

    menu = State()


# ============================================================
# ФУНКЦИИ ФОРМАТИРОВАНИЯ
# ============================================================


def _format_uptime(seconds: float | None) -> str:
    """
    Форматирование времени работы (uptime).

    Args:
        seconds: Время в секундах

    Returns:
        str: Отформатированное время (дни, часы, минуты)
    """
    if seconds is None:
        return "N/A"

    days = int(seconds // 86400)
    hours = int((seconds % 86400) // 3600)
    minutes = int((seconds % 3600) // 60)

    if days > 0:
        return f"{days}д {hours}ч {minutes}м"
    elif hours > 0:
        return f"{hours}ч {minutes}м"
    else:
        return f"{minutes}м"


# ============================================================
# ОСНОВНАЯ КОМАНДА /stats - МЕНЮ
# ============================================================


@router.message(Command("stats"))
@log_exceptions(bot_logger)
async def cmd_stats_menu(message: Message, state: FSMContext) -> None:
    """
    Команда /stats — открытие интерактивного меню статистики.

    Отображает меню с доступными видами статистики.
    Для администраторов доступны дополнительные пункты.

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
    # is_admin = user_id in settings.ADMIN_IDS

    # Проверка авторизации
    if not await is_user_authenticated(user_id):
        await bot_manager.send_answer(
            text="🔐 **Требуется авторизация**\n\n"
            "Для получения статистики необходимо авторизоваться.\n"
            "Используйте /start для начала авторизации.",
            event=message,
            message_type=MessageType.COMMAND_ACTION_INFO,
            delete_by_type=MessageActionType.COMMAND_ACTION_CLEANUP,
            parse_mode="Markdown",
        )
        return

    await show_stats_menu(message, state, bot_manager)


# ============================================================
# ФУНКЦИЯ ПОКАЗА МЕНЮ
# ============================================================


async def show_stats_menu(
    event: Message | CallbackQuery,
    state: FSMContext,
    bot_manager: BotManager,
) -> None:
    """
    Показ меню статистики.

    Args:
        event: Сообщение или CallbackQuery
        state: Состояние FSM
        bot_manager: Менеджер бота
    """
    # Определяем пользователя
    if isinstance(event, Message):
        user_id = event.from_user.id if event.from_user else 0
    else:  # CallbackQuery
        user_id = event.from_user.id if event.from_user else 0

    is_admin = user_id in settings.ADMIN_IDS

    # Формирование клавиатуры меню
    buttons: list[list[InlineKeyboardButton]] = [
        [InlineKeyboardButton(text="📊 Полная статистика", callback_data="stats_full")],
        [InlineKeyboardButton(text="💬 Статистика чатов", callback_data="stats_chats")],
        [InlineKeyboardButton(text="👤 Статистика пользователей", callback_data="stats_users")],
        [InlineKeyboardButton(text="💬 Статистика сообщений", callback_data="stats_messages")],
    ]

    # Для администраторов добавляем дополнительные пункты
    if is_admin:
        buttons.extend(
            [
                [InlineKeyboardButton(text="🚨 Статистика ошибок", callback_data="stats_errors")],
                [InlineKeyboardButton(text="⏰ Статистика напоминаний", callback_data="stats_reminders")],
                [InlineKeyboardButton(text="🤖 Статистика автоматизации", callback_data="stats_automation")],
                [InlineKeyboardButton(text="💻 Системная статистика", callback_data="stats_system")],
                [InlineKeyboardButton(text="🗄️ Статистика БД", callback_data="stats_db")],
            ]
        )

    buttons.append([InlineKeyboardButton(text="❌ Закрыть", callback_data="stats_close")])

    keyboard = InlineKeyboardMarkup(inline_keyboard=buttons)

    # Устанавливаем состояние
    await state.set_state(StatsStates.menu)

    text = (
        "📊 **Меню статистики**\n\n"
        "Выберите вид статистики:\n\n"
        "• 📊 Полная статистика — общая информация о системе\n"
        "• 💬 Чаты — количество и активность чатов\n"
        "• 👤 Пользователи — авторизованные и активные пользователи\n"
        "• 💬 Сообщения — статистика по типам и времени жизни"
    )

    # Отправка в зависимости от типа события
    if isinstance(event, Message):
        await bot_manager.send_answer(
            text=text,
            event=event,
            message_type=MessageType.COMMAND_ACTION_INFO,
            delete_by_type=MessageActionType.COMMAND_ACTION_CLEANUP,
            parse_mode="Markdown",
            reply_markup=keyboard,
        )
    else:  # CallbackQuery
        await bot_manager.edit_callback_message(
            callback=event,
            text=text,
            parse_mode="Markdown",
            reply_markup=keyboard,
        )


# ============================================================
# ОБРАБОТЧИКИ КОЛБЭКОВ МЕНЮ
# ============================================================


@router.callback_query(StatsStates.menu)
@log_exceptions(bot_logger)
async def handle_stats_callback(callback: CallbackQuery, state: FSMContext) -> None:
    """
    Обработка колбэков меню статистики.

    Определяет выбранный вид статистики и вызывает соответствующий обработчик.
    ВАЖНО: Этот обработчик перехватывает ВСЕ callback-запросы в состоянии StatsStates.menu,
    поэтому здесь нужно обрабатывать ВСЕ возможные callback_data.
    """
    bot_logger.debug("🔍 [handle_stats_callback] CALLED")
    bot_logger.debug(f"🔍 [handle_stats_callback] callback.data = {callback.data}")

    bot_manager = get_bot_manager()

    if not callback.from_user:
        await bot_manager.send_toast(text="❌ Не удалось определить пользователя.", event=callback)
        return

    user_id = callback.from_user.id
    is_admin = user_id in settings.ADMIN_IDS

    callback_data = callback.data

    # ============================================================
    # 1. ОБРАБОТКА ВОЗВРАТА В МЕНЮ (stats_back_to_menu)
    # ============================================================
    if callback_data == "stats_back_to_menu":
        bot_logger.debug("🔍 [handle_stats_callback] Handling stats_back_to_menu")
        await callback.answer()
        await show_stats_menu(callback, state, bot_manager)
        return

    # ============================================================
    # 2. ОБРАБОТКА ЗАКРЫТИЯ МЕНЮ
    # ============================================================
    if callback_data == "stats_close":
        await state.clear()
        await bot_manager.send_toast(text="❌ Меню закрыто.", event=callback)
        if callback.message:
            await callback.message.delete()
        return

    # ============================================================
    # 3. ПРОВЕРКА ПРАВ ДЛЯ АДМИНИСТРАТИВНЫХ КОМАНД
    # ============================================================
    admin_stats = ["stats_errors", "stats_reminders", "stats_automation", "stats_system", "stats_db"]
    if callback_data in admin_stats and not is_admin:
        await bot_manager.send_toast(text="⛔ У вас нет прав для этой статистики.", event=callback)
        return

    # ============================================================
    # 4. КАРТА ОБРАБОТЧИКОВ СТАТИСТИКИ
    # ============================================================
    handlers: dict[str, Any] = {
        "stats_full": _show_full_stats,
        "stats_chats": _show_chats_stats,
        "stats_users": _show_users_stats,
        "stats_messages": _show_messages_stats,
        "stats_errors": _show_errors_stats,
        "stats_reminders": _show_reminders_stats,
        "stats_automation": _show_automation_stats,
        "stats_system": _show_system_stats,
        "stats_db": _show_db_stats,
    }

    handler = handlers.get(callback_data)
    if handler:
        await handler(callback, state, bot_manager)
    else:
        bot_logger.warning(f"⚠️ Unknown callback data in stats menu: {callback_data}")
        await bot_manager.send_toast(text="❌ Неизвестное действие.", event=callback)


# ============================================================
# ОБРАБОТЧИКИ КОНКРЕТНЫХ СТАТИСТИК
# ============================================================


async def _show_full_stats(callback: CallbackQuery, state: FSMContext, bot_manager: BotManager) -> None:
    """Показ полной статистики системы."""
    await bot_manager.send_toast(text="⏳ Загрузка полной статистики...", event=callback)

    try:
        async with db_manager.get_session() as session:
            full_stats = await _stats_repo.get_full_stats(session)

        response = _format_full_stats(full_stats)
        await _send_stats_response(callback, response, bot_manager)

    except Exception as e:
        bot_logger.error(f"❌ Failed to get full stats: {e}", exc_info=True)
        await bot_manager.send_toast(text="❌ Ошибка загрузки статистики.", event=callback)


async def _show_chats_stats(callback: CallbackQuery, state: FSMContext, bot_manager: BotManager) -> None:
    """Показ статистики чатов."""
    await bot_manager.send_toast(text="⏳ Загрузка статистики чатов...", event=callback)

    try:
        async with db_manager.get_session() as session:
            stats = await _stats_repo.get_chats_stats(session)

        response = _format_chats_stats(stats)
        await _send_stats_response(callback, response, bot_manager)

    except Exception as e:
        bot_logger.error(f"❌ Failed to get chats stats: {e}", exc_info=True)
        await bot_manager.send_toast(text="❌ Ошибка загрузки статистики.", event=callback)


async def _show_users_stats(callback: CallbackQuery, state: FSMContext, bot_manager: BotManager) -> None:
    """Показ статистики пользователей."""
    await bot_manager.send_toast(text="⏳ Загрузка статистики пользователей...", event=callback)

    try:
        async with db_manager.get_session() as session:
            stats = await _stats_repo.get_users_stats(session)

        response = _format_users_stats(stats)
        await _send_stats_response(callback, response, bot_manager)

    except Exception as e:
        bot_logger.error(f"❌ Failed to get users stats: {e}", exc_info=True)
        await bot_manager.send_toast(text="❌ Ошибка загрузки статистики.", event=callback)


async def _show_messages_stats(callback: CallbackQuery, state: FSMContext, bot_manager: BotManager) -> None:
    """Показ статистики сообщений."""
    await bot_manager.send_toast(text="⏳ Загрузка статистики сообщений...", event=callback)

    try:
        async with db_manager.get_session() as session:
            stats = await _stats_repo.get_messages_stats(session)

        response = _format_messages_stats(stats)
        await _send_stats_response(callback, response, bot_manager)

    except Exception as e:
        bot_logger.error(f"❌ Failed to get messages stats: {e}", exc_info=True)
        await bot_manager.send_toast(text="❌ Ошибка загрузки статистики.", event=callback)


async def _show_errors_stats(callback: CallbackQuery, state: FSMContext, bot_manager: BotManager) -> None:
    """Показ статистики ошибок (только для администраторов)."""
    await bot_manager.send_toast(text="⏳ Загрузка статистики ошибок...", event=callback)

    try:
        async with db_manager.get_session() as session:
            stats = await _stats_repo.get_errors_stats(session)

        response = _format_errors_stats(stats)
        await _send_stats_response(callback, response, bot_manager)

    except Exception as e:
        bot_logger.error(f"❌ Failed to get errors stats: {e}", exc_info=True)
        await bot_manager.send_toast(text="❌ Ошибка загрузки статистики.", event=callback)


async def _show_reminders_stats(callback: CallbackQuery, state: FSMContext, bot_manager: BotManager) -> None:
    """Показ статистики напоминаний (только для администраторов)."""
    await bot_manager.send_toast(text="⏳ Загрузка статистики напоминаний...", event=callback)

    try:
        async with db_manager.get_session() as session:
            stats = await _stats_repo.get_reminders_stats(session)

        response = _format_reminders_stats(stats)
        await _send_stats_response(callback, response, bot_manager)

    except Exception as e:
        bot_logger.error(f"❌ Failed to get reminders stats: {e}", exc_info=True)
        await bot_manager.send_toast(text="❌ Ошибка загрузки статистики.", event=callback)


async def _show_automation_stats(callback: CallbackQuery, state: FSMContext, bot_manager: BotManager) -> None:
    """Показ статистики автоматизации (только для администраторов)."""
    await bot_manager.send_toast(text="⏳ Загрузка статистики автоматизации...", event=callback)

    try:
        async with db_manager.get_session() as session:
            stats = await _stats_repo.get_automation_stats(session)

        response = _format_automation_stats(stats)
        await _send_stats_response(callback, response, bot_manager)

    except Exception as e:
        bot_logger.error(f"❌ Failed to get automation stats: {e}", exc_info=True)
        await bot_manager.send_toast(text="❌ Ошибка загрузки статистики.", event=callback)


async def _show_system_stats(callback: CallbackQuery, state: FSMContext, bot_manager: BotManager) -> None:
    """Показ системной статистики (только для администраторов)."""
    await bot_manager.send_toast(text="⏳ Загрузка системной статистики...", event=callback)

    try:
        stats = await _stats_repo.get_system_stats()

        response = _format_system_stats(stats)
        await _send_stats_response(callback, response, bot_manager)

    except Exception as e:
        bot_logger.error(f"❌ Failed to get system stats: {e}", exc_info=True)
        await bot_manager.send_toast(text="❌ Ошибка загрузки статистики.", event=callback)


async def _show_db_stats(callback: CallbackQuery, state: FSMContext, bot_manager: BotManager) -> None:
    """
    Показ статистики таблиц БД (только для администраторов).

    Отображает количество записей во всех таблицах базы данных main.
    """
    await bot_manager.send_toast(text="⏳ Загрузка статистики БД...", event=callback)

    try:
        async with db_manager.get_session() as session:
            # Получение количества записей в таблицах
            table_stats = await _stats_repo.get_table_stats(session)
            # Получение общей информации о БД
            db_info = await db_manager.get_stats()

        response = _format_db_stats(table_stats, db_info)
        await _send_stats_response(callback, response, bot_manager)

    except Exception as e:
        bot_logger.error(f"❌ Failed to get DB stats: {e}", exc_info=True)
        await bot_manager.send_toast(text="❌ Ошибка загрузки статистики БД.", event=callback)


# ============================================================
# ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ
# ============================================================


async def _send_stats_response(callback: CallbackQuery, response: str, bot_manager: BotManager) -> None:
    """
    Отправка ответа со статистикой.

    Редактирует текущее сообщение, заменяя меню на статистику.
    Добавляет кнопку "Назад к меню" для возврата.
    """
    # Кнопка возврата в меню
    keyboard = InlineKeyboardMarkup(
        inline_keyboard=[[InlineKeyboardButton(text="🔙 Назад к меню", callback_data="stats_back_to_menu")]]
    )

    if callback.message:
        await callback.message.edit_text(
            text=response,
            parse_mode="Markdown",
            reply_markup=keyboard,
        )


# ============================================================
# УДАЛЯЕМ СТАРЫЙ ОБРАБОТЧИК ВОЗВРАТА (он больше не нужен)
# ============================================================
# @router.callback_query(lambda c: c.data == "stats")
# @log_exceptions(bot_logger)
# async def handle_stats_back_to_menu(callback: CallbackQuery, state: FSMContext) -> None:
#     ... УДАЛЕН ...


# ============================================================
# ФУНКЦИИ ФОРМАТИРОВАНИЯ СТАТИСТИКИ (БЕЗ ИЗМЕНЕНИЙ)
# ============================================================


def _format_full_stats(stats: dict[str, Any]) -> str:
    """Форматирование полной статистики."""
    chats = stats.get("chats", {})
    users = stats.get("users", {})
    messages = stats.get("messages", {})
    top_chats = stats.get("top_chats", [])

    response_parts = [
        "📊 **ПОЛНАЯ СТАТИСТИКА**",
        "═" * 30,
        "",
        "**💬 ЧАТЫ**",
        f"├ 📁 Всего: {chats.get('total', 0)}",
        f"├ ✅ Активные: {chats.get('active', 0)}",
        f"└ ⏸️ Неактивные: {chats.get('inactive', 0)}",
        "",
        "**👤 ПОЛЬЗОВАТЕЛИ**",
        f"├ 👤 Всего: {users.get('total', 0)}",
        f"├ ✅ Авторизованы: {users.get('authorized', 0)}",
        f"└ 🟢 Активны (24ч): {users.get('active_24h', 0)}",
        "",
        "**💬 СООБЩЕНИЯ**",
        f"├ 💬 Всего: {messages.get('total', 0)}",
        f"├ 🗑️ Удалено: {messages.get('deleted', 0)}",
        f"├ ⏱️ С временем жизни: {messages.get('with_lifetime', 0)}",
        f"└ ⏳ Истекли: {messages.get('expired_not_deleted', 0)}",
    ]

    if top_chats:
        response_parts.extend(
            [
                "",
                "**🏆 Топ-5 чатов:**",
            ]
        )
        for i, chat in enumerate(top_chats, 1):
            title = chat.get("title", f"Chat {chat.get('chat_id')}")
            count = chat.get("message_count", 0)
            response_parts.append(f"  {i}. {title}: {count} сообщений")

    response_parts.extend(
        [
            "",
            "─" * 30,
            f"🕐 {datetime_now().strftime('%d.%m.%Y %H:%M:%S')}",
        ]
    )

    return "\n".join(response_parts)


def _format_chats_stats(stats: dict[str, Any]) -> str:
    """Форматирование статистики чатов."""
    response_parts = [
        "💬 **СТАТИСТИКА ЧАТОВ**",
        "═" * 30,
        "",
        f"📁 Всего чатов: {stats.get('total', 0)}",
        f"✅ Активных: {stats.get('active', 0)}",
        f"⏸️ Неактивных: {stats.get('inactive', 0)}",
        "",
        "**📋 По типам:**",
    ]

    by_type = stats.get("by_type", {})
    if by_type:
        for chat_type, count in by_type.items():
            response_parts.append(f"  • {chat_type}: {count}")
    else:
        response_parts.append("  Нет данных")

    response_parts.extend(
        [
            "",
            "─" * 30,
            f"🕐 {datetime_now().strftime('%d.%m.%Y %H:%M:%S')}",
        ]
    )

    return "\n".join(response_parts)


def _format_users_stats(stats: dict[str, Any]) -> str:
    """Форматирование статистики пользователей."""
    return "\n".join(
        [
            "👤 **СТАТИСТИКА ПОЛЬЗОВАТЕЛЕЙ**",
            "═" * 30,
            "",
            f"👤 Всего пользователей: {stats.get('total', 0)}",
            f"✅ Авторизованы: {stats.get('authorized', 0)}",
            f"🟢 Активны (24ч): {stats.get('active_24h', 0)}",
            "",
            "─" * 30,
            f"🕐 {datetime_now().strftime('%d.%m.%Y %H:%M:%S')}",
        ]
    )


def _format_messages_stats(stats: dict[str, Any]) -> str:
    """Форматирование статистики сообщений."""
    response_parts = [
        "💬 **СТАТИСТИКА СООБЩЕНИЙ**",
        "═" * 30,
        "",
        f"💬 Всего: {stats.get('total', 0)}",
        f"🗑️ Удалено: {stats.get('deleted', 0)}",
        f"⏱️ С временем жизни: {stats.get('with_lifetime', 0)}",
        f"⏳ Истекли (не удалены): {stats.get('expired_not_deleted', 0)}",
        "",
        "**📋 По типам:**",
    ]

    by_type = stats.get("by_type", {})
    if by_type:
        # Сортируем по убыванию
        sorted_types = sorted(by_type.items(), key=lambda x: x[1], reverse=True)
        for msg_type, count in sorted_types:
            response_parts.append(f"  • {msg_type}: {count}")
    else:
        response_parts.append("  Нет данных")

    response_parts.extend(
        [
            "",
            "**📅 По дням (последние 7 дней):**",
        ]
    )

    by_day = stats.get("by_day", {})
    if by_day:
        for day, count in sorted(by_day.items()):
            response_parts.append(f"  • {day}: {count}")
    else:
        response_parts.append("  Нет данных")

    response_parts.extend(
        [
            "",
            "─" * 30,
            f"🕐 {datetime_now().strftime('%d.%m.%Y %H:%M:%S')}",
        ]
    )

    return "\n".join(response_parts)


def _format_errors_stats(stats: dict[str, Any]) -> str:
    """Форматирование статистики ошибок."""
    response_parts = [
        "🚨 **СТАТИСТИКА ОШИБОК**",
        "═" * 30,
        "",
        f"📋 Всего ошибок: {stats.get('total', 0)}",
        f"🔄 Всего повторений: {stats.get('total_occurrences', 0)}",
        f"📈 Эффективность: {stats.get('resolution_rate', 0):.1f}%",
        "",
        "**📋 По статусам:**",
    ]

    by_status = stats.get("by_status", {})
    if by_status:
        status_labels = {
            "new": "🆕 Новые",
            "in_progress": "🔄 В работе",
            "resolved": "✅ Решено",
            "reopened": "🔁 Переоткрыто",
            "dismissed": "⏭️ Отклонено",
        }
        for status, count in by_status.items():
            label = status_labels.get(status, status)
            response_parts.append(f"  • {label}: {count}")
    else:
        response_parts.append("  Нет данных")

    response_parts.extend(
        [
            "",
            "**📋 По категориям:**",
        ]
    )

    by_category = stats.get("by_category", {})
    if by_category:
        for category, count in by_category.items():
            response_parts.append(f"  • {category}: {count}")
    else:
        response_parts.append("  Нет данных")

    response_parts.extend(
        [
            "",
            "**📋 По серьезности:**",
        ]
    )

    by_severity = stats.get("by_severity", {})
    if by_severity:
        severity_emoji = {
            "critical": "🚨",
            "error": "❌",
            "warning": "⚠️",
            "info": "ℹ️",
        }
        for severity, count in by_severity.items():
            emoji = severity_emoji.get(severity, "📌")
            response_parts.append(f"  • {emoji} {severity}: {count}")
    else:
        response_parts.append("  Нет данных")

    response_parts.extend(
        [
            "",
            "─" * 30,
            f"🕐 {datetime_now().strftime('%d.%m.%Y %H:%M:%S')}",
        ]
    )

    return "\n".join(response_parts)


def _format_reminders_stats(stats: dict[str, Any]) -> str:
    """Форматирование статистики напоминаний."""
    return "\n".join(
        [
            "⏰ **СТАТИСТИКА НАПОМИНАНИЙ**",
            "═" * 30,
            "",
            f"📋 Всего: {stats.get('total', 0)}",
            f"🔔 Активные: {stats.get('active', 0)}",
            f"✅ Завершено: {stats.get('completed', 0)}",
            f"📈 Эффективность: {stats.get('completion_rate', 0):.1f}%",
            f"🔒 Зашифровано: {stats.get('encrypted', 0)}",
            f"👥 Общих: {stats.get('group_reminders', 0)}",
            "",
            "─" * 30,
            f"🕐 {datetime_now().strftime('%d.%m.%Y %H:%M:%S')}",
        ]
    )


def _format_automation_stats(stats: dict[str, Any]) -> str:
    """Форматирование статистики автоматизации."""
    response_parts = [
        "🤖 **СТАТИСТИКА АВТОМАТИЗАЦИИ**",
        "═" * 30,
        "",
        f"📋 Всего заявок: {stats.get('total', 0)}",
        f"📈 Эффективность: {stats.get('completion_rate', 0):.1f}%",
        "",
        "**📋 По статусам:**",
    ]

    by_status = stats.get("by_status", {})
    if by_status:
        status_labels = {
            "new": "🆕 Новые",
            "in_progress": "🔄 В работе",
            "completed": "✅ Выполнено",
            "cancelled": "❌ Отменено",
            "rejected": "⛔ Отклонено",
        }
        for status, count in by_status.items():
            label = status_labels.get(status, status)
            response_parts.append(f"  • {label}: {count}")
    else:
        response_parts.append("  Нет данных")

    response_parts.extend(
        [
            "",
            "**📋 По приоритетам:**",
        ]
    )

    by_priority = stats.get("by_priority", {})
    if by_priority:
        priority_emoji = {
            "low": "🟢",
            "medium": "🟡",
            "high": "🟠",
            "critical": "🔴",
        }
        for priority, count in by_priority.items():
            emoji = priority_emoji.get(priority, "🟡")
            response_parts.append(f"  • {emoji} {priority}: {count}")
    else:
        response_parts.append("  Нет данных")

    response_parts.extend(
        [
            "",
            "─" * 30,
            f"🕐 {datetime_now().strftime('%d.%m.%Y %H:%M:%S')}",
        ]
    )

    return "\n".join(response_parts)


def _format_system_stats(stats: dict[str, Any]) -> str:
    """Форматирование системной статистики."""
    uptime = stats.get("uptime")
    uptime_str = _format_uptime(uptime) if uptime else "N/A"

    return "\n".join(
        [
            "💻 **СИСТЕМНАЯ СТАТИСТИКА**",
            "═" * 30,
            "",
            f"🚀 Версия: {stats.get('version', '1.0.0')}",
            f"🐍 Python: {stats.get('python_version', 'N/A')}",
            f"💻 Платформа: {stats.get('platform', 'N/A')}",
            f"⏱️ Uptime: {uptime_str}",
            f"📁 Окружение: {stats.get('environment', 'N/A')}",
            f"📊 Состояние: {stats.get('state', 'N/A')}",
            f"🔄 Задач: {stats.get('tasks_count', 0)}",
            "",
            "─" * 30,
            f"🕐 {datetime_now().strftime('%d.%m.%Y %H:%M:%S')}",
        ]
    )


def _format_db_stats(table_stats: dict[str, int], db_info: dict[str, Any]) -> str:
    """
    Форматирование статистики таблиц БД.

    Отображает количество записей во всех таблицах базы данных main,
    отсортированных по убыванию, с общей статистикой.

    Args:
        table_stats: Словарь {имя_таблицы: количество_записей}
        db_info: Информация о БД от db_manager.get_stats()
    """
    databases = db_info.get("databases", {})
    primary = db_info.get("primary", "unknown")
    session_counter = db_info.get("session_counter", 0)

    # Сортировка таблиц по количеству записей (по убыванию)
    sorted_tables = sorted(table_stats.items(), key=lambda x: x[1], reverse=True)

    response_parts = [
        "🗄️ **СТАТИСТИКА БАЗЫ ДАННЫХ (main)**",
        "═" * 30,
        "",
        f"📁 Основная БД: {primary}",
        f"📊 Всего БД: {db_info.get('total_databases', 0)}",
        f"🔄 Сессий создано: {session_counter}",
        "",
        "**📋 Информация о БД:**",
    ]

    for name, info in databases.items():
        status = "✅" if info.get("initialized") else "❌"
        is_primary = "⭐" if info.get("is_primary") else ""
        response_parts.append(f"  • {name} {is_primary}: {info.get('type', 'unknown')} {status}")

    response_parts.extend(
        [
            "",
            "**📊 Количество записей по таблицам:**",
        ]
    )

    if sorted_tables:
        total_rows = 0
        for table, count in sorted_tables:
            if count >= 0:
                total_rows += count
                # Форматируем с выравниванием
                count_str = f"{count:,}" if count > 0 else "0"
                response_parts.append(f"  • {table}: {count_str}")
            else:
                response_parts.append(f"  • {table}: ❌ ошибка")

        response_parts.extend(
            [
                "",
                f"📊 **Всего записей: {total_rows:,}**",
            ]
        )
    else:
        response_parts.append("  Нет данных")

    response_parts.extend(
        [
            "",
            "─" * 30,
            f"🕐 {datetime_now().strftime('%d.%m.%Y %H:%M:%S')}",
        ]
    )

    return "\n".join(response_parts)


__all__ = [
    "router",
]
