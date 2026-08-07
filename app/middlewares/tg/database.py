from collections.abc import Awaitable, Callable
from typing import Any

from aiogram import BaseMiddleware
from aiogram.types import TelegramObject

from ...db import db_manager
from ...logger import db_logger


class DatabaseMiddleware(BaseMiddleware):
    """Добавление сессии БД в обработчики"""

    def __init__(self, auto_commit: bool = True) -> None:
        self.auto_commit = auto_commit
        super().__init__()

    async def __call__(
        self,
        handler: Callable[[TelegramObject, dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: dict[str, Any],
    ) -> Any:
        try:
            async with db_manager.get_session() as session:
                data["session"] = session
                result = await handler(event, data)
                return result
        except Exception as e:
            db_logger.error(f"❌ Database middleware error: {e}", exc_info=True)
            raise


__all__ = [
    "DatabaseMiddleware",
]
