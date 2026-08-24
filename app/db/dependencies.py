"""
Модуль зависимостей для получения экземпляра менеджера базы данных.

Назначение:
    Предоставляет функцию для получения глобального экземпляра DBManager
    через систему зависимостей FastAPI. Используется для внедрения
    менеджера БД в обработчики и сервисы.

Основные функции:
    1. get_db_manager() - получение глобального экземпляра DBManager
    2. Проверка инициализации менеджера перед возвратом
    3. Поддержка TYPE_CHECKING для избежания циклических импортов

Технические особенности:
    - Использует TYPE_CHECKING для предотвращения циклических импортов
    - Поднимает RuntimeError если менеджер не инициализирован
    - Импортирует db_manager лениво (внутри функции)

Архитектура:
    - Единая точка доступа к DBManager для всего приложения
    - Интегрируется с системой зависимостей FastAPI через Depends()

Использование:
    >>> from app.db.dependencies import get_db_manager
    >>>
    >>> async def my_handler(session: AsyncSession = Depends(get_session)):
    ...     db_manager = get_db_manager()
    ...     # Использование db_manager для операций с БД
"""

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from ..db import DBManager


def get_db_manager() -> "DBManager":
    """Получение экземпляра DBManager.

    Возвращает глобальный экземпляр DBManager, реализованный как синглтон.
    Используется для управления подключениями к базам данных и выполнения
    операций с БД.

    Returns:
        DBManager: Экземпляр менеджера базы данных

    Raises:
        RuntimeError: Если DBManager не инициализирован
    """
    from ..db import db_manager

    if db_manager is None:
        raise RuntimeError("DBManager is not initialized")
    return db_manager


__all__ = [
    "get_db_manager",
]
