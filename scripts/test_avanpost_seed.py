"""
Тестовый скрипт для синхронизации данных Avanpost с выводом статистики.
"""

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from app.db.manager import db_manager
from app.logger import app_logger as logger
from app.services.avanpost_sync_service import AvanpostSyncService


async def main():
    """Точка входа в приложение"""
    print("=" * 60)
    print("  🔄 Avanpost Sync Service (with Statistics)")
    print("=" * 60)

    try:
        await db_manager.initialize_all()

        sync_service = AvanpostSyncService()
        await sync_service.initialize()

        # Вывод параметров перед вызовом
        print("\n📋 Sync parameters:")
        print("   force: False")
        print(f"   data_types: {sync_service.base_data_types}")
        print(f"   total_types: {len(sync_service.base_data_types)}")
        print()

        # Синхронизация базовых данных
        stats = await sync_service.sync_base_data(force=False)

        # Статистика уже выведена в методе sync_base_data
        # Дополнительный вывод в JSON для отладки
        print("\n📄 Full stats (JSON):")
        import json

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
