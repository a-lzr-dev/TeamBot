"""
Очистка базы данных main (все таблицы)
"""

import argparse
import asyncio
import contextlib
import sys
from pathlib import Path

from sqlalchemy import text

from app.db.manager import db_manager
from app.logger import app_logger

# Добавление корня проекта в PYTHONPATH
project_root = Path(__file__).parent.parent
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


async def clean_table(session, table_name: str, dry_run: bool = False) -> tuple[bool, str]:
    """Очистка одной таблицы с обработкой ошибок"""
    try:
        if dry_run:
            return True, f"[DRY-RUN] Would delete from {table_name}"

        # Пробуем TRUNCATE
        await session.execute(text(f'TRUNCATE TABLE "{table_name}" CASCADE'))
        await session.commit()
        return True, f"TRUNCATE {table_name}"

    except Exception:
        # Если TRUNCATE не работает, пробуем DELETE
        try:
            # Откатываем транзакцию перед DELETE
            await session.rollback()
            await session.execute(text(f'DELETE FROM "{table_name}"'))
            await session.commit()
            return True, f"DELETE {table_name}"
        except Exception as e2:
            # Если DELETE тоже не работает - откатываем и возвращаем ошибку
            await session.rollback()
            return False, f"Failed to clean {table_name}: {str(e2)}"


async def main():
    parser = argparse.ArgumentParser(description="Clean all tables in main database")
    parser.add_argument("--force", action="store_true", help="Skip confirmation")
    parser.add_argument("--dry-run", action="store_true", help="Show without executing")
    parser.add_argument("--show", action="store_true", help="Show statistics only")
    parser.add_argument("--tables", nargs="+", help="Clean only specific tables")

    args = parser.parse_args()

    print("=" * 70)
    print("  🗄️  TeamBot Database Cleanup (main DB)")
    print("=" * 70)

    try:
        await db_manager.initialize_all()

        async with db_manager.get_session("main") as session:
            # Получение существующих таблиц
            existing_tables = await get_existing_tables(session)
            app_logger.info(f"📊 Found {len(existing_tables)} existing tables in main database")

            # Фильтруем только существующие таблицы
            tables_to_check = [t for t in ALL_TABLES if t in existing_tables]

            if not tables_to_check:
                print("No tables found in main database!")
                return 0

            # Получение статистики
            stats = {}
            for table in tables_to_check:
                try:
                    count_result = await session.execute(text(f'SELECT COUNT(*) FROM "{table}"'))
                    count = count_result.scalar() or 0
                    stats[table] = count
                    if count > 0:
                        app_logger.debug(f"  Table {table}: {count:,} rows")
                except Exception as e:
                    app_logger.warning(f"Could not count {table}: {e}")
                    stats[table] = -1

            non_empty = {k: v for k, v in stats.items() if v > 0}
            total_rows = sum(non_empty.values())

            if args.show:
                print(f"\n📊 Table Statistics ({len(non_empty)} non-empty tables):")
                print("-" * 70)
                print(f"{'Table':<45} {'Rows':>12} {'Status':>12}")
                print("-" * 70)

                if non_empty:
                    for table, count in sorted(non_empty.items(), key=lambda x: x[1], reverse=True):
                        print(f"{table:<45} {count:>12,} {'✅':>12}")
                else:
                    print("No tables with data found")

                print("-" * 70)
                print(f"{'TOTAL':<45} {total_rows:>12,}")
                print("-" * 70)

                # Показать все таблицы
                print(f"\n📋 All tables ({len(tables_to_check)}):")
                for table in tables_to_check:
                    count = stats.get(table, 0)
                    status = "✅" if count > 0 else "⏭️"
                    print(f"  • {table:<40} {count:>8,} {status}")

                return 0

            if total_rows == 0:
                print("\n✅ Database is already empty!")
                return 0

            # Выбор таблиц для очистки
            if args.tables:
                tables_to_clean = [t for t in args.tables if t in tables_to_check and stats.get(t, 0) > 0]
            else:
                tables_to_clean = [t for t in tables_to_check if stats.get(t, 0) > 0]

            if not tables_to_clean:
                print("\n✅ No tables with data to clean")
                return 0

            rows_to_delete = sum(stats.get(t, 0) for t in tables_to_clean)

            if not args.force and not args.dry_run:
                print(f"\n⚠️  WARNING: This will DELETE ALL DATA from {len(tables_to_clean)} tables!")
                print(f"   Total rows: {rows_to_delete:,}")
                print("\n   Tables with data:")
                for table in tables_to_clean[:20]:
                    count = stats.get(table, 0)
                    print(f"     • {table}: {count:,} rows")
                if len(tables_to_clean) > 20:
                    print(f"     • ... and {len(tables_to_clean) - 20} more tables")

                print("\n   Type 'yes' to confirm: ", end="")
                confirm = input().strip().lower()
                if confirm != "yes":
                    print("❌ Cancelled")
                    return 0

            app_logger.info("🚀 Starting cleanup...")

            cleaned = 0
            errors = []
            total_deleted = 0

            for table in tables_to_clean:
                count = stats.get(table, 0)

                if args.dry_run:
                    app_logger.info(f"  [DRY-RUN] Would delete {count} rows from {table}")
                    total_deleted += count
                    cleaned += 1
                    continue

                app_logger.info(f"  Cleaning: {table} ({count} rows)")

                # Очищаем таблицу с обработкой ошибок
                success, message = await clean_table(session, table, dry_run=args.dry_run)

                if success:
                    total_deleted += count
                    cleaned += 1
                    app_logger.debug(f"    ✅ {message}")
                else:
                    app_logger.error(f"    ❌ {message}")
                    errors.append(message)

            # Проверка после очистки
            if not args.dry_run:
                remaining = 0
                remaining_tables = {}
                for table in tables_to_clean:
                    try:
                        count_result = await session.execute(text(f'SELECT COUNT(*) FROM "{table}"'))
                        count = count_result.scalar() or 0
                        if count > 0:
                            remaining += count
                            remaining_tables[table] = count
                    except Exception:
                        pass

            print("\n" + "=" * 70)
            print("📊 CLEANUP RESULTS")
            print("=" * 70)
            print(f"✅ Tables cleaned:  {cleaned}/{len(tables_to_clean)}")

            if args.dry_run:
                print(f"📊 Rows to delete: {total_deleted:,}")
                print("\n🔍 DRY RUN - No changes were made")
            else:
                print(f"📊 Rows deleted:    {total_deleted:,}")
                if "remaining" in locals():
                    print(f"📊 Rows remaining:  {remaining:,}")
                    if remaining_tables:
                        print("\n⚠️  Tables with remaining data:")
                        for table, count in sorted(remaining_tables.items(), key=lambda x: x[1], reverse=True)[:10]:
                            print(f"  • {table}: {count:,} rows")
                        if len(remaining_tables) > 10:
                            print(f"  • ... and {len(remaining_tables) - 10} more")

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
