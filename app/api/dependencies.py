"""
Модуль зависимостей для внедрения в FastAPI приложение.

Этот модуль предоставляет функции для получения экземпляров сервисов
и менеджеров приложения через систему зависимостей FastAPI.
"""

from collections.abc import AsyncGenerator
from typing import TYPE_CHECKING

from sqlalchemy.ext.asyncio import AsyncSession

if TYPE_CHECKING:
    from ..api import APIManager


async def get_session() -> AsyncGenerator[AsyncSession]:
    """
    Зависимость для получения асинхронной сессии базы данных.

    Использует контекстный менеджер db_manager для обеспечения правильного
    открытия и закрытия сессии. Сессия автоматически закрывается после
    завершения работы эндпоинта.

    Yields:
        AsyncSession: Асинхронная сессия SQLAlchemy для работы с БД
    """
    from ..db import db_manager

    async with db_manager.get_session() as session:
        yield session


def get_api_manager() -> "APIManager":
    """
    Зависимость для получения экземпляра менеджера API.

    Возвращает глобальный экземпляр APIManager, реализованный как синглтон.
    Используется для управления жизненным циклом API сервера.

    Returns:
        APIManager: Экземпляр менеджера API
    """
    from ..api import api_manager

    if api_manager is None:
        raise RuntimeError("APIManager is not initialized")
    return api_manager


__all__ = [
    "get_session",  # Получение сессии БД
    "get_api_manager",  # Получение менеджера API
]
