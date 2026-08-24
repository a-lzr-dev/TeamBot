"""Управление миграциями данных.

Использование:
    python scripts/migration_manager.py [options]

Опции:
    --run           Выполнить миграции
    --create        Создать новую миграцию
    --name NAME     Имя миграции (для --create)
    --rollback      Откатить миграцию
    --status        Показать статус миграций
    --target ID     Целевая миграция (по умолчанию: latest)

Примеры:
    # Создать новую миграцию
    python scripts/migration_manager.py --create --name add_user_table

    # Выполнить все миграции
    python scripts/migration_manager.py --run

    # Выполнить миграции до определенной
    python scripts/migration_manager.py --run --target 20240101_001

    # Показать статус
    python scripts/migration_manager.py --status

    # Откатить миграцию
    python scripts/migration_manager.py --rollback --target 20240101_001
"""

import argparse
import asyncio
import json
import sys
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from app.db.manager import db_manager
from app.logger import app_logger


class MigrationStatus(Enum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    SKIPPED = "skipped"


@dataclass
class MigrationRecord:
    id: str
    name: str
    status: MigrationStatus
    executed_at: datetime
    duration_seconds: float
    error: str | None = None
    dependencies: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "name": self.name,
            "status": self.status.value,
            "executed_at": self.executed_at.isoformat(),
            "duration_seconds": self.duration_seconds,
            "error": self.error,
            "dependencies": self.dependencies,
        }


class MigrationManager:
    def __init__(self):
        self._migrations: dict[str, dict] = {}
        self._records: dict[str, MigrationRecord] = {}
        self._history_file = Path("migration_history.json")
        self._load_history()

    def _load_history(self):
        if self._history_file.exists():
            try:
                with open(self._history_file) as f:
                    data = json.load(f)
                    self._records = {
                        k: MigrationRecord(
                            id=v["id"],
                            name=v["name"],
                            status=MigrationStatus(v["status"]),
                            executed_at=datetime.fromisoformat(v["executed_at"]),
                            duration_seconds=v["duration_seconds"],
                            error=v.get("error"),
                            dependencies=v.get("dependencies", []),
                        )
                        for k, v in data.items()
                    }
            except Exception as e:
                app_logger.warning(f"Failed to load history: {e}")

    def _save_history(self):
        try:
            with open(self._history_file, "w") as f:
                json.dump(
                    {k: v.to_dict() for k, v in self._records.items()},
                    f,
                    indent=2,
                    default=str,
                )
        except Exception as e:
            app_logger.error(f"Failed to save history: {e}")

    def register(self, migration_id: str, name: str, up_func: Callable, dependencies: list[str] = None):
        self._migrations[migration_id] = {
            "name": name,
            "up": up_func,
            "dependencies": dependencies or [],
        }

    async def run(self, target: str = "latest"):
        """Выполнение миграций."""
        order = self._resolve_order(target)

        if not order:
            app_logger.info("No migrations to run")
            return

        app_logger.info(f"Running {len(order)} migration(s)")

        for migration_id in order:
            if self._is_completed(migration_id):
                app_logger.info(f"⏭️ Migration {migration_id} already completed")
                continue

            await self._run_migration(migration_id)

        app_logger.info("✅ All migrations completed")

    async def rollback(self, target: str):
        """Откат миграций."""
        completed = [m for m, r in self._records.items() if r.status == MigrationStatus.COMPLETED]
        completed.sort()

        if not completed:
            app_logger.info("No migrations to rollback")
            return

        # Находим миграции для отката
        if target == "latest":
            # Откатываем последнюю
            rollback_migrations = [completed[-1]]
        else:
            # Откатываем до target (включая target)
            idx = completed.index(target) if target in completed else -1
            if idx == -1:
                app_logger.error(f"Migration {target} not found or not completed")
                return
            rollback_migrations = completed[idx:]

        app_logger.info(f"Rolling back {len(rollback_migrations)} migration(s)")

        for migration_id in reversed(rollback_migrations):
            await self._rollback_migration(migration_id)

    async def _run_migration(self, migration_id: str):
        migration = self._migrations[migration_id]

        record = MigrationRecord(
            id=migration_id,
            name=migration["name"],
            status=MigrationStatus.RUNNING,
            executed_at=datetime.now(),
            duration_seconds=0,
            dependencies=migration["dependencies"],
        )
        self._records[migration_id] = record
        self._save_history()

        start = datetime.now()
        try:
            app_logger.info(f"🔄 Running migration: {migration_id} - {migration['name']}")

            async with db_manager.get_session() as session:
                await migration["up"](session)

            record.status = MigrationStatus.COMPLETED
            record.duration_seconds = (datetime.now() - start).total_seconds()

            app_logger.info(f"✅ Migration {migration_id} completed in {record.duration_seconds:.2f}s")

        except Exception as e:
            record.status = MigrationStatus.FAILED
            record.error = str(e)
            app_logger.error(f"❌ Migration {migration_id} failed: {e}")
            raise
        finally:
            self._save_history()

    async def _rollback_migration(self, migration_id: str):
        """Откат конкретной миграции."""
        migration = self._migrations[migration_id]

        # Проверяем наличие down функции
        if "down" not in migration:
            app_logger.warning(f"⚠️ No rollback function for {migration_id}, skipping")
            return

        try:
            app_logger.info(f"⏪ Rolling back: {migration_id} - {migration['name']}")

            async with db_manager.get_session() as session:
                await migration["down"](session)

            # Удаляем запись о выполненной миграции
            if migration_id in self._records:
                del self._records[migration_id]
                self._save_history()

            app_logger.info(f"✅ Rollback {migration_id} completed")

        except Exception as e:
            app_logger.error(f"❌ Rollback {migration_id} failed: {e}")
            raise

    def _resolve_order(self, target: str) -> list[str]:
        all_migrations = set(self._migrations.keys())

        target_migrations = all_migrations if target == "latest" else {m for m in all_migrations if m <= target}

        sorted_migrations = []
        visited = set()

        def visit(migration_id: str):
            if migration_id in visited:
                return
            visited.add(migration_id)
            for dep in self._migrations[migration_id]["dependencies"]:
                if dep in target_migrations:
                    visit(dep)
            sorted_migrations.append(migration_id)

        for m in sorted(target_migrations):
            visit(m)

        return sorted_migrations

    def _is_completed(self, migration_id: str) -> bool:
        record = self._records.get(migration_id)
        return record and record.status == MigrationStatus.COMPLETED

    def show_status(self):
        """Показать статус всех миграций."""
        all_migrations = sorted(self._migrations.keys())

        if not all_migrations:
            print("No migrations registered")
            return

        print("\n📋 Migration Status")
        print("=" * 70)
        print(f"{'ID':<20} {'Name':<25} {'Status':<12} {'Date':<20}")
        print("=" * 70)

        for migration_id in all_migrations:
            record = self._records.get(migration_id)
            name = self._migrations[migration_id]["name"]

            if record:
                status = record.status.value
                date = record.executed_at.strftime("%Y-%m-%d %H:%M")
                if record.error:
                    status += " ❌"
            else:
                status = "pending"
                date = "-"

            print(f"{migration_id:<20} {name:<25} {status:<12} {date:<20}")

        print("=" * 70)

        completed = sum(1 for r in self._records.values() if r.status == MigrationStatus.COMPLETED)
        pending = len(all_migrations) - completed
        failed = sum(1 for r in self._records.values() if r.status == MigrationStatus.FAILED)

        print(f"\n📊 Summary: {completed} completed, {pending} pending, {failed} failed")


async def create_migration(name: str):
    """Создание шаблона миграции."""
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    filename = f"{timestamp}_{name}.py"
    migration_path = Path(f"migrations/{filename}")

    template = f'''"""
Migration: {name}
Created: {datetime.now().isoformat()}
"""

from sqlalchemy.ext.asyncio import AsyncSession


async def up(session: AsyncSession) -> None:
    """Apply migration."""
    # TODO: Implement migration
    pass


async def down(session: AsyncSession) -> None:
    """Rollback migration."""
    # TODO: Implement rollback
    pass
'''

    migration_path.parent.mkdir(exist_ok=True)
    migration_path.write_text(template)

    print(f"✅ Migration created: {migration_path}")
    print(f"   ID: {timestamp}_{name}")

    # Регистрируем миграцию
    print("\n📝 Add to migration_manager.py:")
    print(f'   manager.register("{timestamp}_{name}", "{name}", up, down)')


async def main():
    parser = argparse.ArgumentParser(
        description="Data Migration Manager", formatter_class=argparse.RawDescriptionHelpFormatter, epilog=__doc__
    )
    parser.add_argument("--run", action="store_true", help="Run migrations")
    parser.add_argument("--create", action="store_true", help="Create migration")
    parser.add_argument("--name", type=str, help="Migration name")
    parser.add_argument("--rollback", action="store_true", help="Rollback migration")
    parser.add_argument("--status", action="store_true", help="Show status")
    parser.add_argument("--target", type=str, default="latest", help="Target migration ID")

    args = parser.parse_args()

    manager = MigrationManager()

    if args.create:
        if not args.name:
            print("❌ Please specify migration name with --name")
            sys.exit(1)
        await create_migration(args.name)

    elif args.run:
        await manager.run(target=args.target)

    elif args.rollback:
        await manager.rollback(target=args.target)

    elif args.status:
        manager.show_status()

    else:
        parser.print_help()


if __name__ == "__main__":
    asyncio.run(main())
