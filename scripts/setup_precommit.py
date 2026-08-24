"""Настройка pre-commit хуков для TeamBot.

Использование:
    python scripts/setup_precommit.py [options]

Опции:
    --install       Установить pre-commit хуки
    --run           Запустить проверку всех файлов
    --clean         Очистить кэш pre-commit
    --uninstall     Удалить pre-commit хуки
"""

import subprocess
import sys
from pathlib import Path


def run_command(cmd: str, description: str) -> bool:
    """Запуск команды с выводом статуса."""
    print(f"\n🔄 {description}...")
    try:
        result = subprocess.run(
            cmd, shell=True, check=True, capture_output=True, text=True, cwd=Path(__file__).parent.parent
        )
        if result.stdout:
            print(result.stdout)
        print(f"✅ {description} completed!")
        return True
    except subprocess.CalledProcessError as e:
        print(f"❌ {description} failed!")
        if e.stderr:
            print(e.stderr)
        return False


def check_precommit() -> bool:
    """Проверка наличия pre-commit."""
    return run_command("pre-commit --version", "Checking pre-commit")


def install_precommit() -> bool:
    """Установка pre-commit."""
    if not check_precommit():
        print("\n❌ pre-commit not found. Installing...")
        if not run_command("pip install pre-commit", "Installing pre-commit"):
            return False
    return True


def clean_cache() -> bool:
    """Очистка кэша pre-commit."""
    return run_command("pre-commit clean", "Cleaning pre-commit cache")


def install_hooks() -> bool:
    """Установка хуков."""
    return run_command("pre-commit install", "Installing pre-commit hooks")


def uninstall_hooks() -> bool:
    """Удаление хуков."""
    return run_command("pre-commit uninstall", "Uninstalling pre-commit hooks")


def run_all_files() -> bool:
    """Запуск проверки всех файлов."""
    return run_command("pre-commit run --all-files", "Running pre-commit on all files")


def main():
    """Главная функция."""
    print("=" * 60)
    print("  🔧 TeamBot - Pre-commit Setup")
    print("=" * 60)

    args = sys.argv[1:]

    # Если нет аргументов или указан --install, выполняем полную настройку
    if not args or "--install" in args:
        if not install_precommit():
            return False

        # Очистка кэша
        if not clean_cache():
            print("⚠️  Clean failed, continuing...")

        # Установка хуков
        if not install_hooks():
            print("❌ Failed to install hooks!")
            return False

        # Проверка всех файлов
        if not run_all_files():
            print("\n⚠️  Some checks failed, but hooks are installed!")
            print("You can fix issues and run: make pre-commit")
            return False

        print("\n" + "=" * 60)
        print("  ✅ Pre-commit setup complete!")
        print("=" * 60)
        print("\n📝 Hooks will run automatically on 'git commit'")
        print("📝 To run manually: make pre-commit")
        return True

    # Обработка отдельных команд
    if "--run" in args:
        return run_all_files()

    if "--clean" in args:
        return clean_cache()

    if "--uninstall" in args:
        return uninstall_hooks()

    print(__doc__)
    return False


if __name__ == "__main__":
    success = main()
    sys.exit(0 if success else 1)
