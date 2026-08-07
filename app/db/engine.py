from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from ..config import settings
from ..logger import db_logger


def create_engine(
    database_url: str | None = None,
    echo: bool | None = None,
    pool_size: int | None = None,
    max_overflow: int | None = None,
    pool_pre_ping: bool | None = None,
) -> AsyncEngine:
    """Создание асинхронного engine для работы с БД"""
    url = database_url or settings.DB_MAIN_URL
    echo_flag = echo if echo is not None else settings.DB_MAIN_ECHO
    pool_size_value = pool_size if pool_size is not None else settings.DB_MAIN_POOL_SIZE
    max_overflow_value = max_overflow if max_overflow is not None else settings.DB_MAIN_MAX_OVERFLOW
    pre_ping = pool_pre_ping if pool_pre_ping is not None else True

    db_logger.debug(f"🔧 Creating database engine: {url.split('://')[0]}://***")

    try:
        # Использование соединения для SQLite без пула
        if url.startswith("sqlite"):
            db_engine = create_async_engine(
                url,
                echo=echo_flag,
                poolclass=NullPool,
                connect_args={"check_same_thread": False} if "sqlite" in url else {},
            )
            db_logger.debug("✅ Using NullPool for SQLite")
        # Использование соединения для других БД с пулом
        else:
            db_engine = create_async_engine(
                url,
                echo=echo_flag,
                pool_size=pool_size_value,
                max_overflow=max_overflow_value,
                pool_pre_ping=pre_ping,
                pool_recycle=3600,  # Пересоздание соединения каждый час
            )
            db_logger.debug(f"✅ Using connection pool (size={pool_size_value}, overflow={max_overflow_value})")

        return db_engine

    except Exception as e:
        db_logger.error(f"❌ Failed to create database engine: {e}", exc_info=True)
        raise


engine = create_engine()

AsyncSessionLocal = async_sessionmaker(
    engine,
    class_=AsyncSession,
    expire_on_commit=False,
    autocommit=False,
    autoflush=False,
)


async def get_engine_status() -> dict:
    """Получение информации о состоянии engine"""
    pool = engine.pool if hasattr(engine, "pool") else None

    status = {
        "url": settings.DB_MAIN_URL.split("://")[0] + "://***",
        "echo": settings.DB_MAIN_ECHO,
        "pool_type": type(pool).__name__ if pool else "No pool",
    }

    if pool and hasattr(pool, "size"):
        status.update(
            {
                "pool_size": getattr(pool, "size", 0),
                "checked_in": getattr(pool, "checkedin", 0),
                "overflow": getattr(pool, "overflow", 0),
                "total": getattr(pool, "total", 0),
            }
        )

    return status


async def dispose_engine() -> None:
    """Закрытие всех соединений и освобождение ресурсов"""
    try:
        await engine.dispose()
        db_logger.debug("⛔ Database engine disposed")
    except Exception as e:
        db_logger.error(f"❌ Failed to dispose engine: {e}", exc_info=True)
        raise


__all__ = [
    "engine",
    "AsyncSessionLocal",
    "create_engine",
    "get_engine_status",
    "dispose_engine",
]
