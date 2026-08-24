"""Проверка целостности данных в базе данных PostgreSQL.

Использование:
    python scripts/check_integrity.py [command] [options]

Команды:
    check           - Полная проверка целостности данных
    orphans         - Проверка только сиротских записей
    duplicates      - Проверка дубликатов в таблицах
    nulls           - Проверка NULL значений в обязательных полях
    indexes         - Проверка состояния индексов
    stats           - Статистика по таблицам
    all             - Выполнить все проверки
"""

import asyncio
import sys
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

# Добавляем путь к проекту для импорта настроек
SCRIPT_DIR = Path(__file__).parent
PROJECT_ROOT = SCRIPT_DIR.parent
sys.path.insert(0, str(PROJECT_ROOT))

from sqlalchemy import text

from app.db.manager import db_manager


@dataclass
class IntegrityIssue:
    """Представление проблемы целостности."""

    table: str
    column: str
    issue_type: str
    description: str
    count: int
    details: str | None = None


class IntegrityChecker:
    """Класс для проверки целостности данных."""

    def __init__(self, verbose: bool = False):
        self.verbose = verbose
        self.issues: list[IntegrityIssue] = []
        self.stats: dict[str, Any] = {}

    def add_issue(self, table: str, column: str, issue_type: str, description: str, count: int, details: str = None):
        """Добавить проблему в список."""
        self.issues.append(
            IntegrityIssue(
                table=table, column=column, issue_type=issue_type, description=description, count=count, details=details
            )
        )

    async def check_foreign_keys(self, session) -> None:
        """Проверка внешних ключей и сиротских записей."""
        print("\n🔗 Checking foreign keys...")

        # Получаем все внешние ключи
        result = await session.execute(
            text(
                """
            SELECT
                tc.table_name,
                tc.constraint_name,
                kcu.column_name,
                ccu.table_name AS foreign_table_name,
                ccu.column_name AS foreign_column_name
            FROM information_schema.table_constraints AS tc
            JOIN information_schema.key_column_usage AS kcu
                ON tc.constraint_name = kcu.constraint_name
            JOIN information_schema.constraint_column_usage AS ccu
                ON ccu.constraint_name = tc.constraint_name
            WHERE tc.constraint_type = 'FOREIGN KEY'
              AND tc.table_schema = 'public'
              AND tc.table_name NOT LIKE 'alembic_version'
        """
            )
        )

        foreign_keys = result.fetchall()
        self.stats["foreign_keys"] = len(foreign_keys)

        print(f"  Found {len(foreign_keys)} foreign key constraints")

        # Проверяем каждую связь на сиротские записи
        for fk in foreign_keys:
            table, constraint, column, ref_table, ref_column = fk

            # Пропускаем системные таблицы
            if table.startswith("_"):
                continue

            check_sql = text(f"""
                SELECT COUNT(*) as orphan_count
                FROM {table} t
                LEFT JOIN {ref_table} rt ON t.{column} = rt.{ref_column}
                WHERE t.{column} IS NOT NULL AND rt.{ref_column} IS NULL
            """)

            try:
                result = await session.execute(check_sql)
                count = result.scalar()

                if count > 0:
                    self.add_issue(
                        table=table,
                        column=column,
                        issue_type="orphan_records",
                        description=f"Orphan records referencing {ref_table}.{ref_column}",
                        count=count,
                        details=f"FK: {constraint} -> {ref_table}({ref_column})",
                    )

                    if self.verbose:
                        # Показываем примеры сиротских записей
                        sample_sql = text(f"""
                            SELECT t.*
                            FROM {table} t
                            LEFT JOIN {ref_table} rt ON t.{column} = rt.{ref_column}
                            WHERE t.{column} IS NOT NULL AND rt.{ref_column} IS NULL
                            LIMIT 5
                        """)
                        sample = await session.execute(sample_sql)
                        rows = sample.fetchall()
                        if rows:
                            print(f"    ⚠️  Sample orphan records in {table}:")
                            for row in rows:
                                print(f"      {row}")

            except Exception as e:
                if self.verbose:
                    print(f"    ❌ Error checking {table}.{column}: {e}")

    async def check_duplicates(self, session) -> None:
        """Проверка дубликатов в таблицах."""
        print("\n📋 Checking for duplicates...")

        # Получаем список таблиц с первичными ключами
        result = await session.execute(
            text(
                """
            SELECT
                kcu.table_name,
                kcu.column_name
            FROM information_schema.table_constraints tc
            JOIN information_schema.key_column_usage kcu
                ON tc.constraint_name = kcu.constraint_name
            WHERE tc.constraint_type = 'PRIMARY KEY'
              AND tc.table_schema = 'public'
              AND kcu.table_name NOT LIKE 'alembic_version'
              AND kcu.table_name NOT LIKE 'spatial_ref_sys'
        """
            )
        )

        pk_tables = result.fetchall()

        for table, pk_column in pk_tables:
            # Проверяем дубликаты по первичному ключу
            check_sql = text(f"""
                SELECT {pk_column}, COUNT(*) as dup_count
                FROM {table}
                GROUP BY {pk_column}
                HAVING COUNT(*) > 1
                LIMIT 10
            """)

            try:
                result = await session.execute(check_sql)
                duplicates = result.fetchall()

                if duplicates:
                    total_dup_sql = text(f"""
                        SELECT COUNT(DISTINCT {pk_column})
                        FROM {table}
                        GROUP BY {pk_column}
                        HAVING COUNT(*) > 1
                    """)
                    total_result = await session.execute(total_dup_sql)
                    total = len(total_result.fetchall())

                    self.add_issue(
                        table=table,
                        column=pk_column,
                        issue_type="duplicates",
                        description="Duplicate records by primary key",
                        count=total,
                        details=f"Found {total} duplicate values",
                    )

                    if self.verbose:
                        print(f"    ⚠️  Duplicates in {table}.{pk_column}:")
                        for dup in duplicates[:3]:
                            print(f"      {dup[0]} appears {dup[1]} times")

            except Exception as e:
                if self.verbose:
                    print(f"    ❌ Error checking {table}: {e}")

    async def check_null_values(self, session) -> None:
        """Проверка NULL значений в NOT NULL колонках."""
        print("\n🔍 Checking NULL values...")

        # Получаем NOT NULL колонки
        result = await session.execute(
            text(
                """
            SELECT
                table_name,
                column_name,
                data_type
            FROM information_schema.columns
            WHERE table_schema = 'public'
              AND is_nullable = 'NO'
              AND table_name NOT LIKE 'alembic_version'
              AND table_name NOT LIKE 'spatial_ref_sys'
            ORDER BY table_name, column_name
        """
            )
        )

        not_null_columns = result.fetchall()

        for table, column, data_type in not_null_columns:
            # Проверяем NULL значения
            check_sql = text(f"""
                SELECT COUNT(*) as null_count
                FROM {table}
                WHERE {column} IS NULL
            """)

            try:
                result = await session.execute(check_sql)
                count = result.scalar()

                if count > 0:
                    self.add_issue(
                        table=table,
                        column=column,
                        issue_type="null_values",
                        description="NULL values in NOT NULL column",
                        count=count,
                        details=f"Column type: {data_type}",
                    )

                    if self.verbose:
                        print(f"    ⚠️  {count} NULL values in {table}.{column}")

            except Exception as e:
                if self.verbose:
                    print(f"    ❌ Error checking {table}.{column}: {e}")

    async def check_indexes(self, session) -> None:
        """Проверка состояния индексов."""
        print("\n📊 Checking indexes...")

        # Проверяем неиспользуемые индексы
        result = await session.execute(
            text(
                """
            SELECT
                schemaname,
                tablename,
                indexname,
                idx_scan,
                idx_tup_read,
                idx_tup_fetch
            FROM pg_stat_user_indexes
            WHERE idx_scan = 0
              AND schemaname = 'public'
              AND indexname NOT LIKE 'idx_%_gin'
              AND indexname NOT LIKE 'idx_%_gist'
            ORDER BY tablename, indexname
        """
            )
        )

        unused_indexes = result.fetchall()

        if unused_indexes:
            print(f"  ⚠️  Found {len(unused_indexes)} unused indexes:")
            for idx in unused_indexes:
                print(f"    - {idx[2]} on {idx[0]}.{idx[1]} (0 scans)")

        # Проверяем размер индексов
        result = await session.execute(
            text(
                """
            SELECT
                schemaname,
                tablename,
                indexname,
                pg_size_pretty(pg_relation_size(indexrelid)) as index_size
            FROM pg_stat_user_indexes
            WHERE schemaname = 'public'
            ORDER BY pg_relation_size(indexrelid) DESC
            LIMIT 20
        """
            )
        )

        largest_indexes = result.fetchall()

        if self.verbose and largest_indexes:
            print("\n  📦 Largest indexes:")
            for idx in largest_indexes:
                print(f"    - {idx[2]}: {idx[3]} (table: {idx[1]})")

        self.stats["unused_indexes"] = len(unused_indexes)
        self.stats["total_indexes"] = len(result.fetchall()) if False else 0

    async def get_table_stats(self, session) -> dict[str, Any]:
        """Получение статистики по таблицам."""
        print("\n📈 Table statistics...")

        result = await session.execute(
            text(
                """
            SELECT
                schemaname,
                tablename,
                n_live_tup as row_count,
                n_dead_tup as dead_rows,
                n_mod_since_analyze as changes_since_analyze,
                pg_size_pretty(pg_total_relation_size(schemaname||'.'||tablename)) as total_size,
                pg_size_pretty(pg_relation_size(schemaname||'.'||tablename)) as table_size,
                pg_size_pretty(pg_total_relation_size(schemaname||'.'||tablename) -
                               pg_relation_size(schemaname||'.'||tablename)) as index_size
            FROM pg_stat_user_tables
            WHERE schemaname = 'public'
            ORDER BY n_live_tup DESC
        """
            )
        )

        stats = result.fetchall()

        print(f"\n  {'Table':<30} {'Rows':<12} {'Total Size':<12} {'Dead Rows':<12}")
        print("  " + "-" * 70)

        for stat in stats:
            if stat[2] > 0:  # Только непустые таблицы
                print(f"  {stat[1]:<30} {stat[2]:<12,} {stat[5]:<12} {stat[3]:<12,}")

            # Предупреждения
            if stat[3] > stat[2] * 0.1:  # >10% dead rows
                self.add_issue(
                    table=stat[1],
                    column="*",
                    issue_type="high_dead_rows",
                    description="High number of dead rows",
                    count=stat[3],
                    details=f"Dead rows: {stat[3]}, Live rows: {stat[2]}",
                )

            if stat[4] > 10000:  # Много изменений без анализа
                self.add_issue(
                    table=stat[1],
                    column="*",
                    issue_type="stale_statistics",
                    description="Table needs ANALYZE",
                    count=stat[4],
                    details=f"Changes since last analyze: {stat[4]}",
                )

        return {"tables": stats}

    async def run_all_checks(self) -> bool:
        """Запустить все проверки."""
        print("🔍 Starting integrity check...")
        print(f"📅 Time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        print("=" * 60)

        try:
            async with db_manager.get_session() as session:
                await self.check_foreign_keys(session)
                await self.check_duplicates(session)
                await self.check_null_values(session)
                await self.check_indexes(session)
                await self.get_table_stats(session)

            self.print_report()

            return len(self.issues) == 0

        except Exception as e:
            print(f"\n❌ Error during integrity check: {e}")
            return False

    def print_report(self) -> None:
        """Вывести отчет о проверке."""
        print("\n" + "=" * 60)
        print("📋 INTEGRITY CHECK REPORT")
        print("=" * 60)

        if not self.issues:
            print("\n✅ All checks passed! No integrity issues found.")
            return

        print(f"\n⚠️  Found {len(self.issues)} integrity issue(s):")
        print("-" * 60)

        # Группируем по типу
        by_type = {}
        for issue in self.issues:
            by_type.setdefault(issue.issue_type, []).append(issue)

        for issue_type, issues in by_type.items():
            print(f"\n📌 {issue_type.replace('_', ' ').upper()}:")
            for issue in issues:
                print(f"  ❌ {issue.table}.{issue.column}: {issue.description}")
                print(f"     Count: {issue.count}")
                if issue.details:
                    print(f"     Details: {issue.details}")


# ============================================
# Функции для CLI
# ============================================


async def check_integrity(verbose: bool = False) -> bool:
    """Полная проверка целостности."""
    checker = IntegrityChecker(verbose=verbose)
    return await checker.run_all_checks()


async def check_orphans(verbose: bool = False) -> None:
    """Проверка только сиротских записей."""
    print("🔍 Checking orphan records...")

    async with db_manager.get_session() as session:
        checker = IntegrityChecker(verbose=verbose)
        await checker.check_foreign_keys(session)

    if checker.issues:
        print(f"\n⚠️  Found {len(checker.issues)} issues:")
        for issue in checker.issues:
            print(f"  ❌ {issue.table}.{issue.column}: {issue.count} orphan records")
    else:
        print("\n✅ No orphan records found")


async def check_duplicates(verbose: bool = False) -> None:
    """Проверка дубликатов."""
    print("🔍 Checking duplicates...")

    async with db_manager.get_session() as session:
        checker = IntegrityChecker(verbose=verbose)
        await checker.check_duplicates(session)

    if checker.issues:
        print(f"\n⚠️  Found {len(checker.issues)} issues:")
        for issue in checker.issues:
            print(f"  ❌ {issue.table}: {issue.count} duplicate records")
    else:
        print("\n✅ No duplicates found")


async def check_nulls(verbose: bool = False) -> None:
    """Проверка NULL значений."""
    print("🔍 Checking NULL values...")

    async with db_manager.get_session() as session:
        checker = IntegrityChecker(verbose=verbose)
        await checker.check_null_values(session)

    if checker.issues:
        print(f"\n⚠️  Found {len(checker.issues)} issues:")
        for issue in checker.issues:
            print(f"  ❌ {issue.table}.{issue.column}: {issue.count} NULL values")
    else:
        print("\n✅ No NULL violations found")


async def show_stats() -> None:
    """Показать статистику таблиц."""

    async with db_manager.get_session() as session:
        checker = IntegrityChecker(verbose=False)
        await checker.get_table_stats(session)


# ============================================
# Основная функция
# ============================================


async def main():
    """Основная функция обработки команд."""
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(1)

    command = sys.argv[1].lower()
    verbose = "--verbose" in sys.argv or "-v" in sys.argv

    commands = {
        "check": lambda: check_integrity(verbose),
        "orphans": lambda: check_orphans(verbose),
        "duplicates": lambda: check_duplicates(verbose),
        "nulls": lambda: check_nulls(verbose),
        "stats": show_stats,
        "all": lambda: check_integrity(verbose),
    }

    if command in commands:
        result = await commands[command]()
        sys.exit(0 if result is True or result is None else 1)
    else:
        print(f"❌ Unknown command: {command}")
        print(__doc__)
        sys.exit(1)


if __name__ == "__main__":
    asyncio.run(main())
