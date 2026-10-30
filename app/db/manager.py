"""
Менеджер базы данных для управления подключениями к нескольким БД.

Назначение:
    Обеспечивает централизованное управление подключениями к базам данных
    в асинхронном приложении. Поддерживает работу с несколькими БД
    одновременно (основная PostgreSQL и внешняя MSSQL).

Основные функции:
    1. Регистрация и управление несколькими базами данных
    2. Создание асинхронных движков SQLAlchemy с настраиваемыми пулами
    3. Управление жизненным циклом сессий (создание, коммит, откат, закрытие)
    4. Инициализация таблиц через SQLAlchemy metadata
    5. Заполнение системных данных (seed)
    6. Синхронизация данных с Avanpost
    7. Проверка подключения и получение статистики
    8. Graceful shutdown с закрытием всех соединений
    9. Singleton-соединение к SQL Server Teamdroid (pyodbc) для
       хранимых процедур ext.PA_mbl_* (см. TeamdroidProcedureRepository).

Технические особенности:
    - Реализация паттерна Singleton (единственный экземпляр)
    - Поддержка SQLite, PostgreSQL и MSSQL через SQLAlchemy
    - Асинхронные движки с пулами соединений (pool_size, max_overflow)
    - Автоматическое переподключение (pool_pre_ping)
    - Контекстный менеджер для безопасной работы с сессиями
    - Поддержка разных моделей для разных БД (BaseModel для main, None для avanpost)

Архитектура:
    - DBEngine: обёртка для движка SQLAlchemy с конфигурацией
    - DBManager: синглтон для управления всеми движками
    - db_manager: глобальный экземпляр для использования во всём приложении
    - Две зарегистрированные БД: "main" (PostgreSQL) и "avanpost" (MSSQL)
    - Отдельный singleton-соединение к Teamdroid SQL Server (pyodbc) —
      используется только хранимыми процедурами ext.PA_mbl_*.
"""

import asyncio
import threading
from collections.abc import AsyncGenerator, Iterator
from contextlib import asynccontextmanager, contextmanager
from dataclasses import dataclass
from enum import StrEnum
from typing import Any, Optional

import pyodbc
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from ..config import settings
from ..logger import db_logger
from ..models import BaseModel
from ..utils.decorators import log_exceptions


class DBType(StrEnum):
    """Типы поддерживаемых баз данных.

    Определяет тип СУБД для настройки подключения и пула соединений.
    """

    SQLITE = "sqlite"
    MSSQL = "mssql"
    POSTGRES = "postgres"


@dataclass
class DBConfig:
    """Конфигурация для подключения к базе данных.

    Attributes:
        url (str): URL подключения к БД
        echo (bool): Включить логирование SQL-запросов
        pool_size (int): Размер пула соединений
        max_overflow (int): Максимальное количество дополнительных соединений
        pool_pre_ping (bool): Проверять соединение перед использованием
        pool_recycle (int): Время жизни соединения в секундах
        is_primary (bool): Является ли БД основной
        models (type[BaseModel] | None): Модели SQLAlchemy для этой БД
    """

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
        """Определение типа СУБД по URL.

        Returns:
            DBType: Тип базы данных
        """
        if "sqlite" in self.url.lower():
            return DBType.SQLITE
        elif "mssql" in self.url.lower() or "sqlserver" in self.url.lower():
            return DBType.MSSQL
        elif "postgres" in self.url.lower() or "postgresql" in self.url.lower():
            return DBType.POSTGRES
        return DBType.SQLITE


class DBEngine:
    """Обёртка для движка базы данных.

    Управляет жизненным циклом движка SQLAlchemy: создание, инициализация,
    проверка подключения, закрытие.

    Attributes:
        config (DBConfig): Конфигурация БД
        _engine (AsyncEngine | None): Асинхронный движок SQLAlchemy
        _session_factory (async_sessionmaker | None): Фабрика сессий
        _initialized (bool): Флаг инициализации
    """

    def __init__(self, config: DBConfig):
        """Инициализация обёртки движка.

        Args:
            config (DBConfig): Конфигурация БД
        """
        self.config = config
        self._engine: AsyncEngine | None = None
        self._session_factory: async_sessionmaker | None = None
        self._initialized = False

    @property
    def engine(self) -> AsyncEngine:
        """Получение асинхронного движка.

        Returns:
            AsyncEngine: Движок SQLAlchemy

        Raises:
            RuntimeError: Если движок не инициализирован
        """
        if not self._engine:
            raise RuntimeError("Engine not initialized")
        return self._engine

    @property
    def session_factory(self) -> async_sessionmaker:
        """Получение фабрики сессий.

        Returns:
            async_sessionmaker: Фабрика сессий

        Raises:
            RuntimeError: Если фабрика не инициализирована
        """
        if not self._session_factory:
            raise RuntimeError("Session factory not initialized")
        return self._session_factory

    @property
    def is_initialized(self) -> bool:
        """Проверка инициализации движка.

        Returns:
            bool: True если движок инициализирован
        """
        return self._initialized

    async def initialize(self) -> None:
        """Инициализация движка.

        Создаёт асинхронный движок SQLAlchemy с настройками из конфигурации.
        Для SQLite используется NullPool, для остальных БД — пул соединений.
        Выполняет проверку подключения запросом SELECT 1.

        Raises:
            Exception: При ошибке подключения к БД
        """
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
        """Закрытие движка и освобождение ресурсов.

        Закрывает все соединения и очищает пул.
        """
        if self._engine:
            await self._engine.dispose()
            self._initialized = False
            db_logger.debug(f"⛔ {self.config.db_type.upper()} engine disposed")


class DBManager:
    """Универсальный менеджер для работы с несколькими базами данных.

    Реализует паттерн Singleton для централизованного управления всеми
    подключениями к БД в приложении.

    Attributes:
        _engines (dict[str, DBEngine]): Словарь движков {имя: DBEngine}
        _primary_name (str | None): Имя основной БД
        _session_counter (int): Счётчик созданных сессий
        _initialized (bool): Флаг инициализации менеджера
    """

    _instance: Optional["DBManager"] = None

    def __new__(cls) -> "DBManager":
        """Создание единственного экземпляра (Singleton)."""
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    def __init__(self) -> None:
        """Инициализация менеджера БД.

        Создаёт пустые структуры для хранения движков и статистики.
        """
        if hasattr(self, "_initialized"):
            return

        self._engines: dict[str, DBEngine] = {}
        self._primary_name: str | None = None
        self._session_counter = 0
        self._initialized = False

    def register_database(self, name: str, config: DBConfig) -> "DBManager":
        """Регистрация новой базы данных.

        Создаёт обёртку DBEngine для конфигурации и добавляет её в словарь.
        Первая зарегистрированная БД с is_primary=True становится основной.

        Args:
            name (str): Уникальное имя БД
            config (DBConfig): Конфигурация подключения

        Returns:
            DBManager: Ссылка на себя для цепочки вызовов

        Note:
            При повторной регистрации существующей БД выводится предупреждение
            и конфигурация обновляется.
        """
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
        """Получение движка основной БД.

        Returns:
            DBEngine: Движок основной БД

        Raises:
            RuntimeError: Если основная БД не зарегистрирована
        """
        if not self._primary_name or self._primary_name not in self._engines:
            raise RuntimeError("No primary database registered")
        return self._engines[self._primary_name]

    def get_engine(self, name: str) -> DBEngine:
        """Получение движка по имени БД.

        Args:
            name (str): Имя БД

        Returns:
            DBEngine: Движок БД

        Raises:
            KeyError: Если БД с таким именем не зарегистрирована
        """
        if name not in self._engines:
            raise KeyError(f"Database '{name}' not registered")
        return self._engines[name]

    def get_engine_by_type(self, db_type: DBType) -> DBEngine | None:
        """Поиск движка по типу СУБД.

        Args:
            db_type (DBType): Тип СУБД

        Returns:
            DBEngine | None: Движок или None, если не найден
        """
        for engine in self._engines.values():
            if engine.config.db_type == db_type:
                return engine
        return None

    @property
    def is_initialized(self) -> bool:
        """Проверка инициализации менеджера.

        Returns:
            bool: True если все БД инициализированы
        """
        return self._initialized

    @asynccontextmanager
    async def get_session(
        self,
        db_name: str | None = None,
        show_logs: bool = True,
    ) -> AsyncGenerator[AsyncSession]:
        """Получение асинхронной сессии для указанной БД.

        Используется как контекстный менеджер для безопасной работы
        с сессией. Автоматически выполняет коммит при успехе или откат при ошибке.

        Args:
            db_name (str | None): Имя БД (по умолчанию основная)
            show_logs (bool): Логировать создание и закрытие сессии

        Yields:
            AsyncSession: Асинхронная сессия SQLAlchemy
        """
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
        """Инициализация всех зарегистрированных баз данных.

        Последовательно инициализирует каждый движок.
        При ошибке инициализации одной БД остальные всё равно инициализируются.
        """
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
        """Инициализация таблиц для базы данных.

        Создаёт все таблицы, определённые в моделях SQLAlchemy.
        При drop_first=True удаляет существующие таблицы перед созданием.

        Args:
            db_name (str | None): Имя БД (по умолчанию основная)
            drop_first (bool): Удалить существующие таблицы перед созданием
        """
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
        """Заполнение таблиц системными данными (seed).

        Вызывает сервис avanpost_seed_service для заполнения системных таблиц
        Avanpost (типы данных, пользователи, записи синхронизации).
        """
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
        """Синхронизация данных Avanpost с выводом статистики только при изменениях.

        Выполняет синхронизацию базовых справочных данных из Avanpost.
        Статистика выводится только при наличии изменений или ошибок.

        Args:
            force (bool): Принудительная полная синхронизация (игнорировать кеш)

        Returns:
            dict: Результат синхронизации с информацией о статусе и статистикой
        """
        db_logger.info(f"🔄 Starting Avanpost data sync (force={force})...")

        try:
            from app.services.avanpost_sync_service import AvanpostSyncService

            sync_service = AvanpostSyncService()
            await sync_service.initialize()

            stats = await sync_service.sync_base_data(force=force)
            status = await sync_service.get_status()

            stats_dict = stats.to_dict()

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
        """Запуск синхронизации Avanpost в фоновом режиме.

        Создаёт асинхронную задачу для выполнения синхронизации без блокировки
        основного потока.

        Args:
            force (bool): Принудительная полная синхронизация

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
        """Закрытие всех соединений к базам данных.

        Последовательно закрывает все движки, singleton-соединение
        Teamdroid SQL и освобождает ресурсы.
        """
        for name, engine in self._engines.items():
            try:
                await engine.dispose()
                db_logger.debug(f"⛔ Database '{name}' closed")
            except Exception as e:
                db_logger.error(f"❌ Failed to close '{name}': {e}")

        # CHANGED: закрываем singleton-соединение Teamdroid SQL (pyodbc).
        try:
            close_teamdroid_sql()
        except Exception as e:  # noqa: BLE001
            db_logger.warning(f"⚠️ Failed to close Teamdroid SQL connection: {e}")

        self._initialized = False
        db_logger.info("✅ All databases closed")

    @log_exceptions(db_logger)
    async def check_connection(self, db_name: str | None = None) -> bool:
        """Проверка подключения к базе данных.

        Выполняет простой запрос SELECT 1 для проверки доступности БД.

        Args:
            db_name (str | None): Имя БД (по умолчанию основная)

        Returns:
            bool: True если подключение успешно
        """
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
        """Получение статистики всех баз данных.

        Возвращает информацию о каждой зарегистрированной БД:
        тип, состояние инициализации, является ли основной.
        Включает состояние Teamdroid SQL singleton.

        Returns:
            dict: Статистика БД
        """
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
            "teamdroid_sql": {
                "connected": _teamdroid_sql_conn is not None,
                "server": getattr(settings, "TEAMDROID_SQL_SERVER", "") or None,
                "database": getattr(settings, "TEAMDROID_SQL_DATABASE", "") or None,
            },
        }


# ==================== ИНИЦИАЛИЗАЦИЯ ====================

db_manager = DBManager()

# Регистрация основной БД (PostgreSQL)
db_manager.register_database(
    "main",
    DBConfig(
        url=settings.db_main_url,
        echo=settings.DB_MAIN_ECHO,
        pool_size=getattr(settings, "DB_MAIN_POOL_SIZE", 10),
        max_overflow=getattr(settings, "DB_MAIN_MAX_OVERFLOW", 20),
        is_primary=True,
        models=BaseModel,
    ),
)

# Регистрация БД Avanpost (MSSQL)
if settings.db_avanpost_url:
    db_manager.register_database(
        "avanpost",
        DBConfig(
            url=settings.db_avanpost_url,
            echo=getattr(settings, "DB_AVANPOST_ECHO", False),
            pool_size=getattr(settings, "DB_AVANPOST_POOL_SIZE", 5),
            max_overflow=getattr(settings, "DB_AVANPOST_MAX_OVERFLOW", 10),
            is_primary=False,
        ),
    )


# ==================== TEAMDROID SQL (pyodbc singleton) ====================
#
# Отдельное переиспользуемое соединение к SQL Server Teamdroid.
# Используется хранимыми процедурами ext.PA_mbl_* через
# app/db/repositories/teamdroid.py.
#
# Не является SQLAlchemy-движком: pyodbc не thread-safe, поэтому
# доступ сериализуется через _teamdroid_sql_lock. Соединение лениво
# создаётся, автоматически переподключается при разрыве и закрывается
# в DBManager.close_all() / close_teamdroid_sql().

_teamdroid_sql_conn: pyodbc.Connection | None = None
_teamdroid_sql_lock = threading.RLock()


def build_teamdroid_sql_conn_str() -> str:
    """Строка подключения к SQL Server Teamdroid (ODBC Driver 18).

    Публичная функция: используется также в app/api/routers/teamdroid.py
    для _load_files (там нужно ОТДЕЛЬНОЕ соединение для длительного
    чтения больших файлов).

    Raises:
        RuntimeError: если TEAMDROID_SQL_SERVER не задан.
    """
    if not getattr(settings, "TEAMDROID_SQL_SERVER", ""):
        raise RuntimeError(
            "TEAMDROID_SQL_SERVER is not configured. "
            "Set TEAMDROID_SQL_SERVER/DATABASE/USERNAME/PASSWORD in .env "
            "to use ext.PA_mbl_* procedures."
        )
    return (
        "DRIVER={ODBC Driver 18 for SQL Server};"
        f"SERVER={settings.TEAMDROID_SQL_SERVER};"
        f"DATABASE={settings.TEAMDROID_SQL_DATABASE};"
        f"UID={settings.TEAMDROID_SQL_USERNAME};"
        f"PWD={settings.TEAMDROID_SQL_PASSWORD};"
        "TrustServerCertificate=yes;"
    )


def get_teamdroid_sql_conn() -> pyodbc.Connection:
    """Singleton-соединение к SQL Server Teamdroid.

    Переподключается, если соединение разорвано (idle-timeout,
    рестарт SQL Server и т.п.). Вызывающий ОБЯЗАН держать
    _teamdroid_sql_lock на всё время работы с соединением —
    используйте teamdroid_sql_cursor().
    """
    global _teamdroid_sql_conn

    with _teamdroid_sql_lock:
        if _teamdroid_sql_conn is not None:
            try:
                cur = _teamdroid_sql_conn.cursor()
                cur.execute("SELECT 1")
                cur.fetchone()
                cur.close()
                return _teamdroid_sql_conn
            except pyodbc.Error:
                try:
                    _teamdroid_sql_conn.close()
                except Exception:  # noqa: BLE001
                    pass
                _teamdroid_sql_conn = None

        conn = pyodbc.connect(
            build_teamdroid_sql_conn_str(),
            timeout=getattr(settings, "TEAMDROID_SQL_TIMEOUT", 10),
            autocommit=False,
        )
        _teamdroid_sql_conn = conn
        return conn


def close_teamdroid_sql() -> None:
    """Закрыть singleton-соединение к SQL Server Teamdroid."""
    global _teamdroid_sql_conn
    with _teamdroid_sql_lock:
        if _teamdroid_sql_conn is not None:
            try:
                _teamdroid_sql_conn.close()
            except Exception as exc:  # noqa: BLE001
                db_logger.warning(f"[teamdroid_sql] failed to close connection: {exc!r}")
            _teamdroid_sql_conn = None


@contextmanager
def teamdroid_sql_cursor() -> Iterator[pyodbc.Cursor]:
    """Контекстный менеджер: курсор на singleton-соединении.

    Держит _teamdroid_sql_lock на всё время работы, т.к. pyodbc
    не thread-safe. Соединение НЕ закрывается при выходе.
    """
    with _teamdroid_sql_lock:
        conn = get_teamdroid_sql_conn()
        cur = conn.cursor()
        try:
            yield cur
        finally:
            cur.close()


__all__ = [
    "DBType",
    "DBConfig",
    "DBEngine",
    "DBManager",
    "db_manager",
    "build_teamdroid_sql_conn_str",
    "get_teamdroid_sql_conn",
    "close_teamdroid_sql",
    "teamdroid_sql_cursor",
]
