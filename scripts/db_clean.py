"""
Очистка базы данных main.

Режимы работы:
    --users         Удалить только данные пользователей (сохранить структуру)
    --all-data      Удалить все данные из всех таблиц (сохранить структуру)
    --drop-all      Удалить все таблицы (структура + данные)
    --dry-run       Показать, что будет удалено, без выполнения
    --force         Пропустить подтверждение
    --show          Показать статистику таблиц
    --tables T1 T2  Очистить только указанные таблицы
"""

import argparse
import asyncio
import contextlib
import sys
from pathlib import Path

from sqlalchemy import text

from app.db.manager import db_manager
from app.logger import app_logger

# Добавление корня проекта в PYTHONPATH ПЕРВЫМ
project_root = Path(__file__).parent.parent

if str(project_root) in sys.path:
    sys.path.remove(str(project_root))
sys.path.insert(0, str(project_root))

# Все таблицы в правильном порядке (сначала дочерние)
ALL_TABLES = [
    # Связи (дочерние)
    "TErrorsMessagesLinks",
    "TUsersRemindersShares",
    "TAvanpostLinksContactsMsgsFiles",
    "TAvanpostLinksMsgsFiles",
    "TAvanpostDirScenariosGroupsItemsLinksScenariosInstructions",
    "TAvanpostDirScenariosGroupsItemsLinksScenariosGroups",
    "TAvanpostDirScenariosGroupsItemsLinksScenarios",
    "TAvanpostDirScenariosInstructionsFiles",
    "TAvanpostUsersOrdersLinksMissions",
    "TAvanpostUsersLinksChatsContactsMsgs",
    "TAvanpostUsersLinksContactsMsgsControls",
    "TAvanpostUsersLinksContacts",
    # Сообщения
    "TChatsMessages",
    "TAvanpostContactsMsgsProcess",
    "TAvanpostContactsMsgs",
    "TAvanpostMsgs",
    # Ошибки и фильтры
    "TErrors",
    "TErrorsFilters",
    "TChatsNotificationsSettings",
    # Avanpost справочники
    "TAvanpostDirScenariosGroupsItemsLangs",
    "TAvanpostDirScenariosGroupsItems",
    "TAvanpostDirScenariosActionsLangs",
    "TAvanpostDirScenariosActionsValues",
    "TAvanpostDirScenariosActions",
    "TAvanpostDirScenariosCustom",
    "TAvanpostDirScenariosInstructionsLangs",
    "TAvanpostDirScenariosInstructions",
    "TAvanpostDirScenarios",
    "TAvanpostContactsLangs",
    "TAvanpostContactsLinks",
    "TAvanpostContacts",
    # Пользователи Avanpost
    "TAvanpostUsersMissionsItemsLangs",
    "TAvanpostUsersMissionsItems",
    "TAvanpostUsersMissionsLangs",
    "TAvanpostUsersMissions",
    "TAvanpostUsersOrdersLangs",
    "TAvanpostUsersOrders",
    "TAvanpostUsersChatsLangs",
    "TAvanpostUsersChats",
    "TAvanpostUsersStatus",
    "TAvanpostUsersVehicles",
    "TAvanpostUsers",
    # Файлы
    "TAvanpostFiles",
    # Системные
    "TAvanpostSysUsersUpdates",
    "TAvanpostSysUpdates",
    "TAvanpostDirSysDataTypes",
    # Основные таблицы TeamBot
    "TChatsMembers",
    "TUsersReminders",
    "TUsersRequestsAutomations",
    "TPeriodicTasks",
    "TChats",
    "TUsers",
    # Базовые справочники Avanpost (в конце, т.к. на них ссылаются)
    "TAvanpostDirContactsGroups",
    "TAvanpostDirContactsLinksTypes",
    "TAvanpostDirContactsMsgsDirectionsTypes",
    "TAvanpostDirContactsMsgsProcessTypes",
    "TAvanpostDirContactsMsgsTypes",
    "TAvanpostDirFilesTypes",
    "TAvanpostDirLanguages",
    "TAvanpostDirOperators",
    "TAvanpostDirOwners",
    "TAvanpostDirOwnersMotorCades",
    "TAvanpostDirScenariosActionsTypes",
    "TAvanpostDirScenariosActionsValuesTypes",
    "TAvanpostDirScenariosGroupsItemsTypes",
    "TAvanpostDirScenariosGroups",
    "TAvanpostDirScenariosTypes",
    "TAvanpostDirUsersContactsRolesTypes",
    "TAvanpostDirUsersLinksContactsMsgsControlsProcessTypes",
    "TAvanpostDirUsersStatusTypes",
]

# Таблицы, связанные с пользователями (для режима --users)
USER_TABLES = [
    "TUsers",
    "TChatsMembers",
    "TChatsMessages",
    "TUsersReminders",
    "TUsersRequestsAutomations",
    "TUsersRemindersShares",
    "TErrors",
    "TErrorsMessagesLinks",
    "TAvanpostUsers",
    "TAvanpostUsersChats",
    "TAvanpostUsersChatsLangs",
    "TAvanpostUsersStatus",
    "TAvanpostUsersLinksContacts",
    "TAvanpostUsersMissions",
    "TAvanpostUsersMissionsLangs",
    "TAvanpostUsersMissionsItems",
    "TAvanpostUsersMissionsItemsLangs",
    "TAvanpostUsersOrders",
    "TAvanpostUsersOrdersLangs",
    "TAvanpostUsersOrdersLinksMissions",
    "TAvanpostUsersVehicles",
    "TAvanpostUsersLinksChatsContactsMsgs",
    "TAvanpostUsersLinksContactsMsgsControls",
    "TAvanpostSysUsersUpdates",
]


async def get_existing_tables(session) -> set[str]:
    """Получение списка существующих таблиц в БД main"""
    try:
        result = await session.execute(
            text("""
            SELECT table_name
            FROM information_schema.tables
            WHERE table_schema = 'public'
              AND table_type = 'BASE TABLE'
        """)
        )
        return {row[0] for row in result.fetchall()}
    except Exception as e:
        app_logger.error(f"Failed to get existing tables: {e}")
        return set()


async def get_table_count(session, table_name: str) -> int:
    """Получение количества строк в таблице"""
    try:
        result = await session.execute(text(f'SELECT COUNT(*) FROM "{table_name}"'))
        return result.scalar() or 0
    except Exception:
        return -1


async def truncate_table(session, table_name: str) -> tuple[bool, str]:
    """TRUNCATE таблицы"""
    try:
        await session.execute(text(f'TRUNCATE TABLE "{table_name}" CASCADE'))
        return True, f"TRUNCATE {table_name}"
    except Exception as e:
        return False, f"Failed to truncate {table_name}: {str(e)}"


async def delete_table_data(session, table_name: str) -> tuple[bool, str]:
    """DELETE FROM таблицы"""
    try:
        await session.execute(text(f'DELETE FROM "{table_name}"'))
        return True, f"DELETE {table_name}"
    except Exception as e:
        return False, f"Failed to delete from {table_name}: {str(e)}"


async def drop_table(session, table_name: str) -> tuple[bool, str]:
    """DROP TABLE"""
    try:
        await session.execute(text(f'DROP TABLE IF EXISTS "{table_name}" CASCADE'))
        return True, f"DROP {table_name}"
    except Exception as e:
        return False, f"Failed to drop {table_name}: {str(e)}"


async def clean_table(session, table_name: str, dry_run: bool = False, drop: bool = False) -> tuple[bool, str]:
    """Очистка одной таблицы"""
    if dry_run:
        action = "DROP" if drop else "TRUNCATE/DELETE"
        return True, f"[DRY-RUN] Would {action} {table_name}"

    if drop:
        return await drop_table(session, table_name)

    # Сначала пробуем TRUNCATE, если не получается - DELETE
    success, message = await truncate_table(session, table_name)
    if success:
        return True, message

    # Откатываем транзакцию перед DELETE
    await session.rollback()
    success, message = await delete_table_data(session, table_name)
    if success:
        return True, message

    await session.rollback()
    return False, message


async def show_statistics(session, tables: list[str]) -> dict[str, int]:
    """Показ статистики по таблицам"""
    stats = {}
    print("\n📊 Checking table statistics...")
    print("-" * 70)
    print(f"{'Table':<45} {'Rows':>12} {'Status':>12}")
    print("-" * 70)

    total_rows = 0
    non_empty = 0

    for table in tables:
        count = await get_table_count(session, table)
        stats[table] = count
        if count > 0:
            non_empty += 1
            total_rows += count
            status = "✅"
        elif count == 0:
            status = "⏭️"
        else:
            status = "⚠️"
        print(f"{table:<45} {count:>12,} {status:>12}")

    print("-" * 70)
    print(f"{'TOTAL':<45} {total_rows:>12,}")
    print("-" * 70)
    print(f"\n📊 Summary: {len(tables)} tables, {non_empty} non-empty, {total_rows:,} total rows")

    return stats


def get_mode_description(mode: str, tables: list[str] | None = None) -> str:
    """Получение описания режима"""
    descriptions = {
        "show": "Просмотр статистики",
        "users": "Удаление данных пользователей (структура сохраняется)",
        "all_data": "Удаление ВСЕХ данных (структура сохраняется)",
        "drop_all": "Удаление ВСЕХ таблиц (структура + данные)",
    }
    if mode == "tables" and tables:
        return f"Очистка таблиц: {', '.join(tables)}"
    return descriptions.get(mode, "unknown")


async def main():
    parser = argparse.ArgumentParser(
        description="Clean TeamBot database (main)",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Примеры использования:
  # Показать статистику
  python scripts/db_clean.py --show

  # Удалить только данные пользователей
  python scripts/db_clean.py --users

  # Удалить все данные (структура сохраняется)
  python scripts/db_clean.py --all-data

  # Удалить все таблицы (структура + данные)
  python scripts/db_clean.py --drop-all

  # Показать, что будет удалено без выполнения
  python scripts/db_clean.py --users --dry-run

  # Очистить только указанные таблицы
  python scripts/db_clean.py --tables TUsers TChats
        """,
    )

    parser.add_argument("--users", action="store_true", help="Delete only user data (preserve structure)")
    parser.add_argument("--all-data", action="store_true", help="Delete all data from all tables (preserve structure)")
    parser.add_argument("--drop-all", action="store_true", help="Drop all tables (structure + data)")
    parser.add_argument("--dry-run", action="store_true", help="Show what would be deleted without executing")
    parser.add_argument("--force", action="store_true", help="Skip confirmation")
    parser.add_argument("--show", action="store_true", help="Show table statistics only")
    parser.add_argument("--tables", nargs="+", help="Clean only specific tables")

    args = parser.parse_args()

    print("=" * 70)
    print("  🗄️  TeamBot Database Cleanup (main DB)")
    print("=" * 70)

    # Определение режима
    if args.show:
        mode = "show"
    elif args.drop_all:
        mode = "drop_all"
    elif args.all_data:
        mode = "all_data"
    elif args.users:
        mode = "users"
    elif args.tables:
        mode = "tables"
    else:
        mode = "all_data"
        print("\n⚠️  Режим не указан, используется --all-data")
        print("   Используйте --users для очистки только данных пользователей")
        print("   Используйте --drop-all для удаления всех таблиц")
        print("   Используйте --show для просмотра статистики\n")

    try:
        await db_manager.initialize_all()

        async with db_manager.get_session("main") as session:
            existing_tables = await get_existing_tables(session)

            if not existing_tables:
                print("\n❌ No tables found in main database!")
                return 1

            # Определение списка таблиц для работы
            if args.tables:
                tables_to_process = [t for t in args.tables if t in existing_tables]
                if not tables_to_process:
                    print(f"\n❌ None of the specified tables exist: {args.tables}")
                    return 1
            elif mode == "users":
                tables_to_process = [t for t in USER_TABLES if t in existing_tables]
            else:
                tables_to_process = sorted(existing_tables)

            if mode == "show":
                await show_statistics(session, tables_to_process)
                return 0

            # Получение статистики перед очисткой
            stats = {}
            for table in tables_to_process:
                stats[table] = await get_table_count(session, table)

            non_empty = {k: v for k, v in stats.items() if v > 0}
            total_rows = sum(non_empty.values())

            if not non_empty:
                print("\n✅ Database is already empty!")
                return 0

            # Формирование сообщения в зависимости от режима
            mode_desc = get_mode_description(mode, args.tables)

            print(f"\n📋 Режим: {mode_desc}")
            print(f"📊 Будет затронуто: {len(non_empty)} таблиц, {total_rows:,} строк")

            if mode == "users":
                print("\n🗑️  Будут удалены данные следующих таблиц:")
                for table in sorted(non_empty.keys()):
                    print(f"  • {table}: {non_empty[table]:,} rows")
            elif mode != "tables" and mode != "drop_all":
                print("\n⚠️  БУДУТ УДАЛЕНЫ ВСЕ ДАННЫЕ ИЗ ВСЕХ ТАБЛИЦ!")
                print("\n   Таблицы с данными:")
                for table in sorted(non_empty.keys())[:20]:
                    print(f"  • {table}: {non_empty[table]:,} rows")
                if len(non_empty) > 20:
                    print(f"  • ... и еще {len(non_empty) - 20} таблиц")

            if mode == "drop_all":
                print("\n⚠️⚠️⚠️  ВНИМАНИЕ! БУДУТ УДАЛЕНЫ ВСЕ ТАБЛИЦЫ!")
                print("   Это приведет к полной потере структуры БД!")

            if not args.force and not args.dry_run:
                print("\n   Введите 'yes' для подтверждения: ", end="")
                confirm = input().strip().lower()
                if confirm != "yes":
                    print("❌ Отменено")
                    return 0

            # Выполнение очистки
            app_logger.info("🚀 Starting cleanup...")

            cleaned = 0
            errors = []
            total_deleted = 0

            # Для DROP ALL таблицы нужно удалять в обратном порядке (сначала дочерние)
            if mode == "drop_all":
                # Сортируем по индексу в ALL_TABLES (обратный порядок)
                tables_to_process = sorted(
                    tables_to_process, key=lambda x: ALL_TABLES.index(x) if x in ALL_TABLES else 999, reverse=True
                )

            for table in tables_to_process:
                count = stats.get(table, 0)

                if args.dry_run:
                    action = "DROP" if mode == "drop_all" else "TRUNCATE/DELETE"
                    app_logger.info(f"  [DRY-RUN] Would {action} {table} ({count} rows)")
                    if count > 0:
                        total_deleted += count
                    cleaned += 1
                    continue

                success, message = await clean_table(
                    session,
                    table,
                    dry_run=False,
                    drop=(mode == "drop_all"),
                )

                if success:
                    if count > 0:
                        total_deleted += count
                    cleaned += 1
                    app_logger.debug(f"    ✅ {message}")
                else:
                    app_logger.error(f"    ❌ {message}")
                    errors.append(message)

            # Если удаляли таблицы, нужно пересоздать их через SQLAlchemy
            if mode == "drop_all" and not args.dry_run:
                print("\n🔄 Recreating tables...")
                try:
                    await db_manager.init_tables(drop_first=False)
                    print("✅ Tables recreated successfully!")
                except Exception as e:
                    print(f"❌ Failed to recreate tables: {e}")
                    errors.append(f"Recreate tables failed: {e}")

            # Вывод результатов
            print("\n" + "=" * 70)
            print("📊 CLEANUP RESULTS")
            print("=" * 70)
            print(f"✅ Tables cleaned:  {cleaned}/{len(tables_to_process)}")

            if args.dry_run:
                print(f"📊 Rows to delete: {total_deleted:,}")
                print("\n🔍 DRY RUN - No changes were made")
            else:
                print(f"📊 Rows deleted:    {total_deleted:,}")

                # Проверка после очистки (если не удаляли таблицы)
                if mode != "drop_all":
                    remaining = 0
                    remaining_tables = {}
                    for table in tables_to_process:
                        count = await get_table_count(session, table)
                        if count > 0:
                            remaining += count
                            remaining_tables[table] = count

                    if remaining_tables:
                        print("\n⚠️  Tables with remaining data:")
                        for table, count in sorted(remaining_tables.items(), key=lambda x: x[1], reverse=True)[:10]:
                            print(f"  • {table}: {count:,} rows")
                        if len(remaining_tables) > 10:
                            print(f"  • ... and {len(remaining_tables) - 10} more")
                    else:
                        print("\n✅ All tables are empty!")

            if errors:
                print(f"\n❌ Errors ({len(errors)}):")
                for error in errors[:10]:
                    print(f"  • {error}")
                if len(errors) > 10:
                    print(f"  • ... and {len(errors) - 10} more")

            print("=" * 70)

            if not args.dry_run and not errors:
                print("\n✅ Cleanup completed successfully!")
            elif not args.dry_run and errors:
                print(f"\n⚠️  Cleanup completed with {len(errors)} errors")

            return 0 if not errors else 1

    except KeyboardInterrupt:
        print("\n⚠️  Cancelled")
        return 1
    except Exception as e:
        app_logger.error(f"❌ Error: {e}", exc_info=True)
        print(f"\n❌ Error: {e}")
        return 1
    finally:
        with contextlib.suppress(Exception):
            await db_manager.close_all()


if __name__ == "__main__":
    exit_code = asyncio.run(main())
    sys.exit(exit_code)
