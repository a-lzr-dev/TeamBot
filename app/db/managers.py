from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from dataclasses import dataclass
from enum import StrEnum
from typing import Optional

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from ..config import settings
from ..exceptions import log_exceptions
from ..logger import db_logger
from ..models import BaseModel


class DatabaseType(StrEnum):
    """Типы поддерживаемых БД"""

    SQLITE = "sqlite"
    MSSQL = "mssql"
    POSTGRES = "postgres"


@dataclass
class DatabaseConfig:
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
    def db_type(self) -> DatabaseType:
        if "sqlite" in self.url.lower():
            return DatabaseType.SQLITE
        elif "mssql" in self.url.lower() or "sqlserver" in self.url.lower():
            return DatabaseType.MSSQL
        elif "postgres" in self.url.lower() or "postgresql" in self.url.lower():
            return DatabaseType.POSTGRES
        return DatabaseType.SQLITE


class DatabaseEngine:
    """Обертка для движка БД"""

    def __init__(self, config: DatabaseConfig):
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

        if db_type == DatabaseType.SQLITE:
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


class DatabaseManager:
    """Универсальный менеджер для работы с несколькими БД"""

    _instance: Optional["DatabaseManager"] = None

    def __new__(cls) -> "DatabaseManager":
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    def __init__(self) -> None:
        if hasattr(self, "_initialized"):
            return

        self._engines: dict[str, DatabaseEngine] = {}
        self._primary_name: str | None = None
        self._session_counter = 0
        self._initialized = False

    def register_database(self, name: str, config: DatabaseConfig) -> "DatabaseManager":
        """Регистрация новой БД"""
        if name in self._engines:
            db_logger.warning(f"⚠️ Database '{name}' already registered, updating...")

        self._engines[name] = DatabaseEngine(config)

        if config.is_primary or not self._primary_name:
            self._primary_name = name
            db_logger.info(f"✅ Primary database set to '{name}'")

        db_logger.info(f"✅ Database '{name}' registered ({config.db_type.value})")
        return self

    @property
    def primary(self) -> DatabaseEngine:
        if not self._primary_name or self._primary_name not in self._engines:
            raise RuntimeError("No primary database registered")
        return self._engines[self._primary_name]

    def get_engine(self, name: str) -> DatabaseEngine:
        if name not in self._engines:
            raise KeyError(f"Database '{name}' not registered")
        return self._engines[name]

    def get_engine_by_type(self, db_type: DatabaseType) -> DatabaseEngine | None:
        for engine in self._engines.values():
            if engine.config.db_type == db_type:
                return engine
        return None

    @property
    def is_initialized(self) -> bool:
        return self._initialized

    @asynccontextmanager
    async def get_session(self, db_name: str | None = None) -> AsyncGenerator[AsyncSession]:
        """Получение сессии для указанной БД"""
        engine = self.get_engine(db_name) if db_name else self.primary

        if not engine.is_initialized:
            await engine.initialize()

        session = None
        try:
            session = engine.session_factory()
            self._session_counter += 1
            db_logger.debug(f"🔄 Session created for '{db_name or self._primary_name}' (total={self._session_counter})")

            yield session

            await session.commit()
            db_logger.debug("✅ Session committed")

        except Exception as e:
            db_logger.error(f"❌ Session error: {e}", exc_info=True)
            if session:
                await session.rollback()
            raise
        finally:
            if session:
                await session.close()
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

        # Получаем модели, если они не заданы - используем BaseModel
        models = engine.config.models or BaseModel

        # Проверка, что models - это класс с атрибутом metadata
        if not hasattr(models, "metadata"):
            db_logger.error(f"❌ Models {models} has no metadata attribute")
            raise TypeError(f"Models {models} has no metadata attribute")

        async with engine.engine.connect() as conn, conn.begin():
            if drop_first:
                db_logger.warning(f"⚠️ Dropping all tables for '{db_name or self._primary_name}'...")
                await conn.run_sync(models.metadata.drop_all)

            db_logger.debug(f"🔄 Creating tables for '{db_name or self._primary_name}'...")
            await conn.run_sync(models.metadata.create_all)
            db_logger.info(f"✅ Tables created for '{db_name or self._primary_name}'")

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


# ============ Создание экземпляра с настройками ============

db_manager = DatabaseManager()

db_manager.register_database(
    "main",
    DatabaseConfig(
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
        DatabaseConfig(
            url=settings.DB_AVANPOST_URL,
            echo=settings.DB_AVANPOST_ECHO,
            pool_size=getattr(settings, "DB_AVANPOST_POOL_SIZE", 5),
            max_overflow=getattr(settings, "DB_AVANPOST_MAX_OVERFLOW", 10),
            is_primary=False,
        ),
    )

__all__ = [
    "DatabaseType",
    "DatabaseConfig",
    "DatabaseEngine",
    "DatabaseManager",
    "db_manager",
]
