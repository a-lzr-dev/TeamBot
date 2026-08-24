"""Тестовый скрипт для синхронизации данных Avanpost.

Использование:
    python scripts/test_avanpost_sync.py [options]

Опции:
    --force         Принудительная синхронизация (игнорировать кеш)
    --users         Синхронизировать пользовательские данные
    --type TYPE     Синхронизировать только указанный тип данных
    --list-types    Показать доступные типы данных
    --quiet         Минимальный вывод (только ошибки)
"""

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from app.db.manager import db_manager
from app.logger import app_logger as logger
from app.services.avanpost_sync_service import AvanpostSyncService


def print_info(msg: str, quiet: bool = False):
    """Вывод информационного сообщения."""
    if not quiet:
        print(msg)
        logger.info(msg)


async def list_data_types(sync_service: AvanpostSyncService, quiet: bool = False):
    """Показать доступные типы данных для синхронизации."""
    print("\n📋 Available data types:")
    print("-" * 60)
    for dtype in sorted(sync_service.base_data_types):
        print(f"  • {dtype}")
    print("-" * 60)
    print(f"Total: {len(sync_service.base_data_types)} types")


async def main():
    """Точка входа в приложение."""
    args = sys.argv[1:]

    force = "--force" in args
    sync_users = "--users" in args
    list_types = "--list-types" in args
    quiet = "--quiet" in args
    sync_type = None

    # Проверка --type
    for i, arg in enumerate(args):
        if arg == "--type" and i + 1 < len(args):
            sync_type = args[i + 1]
            break

    print("=" * 60)
    print("  🔄 Avanpost Sync Service (Test)")
    print("=" * 60)

    try:
        await db_manager.initialize_all()

        sync_service = AvanpostSyncService()
        await sync_service.initialize()

        if list_types:
            await list_data_types(sync_service, quiet)
            return

        # Вывод параметров перед вызовом
        print_info("📋 Sync parameters:", quiet)
        print_info(f"   force: {force}", quiet)
        print_info(f"   sync_users: {sync_users}", quiet)
        if sync_type:
            print_info(f"   sync_type: {sync_type}", quiet)
        print_info(f"   total_types: {len(sync_service.base_data_types)}", quiet)
        print_info("", quiet)

        # Синхронизация базовых данных
        if sync_type:
            if sync_type not in sync_service.base_data_types:
                print(f"❌ Unknown data type: {sync_type}")
                await list_data_types(sync_service, quiet)
                return
            stats = await sync_service.sync_data_type(sync_type, force=force)
        else:
            stats = await sync_service.sync_base_data(force=force)

            # Синхронизация пользователей (опционально)
            if sync_users:
                print_info("\n👤 Syncing user data...", quiet)
                await sync_service.sync_all_users(force=force)
                print_info("✅ User data sync completed", quiet)

        if not quiet:
            print("\n📊 Sync statistics:")
            print(f"   Updated: {stats.updated}")
            print(f"   Created: {stats.created}")
            print(f"   Skipped: {stats.skipped}")
            print(f"   Errors:  {stats.errors}")

        print("=" * 60)
        print("  ✅ Sync service completed successfully!")
        print("=" * 60)

    except Exception as e:
        logger.error(f"❌ Sync service failed: {e}")
        import traceback

        traceback.print_exc()
        raise
    finally:
        await db_manager.close_all()


if __name__ == "__main__":
    asyncio.run(main())
