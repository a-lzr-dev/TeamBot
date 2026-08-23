"""
Модуль обработчиков синхронизации для Telegram бота.

Этот модуль предоставляет обработчики для команд и колбэков,
связанных с синхронизацией данных Avanpost:

1. /sync - Открытие главного меню синхронизации
2. Синхронизация справочников (/sync_base)
3. Синхронизация контактов (/sync_contacts)
4. Синхронизация пользователя (/sync_user <id>)
5. Синхронизация всех пользователей (/sync_all_users)
6. Загрузка пользователей из Avanpost (/sync_seed_users)

Все команды доступны только администраторам.
"""

from typing import Any

from aiogram import F, Router
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message

from ....bot.dependencies import get_bot_manager
from ....config import settings
from ....db import db_manager
from ....db.repositories import UserRepository
from ....logger import bot_logger
from ....models import MessageActionType, MessageType
from ....services.avanpost_sync_service import AvanpostSyncService
from ....services.seed_service import AvanpostSeedService
from ....utils.decorators import log_exceptions

# ============================================================
# РОУТЕР И РЕПОЗИТОРИИ
# ============================================================

router = Router(name="aiogram_sync")

_user_repo = UserRepository()


# ============================================================
# СОСТОЯНИЯ FSM
# ============================================================


class SyncStates(StatesGroup):
    """Состояния для меню синхронизации."""

    menu = State()
    waiting_for_user_id = State()


# ============================================================
# ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ
# ============================================================


def _is_admin(user_id: int) -> bool:
    """Проверка, является ли пользователь администратором."""
    return user_id in settings.ADMIN_IDS


def _get_back_menu_keyboard() -> InlineKeyboardMarkup:
    """Клавиатура для возврата в меню синхронизации."""
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="🔙 Назад в меню", callback_data="sync_menu")],
            [InlineKeyboardButton(text="❌ Закрыть", callback_data="sync_close")],
        ]
    )


async def _show_result(
    callback: CallbackQuery,
    bot_manager: Any,
    report: str,
    show_back_menu: bool = True,
) -> None:
    """
    Отображение результата синхронизации через callback.

    Args:
        callback: CallbackQuery от пользователя
        bot_manager: Менеджер бота
        report: Текст отчета
        show_back_menu: Показывать кнопку возврата в меню
    """
    keyboard = None
    if show_back_menu:
        keyboard = InlineKeyboardMarkup(
            inline_keyboard=[
                [InlineKeyboardButton(text="🔙 Назад в меню", callback_data="sync_menu")],
                [InlineKeyboardButton(text="❌ Закрыть", callback_data="sync_close")],
            ]
        )

    await bot_manager.edit_callback_message(
        callback=callback,
        text=report,
        parse_mode="Markdown",
        reply_markup=keyboard,
    )


async def _show_result_to_message(
    message: Message,
    bot_manager: Any,
    report: str,
    state: FSMContext,
) -> None:
    """
    Отображение результата синхронизации через сообщение.

    Args:
        message: Сообщение от пользователя
        bot_manager: Менеджер бота
        report: Текст отчета
        state: Состояние FSM
    """
    keyboard = InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="🔙 Назад в меню", callback_data="sync_menu")],
            [InlineKeyboardButton(text="❌ Закрыть", callback_data="sync_close")],
        ]
    )

    await bot_manager.send_answer(
        text=report,
        event=message,
        message_type=MessageType.COMMAND_ADMIN,
        delete_by_type=MessageActionType.COMMAND_ADMIN_CLEANUP,
        parse_mode="Markdown",
        reply_markup=keyboard,
    )

    await state.clear()


# ============================================================
# 1. ГЛАВНОЕ МЕНЮ СИНХРОНИЗАЦИИ (/sync)
# ============================================================


async def show_sync_menu(event: Message | CallbackQuery) -> None:
    """
    Отображение главного меню синхронизации.

    Args:
        event: Сообщение или CallbackQuery
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
            [InlineKeyboardButton(text="📚 Синхр. справочников", callback_data="sync_base")],
            [InlineKeyboardButton(text="📇 Синхр. контактов", callback_data="sync_contacts")],
            [InlineKeyboardButton(text="👤 Синхр. пользователя", callback_data="sync_user_prompt")],
            [InlineKeyboardButton(text="👥 Синхр. всех пользователей", callback_data="sync_all_users")],
            [InlineKeyboardButton(text="🚀 Загрузка пользователей", callback_data="sync_seed_users")],
            [InlineKeyboardButton(text="❌ Закрыть", callback_data="sync_close")],
        ]
    )

    text = (
        "🔄 **Меню синхронизации**\n\n"
        "Выберите действие:\n"
        "• 📚 **Синхр. справочников** — синхронизация базовых данных\n"
        "• 📇 **Синхр. контактов** — синхронизация контактов\n"
        "• 👤 **Синхр. пользователя** — синхронизация данных пользователя\n"
        "• 👥 **Синхр. всех пользователей** — синхронизация всех пользователей\n"
        "• 🚀 **Загрузка пользователей** — загрузка всех пользователей из Avanpost"
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
    else:
        if event.message:
            await bot_manager.edit_callback_message(
                callback=event,
                text=text,
                parse_mode="Markdown",
                reply_markup=keyboard,
            )


@router.message(Command("sync"))
@log_exceptions(bot_logger)
async def cmd_sync(message: Message) -> None:
    """
    Команда /sync — открытие меню синхронизации.

    Args:
        message: Сообщение от пользователя
    """
    await show_sync_menu(message)


# ============================================================
# 2. ОБРАБОТЧИКИ КОЛБЭКОВ МЕНЮ СИНХРОНИЗАЦИИ
# ============================================================


@router.callback_query(F.data.startswith("sync_"))
@log_exceptions(bot_logger)
async def handle_sync_callback(callback: CallbackQuery, state: FSMContext) -> None:
    """
    Обработка колбэков меню синхронизации.

    Args:
        callback: CallbackQuery от пользователя
        state: Состояние FSM
    """
    bot_manager = get_bot_manager()

    if not callback.from_user:
        await bot_manager.send_toast(text="❌ Не удалось определить пользователя.", event=callback)
        return

    user_id = callback.from_user.id

    if not _is_admin(user_id):
        await bot_manager.send_toast(text="⛔ У вас нет прав для этой команды.", event=callback)
        return

    callback_data = callback.data

    # Возврат в меню
    if callback_data == "sync_menu":
        await show_sync_menu(callback)
        return

    # Закрытие
    if callback_data == "sync_close":
        await state.clear()
        await bot_manager.send_toast(text="❌ Меню закрыто.", event=callback)
        if callback.message:
            await callback.message.delete()
        return

    # Выполнение синхронизации
    if callback_data == "sync_base":
        await _handle_sync_base(callback, bot_manager)
    elif callback_data == "sync_contacts":
        await _handle_sync_contacts(callback, bot_manager)
    elif callback_data == "sync_user_prompt":
        await _handle_sync_user_prompt(callback, bot_manager, state)
    elif callback_data == "sync_all_users":
        await _handle_sync_all_users(callback, bot_manager)
    elif callback_data == "sync_seed_users":
        await _handle_sync_seed_users(callback, bot_manager)
    else:
        await bot_manager.send_toast(text="❌ Неизвестное действие.", event=callback)


# ============================================================
# 3. ОБРАБОТЧИКИ КОНКРЕТНЫХ КОМАНД СИНХРОНИЗАЦИИ
# ============================================================


@router.message(Command("sync_base"))
@log_exceptions(bot_logger)
async def cmd_sync_base(message: Message) -> None:
    """
    Команда /sync_base — синхронизация справочников.

    Args:
        message: Сообщение от пользователя
    """
    bot_manager = get_bot_manager()

    if not message.from_user or not _is_admin(message.from_user.id):
        await bot_manager.send_answer(
            text="⛔ У вас нет прав для этой команды.",
            event=message,
            message_type=MessageType.COMMAND_ADMIN,
            delete_by_type=MessageActionType.COMMAND_ADMIN_CLEANUP,
        )
        return

    await bot_manager.delete_message_by_link(message)
    await bot_manager.send_answer(
        text="🔄 Запуск синхронизации справочников...",
        event=message,
        message_type=MessageType.COMMAND_ADMIN,
        delete_by_type=MessageActionType.COMMAND_ADMIN_CLEANUP,
    )

    try:
        sync_service = AvanpostSyncService()
        await sync_service.initialize()

        stats = await sync_service.sync_base_data(force=False)
        stats_dict = stats.to_dict() if hasattr(stats, "to_dict") else {}

        report = (
            f"✅ Синхронизация справочников завершена!\n"
            f"📊 Обработано типов: {stats_dict.get('processed_data_types', 0)}\n"
            f"📈 Вставлено: {stats_dict.get('total_inserted', 0)}\n"
            f"🔄 Обновлено: {stats_dict.get('total_updated', 0)}\n"
            f"🗑️ Удалено: {stats_dict.get('total_deleted', 0)}\n"
            f"⏭️ Без изменений: {stats_dict.get('total_unchanged_upsert', 0)}\n"
            f"❌ Ошибок: {len(stats_dict.get('error_messages', []))}"
        )
        if stats_dict.get("error_messages"):
            report += f"\n⚠️ Первая ошибка: {stats_dict['error_messages'][0][:100]}"

        keyboard = _get_back_menu_keyboard()
        await bot_manager.send_answer(
            text=report,
            event=message,
            message_type=MessageType.COMMAND_ADMIN,
            delete_by_type=MessageActionType.COMMAND_ADMIN_CLEANUP,
            parse_mode="Markdown",
            reply_markup=keyboard,
        )

    except Exception as e:
        bot_logger.error(f"❌ sync_base failed: {e}", exc_info=True)
        await bot_manager.send_answer(
            text=f"❌ Ошибка: {e}",
            event=message,
            message_type=MessageType.COMMAND_ADMIN,
            delete_by_type=MessageActionType.COMMAND_ADMIN_CLEANUP,
        )


@router.message(Command("sync_contacts"))
@log_exceptions(bot_logger)
async def cmd_sync_contacts(message: Message) -> None:
    """
    Команда /sync_contacts — синхронизация контактов.

    Args:
        message: Сообщение от пользователя
    """
    bot_manager = get_bot_manager()

    if not message.from_user or not _is_admin(message.from_user.id):
        await bot_manager.send_answer(
            text="⛔ У вас нет прав для этой команды.",
            event=message,
            message_type=MessageType.COMMAND_ADMIN,
            delete_by_type=MessageActionType.COMMAND_ADMIN_CLEANUP,
        )
        return

    await bot_manager.delete_message_by_link(message)
    await bot_manager.send_answer(
        text="🔄 Запуск синхронизации контактов...",
        event=message,
        message_type=MessageType.COMMAND_ADMIN,
        delete_by_type=MessageActionType.COMMAND_ADMIN_CLEANUP,
    )

    try:
        sync_service = AvanpostSyncService()
        await sync_service.initialize()

        stats = await sync_service.sync_base_data(force=False)
        stats_dict = stats.to_dict() if hasattr(stats, "to_dict") else {}

        table_stats = stats_dict.get("table_stats", {})
        contact_tables = ["TAvanpostContacts", "TAvanpostContactsLangs", "TAvanpostContactsLinks"]
        contact_stats = {k: v for k, v in table_stats.items() if k in contact_tables}

        total_inserted = sum(s.get("inserted", 0) for s in contact_stats.values())
        total_updated = sum(s.get("updated", 0) for s in contact_stats.values())
        total_deleted = sum(s.get("deleted", 0) for s in contact_stats.values())

        report = (
            f"✅ Синхронизация контактов завершена!\n"
            f"📈 Вставлено: {total_inserted}\n"
            f"🔄 Обновлено: {total_updated}\n"
            f"🗑️ Удалено: {total_deleted}\n"
        )

        if contact_stats:
            report += "\n📊 Детали по таблицам:\n"
            for table, s in contact_stats.items():
                report += f"  • {table}: +{s.get('inserted', 0)} / ~{s.get('updated', 0)} / -{s.get('deleted', 0)}\n"

        keyboard = _get_back_menu_keyboard()
        await bot_manager.send_answer(
            text=report,
            event=message,
            message_type=MessageType.COMMAND_ADMIN,
            delete_by_type=MessageActionType.COMMAND_ADMIN_CLEANUP,
            parse_mode="Markdown",
            reply_markup=keyboard,
        )

    except Exception as e:
        bot_logger.error(f"❌ sync_contacts failed: {e}", exc_info=True)
        await bot_manager.send_answer(
            text=f"❌ Ошибка: {e}",
            event=message,
            message_type=MessageType.COMMAND_ADMIN,
            delete_by_type=MessageActionType.COMMAND_ADMIN_CLEANUP,
        )


@router.message(Command("sync_user"))
@log_exceptions(bot_logger)
async def cmd_sync_user(message: Message) -> None:
    """
    Команда /sync_user <id> — синхронизация конкретного пользователя.

    Формат: /sync_user <user_id>

    Args:
        message: Сообщение от пользователя
    """
    bot_manager = get_bot_manager()

    if not message.from_user or not _is_admin(message.from_user.id):
        await bot_manager.send_answer(
            text="⛔ У вас нет прав для этой команды.",
            event=message,
            message_type=MessageType.COMMAND_ADMIN,
            delete_by_type=MessageActionType.COMMAND_ADMIN_CLEANUP,
        )
        return

    await bot_manager.delete_message_by_link(message)

    command_text = message.text or ""
    parts = command_text.split()

    if len(parts) < 2:
        await bot_manager.send_answer(
            text="❌ Использование: /sync_user <user_id>\n"
            "Например: /sync_user 123456789\n\n"
            "💡 user_id - это ID пользователя в Avanpost",
            event=message,
            message_type=MessageType.COMMAND_ADMIN,
            delete_by_type=MessageActionType.COMMAND_ADMIN_CLEANUP,
        )
        return

    try:
        user_id = int(parts[1])
        await bot_manager.send_answer(
            text=f"🔄 Запуск синхронизации для пользователя {user_id}...",
            event=message,
            message_type=MessageType.COMMAND_ADMIN,
            delete_by_type=MessageActionType.COMMAND_ADMIN_CLEANUP,
        )

        sync_service = AvanpostSyncService()
        await sync_service.initialize()

        stats = await sync_service.sync_user_data(user_id=user_id, force=False)
        stats_dict = stats.to_dict() if hasattr(stats, "to_dict") else {}

        report = (
            f"✅ Синхронизация пользователя {user_id} завершена!\n"
            f"📊 Обработано типов: {stats_dict.get('processed_data_types', 0)}\n"
            f"📈 Вставлено: {stats_dict.get('total_inserted', 0)}\n"
            f"🔄 Обновлено: {stats_dict.get('total_updated', 0)}\n"
            f"🗑️ Удалено: {stats_dict.get('total_deleted', 0)}\n"
            f"⏭️ Без изменений: {stats_dict.get('total_unchanged_upsert', 0)}\n"
            f"❌ Ошибок: {len(stats_dict.get('error_messages', []))}"
        )

        table_stats = stats_dict.get("table_stats", {})
        changed_tables = {
            k: v
            for k, v in table_stats.items()
            if v.get("inserted", 0) > 0 or v.get("updated", 0) > 0 or v.get("deleted", 0) > 0
        }
        if changed_tables:
            report += "\n\n📊 Изменения по таблицам:\n"
            for table, s in list(changed_tables.items())[:5]:
                report += f"  • {table}: +{s.get('inserted', 0)} / ~{s.get('updated', 0)} / -{s.get('deleted', 0)}\n"
            if len(changed_tables) > 5:
                report += f"  • ... и еще {len(changed_tables) - 5} таблиц"

        keyboard = _get_back_menu_keyboard()
        await bot_manager.send_answer(
            text=report,
            event=message,
            message_type=MessageType.COMMAND_ADMIN,
            delete_by_type=MessageActionType.COMMAND_ADMIN_CLEANUP,
            parse_mode="Markdown",
            reply_markup=keyboard,
        )

    except ValueError:
        await bot_manager.send_answer(
            text="❌ Неверный формат ID. Используйте число.",
            event=message,
            message_type=MessageType.COMMAND_ADMIN,
            delete_by_type=MessageActionType.COMMAND_ADMIN_CLEANUP,
        )
    except Exception as e:
        bot_logger.error(f"❌ sync_user failed: {e}", exc_info=True)
        await bot_manager.send_answer(
            text=f"❌ Ошибка: {e}",
            event=message,
            message_type=MessageType.COMMAND_ADMIN,
            delete_by_type=MessageActionType.COMMAND_ADMIN_CLEANUP,
        )


@router.message(Command("sync_all_users"))
@log_exceptions(bot_logger)
async def cmd_sync_all_users(message: Message) -> None:
    """
    Команда /sync_all_users — синхронизация всех пользователей.

    Args:
        message: Сообщение от пользователя
    """
    bot_manager = get_bot_manager()

    if not message.from_user or not _is_admin(message.from_user.id):
        await bot_manager.send_answer(
            text="⛔ У вас нет прав для этой команды.",
            event=message,
            message_type=MessageType.COMMAND_ADMIN,
            delete_by_type=MessageActionType.COMMAND_ADMIN_CLEANUP,
        )
        return

    await bot_manager.delete_message_by_link(message)
    await bot_manager.send_answer(
        text="🔄 Запуск синхронизации для всех пользователей...\n"
        "Это может занять длительное время в зависимости от количества пользователей.",
        event=message,
        message_type=MessageType.COMMAND_ADMIN,
        delete_by_type=MessageActionType.COMMAND_ADMIN_CLEANUP,
    )

    try:
        sync_service = AvanpostSyncService()
        await sync_service.initialize()

        result = await sync_service.sync_all_users(force=False)

        report = (
            f"✅ Синхронизация всех пользователей завершена!\n"
            f"👥 Всего пользователей: {result.get('total_users', 0)}\n"
            f"✅ Успешно: {result.get('successful', 0)}\n"
            f"❌ Ошибок: {result.get('failed', 0)}\n"
            f"📈 Вставлено: {result.get('total_inserted', 0)}\n"
            f"🔄 Обновлено: {result.get('total_updated', 0)}\n"
            f"🗑️ Удалено: {result.get('total_deleted', 0)}\n"
            f"⏭️ Без изменений: {result.get('total_unchanged_upsert', 0)}"
        )

        if result.get("errors"):
            report += f"\n⚠️ Первая ошибка: {result['errors'][0][:100]}"

        keyboard = _get_back_menu_keyboard()
        await bot_manager.send_answer(
            text=report,
            event=message,
            message_type=MessageType.COMMAND_ADMIN,
            delete_by_type=MessageActionType.COMMAND_ADMIN_CLEANUP,
            parse_mode="Markdown",
            reply_markup=keyboard,
        )

    except Exception as e:
        bot_logger.error(f"❌ sync_all_users failed: {e}", exc_info=True)
        await bot_manager.send_answer(
            text=f"❌ Ошибка: {e}",
            event=message,
            message_type=MessageType.COMMAND_ADMIN,
            delete_by_type=MessageActionType.COMMAND_ADMIN_CLEANUP,
        )


@router.message(Command("sync_seed_users"))
@log_exceptions(bot_logger)
async def cmd_sync_seed_users(message: Message) -> None:
    """
    Команда /sync_seed_users — загрузка всех пользователей из Avanpost.

    Args:
        message: Сообщение от пользователя
    """
    bot_manager = get_bot_manager()

    if not message.from_user or not _is_admin(message.from_user.id):
        await bot_manager.send_answer(
            text="⛔ У вас нет прав для этой команды.",
            event=message,
            message_type=MessageType.COMMAND_ADMIN,
            delete_by_type=MessageActionType.COMMAND_ADMIN_CLEANUP,
        )
        return

    await bot_manager.delete_message_by_link(message)
    await bot_manager.send_answer(
        text="🚀 Запуск загрузки всех пользователей из Avanpost...",
        event=message,
        message_type=MessageType.COMMAND_ADMIN,
        delete_by_type=MessageActionType.COMMAND_ADMIN_CLEANUP,
    )

    try:
        async with db_manager.get_session() as session:
            result = await AvanpostSeedService.seed_avanpost_users_all(
                session=session,
                create_sync_records=True,
            )

            report = (
                f"✅ Загрузка пользователей из Avanpost завершена!\n"
                f"📊 Загружено ID: {result.get('total_loaded', 0)}\n"
                f"📈 Добавлено: {result.get('total_added', 0)}\n"
                f"⏭️ Пропущено (уже существуют): {result.get('total_skipped', 0)}\n"
                f"❌ Ошибок: {result.get('errors', 0)}"
            )

            if result.get("error_messages"):
                report += f"\n⚠️ Первая ошибка: {result['error_messages'][0][:100]}"

            keyboard = _get_back_menu_keyboard()
            await bot_manager.send_answer(
                text=report,
                event=message,
                message_type=MessageType.COMMAND_ADMIN,
                delete_by_type=MessageActionType.COMMAND_ADMIN_CLEANUP,
                parse_mode="Markdown",
                reply_markup=keyboard,
            )

    except Exception as e:
        bot_logger.error(f"❌ sync_seed_users failed: {e}", exc_info=True)
        await bot_manager.send_answer(
            text=f"❌ Ошибка: {e}",
            event=message,
            message_type=MessageType.COMMAND_ADMIN,
            delete_by_type=MessageActionType.COMMAND_ADMIN_CLEANUP,
        )


# ============================================================
# 4. ОБРАБОТЧИК ВВОДА ID ПОЛЬЗОВАТЕЛЯ (FSM)
# ============================================================


async def _handle_sync_user_prompt(
    callback: CallbackQuery,
    bot_manager: Any,
    state: FSMContext,
) -> None:
    """
    Запрос ID пользователя для синхронизации.

    Args:
        callback: CallbackQuery от пользователя
        bot_manager: Менеджер бота
        state: Состояние FSM
    """
    await bot_manager.send_toast(text="👤 Введите ID пользователя для синхронизации", event=callback)

    await state.set_state(SyncStates.waiting_for_user_id)
    await state.update_data(action="sync_user")

    keyboard = InlineKeyboardMarkup(
        inline_keyboard=[[InlineKeyboardButton(text="❌ Отмена", callback_data="sync_menu")]]
    )

    await bot_manager.edit_callback_message(
        callback=callback,
        text="👤 **Синхронизация пользователя**\n\n"
        "Введите ID пользователя в Avanpost для синхронизации.\n\n"
        "Используйте /cancel для отмены.",
        parse_mode="Markdown",
        reply_markup=keyboard,
    )


@router.message(SyncStates.waiting_for_user_id)
@log_exceptions(bot_logger)
async def handle_sync_user_input(message: Message, state: FSMContext) -> None:
    """
    Обработка ввода ID пользователя для синхронизации.

    Args:
        message: Сообщение от пользователя
        state: Состояние FSM
    """
    bot_manager = get_bot_manager()

    if not message.from_user or not _is_admin(message.from_user.id):
        await bot_manager.send_answer(
            text="⛔ У вас нет прав для этой команды.",
            event=message,
            message_type=MessageType.COMMAND_ADMIN,
            delete_by_type=MessageActionType.COMMAND_ADMIN_CLEANUP,
        )
        return

    data = await state.get_data()
    action = data.get("action")

    if action != "sync_user":
        await state.clear()
        return

    if not message.text or not message.text.strip():
        await bot_manager.send_answer(
            text="❌ Введите корректный ID пользователя.",
            event=message,
            message_type=MessageType.COMMAND_ADMIN,
            delete_by_type=MessageActionType.COMMAND_ADMIN_CLEANUP,
        )
        return

    try:
        user_id = int(message.text.strip())

        if user_id <= 0:
            raise ValueError

        await bot_manager.delete_message_by_link(message)

        await bot_manager.send_answer(
            text=f"🔄 Запуск синхронизации пользователя {user_id}...",
            event=message,
            message_type=MessageType.COMMAND_ADMIN,
            delete_by_type=MessageActionType.COMMAND_ADMIN_CLEANUP,
        )

        sync_service = AvanpostSyncService()
        await sync_service.initialize()

        stats = await sync_service.sync_user_data(user_id=user_id, force=False)
        stats_dict = stats.to_dict() if hasattr(stats, "to_dict") else {}

        report = (
            f"✅ Синхронизация пользователя {user_id} завершена!\n"
            f"📊 Обработано типов: {stats_dict.get('processed_data_types', 0)}\n"
            f"📈 Вставлено: {stats_dict.get('total_inserted', 0)}\n"
            f"🔄 Обновлено: {stats_dict.get('total_updated', 0)}\n"
            f"🗑️ Удалено: {stats_dict.get('total_deleted', 0)}\n"
            f"⏭️ Без изменений: {stats_dict.get('total_unchanged_upsert', 0)}\n"
            f"❌ Ошибок: {len(stats_dict.get('error_messages', []))}"
        )

        await _show_result_to_message(message, bot_manager, report, state)

    except ValueError:
        await bot_manager.send_answer(
            text="❌ Неверный формат ID. Используйте число.",
            event=message,
            message_type=MessageType.COMMAND_ADMIN,
            delete_by_type=MessageActionType.COMMAND_ADMIN_CLEANUP,
        )
    except Exception as e:
        bot_logger.error(f"❌ sync_user failed: {e}", exc_info=True)
        await bot_manager.send_answer(
            text=f"❌ Ошибка: {e}",
            event=message,
            message_type=MessageType.COMMAND_ADMIN,
            delete_by_type=MessageActionType.COMMAND_ADMIN_CLEANUP,
        )


# ============================================================
# 5. ОБРАБОТЧИКИ КОЛБЭКОВ ДЛЯ КОНКРЕТНЫХ ДЕЙСТВИЙ
# ============================================================


async def _handle_sync_base(callback: CallbackQuery, bot_manager: Any) -> None:
    """Обработка синхронизации справочников из меню."""
    await bot_manager.send_toast(text="🔄 Запуск синхронизации справочников...", event=callback)

    try:
        sync_service = AvanpostSyncService()
        await sync_service.initialize()

        stats = await sync_service.sync_base_data(force=False)
        stats_dict = stats.to_dict() if hasattr(stats, "to_dict") else {}

        report = (
            f"✅ Синхронизация справочников завершена!\n"
            f"📊 Обработано типов: {stats_dict.get('processed_data_types', 0)}\n"
            f"📈 Вставлено: {stats_dict.get('total_inserted', 0)}\n"
            f"🔄 Обновлено: {stats_dict.get('total_updated', 0)}\n"
            f"🗑️ Удалено: {stats_dict.get('total_deleted', 0)}\n"
            f"⏭️ Без изменений: {stats_dict.get('total_unchanged_upsert', 0)}\n"
            f"❌ Ошибок: {len(stats_dict.get('error_messages', []))}"
        )

        await _show_result(callback, bot_manager, report)

    except Exception as e:
        bot_logger.error(f"❌ sync_base callback failed: {e}", exc_info=True)
        await bot_manager.send_toast(text=f"❌ Ошибка: {str(e)[:100]}", event=callback)


async def _handle_sync_contacts(callback: CallbackQuery, bot_manager: Any) -> None:
    """Обработка синхронизации контактов из меню."""
    await bot_manager.send_toast(text="🔄 Запуск синхронизации контактов...", event=callback)

    try:
        sync_service = AvanpostSyncService()
        await sync_service.initialize()

        stats = await sync_service.sync_base_data(force=False)
        stats_dict = stats.to_dict() if hasattr(stats, "to_dict") else {}

        table_stats = stats_dict.get("table_stats", {})
        contact_tables = ["TAvanpostContacts", "TAvanpostContactsLangs", "TAvanpostContactsLinks"]
        contact_stats = {k: v for k, v in table_stats.items() if k in contact_tables}

        total_inserted = sum(s.get("inserted", 0) for s in contact_stats.values())
        total_updated = sum(s.get("updated", 0) for s in contact_stats.values())
        total_deleted = sum(s.get("deleted", 0) for s in contact_stats.values())

        report = (
            f"✅ Синхронизация контактов завершена!\n"
            f"📈 Вставлено: {total_inserted}\n"
            f"🔄 Обновлено: {total_updated}\n"
            f"🗑️ Удалено: {total_deleted}\n"
        )

        await _show_result(callback, bot_manager, report)

    except Exception as e:
        bot_logger.error(f"❌ sync_contacts callback failed: {e}", exc_info=True)
        await bot_manager.send_toast(text=f"❌ Ошибка: {str(e)[:100]}", event=callback)


async def _handle_sync_all_users(callback: CallbackQuery, bot_manager: Any) -> None:
    """Обработка синхронизации всех пользователей из меню."""
    await bot_manager.send_toast(
        text="🔄 Запуск синхронизации всех пользователей...\nЭто может занять время.",
        event=callback,
    )

    try:
        sync_service = AvanpostSyncService()
        await sync_service.initialize()

        result = await sync_service.sync_all_users(force=False)

        report = (
            f"✅ Синхронизация всех пользователей завершена!\n"
            f"👥 Всего пользователей: {result.get('total_users', 0)}\n"
            f"✅ Успешно: {result.get('successful', 0)}\n"
            f"❌ Ошибок: {result.get('failed', 0)}\n"
            f"📈 Вставлено: {result.get('total_inserted', 0)}\n"
            f"🔄 Обновлено: {result.get('total_updated', 0)}\n"
            f"🗑️ Удалено: {result.get('total_deleted', 0)}"
        )

        await _show_result(callback, bot_manager, report)

    except Exception as e:
        bot_logger.error(f"❌ sync_all_users callback failed: {e}", exc_info=True)
        await bot_manager.send_toast(text=f"❌ Ошибка: {str(e)[:100]}", event=callback)


async def _handle_sync_seed_users(callback: CallbackQuery, bot_manager: Any) -> None:
    """Обработка загрузки пользователей из Avanpost из меню."""
    await bot_manager.send_toast(text="🚀 Загрузка пользователей из Avanpost...", event=callback)

    try:
        async with db_manager.get_session() as session:
            result = await AvanpostSeedService.seed_avanpost_users_all(
                session=session,
                create_sync_records=True,
            )

            report = (
                f"✅ Загрузка пользователей из Avanpost завершена!\n"
                f"📊 Загружено ID: {result.get('total_loaded', 0)}\n"
                f"📈 Добавлено: {result.get('total_added', 0)}\n"
                f"⏭️ Пропущено (уже существуют): {result.get('total_skipped', 0)}\n"
                f"❌ Ошибок: {result.get('errors', 0)}"
            )

            await _show_result(callback, bot_manager, report)

    except Exception as e:
        bot_logger.error(f"❌ sync_seed_users callback failed: {e}", exc_info=True)
        await bot_manager.send_toast(text=f"❌ Ошибка: {str(e)[:100]}", event=callback)


__all__ = [
    "router",
    "cmd_sync",
    "cmd_sync_base",
    "cmd_sync_contacts",
    "cmd_sync_user",
    "cmd_sync_all_users",
    "cmd_sync_seed_users",
    "SyncStates",
    "show_sync_menu",
]
