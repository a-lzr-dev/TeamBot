from collections.abc import Awaitable, Callable
from typing import TYPE_CHECKING, Any

from aiogram import BaseMiddleware
from aiogram.types import Message, TelegramObject

from ...config import settings
from ...logger import tg_logger

if TYPE_CHECKING:
    from ...tg import TelegramManager


def get_tg_manager() -> "TelegramManager":
    """Получение глобального tg_manager"""
    from ...tg import tg_manager

    return tg_manager


class DynamicCommandsMiddleware(BaseMiddleware):
    """Middleware для динамического обновления команд при авторизации"""

    # Убираем tg_manager из __init__, так как мы будем получать его через get_tg_manager()
    # def __init__(self, tg_manager: TelegramManager) -> None:
    #     self.tg_manager = tg_manager
    #     super().__init__()

    # Если вы хотите оставить возможность передавать менеджер через конструктор,
    # можно сделать его опциональным, но проще будет всегда получать его глобально.
    # Для единообразия с остальным кодом, лучше использовать глобальный экземпляр.
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
            tg_manager = get_tg_manager()  # Лениво получаем менеджер здесь

            # Проверка, является ли пользователь администратором
            is_admin = user_id in getattr(settings, "ADMIN_IDS", [])

            # Проверка, есть ли пользователь в кеше через публичный метод
            if not tg_manager.is_user_in_cache(user_id):
                # Проверка авторизацию через публичный метод
                is_authorized = await tg_manager.is_user_authorized(user_id)

                if is_authorized or is_admin:
                    await tg_manager.update_user_commands(user_id, is_admin)
                    tg_logger.debug(f"✅ Commands updated for user {user_id} via middleware")
                else:
                    tg_logger.debug(f"ℹ️ User {user_id} not authorized, skipping commands update")

        return await handler(event, data)
