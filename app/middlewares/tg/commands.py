from collections.abc import Awaitable, Callable
from typing import Any

from aiogram import BaseMiddleware
from aiogram.types import Message, TelegramObject

from ...config import settings
from ...logger import tg_logger
from ...tg.dependencies import get_tg_manager


class DynamicCommandsMiddleware(BaseMiddleware):
    """Middleware для динамического обновления команд при авторизации"""

    def __init__(self) -> None:
        super().__init__()

    async def __call__(
        self,
        handler: Callable[[TelegramObject, dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: dict[str, Any],
    ) -> Any:
        # Обновление команды для пользователя при любом сообщении
        if isinstance(event, Message) and event.from_user:
            user_id = event.from_user.id
            tg_manager = get_tg_manager()

            is_admin = user_id in getattr(settings, "ADMIN_IDS", [])
            is_authorized = await tg_manager.is_user_authorized(user_id)

            # Если пользователь авторизован или админ, но нет в кеше - обновляем
            if (is_authorized or is_admin) and not tg_manager.is_user_in_cache(user_id):
                await tg_manager.update_user_commands(user_id, is_admin)
                tg_logger.debug(f"✅ Commands updated for user {user_id} via middleware")
            elif not is_authorized and tg_manager.is_user_in_cache(user_id):
                # Если пользователь разлогинился - очищаем кеш
                tg_manager.clear_user_cache(user_id)
                tg_logger.debug(f"🧹 Cache cleared for unauthorized user {user_id}")

        return await handler(event, data)
