"""Резервное копирование и восстановление базы данных PostgreSQL.

Использование:
    python scripts/backup.py [command] [options]

Команды:
    create          - Создать резервную копию
    restore [file]  - Восстановить из копии
    list            - Показать список доступных бэкапов
    clean [N]       - Удалить старые бэкапы, оставив N последних
"""

import subprocess
import sys
from datetime import datetime
from pathlib import Path

# Добавляем путь к проекту для импорта настроек
SCRIPT_DIR = Path(__file__).parent
PROJECT_ROOT = SCRIPT_DIR.parent
sys.path.insert(0, str(PROJECT_ROOT))

from app.config import settings


class BackupError(Exception):
    """Исключение при ошибке бэкапа."""

    pass


def get_backup_dir() -> Path:
    """Получить директорию для хранения бэкапов."""
    backup_dir = Path("backups")
    backup_dir.mkdir(exist_ok=True)
    return backup_dir


def get_backup_files() -> list[Path]:
    """Получить список всех файлов бэкапов, отсортированных по дате."""
    backup_dir = get_backup_dir()
    files = list(backup_dir.glob("team_bot_*.sql"))
    return sorted(files, key=lambda p: p.stat().st_mtime, reverse=True)


def get_db_env() -> dict:
    """Получить переменные окружения для подключения к БД."""
    return {"PGPASSWORD": settings.DB_MAIN_PASSWORD}


def get_db_args() -> list[str]:
    """Получить аргументы подключения к БД."""
    return [
        "-h",
        settings.DB_MAIN_HOST,
        "-p",
        str(settings.DB_MAIN_PORT),
        "-U",
        settings.DB_MAIN_USER,
        "-d",
        settings.DB_MAIN_NAME,
    ]


def create_backup(compress: bool = True) -> Path:
    """Создание резервной копии БД.

    Args:
        compress: Использовать сжатый формат (custom)

    Returns:
        Path: Путь к созданному файлу бэкапа

    Raises:
        BackupError: При ошибке создания бэкапа
    """
    backup_dir = get_backup_dir()
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    backup_file = backup_dir / f"team_bot_{timestamp}.sql"

    print(f"📦 Creating backup: {backup_file}")

    # Базовые аргументы pg_dump
    cmd = [
        "pg_dump",
        *get_db_args(),
        "-f",
        str(backup_file),
    ]

    if compress:
        cmd.extend(["-F", "c"])  # Custom format (сжатый)
    else:
        cmd.extend(["-F", "p"])  # Plain SQL

    # Добавляем опции для целостности
    cmd.extend(
        [
            "--no-owner",  # Не сохранять владельцев
            "--no-privileges",  # Не сохранять привилегии
        ]
    )

    try:
        result = subprocess.run(
            cmd,
            env=get_db_env(),
            capture_output=True,
            text=True,
            check=False,
        )

        if result.returncode != 0:
            raise BackupError(f"pg_dump failed (code {result.returncode}):\n{result.stderr}")

        # Проверяем, что файл создан и не пустой
        if not backup_file.exists() or backup_file.stat().st_size == 0:
            raise BackupError("Backup file is empty or was not created")

        size_mb = backup_file.stat().st_size / (1024 * 1024)
        print(f"✅ Backup created successfully: {backup_file} ({size_mb:.2f} MB)")
        return backup_file

    except subprocess.SubprocessError as e:
        raise BackupError(f"Failed to run pg_dump: {e}") from e


def restore_backup(backup_file: Path, drop_first: bool = True) -> None:
    """Восстановление из резервной копии.

    Args:
        backup_file: Путь к файлу бэкапа
        drop_first: Удалить существующие объекты перед восстановлением

    Raises:
        BackupError: При ошибке восстановления
        FileNotFoundError: Если файл бэкапа не найден
    """
    if not backup_file.exists():
        raise FileNotFoundError(f"Backup file not found: {backup_file}")

    print(f"🔄 Restoring from: {backup_file}")

    # Проверяем формат файла
    is_custom = backup_file.suffix == ".sql"  # Все наши бэкапы .sql

    cmd = ["pg_restore" if is_custom else "psql"]

    if is_custom:
        cmd.extend(get_db_args())
        if drop_first:
            cmd.extend(["--clean", "--if-exists"])
        cmd.append(str(backup_file))
    else:
        # Для plain SQL используем psql
        cmd.extend(get_db_args())
        cmd.extend(["-f", str(backup_file)])

    try:
        result = subprocess.run(
            cmd,
            env=get_db_env(),
            capture_output=True,
            text=True,
            check=False,
        )

        if result.returncode != 0:
            raise BackupError(f"Restore failed (code {result.returncode}):\n{result.stderr}")

        print(f"✅ Restored successfully from: {backup_file}")

    except subprocess.SubprocessError as e:
        raise BackupError(f"Failed to run restore: {e}") from e


def list_backups(limit: int | None = None) -> None:
    """Показать список доступных бэкапов.

    Args:
        limit: Максимальное количество бэкапов для показа
    """
    files = get_backup_files()

    if not files:
        print("📭 No backups found")
        return

    if limit:
        files = files[:limit]

    print(f"\n📋 Available backups ({len(files)} total):\n")
    print(f"{'#':<4} {'File':<30} {'Size':<12} {'Date':<20}")
    print("-" * 70)

    for idx, file in enumerate(files, 1):
        size_mb = file.stat().st_size / (1024 * 1024)
        mtime = datetime.fromtimestamp(file.stat().st_mtime)
        date_str = mtime.strftime("%Y-%m-%d %H:%M:%S")
        print(f"{idx:<4} {file.name:<30} {size_mb:>8.2f} MB  {date_str}")


def clean_backups(keep_last: int = 10, dry_run: bool = False) -> None:
    """Удалить старые бэкапы, оставив только N последних.

    Args:
        keep_last: Количество последних бэкапов для сохранения
        dry_run: Только показать, что будет удалено
    """
    files = get_backup_files()

    if len(files) <= keep_last:
        print(f"✅ Only {len(files)} backups found, keeping all (limit: {keep_last})")
        return

    to_delete = files[keep_last:]

    print(f"\n🧹 Cleaning backups: keeping {keep_last} of {len(files)}")
    print(f"  Will delete {len(to_delete)} old backup(s)\n")

    for file in to_delete:
        size_mb = file.stat().st_size / (1024 * 1024)
        mtime = datetime.fromtimestamp(file.stat().st_mtime)
        date_str = mtime.strftime("%Y-%m-%d %H:%M:%S")

        if dry_run:
            print(f"  [DRY RUN] Would delete: {file.name} ({size_mb:.2f} MB, {date_str})")
        else:
            try:
                file.unlink()
                print(f"  ✅ Deleted: {file.name} ({size_mb:.2f} MB, {date_str})")
            except Exception as e:
                print(f"  ❌ Failed to delete {file.name}: {e}")

    if dry_run:
        print("\n  Run without --dry-run to actually delete these files")


def main():
    """Основная функция обработки команд."""
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(1)

    command = sys.argv[1].lower()

    try:
        if command == "create":
            compress = "--no-compress" not in sys.argv
            create_backup(compress=compress)

        elif command == "restore":
            if len(sys.argv) < 3:
                print("❌ Please specify backup file to restore")
                print("  Usage: python scripts/backup.py restore <backup_file>")
                sys.exit(1)

            backup_path = Path(sys.argv[2])
            drop_first = "--keep-data" not in sys.argv
            restore_backup(backup_path, drop_first=drop_first)

        elif command == "list":
            limit = None
            if len(sys.argv) > 2:
                try:
                    limit = int(sys.argv[2])
                except ValueError:
                    print(f"❌ Invalid limit: {sys.argv[2]}")
                    sys.exit(1)
            list_backups(limit)

        elif command == "clean":
            keep_last = 10
            dry_run = "--dry-run" in sys.argv

            if len(sys.argv) > 2 and sys.argv[2].isdigit():
                keep_last = int(sys.argv[2])
            elif len(sys.argv) > 2 and sys.argv[2] != "--dry-run":
                print(f"❌ Invalid argument: {sys.argv[2]}")
                print("  Usage: python scripts/backup.py clean [N] [--dry-run]")
                sys.exit(1)

            clean_backups(keep_last, dry_run=dry_run)

        else:
            print(f"❌ Unknown command: {command}")
            print(__doc__)
            sys.exit(1)

    except (BackupError, FileNotFoundError) as e:
        print(f"❌ Error: {e}")
        sys.exit(1)
    except KeyboardInterrupt:
        print("\n⚠️ Operation cancelled by user")
        sys.exit(130)


if __name__ == "__main__":
    main()
