from typing import TYPE_CHECKING, Any

from sqlalchemy.ext.asyncio import AsyncSession
from telethon.errors import FloodWaitError

from app.core.services.base import BaseService

from ....db.repositories.users import UserRepository
from ....exceptions import log_exceptions
from ....logger import bot_logger
from ....models import UserModel
from ...clients.telethon_client import TelethonClient

if TYPE_CHECKING:
    from telethon import TelegramClient


class TelethonUserService(BaseService):
    """Сервис для работы с пользователями через Telethon"""

    def __init__(self, telethon_client: TelethonClient) -> None:
        self._client = telethon_client
        self._telethon: TelegramClient | None = None
        self._initialized = False

    async def initialize(self) -> None:
        """Инициализация сервиса"""
        if self._initialized:
            return

        if not self._client.client:
            await self._client.initialize()

        self._telethon = self._client.client
        self._initialized = True
        bot_logger.debug("✅ Telethon User Service initialized")

    @log_exceptions(bot_logger)
    async def get_user_from_telegram(self, user_id: int) -> dict[str, Any] | None:
        """Получение информации о пользователе из Telegram"""
        if not self._initialized:
            await self.initialize()

        if not self._telethon:
            return None

        try:
            user = await self._telethon.get_entity(user_id)

            return {
                "id": user.id,
                "username": getattr(user, "username", None),
                "first_name": getattr(user, "first_name", None),
                "last_name": getattr(user, "last_name", None),
                "is_bot": getattr(user, "bot", False),
                "phone": getattr(user, "phone", None),
            }

        except FloodWaitError as e:
            bot_logger.warning(f"⏳ Flood wait: {e.seconds}s")
            return None
        except Exception as e:
            bot_logger.error(f"❌ Failed to get user {user_id}: {e}")
            return None

    @log_exceptions(bot_logger)
    async def save_user(
        self,
        session: AsyncSession,
        user_id: int,
        is_bot: bool,
        first_name: str,
        last_name: str | None = None,
        username: str | None = None,
    ) -> UserModel:
        """Сохранение пользователя в БД"""
        return await UserRepository.save_user(
            session=session,
            user_id=user_id,
            is_bot=is_bot,
            first_name=first_name,
            last_name=last_name,
            username=username,
        )

    @log_exceptions(bot_logger)
    async def get_me(self) -> dict[str, Any]:
        """Получение информации о текущем пользователе"""
        if not self._initialized:
            await self.initialize()

        if not self._telethon:
            return {}

        try:
            me = await self._telethon.get_me()
            return {
                "id": me.id,
                "username": getattr(me, "username", None),
                "first_name": getattr(me, "first_name", None),
                "last_name": getattr(me, "last_name", None),
                "is_bot": getattr(me, "bot", False),
                "phone": getattr(me, "phone", None),
            }
        except Exception as e:
            bot_logger.error(f"❌ Failed to get me: {e}")
            return {}

    async def get_status(self) -> dict[str, Any]:
        """Получение статуса сервиса"""
        return {"initialized": self._initialized, "client_available": bool(self._telethon), "service": "telethon_user"}

    async def health_check(self) -> bool:
        """Проверка здоровья сервиса"""
        if not self._initialized or not self._telethon:
            return False

        try:
            await self._telethon.get_me()
            return True
        except Exception:
            return False


__all__ = ["TelethonUserService"]
