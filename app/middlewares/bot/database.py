"""
Middleware для добавления сессии базы данных в обработчики Aiogram.

Назначение:
    Автоматическое внедрение сессии SQLAlchemy в контекст обработчиков
    для удобного доступа к базе данных.

Основные функции:
    1. Создание сессии базы данных для каждого события
    2. Внедрение сессии в контекст обработчика
    3. Автоматическое управление жизненным циклом сессии
    4. Логирование ошибок при работе с БД

Технические особенности:
    - Интеграция с Aiogram через BaseMiddleware
    - Использование async with для управления сессией
    - Автоматическое закрытие сессии после обработки
    - Обработка исключений с логированием

Архитектура:
    - Реализует интерфейс BaseMiddleware от Aiogram
    - Интегрируется с db_manager для получения сессий
    - Использует db_logger для логирования ошибок
"""

from collections.abc import Awaitable, Callable
from typing import Any

from aiogram import BaseMiddleware
from aiogram.types import TelegramObject

from ...db import db_manager
from ...logger import db_logger

# ============================================================
# 1. КЛАСС MIDDLEWARE ДЛЯ СЕССИИ БД
# ============================================================


class DatabaseMiddleware(BaseMiddleware):
    """
    Middleware для добавления сессии базы данных в обработчики.

    Автоматически создаёт и внедряет сессию SQLAlchemy в контекст
    каждого обработчика события.

    Пример использования в Aiogram:
        dp.update.outer_middleware(DatabaseMiddleware(auto_commit=True))

    Attributes:
        auto_commit (bool): Автоматический коммит после обработки (зарезервировано)
    """

    def __init__(self, auto_commit: bool = True) -> None:
        """
        Инициализация middleware сессии БД.

        Args:
            auto_commit: Автоматический коммит после обработки (зарезервировано)
        """
        self.auto_commit = auto_commit
        super().__init__()

    # ============================================================
    # 1.1. ОСНОВНОЙ МЕТОД ОБРАБОТКИ СОБЫТИЯ
    # ============================================================

    async def __call__(
        self,
        handler: Callable[[TelegramObject, dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: dict[str, Any],
    ) -> Any:
        """
        Основной метод обработки события с добавлением сессии БД.

        Args:
            handler: Функция-обработчик события
            event: Объект события (Message, CallbackQuery и т.д.)
            data: Данные контекста для передачи обработчику

        Returns:
            Any: Результат выполнения обработчика

        Flow:
            1. Создание сессии через db_manager
            2. Внедрение сессии в контекст (data["session"])
            3. Вызов обработчика
            4. Автоматическое закрытие сессии (через async with)

        Note:
            Сессия автоматически закрывается после выхода из контекста.
            При возникновении ошибки — логирование и проброс исключения.
        """
        try:
            # 1. Создание сессии и внедрение в контекст
            async with db_manager.get_session() as session:
                data["session"] = session

                # 2. Вызов обработчика
                result = await handler(event, data)
                return result

        except Exception as e:
            # 3. Логирование ошибки
            db_logger.error(f"❌ Database middleware error: {e}", exc_info=True)
            raise


__all__ = [
    "DatabaseMiddleware",
]
