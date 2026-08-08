from collections.abc import AsyncGenerator
from typing import TYPE_CHECKING

from sqlalchemy.ext.asyncio import AsyncSession

if TYPE_CHECKING:
    from ..api import APIManager


async def get_session() -> AsyncGenerator[AsyncSession]:
    """Зависимость для получения сессии БД"""
    from ..db import db_manager

    async with db_manager.get_session() as session:
        yield session


def get_api_manager() -> "APIManager":
    """Получение экземпляра APIManager"""
    from ..api import api_manager

    if api_manager is None:
        raise RuntimeError("APIManager is not initialized")
    return api_manager


__all__ = [
    "get_session",
    "get_api_manager",
]
