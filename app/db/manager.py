# app/db/manager.py

import asyncio
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from dataclasses import dataclass
from enum import StrEnum
from typing import Any, Optional

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from ..config import settings
from ..logger import db_logger
from ..models import BaseModel
from ..utils.decorators import log_exceptions


class DBType(StrEnum):
    """Типы поддерживаемых БД"""

    SQLITE = "sqlite"
    MSSQL = "mssql"
    POSTGRES = "postgres"


@dataclass
class DBConfig:
    """Конфигурация для подключения к БД"""

    url: str
    echo: bool = False
    pool_size: int = 5
    max_overflow: int = 10
    pool_pre_ping: bool = True
    pool_recycle: int = 3600
    is_primary: bool = False
    models: type[BaseModel] | None = None

    @property
    def db_type(self) -> DBType:
        if "sqlite" in self.url.lower():
            return DBType.SQLITE
        elif "mssql" in self.url.lower() or "sqlserver" in self.url.lower():
            return DBType.MSSQL
        elif "postgres" in self.url.lower() or "postgresql" in self.url.lower():
            return DBType.POSTGRES
        return DBType.SQLITE


class DBEngine:
    """Обертка для движка БД"""

    def __init__(self, config: DBConfig):
        self.config = config
        self._engine: AsyncEngine | None = None
        self._session_factory: async_sessionmaker | None = None
        self._initialized = False

    @property
    def engine(self) -> AsyncEngine:
        if not self._engine:
            raise RuntimeError("Engine not initialized")
        return self._engine

    @property
    def session_factory(self) -> async_sessionmaker:
        if not self._session_factory:
            raise RuntimeError("Session factory not initialized")
        return self._session_factory

    @property
    def is_initialized(self) -> bool:
        return self._initialized

    async def initialize(self) -> None:
        """Инициализация движка"""
        if self._initialized:
            return

        db_type = self.config.db_type

        if db_type == DBType.SQLITE:
            self._engine = create_async_engine(
                self.config.url,
                echo=self.config.echo,
                poolclass=NullPool,
                connect_args={"check_same_thread": False} if "sqlite" in self.config.url else {},
            )
        else:
            self._engine = create_async_engine(
                self.config.url,
                echo=self.config.echo,
                pool_size=self.config.pool_size,
                max_overflow=self.config.max_overflow,
                pool_pre_ping=self.config.pool_pre_ping,
                pool_recycle=self.config.pool_recycle,
            )

        self._session_factory = async_sessionmaker(
            self._engine,
            class_=AsyncSession,
            expire_on_commit=False,
            autocommit=False,
            autoflush=False,
        )

        # Проверка подключения
        try:
            async with self._engine.connect() as conn:
                await conn.execute(text("SELECT 1"))
                await conn.commit()
            db_logger.info(f"✅ {db_type.upper()} connection successful")
        except Exception as e:
            db_logger.error(f"❌ {db_type.upper()} connection failed: {e}")
            raise

        self._initialized = True

    async def dispose(self) -> None:
        """Закрытие движка"""
        if self._engine:
            await self._engine.dispose()
            self._initialized = False
            db_logger.debug(f"⛔ {self.config.db_type.upper()} engine disposed")


class DBManager:
    """Универсальный менеджер для работы с несколькими БД"""

    _instance: Optional["DBManager"] = None

    def __new__(cls) -> "DBManager":
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    def __init__(self) -> None:
        if hasattr(self, "_initialized"):
            return

        self._engines: dict[str, DBEngine] = {}
        self._primary_name: str | None = None
        self._session_counter = 0
        self._initialized = False

    def register_database(self, name: str, config: DBConfig) -> "DBManager":
        """Регистрация новой БД"""
        if name in self._engines:
            db_logger.warning(f"⚠️ Database '{name}' already registered, updating...")

        self._engines[name] = DBEngine(config)

        if config.is_primary or not self._primary_name:
            self._primary_name = name
            db_logger.info(f"✅ Primary database set to '{name}'")

        db_logger.info(f"✅ Database '{name}' registered ({config.db_type.value})")
        return self

    @property
    def primary(self) -> DBEngine:
        if not self._primary_name or self._primary_name not in self._engines:
            raise RuntimeError("No primary database registered")
        return self._engines[self._primary_name]

    def get_engine(self, name: str) -> DBEngine:
        if name not in self._engines:
            raise KeyError(f"Database '{name}' not registered")
        return self._engines[name]

    def get_engine_by_type(self, db_type: DBType) -> DBEngine | None:
        for engine in self._engines.values():
            if engine.config.db_type == db_type:
                return engine
        return None

    @property
    def is_initialized(self) -> bool:
        return self._initialized

    @asynccontextmanager
    async def get_session(
        self,
        db_name: str | None = None,
        show_logs: bool = True,
    ) -> AsyncGenerator[AsyncSession]:
        """Получение сессии для указанной БД"""
        engine = self.get_engine(db_name) if db_name else self.primary

        if not engine.is_initialized:
            await engine.initialize()

        session = None
        try:
            session = engine.session_factory()
            self._session_counter += 1
            if show_logs:
                db_logger.debug(
                    f"🔄 Session created for '{db_name or self._primary_name}' (total={self._session_counter})"
                )

            yield session

            await session.commit()
            if show_logs:
                db_logger.debug("✅ Session committed")

        except Exception as e:
            db_logger.error(f"❌ Session error: {e}", exc_info=True)
            if session:
                await session.rollback()
            raise
        finally:
            if session:
                await session.close()
                if show_logs:
                    db_logger.debug("🔒 Session closed")

    @log_exceptions(db_logger)
    async def initialize_all(self) -> None:
        """Инициализация всех зарегистрированных БД"""
        if self._initialized:
            return

        db_logger.info("🚀 Initializing all databases...")

        for name, engine in self._engines.items():
            try:
                await engine.initialize()
                db_logger.info(f"✅ Database '{name}' initialized")
            except Exception as e:
                db_logger.error(f"❌ Failed to initialize '{name}': {e}")

        self._initialized = True
        db_logger.info("✅ All databases initialized")

    @log_exceptions(db_logger)
    async def init_tables(self, db_name: str | None = None, drop_first: bool = False) -> None:
        """Инициализация таблиц для БД"""
        engine = self.get_engine(db_name) if db_name else self.primary

        if not engine.is_initialized:
            await engine.initialize()

        models = engine.config.models or BaseModel

        async with engine.engine.connect() as conn, conn.begin():
            if drop_first:
                db_logger.warning(f"⚠️ Dropping all tables for '{db_name or self._primary_name}'...")
                await conn.run_sync(models.metadata.drop_all)

            db_logger.debug(f"🔄 Creating tables for '{db_name or self._primary_name}'...")

            await conn.run_sync(models.metadata.create_all)

            db_logger.info(f"✅ Tables created for '{db_name or self._primary_name}'")

    @log_exceptions(db_logger)
    async def seed_tables(self) -> None:
        """Заполнение таблиц данными"""
        from app.services.seed_service import avanpost_seed_service

        db_logger.debug("🔍 Seeding Avanpost system data types...")

        async with self.get_session(db_name="main") as session:
            success = await avanpost_seed_service.seed_system_tables(session)
            if success:
                db_logger.info("✅ Avanpost system data seeded successfully")
            else:
                db_logger.warning("⚠️ Avanpost seeding completed with errors")

    # ==================== AVANPOST SYNC ====================

    @log_exceptions(db_logger)
    async def sync_avanpost(self, force: bool = False) -> dict[str, Any]:
        """
        Синхронизация данных Avanpost с выводом статистики только при изменениях.

        Args:
            force: Принудительная полная синхронизация (игнорировать кеш)

        Returns:
            dict: Результат синхронизации с информацией о статусе и статистикой
        """
        db_logger.info(f"🔄 Starting Avanpost data sync (force={force})...")

        try:
            from app.services.avanpost_sync_service import AvanpostSyncService

            sync_service = AvanpostSyncService()
            await sync_service.initialize()

            # Запуск синхронизации базовых данных с получением статистики
            stats = await sync_service.sync_base_data(force=force)

            # Получение статуса после синхронизации
            status = await sync_service.get_status()

            stats_dict = stats.to_dict()

            # Проверяем, были ли изменения или ошибки
            has_changes = (
                stats_dict.get("total_inserted", 0) > 0
                or stats_dict.get("total_updated", 0) > 0
                or stats_dict.get("total_deleted", 0) > 0
            )
            has_errors = len(stats_dict.get("error_messages", [])) > 0

            if has_changes or has_errors:
                db_logger.info("✅ Avanpost data sync completed with changes")
                db_logger.info(f"📊 Inserted: {stats_dict.get('total_inserted', 0)}")
                db_logger.info(f"📊 Updated:  {stats_dict.get('total_updated', 0)}")
                db_logger.info(f"📊 Deleted:  {stats_dict.get('total_deleted', 0)}")
                db_logger.info(f"📊 Skipped:  {stats_dict.get('total_skipped', 0)}")
                if has_errors:
                    db_logger.warning(f"📊 Errors:   {len(stats_dict.get('error_messages', []))}")
            else:
                db_logger.info("✅ Avanpost data sync completed - no changes detected")

            return {
                "success": True,
                "message": "Avanpost data sync completed successfully",
                "status": status,
                "stats": stats_dict,
                "has_changes": has_changes,
                "has_errors": has_errors,
                "force": force,
            }

        except ImportError as e:
            db_logger.warning(f"⚠️ Avanpost sync service not available: {e}")
            return {
                "success": False,
                "message": "Sync service not available",
                "error": str(e),
                "force": force,
            }
        except Exception as e:
            db_logger.error(f"❌ Avanpost data sync failed: {e}", exc_info=True)
            return {
                "success": False,
                "message": f"Sync failed: {str(e)}",
                "error": str(e),
                "force": force,
            }

    @log_exceptions(db_logger)
    async def sync_avanpost_async(self, force: bool = False) -> asyncio.Task:
        """
        Запуск синхронизации Avanpost в фоновом режиме.

        Args:
            force: Принудительная полная синхронизация

        Returns:
            asyncio.Task: Задача фоновой синхронизации
        """
        db_logger.info(f"🔄 Starting Avanpost sync in background (force={force})...")

        async def _sync_task() -> None:
            try:
                result = await self.sync_avanpost(force=force)
                if result.get("success"):
                    db_logger.info("✅ Background Avanpost sync completed")
                    stats = result.get("stats", {})
                    if (
                        stats.get("total_inserted", 0) > 0
                        or stats.get("total_updated", 0) > 0
                        or stats.get("total_deleted", 0) > 0
                    ):
                        db_logger.info(
                            f"📊 Inserted: {stats.get('total_inserted', 0)}, "
                            f"Updated: {stats.get('total_updated', 0)}, "
                            f"Deleted: {stats.get('total_deleted', 0)}, "
                            f"Skipped: {stats.get('total_skipped', 0)}"
                        )
                    else:
                        db_logger.info("📊 No changes detected")
                else:
                    db_logger.warning(f"⚠️ Background Avanpost sync failed: {result.get('message')}")
            except asyncio.CancelledError:
                db_logger.debug("ℹ️ Background Avanpost sync cancelled")
                raise
            except Exception as e:
                db_logger.error(f"❌ Background Avanpost sync error: {e}", exc_info=True)

        task = asyncio.create_task(_sync_task(), name="avanpost_background_sync")
        return task

    # ==================== ЗАКРЫТИЕ И СТАТУС ====================

    @log_exceptions(db_logger)
    async def close_all(self) -> None:
        """Закрытие всех соединений"""
        for name, engine in self._engines.items():
            try:
                await engine.dispose()
                db_logger.debug(f"⛔ Database '{name}' closed")
            except Exception as e:
                db_logger.error(f"❌ Failed to close '{name}': {e}")

        self._initialized = False
        db_logger.info("✅ All databases closed")

    @log_exceptions(db_logger)
    async def check_connection(self, db_name: str | None = None) -> bool:
        """Проверка подключения к БД"""
        engine = self.get_engine(db_name) if db_name else self.primary

        if not engine.is_initialized:
            await engine.initialize()

        try:
            async with engine.engine.connect() as conn:
                await conn.execute(text("SELECT 1"))
                await conn.commit()
            return True
        except Exception as e:
            db_logger.error(f"❌ Connection check failed: {e}")
            return False

    @log_exceptions(db_logger)
    async def get_stats(self) -> dict:
        """Получение статистики всех БД"""
        return {
            "databases": {
                name: {
                    "type": engine.config.db_type.value,
                    "initialized": engine.is_initialized,
                    "url": engine.config.url.split("://")[0] + "://***",
                    "is_primary": name == self._primary_name,
                }
                for name, engine in self._engines.items()
            },
            "primary": self._primary_name,
            "session_counter": self._session_counter,
            "total_databases": len(self._engines),
        }


# ==================== ИНИЦИАЛИЗАЦИЯ ====================

db_manager = DBManager()

db_manager.register_database(
    "main",
    DBConfig(
        url=settings.DB_MAIN_URL,
        echo=settings.DB_MAIN_ECHO,
        pool_size=getattr(settings, "DB_MAIN_POOL_SIZE", 10),
        max_overflow=getattr(settings, "DB_MAIN_MAX_OVERFLOW", 20),
        is_primary=True,
        models=BaseModel,
    ),
)

if settings.DB_AVANPOST_URL:
    db_manager.register_database(
        "avanpost",
        DBConfig(
            url=settings.DB_AVANPOST_URL,
            echo=settings.DB_AVANPOST_ECHO,
            pool_size=getattr(settings, "DB_AVANPOST_POOL_SIZE", 5),
            max_overflow=getattr(settings, "DB_AVANPOST_MAX_OVERFLOW", 10),
            is_primary=False,
        ),
    )

__all__ = [
    "DBType",
    "DBConfig",
    "DBEngine",
    "DBManager",
    "db_manager",
]
