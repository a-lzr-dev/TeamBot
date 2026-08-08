import asyncio
import contextlib
from collections.abc import Callable
from typing import Any

from telethon import TelegramClient
from telethon.errors import FloodWaitError, RPCError
from telethon.events.common import EventBuilder

from ...config import settings
from ...logger import tg_logger
from .base import BaseTelegramClient


class TelethonClient(BaseTelegramClient):
    """Обертка для Telethon клиента"""

    def __init__(self) -> None:
        self._client: TelegramClient | None = None
        self._is_running = False
        self._initialized = False
        self._event_handlers: list[tuple] = []  # Уточняем тип
        self._reconnect_delay = settings.TELEGRAM_RECONNECT_DELAY
        self._max_reconnect_delay = 300

    async def initialize(self, is_bot: bool = True) -> None:
        """Инициализация клиента"""
        if self._initialized:
            return

        try:
            if is_bot:
                self._client = TelegramClient(settings.BOT_SESSION_NAME, settings.BOT_ID, settings.BOT_HASH)
            else:
                self._client = TelegramClient(settings.USER_SESSION_NAME, settings.BOT_ID, settings.BOT_HASH)

            self._initialized = True
            tg_logger.info(f"✅ Telethon client initialized ({'bot' if is_bot else 'user'})")
        except Exception as err:
            tg_logger.error(f"❌ Failed to initialize Telethon client: {err}")
            raise

    async def start(self) -> None:
        """Запуск клиента с автоматическим переподключением"""
        if not self._client:
            raise RuntimeError("Client not initialized. Call initialize() first.")

        self._is_running = True

        while self._is_running:
            try:
                # Проверка подключение
                if not self._client.is_connected():
                    tg_logger.debug("🔄 Connecting to Telegram...")
                    await self._client.connect()

                    # Авторизация
                    if settings.is_bot_account:
                        # noinspection PyUnresolvedReferences
                        await self._client.start(bot_token=settings.BOT_TOKEN)
                    else:
                        # noinspection PyUnresolvedReferences
                        await self._client.start(phone=settings.USER_PHONE)

                    tg_logger.info("✅ Telethon client started successfully")

                    # Проверка работы клиента
                    me = await self._client.get_me()
                    tg_logger.info(f"✅ Connected as: {me.first_name} (@{me.username})")
                    break

                # Ожидание
                await asyncio.sleep(1)

            except FloodWaitError as err:
                wait_time = err.seconds
                tg_logger.warning(f"⏳ Flood wait: {wait_time}s")
                await asyncio.sleep(wait_time)

            except (RPCError, ConnectionError) as err:
                tg_logger.error(f"❌ Connection error: {err}")
                await asyncio.sleep(self._reconnect_delay)

            except Exception as err:
                tg_logger.error(f"❌ Failed to start client: {err}")
                await asyncio.sleep(self._reconnect_delay)

    async def stop(self) -> None:
        """Остановка клиента"""
        self._is_running = False

        if self._client:
            try:
                if self._client.is_connected():
                    self._client.disconnect()
                    tg_logger.info("⛔ Telethon client stopped")
            except Exception as err:
                tg_logger.error(f"❌ Error disconnecting: {err}")

        # Очистка обработчиков
        self._event_handlers.clear()

    async def is_connected(self) -> bool:
        """Проверка подключения"""
        if not self._client:
            return False
        try:
            return bool(self._client.is_connected())
        except Exception:
            return False

    async def get_status(self) -> dict[str, Any]:
        """Получение статуса клиента"""
        connected = False
        user_info = {}

        with contextlib.suppress(Exception):
            connected = await self.is_connected()

        if connected and self._client:
            try:
                me = await self._client.get_me()
                user_info = {
                    "id": me.id,
                    "username": getattr(me, "username", None),
                    "first_name": getattr(me, "first_name", None),
                    "last_name": getattr(me, "last_name", None),
                    "is_bot": getattr(me, "bot", False),
                }
            except Exception as err:
                tg_logger.debug(f"Could not get user info: {err}")

        return {
            "initialized": self._initialized,
            "is_running": self._is_running,
            "connected": connected,
            "client_type": self.client_type,
            "is_bot": settings.is_bot_account,
            "user_info": user_info,
            "event_handlers_count": len(self._event_handlers),
        }

    async def send_message(self, chat_id: int, text: str, **kwargs: Any) -> dict[str, Any]:
        """
        Отправка сообщения через Telethon
        """
        if not self._client:
            return {"success": False, "error": "Client not initialized", "chat_id": chat_id}

        if not self._client.is_connected():
            return {"success": False, "error": "Client not connected", "chat_id": chat_id}

        try:
            # Извлечение поддерживаемых параметров Telethon
            parse_mode = kwargs.get("parse_mode")
            disable_notification = kwargs.get("disable_notification", False)
            reply_to = kwargs.get("reply_to_message_id") or kwargs.get("reply_to")
            schedule = kwargs.get("schedule")

            silent = disable_notification

            # Формирование параметров для Telethon
            send_kwargs: dict[str, Any] = {}
            if parse_mode is not None:
                if parse_mode == "HTML":
                    send_kwargs["parse_mode"] = "html"
                elif parse_mode == "MARKDOWN":
                    send_kwargs["parse_mode"] = "markdown"
                elif parse_mode == "MARKDOWN_V2":
                    send_kwargs["parse_mode"] = "MarkdownV2"
                else:
                    send_kwargs["parse_mode"] = parse_mode.lower()

            if silent:
                send_kwargs["silent"] = True

            if reply_to is not None:
                send_kwargs["reply_to"] = reply_to

            if schedule is not None:
                send_kwargs["schedule"] = schedule

            # Отправка сообщения
            result = await self._client.send_message(chat_id, text, **send_kwargs)

            return {
                "success": True,
                "message_id": result.id,
                "chat_id": chat_id,
                "date": result.date.isoformat() if result.date else None,
            }
        except FloodWaitError as err:
            tg_logger.warning(f"⏳ Flood wait sending message: {err.seconds}s")
            return {
                "success": False,
                "error": f"Flood wait: {err.seconds}s",
                "chat_id": chat_id,
                "retry_after": err.seconds,
            }
        except RPCError as err:
            tg_logger.error(f"❌ RPC error sending message: {err}")
            return {
                "success": False,
                "error": str(err),
                "chat_id": chat_id,
            }
        except Exception as err:
            tg_logger.error(f"❌ Failed to send message: {err}")
            return {
                "success": False,
                "error": str(err),
                "chat_id": chat_id,
            }

    async def get_me(self) -> dict[str, Any]:
        """Получение информации о текущем пользователе"""
        if not self._client:
            raise RuntimeError("Client not initialized")

        if not self._client.is_connected():
            raise RuntimeError("Client not connected")

        try:
            me = await self._client.get_me()
            return {
                "id": me.id,
                "username": getattr(me, "username", None),
                "first_name": getattr(me, "first_name", None),
                "last_name": getattr(me, "last_name", None),
                "is_bot": getattr(me, "bot", False),
                "phone": getattr(me, "phone", None),
                "is_contact": getattr(me, "contact", False),
                "is_mutual_contact": getattr(me, "mutual_contact", False),
            }
        except RPCError as err:
            tg_logger.error(f"❌ RPC error getting user: {err}")
            raise
        except Exception as err:
            tg_logger.error(f"❌ Failed to get user: {err}")
            raise

    async def add_event_handler(self, handler_func: Callable, event_type: EventBuilder | None = None) -> None:
        """Добавление обработчика событий"""
        if not self._client:
            raise RuntimeError("Client not initialized")

        try:
            if event_type is None:
                self._client.add_event_handler(handler_func)
            else:
                self._client.add_event_handler(handler_func, event_type)
            self._event_handlers.append((handler_func, event_type))
            tg_logger.debug("✅ Event handler added")
        except Exception as err:
            tg_logger.error(f"❌ Failed to add event handler: {err}")
            raise

    async def remove_event_handler(self, handler_func: Callable) -> bool:
        """Удаление обработчика событий"""
        if not self._client:
            return False

        try:
            self._client.remove_event_handler(handler_func)
            # Удаляем из списка
            self._event_handlers = [(h, e) for (h, e) in self._event_handlers if h != handler_func]
            tg_logger.debug("✅ Event handler removed")
            return True
        except Exception as err:
            tg_logger.error(f"❌ Failed to remove event handler: {err}")
            return False

    async def get_dialogs(self, limit: int = 100) -> list[dict[str, Any]]:
        """Получение списка диалогов"""
        if not self._client:
            return []

        if not self._client.is_connected():
            return []

        dialogs = []
        try:
            async for dialog in self._client.iter_dialogs(limit=limit):
                dialogs.append(
                    {
                        "id": dialog.id,
                        "name": dialog.name,
                        "title": dialog.title,
                        "is_user": dialog.is_user,
                        "is_group": dialog.is_group,
                        "is_channel": dialog.is_channel,
                        "unread_count": dialog.unread_count,
                    }
                )
            tg_logger.debug(f"✅ Retrieved {len(dialogs)} dialogs")
        except Exception as err:
            tg_logger.error(f"❌ Failed to get dialogs: {err}")

        return dialogs

    async def health_check(self) -> bool:
        """Проверка здоровья клиента"""
        try:
            if not self._client:
                return False
            if not self._client.is_connected():
                return False
            await self._client.get_me()
            return True
        except Exception:
            return False

    @property
    def client_type(self) -> str:
        """Тип клиента"""
        return "user" if settings.is_user_account else "bot"

    @property
    def is_initialized(self) -> bool:
        """Проверка инициализации"""
        return self._initialized

    @property
    def is_running(self) -> bool:
        """Проверка запуска"""
        return self._is_running

    @property
    def client(self) -> TelegramClient | None:
        """Получение экземпляра TelegramClient"""
        return self._client

    async def __aenter__(self) -> "TelethonClient":
        """Поддержка async context manager"""
        await self.start()
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: Any | None,
    ) -> None:
        """Поддержка async context manager"""
        await self.stop()


__all__ = ["TelethonClient"]
