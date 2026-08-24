"""Тестовый скрипт для синхронизации данных Avanpost с выводом статистики.

Использование:
    python scripts/test_avanpost_sync.py [options]

Опции:
    --force         Принудительная синхронизация (игнорировать кеш)
    --users         Синхронизировать пользовательские данные
    --type TYPE     Синхронизировать только указанный тип данных
    --list-types    Показать доступные типы данных
"""

import asyncio
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from app.db.manager import db_manager
from app.logger import app_logger as logger
from app.services.avanpost_sync_service import AvanpostSyncService


async def list_data_types(sync_service: AvanpostSyncService):
    """Показать доступные типы данных для синхронизации."""
    print("\n📋 Available data types:")
    print("-" * 60)
    for dtype in sync_service.base_data_types:
        print(f"  • {dtype}")
    print("-" * 60)
    print(f"Total: {len(sync_service.base_data_types)} types")


async def main():
    """Точка входа в приложение."""
    args = sys.argv[1:]

    force = "--force" in args
    sync_users = "--users" in args
    list_types = "--list-types" in args
    sync_type = None

    # Проверка --type
    for i, arg in enumerate(args):
        if arg == "--type" and i + 1 < len(args):
            sync_type = args[i + 1]
            break

    print("=" * 60)
    print("  🔄 Avanpost Sync Service (with Statistics)")
    print("=" * 60)

    try:
        await db_manager.initialize_all()

        sync_service = AvanpostSyncService()
        await sync_service.initialize()

        if list_types:
            await list_data_types(sync_service)
            return

        # Вывод параметров перед вызовом
        print("\n📋 Sync parameters:")
        print(f"   force: {force}")
        print(f"   sync_users: {sync_users}")
        if sync_type:
            print(f"   sync_type: {sync_type}")
        print(f"   total_types: {len(sync_service.base_data_types)}")
        print()

        # Синхронизация базовых данных
        if sync_type:
            if sync_type not in sync_service.base_data_types:
                print(f"❌ Unknown data type: {sync_type}")
                await list_data_types(sync_service)
                return
            stats = await sync_service.sync_data_type(sync_type, force=force)
        else:
            stats = await sync_service.sync_base_data(force=force)

            # Синхронизация пользователей (опционально)
            if sync_users:
                print("\n👤 Syncing user data...")
                await sync_service.sync_all_users(force=force)
                print("✅ User data sync completed")

        # Статистика уже выведена в методе sync_base_data
        # Дополнительный вывод в JSON для отладки
        print("\n📄 Full stats (JSON):")
        print(json.dumps(stats.to_dict(), indent=2, default=str, ensure_ascii=False))

        print("\n" + "=" * 60)
        print("  ✅ Sync completed!")
        print("=" * 60)

    except Exception as e:
        logger.error(f"❌ Sync failed: {e}")
        import traceback

        traceback.print_exc()
        raise
    finally:
        await db_manager.close_all()


if __name__ == "__main__":
    asyncio.run(main())
