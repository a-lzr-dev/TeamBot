"""
Скрипт для управления миграциями базы данных TeamBot

Использование:
    python scripts/db_migrate.py --create    # Создать таблицы
    python scripts/db_migrate.py --drop      # Удалить все таблицы
    python scripts/db_migrate.py --reset     # Пересоздать таблицы
    python scripts/db_migrate.py --show      # Показать все таблицы
    python scripts/db_migrate.py --init      # Инициализировать все БД
    python scripts/db_migrate.py --seed      # Заполнить системные данные Avanpost
"""

import argparse
import asyncio
import contextlib
import sys
from pathlib import Path

# Добавление корня проекта в PYTHONPATH
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from sqlalchemy import inspect, text  # noqa: E402

from app.db.manager import db_manager  # noqa: E402
from app.models import BaseModel  # noqa: E402


async def create_tables(db_name: str | None = None):
    """Создание всех таблиц в указанной БД"""
    print(f"🔄 Creating tables for database: {db_name or 'main'}...")
    try:
        await db_manager.init_tables(db_name=db_name, drop_first=False)
        print(f"✅ Tables created successfully for {db_name or 'main'}!")
    except Exception as e:
        print(f"❌ Error creating tables: {e}")
        sys.exit(1)


async def drop_tables(db_name: str | None = None):
    """Удаление всех таблиц (ОСТОРОЖНО!)"""
    confirm = input(f"⚠️  Are you sure you want to DROP ALL TABLES in {db_name or 'main'}? (yes/no): ")
    if confirm.lower() != "yes":
        print("❌ Cancelled")
        return

    print(f"🗑️  Dropping all tables from {db_name or 'main'}...")
    try:
        engine_instance = db_manager.get_engine(db_name) if db_name else db_manager.primary

        if not engine_instance.is_initialized:
            await engine_instance.initialize()

        async with engine_instance.engine.connect() as conn:
            await conn.run_sync(BaseModel.metadata.drop_all)
            await conn.commit()

        print(f"✅ Tables dropped successfully from {db_name or 'main'}!")
    except Exception as e:
        print(f"❌ Error dropping tables: {e}")
        sys.exit(1)


async def reset_tables(db_name: str | None = None):
    """Пересоздание всех таблиц"""
    print(f"🔄 Resetting database: {db_name or 'main'}...")
    await drop_tables(db_name)
    await create_tables(db_name)
    print(f"✅ Database reset complete for {db_name or 'main'}!")


async def show_tables(db_name: str | None = None):
    """Отображение всех таблиц в БД"""
    print(f"📋 Listing all tables in {db_name or 'main'}...")
    try:
        engine_instance = db_manager.get_engine(db_name) if db_name else db_manager.primary

        if not engine_instance.is_initialized:
            await engine_instance.initialize()

        async with engine_instance.engine.connect() as conn:
            # Получение инспектора для текущего движка
            inspector = inspect(engine_instance.engine.sync_engine)
            tables = inspector.get_table_names()

            if tables:
                print(f"📊 Found {len(tables)} tables:")
                for table in sorted(tables):
                    # Получение количества строк в таблице
                    try:
                        result = await conn.execute(text(f"SELECT COUNT(*) FROM {table}"))
                        count = result.scalar()
                        print(f"  - {table}: {count} rows")
                    except Exception:
                        print(f"  - {table}")
            else:
                print("No tables found")

    except Exception as e:
        print(f"❌ Error listing tables: {e}")
        sys.exit(1)


async def show_stats():
    """Отображение статистики по всем БД"""
    print("📊 Database Statistics")
    print("=" * 50)

    stats = await db_manager.get_stats()

    print(f"Primary database: {stats['primary']}")
    print(f"Total databases: {stats['total_databases']}")
    print(f"Total sessions created: {stats['session_counter']}")
    print("\nDatabases:")

    for name, info in stats["databases"].items():
        print(f"\n  📁 {name}:")
        print(f"    Type: {info['type']}")
        print(f"    Initialized: {'✅' if info['initialized'] else '❌'}")
        print(f"    Primary: {'✅' if info['is_primary'] else '❌'}")
        print(f"    URL: {info['url']}")


async def initialize_all():
    """Инициализация всех зарегистрированных БД"""
    print("🔄 Initializing all databases...")
    try:
        await db_manager.initialize_all()
        print("✅ All databases initialized successfully!")

        # Отображение статуса после инициализации
        await show_stats()

    except Exception as e:
        print(f"❌ Error initializing databases: {e}")
        sys.exit(1)


async def seed_avanpost_data():
    """Заполнение системных данных Avanpost"""
    print("🌱 Seeding Avanpost system data types...")

    try:
        # Импорт функции из скрипта
        from scripts.test_avanpost_seed import main as seed_main

        await seed_main()
        print("✅ Avanpost system data seeded successfully!")
    except ImportError as e:
        print(f"❌ Could not import seed script: {e}")
        print("   Please run manually: python scripts/seed_avanpost_sys_data_types.py")
        sys.exit(1)
    except Exception as e:
        print(f"❌ Error seeding Avanpost data: {e}")
        sys.exit(1)


async def close_all():
    """Закрытие всех соединений"""
    print("🔄 Closing all database connections...")
    try:
        await db_manager.close_all()
        print("✅ All database connections closed!")
    except Exception as e:
        print(f"❌ Error closing connections: {e}")
        sys.exit(1)


async def main():
    """Главная функция"""
    parser = argparse.ArgumentParser(description="TeamBot Database Migration Tool")
    parser.add_argument("--create", action="store_true", help="Create all tables")
    parser.add_argument("--drop", action="store_true", help="Drop all tables")
    parser.add_argument("--reset", action="store_true", help="Reset all tables (drop + create)")
    parser.add_argument("--show", action="store_true", help="Show all tables")
    parser.add_argument("--stats", action="store_true", help="Show database statistics")
    parser.add_argument("--init", action="store_true", help="Initialize all databases")
    parser.add_argument("--seed", action="store_true", help="Seed Avanpost system data types")
    parser.add_argument("--close", action="store_true", help="Close all database connections")
    parser.add_argument("--db", type=str, default=None, help="Database name (main, avanpost, etc.)")

    args = parser.parse_args()

    try:
        if args.init:
            await initialize_all()
        elif args.create:
            await create_tables(args.db)
        elif args.drop:
            await drop_tables(args.db)
        elif args.reset:
            await reset_tables(args.db)
        elif args.show:
            await show_tables(args.db)
        elif args.stats:
            await show_stats()
        elif args.seed:
            await seed_avanpost_data()
        elif args.close:
            await close_all()
        else:
            parser.print_help()
            print("\n" + "=" * 50)
            print("Available database names:")
            stats = await db_manager.get_stats()
            for name in stats["databases"]:
                print(f"  - {name}")

    except KeyboardInterrupt:
        print("\n⚠️  Operation cancelled by user")
        sys.exit(1)
    except Exception as e:
        print(f"❌ Unexpected error: {e}")
        import traceback

        traceback.print_exc()
        sys.exit(1)
    finally:
        # Закрытие соединения при завершении
        with contextlib.suppress(Exception):
            await db_manager.close_all()


if __name__ == "__main__":
    print("=" * 60)
    print("  🗄️  TeamBot Database Migration Tool")
    print("=" * 60)
    asyncio.run(main())
