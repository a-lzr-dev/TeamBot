"""
Модуль зависимостей для внедрения в FastAPI приложение.

Назначение:
    Предоставляет функции для получения экземпляров сервисов и менеджеров
    приложения через систему зависимостей FastAPI. Обеспечивает единую точку
    доступа к ключевым компонентам системы.

Основные разделы:
    1.  Получение сессии базы данных:
        - get_session: асинхронная сессия SQLAlchemy
        - Автоматическое управление жизненным циклом сессии
        - Использование контекстного менеджера db_manager

    2.  Получение менеджера API:
        - get_api_manager: глобальный экземпляр APIManager
        - Проверка инициализации перед возвратом
        - Использование паттерна Singleton

Технические особенности:
    - Использование TYPE_CHECKING для предотвращения циклических импортов
    - Ленивый импорт внутри функций для избежания зависимостей
    - Поддержка асинхронных генераторов для управления сессией
    - Проверка инициализации менеджеров с поднятием RuntimeError
    - Интеграция с системой зависимостей FastAPI через Depends()

Архитектура:
    - Единая точка доступа к ключевым компонентам
    - Используется в API роутерах и сервисах
    - Поддержка инъекции зависимостей в FastAPI
"""

from collections.abc import AsyncGenerator
from typing import TYPE_CHECKING

from sqlalchemy.ext.asyncio import AsyncSession

if TYPE_CHECKING:
    from ..api import APIManager


async def get_session() -> AsyncGenerator[AsyncSession]:
    """Зависимость для получения асинхронной сессии базы данных.

    Использует контекстный менеджер db_manager для обеспечения правильного
    открытия и закрытия сессии. Сессия автоматически закрывается после
    завершения работы эндпоинта.

    Yields:
        AsyncSession: Асинхронная сессия SQLAlchemy для работы с БД

    Пример использования в FastAPI:
        @router.get("/users")
        async def get_users(session: AsyncSession = Depends(get_session)):
            users = await user_repo.get_all(session)
            return users
    """
    from ..db import db_manager

    async with db_manager.get_session() as session:
        yield session


def get_api_manager() -> "APIManager":
    """Зависимость для получения экземпляра менеджера API.

    Возвращает глобальный экземпляр APIManager, реализованный как синглтон.
    Используется для управления жизненным циклом API сервера.

    Returns:
        APIManager: Экземпляр менеджера API

    Raises:
        RuntimeError: Если APIManager не инициализирован

    Пример использования в FastAPI:
        @router.get("/api/status")
        async def get_api_status(api_manager: APIManager = Depends(get_api_manager)):
            return await api_manager.get_status()
    """
    from ..api import api_manager

    if api_manager is None:
        raise RuntimeError("APIManager is not initialized")
    return api_manager


__all__ = [
    "get_session",  # Получение сессии БД
    "get_api_manager",  # Получение менеджера API
]
