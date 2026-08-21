from typing import TYPE_CHECKING, Any

from sqlalchemy.ext.asyncio import AsyncSession
from telethon.errors import FloodWaitError

from ....core.services import BaseService
from ....db.repositories import ChatRepository
from ....logger import bot_logger
from ....models import ChatModel, ChatType
from ....utils.decorators import log_exceptions
from ...clients.telethon_client import TelethonClient

if TYPE_CHECKING:
    from telethon import TelegramClient


class TelethonChatService(BaseService):
    """Сервис для работы с чатами через Telethon"""

    def __init__(self, telethon_client: TelethonClient) -> None:
        """Инициализация сервиса"""
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
        bot_logger.debug("✅ Telethon Chat Service initialized")

    @log_exceptions(bot_logger)
    async def get_chats(self, session: AsyncSession, is_active: bool | None = None) -> list[ChatModel]:
        """Получение списка чатов из БД"""
        if not self._initialized:
            await self.initialize()

        return await ChatRepository.get_chats(session, is_active=is_active)  # type: ignore[no-any-return]

    @log_exceptions(bot_logger)
    async def get_chat_from_telegram(self, chat_id: int) -> dict[str, Any] | None:
        """Получение информации о чате из Telegram"""
        if not self._initialized:
            await self.initialize()

        if not self._telethon:
            return None

        try:
            chat = await self._telethon.get_entity(chat_id)

            # Определение типа чата
            chat_type = ChatType.PRIVATE
            if hasattr(chat, "megagroup") and chat.megagroup:
                chat_type = ChatType.SUPERGROUP
            elif hasattr(chat, "channel") and chat.channel:
                chat_type = ChatType.CHANNEL
            elif hasattr(chat, "group") and chat.group:
                chat_type = ChatType.GROUP

            return {
                "id": chat.id,
                "title": getattr(chat, "title", None),
                "type": chat_type.value,
                "username": getattr(chat, "username", None),
                "participants_count": getattr(chat, "participants_count", None),
                "is_active": True,
            }

        except FloodWaitError as e:
            bot_logger.warning(f"⏳ Flood wait: {e.seconds}s")
            return None
        except Exception as e:
            bot_logger.error(f"❌ Failed to get chat {chat_id}: {e}")
            return None

    @log_exceptions(bot_logger)
    async def save_chat(
        self, session: AsyncSession, chat_id: int, chat_type: str, title: str | None = None, is_active: bool = True
    ) -> ChatModel:
        """Сохранение чата в БД"""
        return await ChatRepository.save_chat(  # type: ignore[no-any-return]
            session=session, chat_id=chat_id, chat_type=chat_type, title=title, is_active=is_active
        )

    async def get_status(self) -> dict[str, Any]:
        """Получение статуса сервиса"""
        return {"initialized": self._initialized, "client_available": bool(self._telethon), "service": "telethon_chat"}

    async def health_check(self) -> bool:
        """Проверка здоровья сервиса"""
        if not self._initialized or not self._telethon:
            return False

        try:
            return bool(self._telethon.is_connected())
        except Exception as e:
            bot_logger.error(f"❌ Health check failed: {e}")
            return False


__all__ = ["TelethonChatService"]
