from typing import Any, Optional

from aiogram.types import (
    BotCommand,
    ChatMember,
    ChatMemberAdministrator,
    ChatMemberBanned,
    ChatMemberLeft,
    ChatMemberMember,
    ChatMemberOwner,
    ChatMemberRestricted,
)

from ....exceptions import log_exceptions
from ....logger import tg_logger
from ...clients import AiogramClient
from ..base import BaseService


class AiogramBotService(BaseService):
    """Сервис для управления ботом"""

    _instance: Optional["AiogramBotService"] = None

    # Явное объявление типов атрибутов класса
    _client: AiogramClient | None
    _bot: Any | None  # Bot из aiogram
    _initialized: bool

    def __new__(cls, aiogram_client: AiogramClient | None = None) -> "AiogramBotService":
        """Создание или получение единственного экземпляра сервиса"""
        if cls._instance is None:
            if aiogram_client is None:
                raise ValueError("AiogramClient required for first initialization")
            cls._instance = super().__new__(cls)
            # Инициализация атрибутов при первом создании
            cls._instance._client = None
            cls._instance._bot = None
            cls._instance._initialized = False
        return cls._instance

    def __init__(self, aiogram_client: AiogramClient | None = None) -> None:
        """Инициализация сервиса"""
        # Пропуск если уже инициализирован
        if hasattr(self, "_initialized") and self._initialized:
            return

        # Сохранение клиента при первом создании
        if self._client is None:
            if aiogram_client is None:
                raise ValueError("AiogramClient required for first initialization")
            self._client = aiogram_client
            self._bot = None
            self._initialized = False

    async def initialize(self) -> None:
        """Инициализация сервиса (выполняется только один раз)"""
        if self._initialized:
            tg_logger.debug("ℹ️ Aiogram Bot Service already initialized, skipping")
            return

        if self._client is None:
            raise RuntimeError("AiogramClient not initialized")

        if not self._client.bot:
            await self._client.initialize()

        self._bot = self._client.bot
        self._initialized = True
        tg_logger.info("✅ Aiogram Bot Service initialized")

    @log_exceptions(tg_logger)
    async def set_commands(self, commands: list[dict[str, str]], scope: str | None = None) -> bool:
        """
        Установка команд бота.

        Args:
            commands: Список команд [{"command": "/start", "description": "Start"}]
            scope: Опциональный scope для команд

        Returns:
            bool: True если команды установлены успешно
        """
        if not self._initialized:
            await self.initialize()

        if not self._bot:
            return False

        try:
            bot_commands = [BotCommand(command=cmd["command"], description=cmd["description"]) for cmd in commands]

            if scope:
                # Можно добавить поддержку разных скоупов
                pass

            await self._bot.set_my_commands(bot_commands)
            tg_logger.info(f"✅ Commands set: {len(commands)} commands")
            return True

        except Exception as e:
            tg_logger.error(f"❌ Failed to set commands: {e}")
            return False

    @log_exceptions(tg_logger)
    async def get_me(self) -> dict[str, Any]:
        """Получение информации о боте"""
        if not self._initialized:
            await self.initialize()

        if not self._bot:
            return {}

        try:
            me = await self._bot.get_me()
            return {
                "id": me.id,
                "username": me.username,
                "first_name": me.first_name,
                "last_name": me.last_name,
                "is_bot": me.is_bot,
                "can_join_groups": me.can_join_groups,
                "can_read_all_group_messages": me.can_read_all_group_messages,
                "supports_inline_queries": me.supports_inline_queries,
            }
        except Exception as e:
            tg_logger.error(f"❌ Failed to get bot info: {e}")
            return {}

    @log_exceptions(tg_logger)
    async def get_chat_member_count(self, chat_id: int) -> int | None:
        """Получение количества участников чата"""
        if not self._initialized:
            await self.initialize()

        if not self._bot:
            return None

        try:
            chat = await self._bot.get_chat(chat_id)
            return chat.full_chat.participants_count if hasattr(chat, "full_chat") else None
        except Exception as e:
            tg_logger.error(f"❌ Failed to get chat member count for {chat_id}: {e}")
            return None

    @log_exceptions(tg_logger)
    async def get_chat_member(self, chat_id: int, user_id: int) -> dict[str, Any]:
        """Получение информации об участнике чата"""
        if not self._initialized:
            await self.initialize()

        if not self._bot:
            return {}

        try:
            member: ChatMember = await self._bot.get_chat_member(chat_id, user_id)

            # Получение статуса
            status = getattr(member, "status", None)
            if status is None:
                status_str = "unknown"
            elif hasattr(status, "value"):
                status_str = status.value
            else:
                status_str = str(status)

            # Получение пользователя
            user_obj = getattr(member, "user", None)

            # Базовые поля
            result: dict[str, Any] = {
                "user_id": getattr(user_obj, "id", 0) if user_obj else 0,
                "username": getattr(user_obj, "username", None) if user_obj else None,
                "first_name": getattr(user_obj, "first_name", "") if user_obj else "",
                "last_name": getattr(user_obj, "last_name", None) if user_obj else None,
                "is_bot": getattr(user_obj, "is_bot", False) if user_obj else False,
                "status": status_str,
                "is_member": getattr(member, "is_member", False),
            }

            # Добавление полей в зависимости от типа статуса
            if isinstance(member, ChatMemberOwner | ChatMemberAdministrator):
                result.update(
                    {
                        "can_change_info": getattr(member, "can_change_info", False),
                        "can_invite_users": getattr(member, "can_invite_users", False),
                        "can_pin_messages": getattr(member, "can_pin_messages", False),
                        "can_manage_chat": getattr(member, "can_manage_chat", False),
                        "can_edit_messages": getattr(member, "can_edit_messages", False),
                        "can_delete_messages": getattr(member, "can_delete_messages", False),
                        "can_manage_voice_chats": getattr(member, "can_manage_voice_chats", False),
                        "can_restrict_members": getattr(member, "can_restrict_members", False),
                        "can_promote_members": getattr(member, "can_promote_members", False),
                    }
                )
                if isinstance(member, ChatMemberAdministrator):
                    result["can_be_edited"] = getattr(member, "can_be_edited", False)
                if isinstance(member, ChatMemberOwner):
                    result["is_creator"] = True

            elif isinstance(member, ChatMemberMember):
                result.update(
                    {
                        "can_send_messages": True,
                        "can_send_media_messages": True,
                        "can_send_polls": True,
                        "can_send_other_messages": True,
                        "can_add_web_page_previews": True,
                    }
                )

            elif isinstance(member, ChatMemberRestricted):
                result.update(
                    {
                        "can_send_messages": getattr(member, "can_send_messages", False),
                        "can_send_media_messages": getattr(member, "can_send_media_messages", False),
                        "can_send_polls": getattr(member, "can_send_polls", False),
                        "can_send_other_messages": getattr(member, "can_send_other_messages", False),
                        "can_add_web_page_previews": getattr(member, "can_add_web_page_previews", False),
                        "can_change_info": getattr(member, "can_change_info", False),
                        "can_invite_users": getattr(member, "can_invite_users", False),
                        "can_pin_messages": getattr(member, "can_pin_messages", False),
                        "until_date": getattr(member, "until_date", None),
                    }
                )

            elif isinstance(member, ChatMemberLeft | ChatMemberBanned):
                result.update(
                    {
                        "is_member": False,
                        "until_date": getattr(member, "until_date", None)
                        if isinstance(member, ChatMemberBanned)
                        else None,
                    }
                )

            return result

        except Exception as e:
            tg_logger.error(f"❌ Failed to get chat member: {e}")
            return {}

    # ==================== ПУБЛИЧНЫЕ МЕТОДЫ ДЛЯ ПРОВЕРКИ СТАТУСА ====================

    def is_initialized(self) -> bool:
        """Проверка, инициализирован ли сервис"""
        return self._initialized

    def is_available(self) -> bool:
        """Проверка, доступен ли бот"""
        return self._bot is not None

    async def get_status(self) -> dict[str, Any]:
        """Получение статуса сервиса"""
        return {
            "initialized": self._initialized,
            "bot_available": bool(self._bot),
            "service": "aiogram_bot",
            "is_singleton": True,
        }

    async def health_check(self) -> bool:
        """Проверка здоровья сервиса"""
        if not self._initialized or not self._bot:
            return False

        try:
            await self._bot.get_me()
            return True
        except Exception:
            return False

    @classmethod
    def reset_instance(cls) -> None:
        """Сброс синглтон-экземпляра"""
        cls._instance = None

    def __repr__(self) -> str:
        """Строковое представление сервиса"""
        status = "initialized" if self._initialized else "not initialized"
        bot_status = "available" if self._bot else "not available"
        return f"<AiogramBotService status={status}, bot={bot_status}>"


__all__ = ["AiogramBotService"]
