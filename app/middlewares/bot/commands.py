from collections.abc import Awaitable, Callable
from typing import Any

from aiogram import BaseMiddleware
from aiogram.types import Message, TelegramObject

from ...bot.dependencies import get_bot_manager
from ...config import settings
from ...logger import bot_logger


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
            bot_manager = get_bot_manager()

            is_admin = user_id in getattr(settings, "ADMIN_IDS", [])
            is_authorized = await bot_manager.is_user_authorized(user_id)

            # Если пользователь авторизован или админ, но нет в кеше - обновляем
            if (is_authorized or is_admin) and not bot_manager.is_user_in_cache(user_id):
                await bot_manager.update_user_commands(user_id, is_admin)
                bot_logger.debug(f"✅ Commands updated for user {user_id} via middleware")
            elif not is_authorized and bot_manager.is_user_in_cache(user_id):
                # Если пользователь разлогинился - очищаем кеш
                bot_manager.clear_user_cache(user_id)
                bot_logger.debug(f"🧹 Cache cleared for unauthorized user {user_id}")

        return await handler(event, data)
