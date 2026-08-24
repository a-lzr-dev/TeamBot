"""Проверка существования таблиц в PostgreSQL.

Использование:
    python scripts/check_tables.py [command]

Команды:
    check           - Проверить наличие таблиц TAvanpostSysUpdates и TAvanpostSysUsersUpdates
    all             - Проверить все таблицы в схеме public
    info            - Показать информацию о всех таблицах (колонки, типы)
"""

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from sqlalchemy import text

from app.db.manager import db_manager


async def check_tables():
    """Проверка существования таблиц TAvanpostSysUpdates и TAvanpostSysUsersUpdates."""
    print("=" * 60)
    print("  🔍 Checking Tables in PostgreSQL")
    print("=" * 60)

    try:
        await db_manager.initialize_all()

        async with db_manager.get_session("main") as session:
            # Проверка таблицы TAvanpostSysUpdates
            print("\n📋 Checking TAvanpostSysUpdates...")
            try:
                result = await session.execute(text("SELECT COUNT(*) FROM TAvanpostSysUpdates"))
                count = result.scalar()
                print(f"   ✅ TAvanpostSysUpdates exists, rows: {count}")
            except Exception as e:
                print(f"   ❌ Error: {e}")

            # Проверка таблицы TAvanpostSysUsersUpdates
            print("\n📋 Checking TAvanpostSysUsersUpdates...")
            try:
                result = await session.execute(text("SELECT COUNT(*) FROM TAvanpostSysUsersUpdates"))
                count = result.scalar()
                print(f"   ✅ TAvanpostSysUsersUpdates exists, rows: {count}")
            except Exception as e:
                print(f"   ❌ Error: {e}")

            # Проверка через information_schema
            print("\n📋 Checking via information_schema...")
            result = await session.execute(
                text("""SELECT table_name FROM information_schema.tables WHERE table_name IN ('TAvanpostSysUpdates',
                     'TAvanpostSysUsersUpdates')""")
            )
            tables = [row[0] for row in result.fetchall()]
            print(f"   Tables found: {tables}")

    except Exception as e:
        print(f"❌ Error: {e}")
        import traceback

        traceback.print_exc()
    finally:
        await db_manager.close_all()


async def check_all_tables():
    """Проверить все таблицы в схеме public."""
    print("=" * 60)
    print("  📋 All Tables in Schema public")
    print("=" * 60)

    try:
        await db_manager.initialize_all()

        async with db_manager.get_session("main") as session:
            result = await session.execute(
                text(
                    """
                SELECT
                    table_name,
                    (SELECT COUNT(*) FROM information_schema.columns
                     WHERE table_name = t.table_name) as columns_count
                FROM information_schema.tables t
                WHERE table_schema = 'public'
                ORDER BY table_name
            """
                )
            )
            tables = result.fetchall()

            print(f"\n📊 Total tables: {len(tables)}\n")
            for table in tables:
                print(f"   📄 {table[0]} ({table[1]} columns)")

    except Exception as e:
        print(f"❌ Error: {e}")
    finally:
        await db_manager.close_all()


async def show_table_info():
    """Показать информацию о таблицах (колонки, типы данных)."""
    print("=" * 60)
    print("  📋 Table Schema Information")
    print("=" * 60)

    try:
        await db_manager.initialize_all()

        async with db_manager.get_session("main") as session:
            # Проверка структуры TAvanpostSysUpdates
            print("\n📋 TAvanpostSysUpdates structure:")
            result = await session.execute(
                text(
                    """
                SELECT
                    column_name,
                    data_type,
                    is_nullable,
                    column_default
                FROM information_schema.columns
                WHERE table_name = 'TAvanpostSysUpdates'
                ORDER BY ordinal_position
            """
                )
            )
            columns = result.fetchall()
            for col in columns:
                print(f"   {col[0]:20} {col[1]:15} nullable: {col[2]:5} default: {col[3]}")

            # Проверка структуры TAvanpostSysUsersUpdates
            print("\n📋 TAvanpostSysUsersUpdates structure:")
            result = await session.execute(
                text(
                    """
                SELECT
                    column_name,
                    data_type,
                    is_nullable,
                    column_default
                FROM information_schema.columns
                WHERE table_name = 'TAvanpostSysUsersUpdates'
                ORDER BY ordinal_position
            """
                )
            )
            columns = result.fetchall()
            for col in columns:
                print(f"   {col[0]:20} {col[1]:15} nullable: {col[2]:5} default: {col[3]}")

    except Exception as e:
        print(f"❌ Error: {e}")
    finally:
        await db_manager.close_all()


if __name__ == "__main__":
    if len(sys.argv) < 2:
        asyncio.run(check_tables())
        sys.exit(0)

    command = sys.argv[1].lower()

    if command == "check":
        asyncio.run(check_tables())
    elif command == "all":
        asyncio.run(check_all_tables())
    elif command == "info":
        asyncio.run(show_table_info())
    else:
        print(f"❌ Unknown command: {command}")
        print(__doc__)
        sys.exit(1)
