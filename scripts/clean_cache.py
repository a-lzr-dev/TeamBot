"""Очистка кэша и временных файлов.

Использование:
    python scripts/clean_cache.py [command]

Команды:
    clean           - Очистить все кэши и временные файлы
    dry-run         - Показать, что будет удалено, без фактического удаления
    python          - Очистить только Python кэши (__pycache__, *.pyc)
    test            - Очистить только тестовые кэши (pytest, coverage)
    build           - Очистить только сборочные файлы (dist, build, egg-info)
"""

import shutil
import sys
from pathlib import Path


def get_patterns() -> dict:
    """Возвращает словарь с паттернами для очистки."""
    return {
        "python": {"dirs": ["__pycache__"], "files": ["*.pyc", "*.pyo"]},
        "test": {"dirs": [".pytest_cache", ".coverage", "htmlcov"], "files": [".coverage", "*.coverage"]},
        "build": {"dirs": ["dist", "build", "*.egg-info"], "files": ["*.egg-info"]},
        "cache": {
            "dirs": [
                ".mypy_cache",
                ".ruff_cache",
                ".pytest_cache",
                ".coverage",
                "htmlcov",
                "dist",
                "build",
                "__pycache__",
            ],
            "files": ["*.pyc", "*.pyo", ".coverage"],
        },
    }


def clean_directory(path: Path, dry_run: bool = False):
    """Очистка директории."""
    if path.exists():
        if dry_run:
            print(f"🔍 Would remove: {path}")
        else:
            shutil.rmtree(path)
            print(f"🧹 Removed: {path}")


def clean_files(pattern: str, dry_run: bool = False):
    """Удаление файлов по паттерну."""
    for file in Path(".").rglob(pattern):
        if dry_run:
            print(f"🔍 Would remove: {file}")
        else:
            file.unlink()
            print(f"🧹 Removed: {file}")


def clean_dirs(dirs: list, dry_run: bool = False):
    """Очистка списка директорий."""
    for dir_path in dirs:
        path = Path(dir_path)
        if "*" in dir_path:
            # Для паттернов с звездочкой ищем соответствующие директории
            for match in Path(".").glob(dir_path):
                if match.is_dir():
                    clean_directory(match, dry_run)
        else:
            clean_directory(path, dry_run)


def clean_by_pattern(pattern_type: str, dry_run: bool = False):
    """Очистка по типу паттерна."""
    patterns = get_patterns()

    if pattern_type not in patterns:
        print(f"❌ Unknown pattern type: {pattern_type}")
        return

    pattern = patterns[pattern_type]

    # Очищаем директории
    for dir_path in pattern["dirs"]:
        if "*" in dir_path:
            for match in Path(".").glob(dir_path):
                if match.is_dir():
                    clean_directory(match, dry_run)
        else:
            clean_directory(Path(dir_path), dry_run)

    # Очищаем файлы
    for file_pattern in pattern["files"]:
        clean_files(file_pattern, dry_run)


def main():
    """Основная функция обработки команд."""
    dry_run = "--dry-run" in sys.argv or "dry-run" in sys.argv

    # Убираем флаги из аргументов
    args = [arg for arg in sys.argv[1:] if not arg.startswith("--")]

    if not args or args[0] in ["clean", "all"]:
        print("🧹 Cleaning all cache files...")
        clean_by_pattern("cache", dry_run)
    elif args[0] == "dry-run":
        print("🔍 Dry run - showing what would be deleted...")
        clean_by_pattern("cache", dry_run=True)
    elif args[0] == "python":
        print("🧹 Cleaning Python cache...")
        clean_by_pattern("python", dry_run)
    elif args[0] == "test":
        print("🧹 Cleaning test cache...")
        clean_by_pattern("test", dry_run)
    elif args[0] == "build":
        print("🧹 Cleaning build files...")
        clean_by_pattern("build", dry_run)
    else:
        print(f"❌ Unknown command: {args[0]}")
        print(__doc__)
        sys.exit(1)

    if not dry_run:
        print("✅ Clean complete!")


if __name__ == "__main__":
    main()
