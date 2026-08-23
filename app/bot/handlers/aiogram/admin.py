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

3. СИНХРОНИЗАЦИЯ С AVANPOST
   - /sync_base - Синхронизация справочных данных (модели до 205)
   - /sync_contacts - Синхронизация контактов (модели 301-303)
   - /sync_user <id> - Синхронизация данных конкретного пользователя
   - /sync_all_users - Синхронизация данных всех пользователей
   - /sync_light - Стандартная синхронизация (без Force)
   - /sync_force - Полная синхронизация (Force=True)
   - /sync_vehicles - Загрузка пользователей из Avanpost Vehicles

4. ОБРАБОТЧИКИ КОЛБЭКОВ
   - delete_confirm / delete_cancel - Подтверждение/отмена удаления

Примечания:
- Все команды доступны только администраторам (проверка по settings.ADMIN_IDS)
- Синхронизация использует AvanpostSyncService из app.services
- Загрузка пользователей из Vehicles использует AvanpostSeedService
- Колбэки удаления обрабатываются через admin_callback_handler
"""

from aiogram import Router
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message

from ....bot.dependencies import get_bot_manager
from ....config import settings
from ....db import db_manager
from ....db.repositories import ChatRepository, MessageRepository, UserRepository
from ....logger import bot_logger
from ....models import MessageActionType, MessageType
from ....services.avanpost_sync_service import AvanpostSyncService
from ....services.seed_service import AvanpostSeedService
from ....utils.decorators import log_exceptions

# ============================================================
# РОУТЕР И РЕПОЗИТОРИИ
# ============================================================

router = Router(name="aiogram_admin")

_chat_repo = ChatRepository()
_message_repo = MessageRepository()
_user_repo = UserRepository()


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
# 3. СИНХРОНИЗАЦИЯ С AVANPOST
# ============================================================


@router.message(Command("sync_base"))
@log_exceptions(bot_logger)
async def cmd_sync_base(message: Message) -> None:
    """
    Синхронизация справочных данных Avanpost.

    Синхронизирует модели с ID 1-205 (справочники, сценарии, меню действий).

    Args:
        message: Сообщение от пользователя
    """
    bot_manager = get_bot_manager()

    if not message.from_user or message.from_user.id not in settings.ADMIN_IDS:
        await bot_manager.send_answer(text="⛔ У вас нет прав.", event=message)
        return

    await bot_manager.delete_message_by_link(message)
    await bot_manager.send_answer(text="🔄 Запуск синхронизации справочников...", event=message)

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

        await bot_manager.send_answer(text=report, event=message)

    except Exception as e:
        bot_logger.error(f"❌ sync_base failed: {e}", exc_info=True)
        await bot_manager.send_answer(text=f"❌ Ошибка: {e}", event=message)


@router.message(Command("sync_contacts"))
@log_exceptions(bot_logger)
async def cmd_sync_contacts(message: Message) -> None:
    """
    Синхронизация контактов Avanpost.

    Синхронизирует модели TAvanpostContacts, TAvanpostContactsLangs, TAvanpostContactsLinks.

    Args:
        message: Сообщение от пользователя
    """
    bot_manager = get_bot_manager()

    if not message.from_user or message.from_user.id not in settings.ADMIN_IDS:
        await bot_manager.send_answer(text="⛔ У вас нет прав.", event=message)
        return

    await bot_manager.delete_message_by_link(message)
    await bot_manager.send_answer(text="🔄 Запуск синхронизации контактов...", event=message)

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

        await bot_manager.send_answer(text=report, event=message)

    except Exception as e:
        bot_logger.error(f"❌ sync_contacts failed: {e}", exc_info=True)
        await bot_manager.send_answer(text=f"❌ Ошибка: {e}", event=message)


@router.message(Command("sync_user"))
@log_exceptions(bot_logger)
async def cmd_sync_user(message: Message) -> None:
    """
    Синхронизация данных конкретного пользователя Avanpost.

    Формат: /sync_user <user_id>

    Args:
        message: Сообщение от пользователя
    """
    bot_manager = get_bot_manager()

    if not message.from_user or message.from_user.id not in settings.ADMIN_IDS:
        await bot_manager.send_answer(text="⛔ У вас нет прав.", event=message)
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
        )
        return

    try:
        user_id = int(parts[1])
        await bot_manager.send_answer(text=f"🔄 Запуск синхронизации для пользователя {user_id}...", event=message)

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

        await bot_manager.send_answer(text=report, event=message)

    except ValueError:
        await bot_manager.send_answer(text="❌ Неверный формат ID. Используйте число.", event=message)
    except Exception as e:
        bot_logger.error(f"❌ sync_user failed: {e}", exc_info=True)
        await bot_manager.send_answer(text=f"❌ Ошибка: {e}", event=message)


@router.message(Command("sync_all_users"))
@log_exceptions(bot_logger)
async def cmd_sync_all_users(message: Message) -> None:
    """
    Синхронизация данных всех пользователей Avanpost.

    Args:
        message: Сообщение от пользователя
    """
    bot_manager = get_bot_manager()

    if not message.from_user or message.from_user.id not in settings.ADMIN_IDS:
        await bot_manager.send_answer(text="⛔ У вас нет прав.", event=message)
        return

    await bot_manager.delete_message_by_link(message)
    await bot_manager.send_answer(
        text="🔄 Запуск синхронизации для всех пользователей...\n"
        "Это может занять длительное время в зависимости от количества пользователей.",
        event=message,
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

        await bot_manager.send_answer(text=report, event=message)

    except Exception as e:
        bot_logger.error(f"❌ sync_all_users failed: {e}", exc_info=True)
        await bot_manager.send_answer(text=f"❌ Ошибка: {e}", event=message)


@router.message(Command("sync_light"))
@log_exceptions(bot_logger)
async def cmd_sync_light(message: Message) -> None:
    """
    Стандартная синхронизация Avanpost (без Force).

    Args:
        message: Сообщение от пользователя
    """
    bot_manager = get_bot_manager()

    if not message.from_user or message.from_user.id not in settings.ADMIN_IDS:
        await bot_manager.send_answer(text="⛔ У вас нет прав.", event=message)
        return

    await bot_manager.delete_message_by_link(message)
    await bot_manager.send_answer(text="🔄 Запуск стандартной синхронизации...", event=message)

    try:
        result = await db_manager.sync_avanpost(force=False)

        if result.get("success"):
            stats = result.get("stats", {})
            report = (
                f"✅ Стандартная синхронизация завершена!\n"
                f"📈 Вставлено: {stats.get('total_inserted', 0)}\n"
                f"🔄 Обновлено: {stats.get('total_updated', 0)}\n"
                f"🗑️ Удалено: {stats.get('total_deleted', 0)}\n"
                f"⏭️ Без изменений: {stats.get('total_unchanged_upsert', 0)}\n"
                f"❌ Ошибок: {len(stats.get('error_messages', []))}"
            )
            if stats.get("error_messages"):
                report += f"\n⚠️ Первая ошибка: {stats['error_messages'][0][:100]}"
        else:
            report = f"❌ Синхронизация завершена с ошибкой: {result.get('message', 'Unknown error')}"

        await bot_manager.send_answer(text=report, event=message)

    except Exception as e:
        bot_logger.error(f"❌ sync_light failed: {e}", exc_info=True)
        await bot_manager.send_answer(text=f"❌ Ошибка: {e}", event=message)


@router.message(Command("sync_force"))
@log_exceptions(bot_logger)
async def cmd_sync_force(message: Message) -> None:
    """
    Полная синхронизация Avanpost с Force=True.

    Принудительно перезаписывает все данные, игнорируя кеш.

    Args:
        message: Сообщение от пользователя
    """
    bot_manager = get_bot_manager()

    if not message.from_user or message.from_user.id not in settings.ADMIN_IDS:
        await bot_manager.send_answer(text="⛔ У вас нет прав.", event=message)
        return

    await bot_manager.delete_message_by_link(message)
    await bot_manager.send_answer(
        text="🔄 Запуск полной синхронизации (Force)...\nЭто может занять длительное время.",
        event=message,
    )

    try:
        result = await db_manager.sync_avanpost(force=True)

        if result.get("success"):
            stats = result.get("stats", {})
            report = (
                f"✅ Полная синхронизация (Force) завершена!\n"
                f"📈 Вставлено: {stats.get('total_inserted', 0)}\n"
                f"🔄 Обновлено: {stats.get('total_updated', 0)}\n"
                f"🗑️ Удалено: {stats.get('total_deleted', 0)}\n"
                f"⏭️ Без изменений: {stats.get('total_unchanged_upsert', 0)}\n"
                f"❌ Ошибок: {len(stats.get('error_messages', []))}"
            )
            if stats.get("error_messages"):
                report += f"\n⚠️ Первая ошибка: {stats['error_messages'][0][:100]}"
        else:
            report = f"❌ Полная синхронизация завершена с ошибкой: {result.get('message', 'Unknown error')}"

        await bot_manager.send_answer(text=report, event=message)

    except Exception as e:
        bot_logger.error(f"❌ sync_force failed: {e}", exc_info=True)
        await bot_manager.send_answer(text=f"❌ Ошибка: {e}", event=message)


@router.message(Command("sync_vehicles"))
@log_exceptions(bot_logger)
async def cmd_sync_vehicles(message: Message) -> None:
    """
    Загрузка пользователей из Avanpost Vehicles.

    Вызывает хранимую процедуру ext.PA_avp_RSAppUsers_DefaultAdding_Load
    и добавляет полученных пользователей в TAvanpostUsers.

    Args:
        message: Сообщение от пользователя
    """
    bot_manager = get_bot_manager()

    if not message.from_user or message.from_user.id not in settings.ADMIN_IDS:
        await bot_manager.send_answer(text="⛔ У вас нет прав.", event=message)
        return

    await bot_manager.delete_message_by_link(message)
    await bot_manager.send_answer(
        text="🚗 Запуск загрузки пользователей из Avanpost Vehicles...",
        event=message,
    )

    try:
        async with db_manager.get_session() as session:
            result = await AvanpostSeedService.seed_avanpost_users_all(
                session=session,
                create_sync_records=True,
            )

        report = (
            f"✅ Загрузка пользователей из ТС завершена!\n"
            f"📊 Загружено ID: {result['total_loaded']}\n"
            f"📈 Добавлено: {result['total_added']}\n"
            f"📝 Создано записей синхронизации: {result['sync_records_created']}\n"
            f"❌ Ошибок: {result['errors']}"
        )

        if result.get("error_messages"):
            report += f"\n⚠️ Первая ошибка: {result['error_messages'][0][:100]}"

        await bot_manager.send_answer(text=report, event=message)

    except Exception as e:
        bot_logger.error(f"❌ sync_vehicles failed: {e}", exc_info=True)
        await bot_manager.send_answer(text=f"❌ Ошибка: {e}", event=message)


# ============================================================
# 4. ОБРАБОТЧИКИ КОЛБЭКОВ
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
    "cmd_sync_base",
    "cmd_sync_contacts",
    "cmd_sync_user",
    "cmd_sync_all_users",
    "cmd_sync_light",
    "cmd_sync_force",
    "cmd_sync_vehicles",
]
