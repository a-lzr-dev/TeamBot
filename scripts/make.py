"""Утилита для управления проектом через удобные команды.

Использование:
    python scripts/make.py [command]

Доступные команды группированы по назначению:
    - Настройка и инициализация
    - База данных
    - Запуск приложения
    - Качество кода
    - Очистка и утилиты
"""

import subprocess
import sys
from pathlib import Path

# Добавляем путь к скриптам
SCRIPT_DIR = Path(__file__).parent
PROJECT_ROOT = SCRIPT_DIR.parent
sys.path.insert(0, str(PROJECT_ROOT))


def run_command(cmd: str) -> None:
    """Запуск команды с выводом в реальном времени."""
    print(f"🔧 Running: {cmd}")
    subprocess.run(cmd, shell=True, check=True)


# ============================================
# 1. НАСТРОЙКА И ИНИЦИАЛИЗАЦИЯ
# ============================================


def setup() -> None:
    """Полная настройка проекта с нуля."""
    print("🔧 Setting up project...")
    run_command("pip install -r requirements.txt")
    run_command("pre-commit install")
    run_command("python scripts/init_project.py --force --no-sync")


def init() -> None:
    """Инициализация БД с наполнением системными данными."""
    print("🗄️ Initializing database...")
    run_command("python scripts/db_migrate.py --reset")
    run_command("python scripts/init_project.py --force --no-sync")


def reset() -> None:
    """Полный сброс БД (миграции + инициализация)."""
    print("🔄 Resetting database...")
    run_command("python scripts/db_migrate.py --reset")
    run_command("python scripts/init_project.py --force --no-sync")


def seed() -> None:
    """Заполнение базы системными данными (без сброса)."""
    print("🌱 Seeding database...")
    run_command("python scripts/test_avanpost_seed.py")


# ============================================
# 2. БАЗА ДАННЫХ
# ============================================


def sync() -> None:
    """Синхронизация данных с Avanpost."""
    print("🔄 Syncing Avanpost...")
    run_command("python scripts/test_avanpost_sync.py")


def db_clean_show() -> None:
    """Показать статистику таблиц в БД."""
    print("📊 Showing table statistics...")
    run_command("python scripts/db_clean.py --show")


def db_clean_dry() -> None:
    """Показать, что будет удалено, без фактического выполнения."""
    print("🔍 Dry run - showing what would be deleted...")
    run_command("python scripts/db_clean.py --all-data --dry-run")


def db_clean() -> None:
    """Очистка БД в интерактивном режиме (с подтверждением)."""
    print("🗄️ Cleaning database...")
    run_command("python scripts/db_clean.py")


def db_clean_users() -> None:
    """Очистка только пользовательских данных."""
    print("🗄️ Cleaning user data...")
    run_command("python scripts/db_clean.py --users")


def db_clean_all() -> None:
    """Полная очистка всех данных (с принудительным подтверждением)."""
    print("🗄️ Cleaning all data...")
    run_command("python scripts/db_clean.py --all-data --force")


def db_clean_drop() -> None:
    """Удаление всех таблиц в БД (необратимо)."""
    print("🗄️ Dropping all tables...")
    run_command("python scripts/db_clean.py --drop-all --force")


# ============================================
# 3. ЗАПУСК ПРИЛОЖЕНИЯ
# ============================================


def dev() -> None:
    """Запуск сервера в режиме разработки."""
    print("🚀 Starting dev server...")
    run_command("python run.py --mode dev")


def full() -> None:
    """Полноценный запуск приложения."""
    print("🚀 Starting full server...")
    run_command("python run.py --mode full")


# ============================================
# 4. КАЧЕСТВО КОДА
# ============================================


def format_code() -> None:
    """Автоматическое форматирование кода (ruff)."""
    print("🎨 Formatting code...")
    run_command("ruff format app/")


def lint() -> None:
    """Запуск линтеров (ruff + mypy)."""
    print("🔍 Running linters...")
    run_command("ruff check app/")
    run_command("mypy app/")


def check() -> None:
    """Проверка типов с помощью mypy."""
    print("🔍 Running mypy type check...")
    run_command("mypy app/")


def test() -> None:
    """Запуск тестов с подробным выводом."""
    print("🧪 Running tests...")
    run_command("pytest tests/ -v")


def precommit() -> None:
    """Запуск всех pre-commit хуков на всех файлах."""
    print("🔧 Running pre-commit...")
    run_command("pre-commit run --all-files")


# ============================================
# 5. ОЧИСТКА И УТИЛИТЫ
# ============================================


def clean() -> None:
    """Очистка кешей и временных файлов."""
    print("🧹 Cleaning cache...")
    run_command("python scripts/clean_cache.py")


def show_help() -> None:
    """Показать справку по всем доступным командам."""
    commands = {
        # Настройка и инициализация
        "setup": "Полная настройка проекта с нуля",
        "init": "Инициализация БД с наполнением",
        "reset": "Полный сброс БД (миграции + инициализация)",
        "seed": "Заполнение системными данными (без сброса)",
        # База данных
        "sync": "Синхронизация с Avanpost",
        "db-clean-show": "Статистика таблиц",
        "db-clean-dry": "Показать, что будет удалено (dry-run)",
        "db-clean": "Очистка БД (интерактивно)",
        "db-clean-users": "Очистка только пользователей",
        "db-clean-all": "Полная очистка всех данных",
        "db-clean-drop": "Удаление всех таблиц",
        # Запуск
        "dev": "Запуск в режиме разработки",
        "full": "Полноценный запуск приложения",
        # Качество кода
        "format": "Форматирование кода (ruff)",
        "lint": "Линтеры (ruff + mypy)",
        "check": "Проверка типов (mypy)",
        "test": "Запуск тестов",
        "precommit": "Запуск pre-commit хуков",
        # Очистка и утилиты
        "clean": "Очистка кешей",
    }

    print("\n📋 Доступные команды:\n")
    print("🔹 НАСТРОЙКА И ИНИЦИАЛИЗАЦИЯ:")
    for cmd in ("setup", "init", "reset", "seed"):
        print(f"  {cmd:18} - {commands[cmd]}")

    print("\n🔹 БАЗА ДАННЫХ:")
    for cmd in ("sync", "db-clean-show", "db-clean-dry", "db-clean", "db-clean-users", "db-clean-all", "db-clean-drop"):
        print(f"  {cmd:18} - {commands[cmd]}")

    print("\n🔹 ЗАПУСК ПРИЛОЖЕНИЯ:")
    for cmd in ("dev", "full"):
        print(f"  {cmd:18} - {commands[cmd]}")

    print("\n🔹 КАЧЕСТВО КОДА:")
    for cmd in ("format", "lint", "check", "test", "precommit"):
        print(f"  {cmd:18} - {commands[cmd]}")

    print("\n🔹 ОЧИСТКА И УТИЛИТЫ:")
    print(f"  {'clean':18} - {commands['clean']}")

    print("\n  help            - Показать эту справку")


# ============================================
# ОБРАБОТЧИК КОМАНД
# ============================================

if __name__ == "__main__":
    command_handlers = {
        # Настройка
        "setup": setup,
        "init": init,
        "reset": reset,
        "seed": seed,
        # База данных
        "sync": sync,
        "db-clean-show": db_clean_show,
        "db-clean-dry": db_clean_dry,
        "db-clean": db_clean,
        "db-clean-users": db_clean_users,
        "db-clean-all": db_clean_all,
        "db-clean-drop": db_clean_drop,
        # Запуск
        "dev": dev,
        "full": full,
        # Качество кода
        "format": format_code,
        "lint": lint,
        "check": check,
        "test": test,
        "precommit": precommit,
        # Утилиты
        "clean": clean,
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
