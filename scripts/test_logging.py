"""Тестирование логгеров TeamBot.

Использование:
    python scripts/test_loggers.py [options]

Опции:
    --all          Тестировать все логгеры
    --app          Тестировать только app_logger
    --db           Тестировать только db_logger
    --api          Тестировать только api_logger
    --bot          Тестировать только bot_logger
    --admin        Тестировать только admin_logger
    --levels       Тестировать все уровни логирования
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from app.logger import admin_logger, api_logger, app_logger, bot_logger, db_logger


def test_logger(logger, name: str, levels: bool = False):
    """Тестирование одного логгера."""
    print(f"\n📋 Testing {name}...")

    if levels:
        logger.debug(f"✅ DEBUG: {name} works")
        logger.info(f"✅ INFO: {name} works")
        logger.warning(f"✅ WARNING: {name} works")
        logger.error(f"✅ ERROR: {name} works")
        logger.critical(f"✅ CRITICAL: {name} works")
    else:
        logger.info(f"✅ INFO: {name} works")


def main():
    """Главная функция."""
    args = sys.argv[1:]

    if not args or "--all" in args:
        print("🔍 Testing all loggers...")
        print(f"🔍 Current dir: {Path.cwd()}")
        print("-" * 60)

        test_logger(app_logger, "app_logger")
        test_logger(db_logger, "db_logger")
        test_logger(api_logger, "api_logger")
        test_logger(bot_logger, "bot_logger")
        test_logger(admin_logger, "admin_logger")

        print("\n" + "-" * 60)
        print("✅ Log messages sent. Check logs/ directory.")
        return

    if "--levels" in args:
        print("🔍 Testing all log levels...")
        print(f"🔍 Current dir: {Path.cwd()}")
        print("-" * 60)

        test_logger(app_logger, "app_logger", levels=True)
        test_logger(db_logger, "db_logger", levels=True)
        test_logger(api_logger, "api_logger", levels=True)
        test_logger(bot_logger, "bot_logger", levels=True)
        test_logger(admin_logger, "admin_logger", levels=True)

        print("\n" + "-" * 60)
        print("✅ Log messages sent. Check logs/ directory.")
        return

    # Тестирование отдельных логгеров
    logger_map = {
        "--app": app_logger,
        "--db": db_logger,
        "--api": api_logger,
        "--bot": bot_logger,
        "--admin": admin_logger,
    }

    for arg in args:
        if arg in logger_map:
            test_logger(logger_map[arg], arg[2:], levels="--levels" in args)

    print("\n✅ Log messages sent. Check logs/ directory.")


if __name__ == "__main__":
    main()
