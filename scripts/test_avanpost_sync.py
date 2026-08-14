"""
Тестовый скрипт для синхронизации данных Avanpost.
Использует основной сервис из app.services
"""

import asyncio

from app.db.manager import db_manager
from app.logger import app_logger as logger
from app.services.avanpost_sync_service import AvanpostSyncService


async def main():
    """Точка входа в приложение"""
    logger.info("=" * 60)
    logger.info("  🔄 Avanpost Sync Service (Test)")
    logger.info("=" * 60)

    try:
        await db_manager.initialize_all()

        sync_service = AvanpostSyncService()

        # Вывод параметров перед вызовом
        logger.info("📋 Sync parameters:")
        logger.info("   force: False")
        logger.info("   debug: True")
        logger.info(f"   data_types: {sync_service.base_data_types}")
        logger.info(f"   total_types: {len(sync_service.base_data_types)}")

        # Синхронизация базовых данных
        await sync_service.sync_base_data(force=False)

        logger.info("=" * 60)
        logger.info("  ✅ Sync service completed successfully!")
        logger.info("=" * 60)

    except Exception as e:
        logger.error(f"❌ Sync service failed: {e}")
        import traceback

        traceback.print_exc()
        raise
    finally:
        await db_manager.close_all()


if __name__ == "__main__":
    asyncio.run(main())
