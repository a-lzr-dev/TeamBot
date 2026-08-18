import argparse
import asyncio
import sys
from pathlib import Path

from app.logger import app_logger

# Флаг для отслеживания инициализации проекта
PROJECT_ROOT = Path(__file__).parent
INIT_FLAG_FILE = PROJECT_ROOT / ".project_initialized"


def parse_arguments() -> argparse.Namespace:
    """Парсинг аргументов командной строки"""
    parser = argparse.ArgumentParser(
        description="Запуск приложения TeamBot",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
        Режимы запуска:
          full    - Запуск всех компонентов (БД + API + Bot) [по умолчанию]
          api     - Запуск только API (БД + API)
          bot     - Запуск только Bot (БД + Bot)
          dev     - Запуск API в режиме разработки с автоперезагрузкой

        Примеры:
          python run.py              # Запуск всех компонентов
          python run.py --mode api   # Запуск только API
          python run.py --mode dev   # Запуск API с автоперезагрузкой
          python run.py --mode bot    # Запуск только Bot
        """,
    )

    parser.add_argument(
        "--mode",
        "-m",
        type=str,
        choices=["full", "api", "bot", "dev"],
        default="full",
        help="Режим запуска (по умолчанию: full)",
    )

    parser.add_argument("--host", type=str, default=None, help="Хост для API (переопределяет настройки)")

    parser.add_argument("--port", type=int, default=None, help="Порт для API (переопределяет настройки)")

    parser.add_argument("--reload", action="store_true", help="Включить автоперезагрузку (только для dev режима)")

    parser.add_argument(
        "--workers", type=int, default=1, help="Количество воркеров для uvicorn (только для dev режима)"
    )

    parser.add_argument(
        "--skip-init",
        action="store_true",
        help="Пропустить проверку инициализации проекта",
    )

    parser.add_argument(
        "--force-init",
        action="store_true",
        help="Принудительно запустить инициализацию (игнорирует флаг .project_initialized)",
    )

    return parser.parse_args()


def get_components_for_mode(mode: str) -> list[str]:
    """Определение списка компонентов для запуска в зависимости от режима"""
    components_map = {
        "full": ["db", "api", "bot"],
        "api": ["db", "api"],
        "bot": ["db", "bot"],
        "dev": ["db", "api"],  # В dev режиме запускаем только БД и API
    }

    return components_map.get(mode, ["db", "api", "bot"])


def is_dev_mode(mode: str) -> bool:
    """Проверка, является ли режим режимом разработки"""
    return mode == "dev"


async def check_and_init_project(force: bool = False, skip: bool = False) -> None:
    """
    Проверка инициализации проекта и запуск seed при необходимости.

    Args:
        force: Принудительно запустить инициализацию
        skip: Пропустить проверку
    """
    if skip:
        app_logger.debug("ℹ️ Skipping project initialization check")
        return

    # Проверка флага принудительной инициализации
    if force:
        app_logger.info("🔄 Force initialization requested")
        if INIT_FLAG_FILE.exists():
            INIT_FLAG_FILE.unlink()
            app_logger.debug("🗑️ Removed existing initialization flag")

    # Если проект уже инициализирован и нет force
    if INIT_FLAG_FILE.exists():
        app_logger.debug("✅ Project already initialized")
        return

    app_logger.info("🔍 Project not initialized. Running initial setup...")

    try:
        # Импорт только при необходимости
        from scripts.init_project import init_project

        print("\n" + "=" * 60)
        print("  🔄 Running initial project setup...")
        print("=" * 60)

        # ============================================================
        # АВТОМАТИЧЕСКАЯ ИНИЦИАЛИЗАЦИЯ (force=True)
        # - Не запрашивает подтверждение
        # - Не создает тестовые данные
        # - Пропускает все интерактивные запросы
        # ============================================================
        await init_project(seed_test_data=False, force=True)

        # Создание файла флага
        INIT_FLAG_FILE.touch()
        app_logger.info("✅ Project initialized successfully")

    except ImportError as e:
        app_logger.warning(f"⚠️ Could not import init_project: {e}")
        app_logger.info("ℹ️ Please run manually: python scripts/init_project.py")
        app_logger.info("ℹ️ Continuing without initialization...")

    except KeyboardInterrupt:
        app_logger.warning("⛔ Initialization cancelled by user")
        app_logger.info("ℹ️ You can run initialization manually: python scripts/init_project.py")
        raise

    except Exception as e:
        app_logger.error(f"❌ Project initialization failed: {e}")
        app_logger.info("ℹ️ Please run manually: python scripts/init_project.py")
        app_logger.info("ℹ️ Continuing without initialization...")


async def run_application(mode: str, components: list[str]) -> None:
    """Запуск приложения в указанном режиме"""
    app_logger.debug(f"🚀 Starting application in {mode} mode...")

    from app.config import settings
    from app.core.application import get_app_manager

    manager = get_app_manager()

    try:
        # Запуск компонентов
        app_logger.info(f"📋 Starting components: {', '.join(components)}")
        await manager.start(components)

        # Вывод информации о запуске
        if mode == "dev":
            app_logger.info(
                f"✅ API is running on {settings.API_HOST}:{settings.API_PORT} (development mode with auto-reload)"
            )
        elif "api" in components:
            app_logger.info(f"✅ API is running on {manager.api.host}:{manager.api.port}")

        if "bot" in components:
            app_logger.info("✅ Bot is running")

        app_logger.info("✅ Application is running. Press Ctrl+C to stop.")

        # Ожидание сигнала остановки
        try:
            while manager.is_running:
                await asyncio.sleep(1)
        except KeyboardInterrupt:
            app_logger.info("⛔ Interrupt signal received")

    except KeyboardInterrupt:
        app_logger.info("⛔ Application stopped by user")

    except Exception as e:
        app_logger.error(f"❌ Application failed: {e}", exc_info=True)
        sys.exit(1)

    finally:
        app_logger.debug("🚀 Components stopped starting...")
        await manager.stop(components)
        app_logger.info("✅ Application Shutdown complete")


async def run_dev_mode(host: str | None = None, port: int | None = None) -> None:
    """Запуск API в режиме разработки с автоперезагрузкой"""
    try:
        import uvicorn

        from app.config import settings
        from app.core.application import get_app_manager

        host = host or settings.API_HOST
        port = port or settings.API_PORT

        app_logger.debug("🚀 Starting API in DEVELOPMENT mode...")
        app_logger.info(f"   Host: {host}")
        app_logger.info(f"   Port: {port}")
        app_logger.info("   Auto-reload: Enabled")
        app_logger.info("   Watch directory: app/")

        manager = get_app_manager()

        # Инициализация компонентов (без запуска сервера)
        app_logger.info("📋 Initializing components: db, api")
        await manager.start(["db", "api"])

        # Получение FastAPI приложения
        app_instance = manager.api.app

        # Остановка менеджера (uvicorn будет управлять жизненным циклом)
        await manager.stop(["db", "api"])

        # Запуск uvicorn с автоперезагрузкой
        uvicorn.run(
            app_instance,
            host=host,
            port=port,
            log_level=settings.LOG_LEVEL.lower(),
            access_log=False,
            reload=True,
            reload_dirs=["app"],
            workers=1,
            loop="asyncio",
            timeout_keep_alive=getattr(settings, "HTTP_TIMEOUT_KEEP_ALIVE", 30),
        )

    except KeyboardInterrupt:
        app_logger.info("⛔ API stopped by user")

    except ImportError:
        app_logger.error("❌ uvicorn not installed. Please install it: pip install uvicorn")
        sys.exit(1)

    except Exception as e:
        app_logger.error(f"❌ API failed: {e}", exc_info=True)
        sys.exit(1)


async def main() -> None:
    """Основная асинхронная функция"""
    args = parse_arguments()

    # Проверка инициализации проекта
    # Пропускаем только в dev режиме без force-init
    if args.mode != "dev" or args.force_init:
        try:
            await check_and_init_project(force=args.force_init, skip=args.skip_init)
        except KeyboardInterrupt:
            app_logger.info("⛔ Initialization cancelled, exiting...")
            sys.exit(0)

    # Проверка режима разработки
    if args.mode == "dev":
        await run_dev_mode(args.host, args.port)
        return

    from app.config import settings

    # Получение компонентов для запуска
    components = get_components_for_mode(args.mode)

    # Переопределение настроек, если указаны
    if args.host:
        settings.API_HOST = args.host
    if args.port:
        settings.API_PORT = args.port

    # Запуск приложения
    await run_application(args.mode, components)


if __name__ == "__main__":
    """Точка входа в приложение"""
    app_logger.debug("🚀 Application starting...")

    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        app_logger.info("⛔ Application stopped by user")
    except Exception as err:
        app_logger.critical(f"❌ Application Fatal Error: {err}", exc_info=True)
        sys.exit(1)
