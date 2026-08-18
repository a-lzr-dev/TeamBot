"""
Команды для управления проектом.
Использование: python scripts/make.py [command]
"""

import subprocess
import sys


def run_command(cmd: str) -> None:
    """Запуск команды с выводом в реальном времени"""
    print(f"🔧 Running: {cmd}")
    subprocess.run(cmd, shell=True, check=True)


def clean() -> None:
    """Очистка кешей и временных файлов"""
    print("🧹 Cleaning cache...")
    run_command("python scripts/clean_cache.py")


def check() -> None:
    """Проверка типов mypy"""
    print("🔍 Running mypy type check...")
    run_command("mypy app/")
    print("✅ Type check completed")


def setup() -> None:
    """Полная настройка проекта"""
    print("🔧 Setting up project...")
    run_command("pip install -r requirements.txt")
    run_command("pre-commit install")
    run_command("python scripts/init_project.py --force --no-sync")


# ============ БАЗА ДАННЫХ ============


def db_clean() -> None:
    """Очистка базы данных (интерактивно)"""
    print("🗄️ Cleaning database...")
    run_command("python -m scripts.db_clean")
    print("✅ Database cleaned")


def db_clean_users() -> None:
    """Очистка только данных пользователей"""
    print("🗄️ Cleaning user data...")
    run_command("python -m scripts.db_clean --users")
    print("✅ User data cleaned")


def db_clean_all() -> None:
    """Полная очистка всех данных (структура сохраняется)"""
    print("🗄️ Cleaning all data...")
    run_command("python -m scripts.db_clean --all-data --force")
    print("✅ All data cleaned")


def db_clean_drop() -> None:
    """Удаление всех таблиц (структура + данные)"""
    print("🗄️ Dropping all tables...")
    run_command("python -m scripts.db_clean --drop-all --force")
    print("✅ Tables dropped")


def db_clean_show() -> None:
    """Показать статистику таблиц"""
    print("📊 Showing table statistics...")
    run_command("python -m scripts.db_clean --show")
    print("✅ Statistics shown")


def db_clean_dry() -> None:
    """Показать что будет удалено без выполнения"""
    print("🔍 Dry run - showing what would be deleted...")
    run_command("python -m scripts.db_clean --all-data --dry-run")
    print("✅ Dry run completed")


def init() -> None:
    """Инициализация БД с seed"""
    print("🗄️ Initializing database...")
    run_command("python scripts/db_migrate.py --reset")
    run_command("python scripts/init_project.py --force --no-sync")


def sync() -> None:
    """Синхронизация Avanpost"""
    print("🔄 Syncing Avanpost...")
    run_command("python scripts/test_avanpost_sync.py")


def seed() -> None:
    """Заполнение системных данных"""
    print("🌱 Seeding database...")
    run_command("python scripts/test_avanpost_seed.py")


def reset() -> None:
    """Полный сброс БД и пересоздание"""
    print("🔄 Resetting database...")
    run_command("python scripts/db_migrate.py --reset")
    run_command("python scripts/init_project.py --force --no-sync")


# ============ ЗАПУСК ============


def dev() -> None:
    """Запуск в режиме разработки"""
    print("🚀 Starting dev server...")
    run_command("python run.py --mode dev")


def full() -> None:
    """Полный запуск приложения"""
    print("🚀 Starting full server...")
    run_command("python run.py --mode full")


# ============ КАЧЕСТВО КОДА ============


def lint() -> None:
    """Запуск линтеров"""
    print("🔍 Running linters...")
    run_command("ruff check app/")
    run_command("mypy app/")


def format_code() -> None:
    """Форматирование кода"""
    print("🎨 Formatting code...")
    run_command("ruff format app/")


def precommit() -> None:
    """Запуск pre-commit хуков"""
    print("🔧 Running pre-commit...")
    run_command("pre-commit run --all-files")


def test() -> None:
    """Запуск тестов"""
    print("🧪 Running tests...")
    run_command("pytest tests/")


# ============ HELP ============


def show_help() -> None:
    """Показать доступные команды"""
    available_commands = {
        # Очистка
        "clean": "Очистка кешей",
        "check": "Проверка типов mypy",
        # База данных
        "db-clean": "Очистка БД (интерактивно)",
        "db-clean-users": "Очистка только данных пользователей",
        "db-clean-all": "Полная очистка всех данных",
        "db-clean-drop": "Удаление всех таблиц",
        "db-clean-show": "Показать статистику таблиц",
        "db-clean-dry": "Показать что будет удалено (dry-run)",
        "init": "Инициализация БД с seed",
        "sync": "Синхронизация Avanpost",
        "seed": "Заполнение системных данных",
        "reset": "Полный сброс БД",
        # Запуск
        "dev": "Запуск в режиме разработки",
        "full": "Полный запуск приложения",
        # Качество кода
        "lint": "Запуск линтеров",
        "format": "Форматирование кода",
        "precommit": "Запуск pre-commit хуков",
        "test": "Запуск тестов",
        # Другое
        "setup": "Полная настройка проекта",
    }

    print("\n📋 Доступные команды:\n")
    for cmd, desc in sorted(available_commands.items()):
        print(f"  {cmd:18} - {desc}")
    print("\n  help            - Показать эту справку")


if __name__ == "__main__":
    command_handlers = {
        # Очистка
        "clean": clean,
        "check": check,
        # База данных
        "db-clean": db_clean,
        "db-clean-users": db_clean_users,
        "db-clean-all": db_clean_all,
        "db-clean-drop": db_clean_drop,
        "db-clean-show": db_clean_show,
        "db-clean-dry": db_clean_dry,
        "init": init,
        "sync": sync,
        "seed": seed,
        "reset": reset,
        # Запуск
        "dev": dev,
        "full": full,
        # Качество кода
        "lint": lint,
        "format": format_code,
        "precommit": precommit,
        "test": test,
        # Другое
        "setup": setup,
        "help": show_help,
    }

    if len(sys.argv) < 2:
        show_help()
        sys.exit(1)

    command = sys.argv[1].lower()
    if command in command_handlers:
        command_handlers[command]()
    else:
        print(f"❌ Неизвестная команда: {command}")
        show_help()
        sys.exit(1)
