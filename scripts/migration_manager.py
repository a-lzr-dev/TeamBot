"""
Управление миграциями данных.
Использование: python scripts/migration_manager.py --run
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
        # Сортировка по зависимостям
        order = self._resolve_order(target)

        for migration_id in order:
            if self._is_completed(migration_id):
                app_logger.info(f"⏭️ Migration {migration_id} already completed")
                continue

            await self._run_migration(migration_id)

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


async def main():
    parser = argparse.ArgumentParser(description="Data Migration Manager")
    parser.add_argument("--run", action="store_true", help="Run migrations")
    parser.add_argument("--create", action="store_true", help="Create migration")
    parser.add_argument("--name", type=str, help="Migration name")
    parser.add_argument("--rollback", action="store_true", help="Rollback migration")
    parser.add_argument("--status", action="store_true", help="Show status")

    args = parser.parse_args()

    manager = MigrationManager()

    if args.run:
        await manager.run()
    elif args.create and args.name:
        # Создание шаблона миграции
        template = f"""# migrations/{args.name}.py
\"\"\"
Migration: {args.name}
Created: {datetime.now().isoformat()}
\"\"\"

from sqlalchemy.ext.asyncio import AsyncSession

async def up(session: AsyncSession) -> None:
    \"\"\"Apply migration.\"\"\"
    # TODO: Implement migration
    pass

async def down(session: AsyncSession) -> None:
    \"\"\"Rollback migration.\"\"\"
    # TODO: Implement rollback
    pass
"""
        migration_file = Path(f"migrations/{args.name}.py")
        migration_file.parent.mkdir(exist_ok=True)
        migration_file.write_text(template)
        print(f"✅ Migration created: {migration_file}")
    else:
        parser.print_help()


if __name__ == "__main__":
    asyncio.run(main())
