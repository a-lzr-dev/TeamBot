"""
Полная инициализация проекта TeamBot

Запуск: python scripts/init_project.py

Выполняет:
1. Инициализацию всех БД
2. Создание таблиц
3. Заполнение системных данных Avanpost (seed)
4. Синхронизацию данных Avanpost (sync) - ОПЦИОНАЛЬНО
5. Создание тестовых данных (опционально)
"""

import argparse
import asyncio
import sys
from pathlib import Path

# Добавление корня проекта в PYTHONPATH
sys.path.insert(0, str(Path(__file__).parent.parent))

from app.db.manager import db_manager


async def seed_avanpost_data() -> bool:
    """
    Заполнение системных данных Avanpost.

    Returns:
        bool: True если успешно, False если ошибка
    """
    try:
        from app.services.seed_service import avanpost_seed_service
    except ImportError as e:
        print(f"⚠️  Could not import seeder: {e}")
        print("   Run manually: python scripts/test_avanpost_seed.py")
        return False

    try:
        async with db_manager.get_session("main") as session:
            success = await avanpost_seed_service.seed_system_tables(session)

            if success:
                print("✅ Avanpost system data seeded")
            else:
                print("⚠️  Avanpost seeding completed with errors")
            return success
    except Exception as e:
        print(f"❌ Error seeding Avanpost data: {e}")
        return False


async def execute_avanpost_sync(force: bool = False, sync_users: bool = False) -> bool:
    """
    Запуск синхронизации данных Avanpost.

    Args:
        force: Принудительная синхронизация (игнорировать кеш)
        sync_users: Синхронизировать пользовательские данные

    Returns:
        bool: True если успешно, False если ошибка
    """
    try:
        from app.services.avanpost_sync_service import AvanpostSyncService

        print("🔄 Starting Avanpost data sync...")

        # Инициализация БД (на случай, если ещё не инициализирована)
        await db_manager.initialize_all()

        # Создание сервиса синхронизации
        sync_service = AvanpostSyncService()
        await sync_service.initialize()

        # Запуск синхронизации базовых данных
        print(f"   📊 Syncing base data (force={force})...")
        await sync_service.sync_base_data(force=force)
        print("   ✅ Base data sync completed")

        # Синхронизация пользователей (опционально)
        if sync_users:
            print("   👤 Syncing user data...")
            await sync_service.sync_all_users(force=force)
            print("   ✅ User data sync completed")

        print("✅ Avanpost sync completed successfully")
        return True

    except ImportError as e:
        print(f"⚠️  Could not import sync service: {e}")
        print("ℹ️  Sync skipped. Run manually: python scripts/test_avanpost_sync.py")
        return False
    except Exception as e:
        print(f"❌ Avanpost sync failed: {e}")
        import traceback

        traceback.print_exc()
        return False


async def create_test_data() -> bool:
    """
    Создание тестовых данных.

    Returns:
        bool: True если успешно, False если ошибка
    """
    try:
        from scripts.seed_data import TestDataGenerator
    except ImportError as e:
        print(f"⚠️  Could not import seed_data: {e}")
        print("   Run manually: python scripts/seed_data.py")
        return False

    try:
        async with db_manager.get_session("main") as session:
            generator = TestDataGenerator()
            result = await generator.generate_all(session)
            print(f"✅ Test data created: {result}")
            return True
    except Exception as e:
        print(f"❌ Error creating test data: {e}")
        return False


async def init_project(
    seed_test_data: bool = False,
    force: bool = False,
    do_sync: bool = True,
    sync_force: bool = False,
    sync_users: bool = False,
    skip_seed: bool = False,
) -> None:
    """
    Полная инициализация проекта.

    Args:
        seed_test_data: Создать тестовые данные
        force: Пропустить подтверждения
        do_sync: Выполнить синхронизацию Avanpost
        sync_force: Принудительная синхронизация
        sync_users: Синхронизировать пользователей
        skip_seed: Пропустить seed (только sync)
    """
    print("=" * 60)
    print("  🚀 TeamBot Project Initialization")
    print("=" * 60)

    if not force:
        print("\n⚠️  This will:")
        print("  1. Initialize all databases")
        print("  2. Create all tables")
        if not skip_seed:
            print("  3. Seed Avanpost system data types")
        if do_sync:
            print(f"  {'4' if not skip_seed else '3'}. Sync data from Avanpost (force={sync_force})")
            if sync_users:
                print(f"  {'5' if not skip_seed else '4'}. Sync users from Avanpost")
        if seed_test_data:
            print(f"  {'6' if not skip_seed else '5'}. Create test data")
        print("\n   Press Enter to continue or Ctrl+C to cancel...")
        input()

    try:
        # 1. Инициализация БД
        print("\n📦 Step 1: Initializing databases...")
        await db_manager.initialize_all()
        print("✅ Databases initialized")

        # 2. Создание таблиц
        print("\n📋 Step 2: Creating tables...")
        await db_manager.init_tables(drop_first=False)
        print("✅ Tables created")

        step_num = 3

        # 3. Заполнение системных данных Avanpost (seed)
        if not skip_seed:
            print(f"\n🌱 Step {step_num}: Seeding Avanpost system data...")
            await seed_avanpost_data()
            step_num += 1
        else:
            print("\n⏭️  Seed skipped (--skip-seed flag)")

        # 4. Синхронизация данных Avanpost
        if do_sync:
            print(f"\n🔄 Step {step_num}: Syncing Avanpost data...")
            await execute_avanpost_sync(force=sync_force, sync_users=sync_users)
            step_num += 1
        else:
            print("\n⏭️  Sync skipped (--no-sync flag)")

        # 5. Создание тестовых данных (опционально)
        if seed_test_data:
            print(f"\n🧪 Step {step_num}: Creating test data...")
            await create_test_data()
            step_num += 1

        # Итог
        print("\n" + "=" * 60)
        print("  ✅ Project initialization complete!")
        print("=" * 60)
        print("\n📝 Next steps:")
        print("  1. Update .env with your configuration")
        print("  2. Run: python run.py --mode dev")
        print("  3. Test the bot in Telegram")

    except KeyboardInterrupt:
        print("\n⚠️  Initialization cancelled by user")
        sys.exit(0)
    except Exception as e:
        print(f"\n❌ Initialization failed: {e}")
        import traceback

        traceback.print_exc()
        sys.exit(1)
    finally:
        await db_manager.close_all()


async def main() -> None:
    """Точка входа в приложение"""
    parser = argparse.ArgumentParser(
        description="TeamBot Project Initialization",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
    # Полная инициализация с seed и sync
    python scripts/init_project.py

    # Только seed, без sync
    python scripts/init_project.py --no-sync

    # Только sync (без seed)
    python scripts/init_project.py --skip-seed

    # С тестовыми данными
    python scripts/init_project.py --test-data

    # Принудительная синхронизация (полная перезапись)
    python scripts/init_project.py --sync-force

    # С синхронизацией пользователей
    python scripts/init_project.py --sync-users

    # Пропустить подтверждения
    python scripts/init_project.py --force

    # Комбинация: force + sync force + users
    python scripts/init_project.py --force --sync-force --sync-users

    # Только sync (без seed) с пользователями
    python scripts/init_project.py --skip-seed --sync-users
        """,
    )
    parser.add_argument("--test-data", action="store_true", help="Create test data after initialization")
    parser.add_argument("--force", action="store_true", help="Skip confirmation prompts")
    parser.add_argument("--no-sync", action="store_true", help="Skip Avanpost data sync")
    parser.add_argument("--sync-force", action="store_true", help="Force full Avanpost sync (ignore cache)")
    parser.add_argument("--sync-users", action="store_true", help="Sync Avanpost user data")
    parser.add_argument("--skip-seed", action="store_true", help="Skip Avanpost seed (only sync)")

    args = parser.parse_args()

    await init_project(
        seed_test_data=args.test_data,
        force=args.force,
        do_sync=not args.no_sync,
        sync_force=args.sync_force,
        sync_users=args.sync_users,
        skip_seed=args.skip_seed,
    )


if __name__ == "__main__":
    asyncio.run(main())
