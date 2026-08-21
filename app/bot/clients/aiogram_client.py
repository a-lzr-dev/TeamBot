"""
Реализация клиента Telegram на основе Aiogram.

Этот модуль предоставляет обертку над библиотекой Aiogram,
реализующую интерфейс BaseBotClient.

Основные компоненты:
    - AiogramClient: Обертка для Aiogram бота

Функциональность:
    - Инициализация бота с токеном из настроек
    - Запуск и остановка
    - Отправка сообщений
    - Проверка подключения
    - Получение информации о боте
    - Обработка ошибок Telegram API
    - Защита от флуда при закрытии
"""

import contextlib
from typing import Any

from aiogram import Bot
from aiogram.client.session.aiohttp import AiohttpSession
from aiogram.exceptions import TelegramAPIError

from ...config import settings
from ...logger import bot_logger
from .base import BaseBotClient


class AiogramClient(BaseBotClient):
    """
    Обертка для Aiogram бота.

    Реализует интерфейс BaseBotClient для работы с Telegram через
    библиотеку Aiogram. Управляет жизненным циклом бота,
    отправкой сообщений и проверкой состояния.

    Атрибуты:
        _bot (Bot | None): Экземпляр Aiogram бота
        _session (AiohttpSession | None): HTTP сессия
        _is_running (bool): Флаг запуска
        _initialized (bool): Флаг инициализации
    """

    def __init__(self) -> None:
        """Инициализация клиента Aiogram."""
        self._bot: Bot | None = None
        self._session: AiohttpSession | None = None
        self._is_running = False
        self._initialized = False

    async def initialize(self) -> None:
        """
        Инициализация Aiogram бота.

        Создает экземпляр Bot с токеном из настроек,
        настраивает HTTP сессию и проверяет работоспособность.

        Raises:
            ValueError: Если BOT_TOKEN не настроен
            Exception: При ошибках инициализации
        """
        if self._initialized:
            return

        if not settings.BOT_TOKEN:
            raise ValueError("BOT_TOKEN is not configured")

        try:
            # Создание HTTP сессии и бота
            self._session = AiohttpSession()
            self._bot = Bot(token=settings.BOT_TOKEN, session=self._session)
            self._initialized = True

            # Проверка работоспособности бота
            await self._bot.get_me()
            bot_logger.info("✅ Aiogram client initialized successfully")
        except Exception as err:
            bot_logger.error(f"❌ Failed to initialize Aiogram client: {err}")
            # Закрытие сессии в случае ошибки
            if self._bot:
                with contextlib.suppress(Exception):
                    await self._bot.session.close()
            raise

    async def start(self) -> None:
        """
        Запуск бота.

        Устанавливает флаг запуска. Поллинг обрабатывается
        менеджером бота, а не этим клиентом.
        """
        if not self._initialized:
            await self.initialize()

        self._is_running = True
        bot_logger.debug("✅ Aiogram client started (polling will be handled by manager)")

    async def stop(self) -> None:
        """
        Остановка бота.

        Закрывает сессию и освобождает ресурсы.
        Устойчив к ошибкам флуда при закрытии.
        """
        self._is_running = False

        if self._bot:
            try:
                # Закрытие бота с игнорированием ошибок флуда
                try:
                    if hasattr(self._bot, "close"):
                        await self._bot.close()
                except TelegramAPIError as err:
                    error_str = str(err).lower()
                    if "flood" in error_str or "retry after" in error_str:
                        bot_logger.debug(f"ℹ️ Bot close skipped due to flood: {err}")
                    else:
                        raise
                except Exception as err:
                    bot_logger.debug(f"ℹ️ Bot close error (ignored): {err}")

                # Закрытие HTTP сессии
                if hasattr(self._bot, "session") and self._bot.session:
                    await self._bot.session.close()
                    bot_logger.debug("⛔ Aiogram session closed")

            except Exception as err:
                bot_logger.error(f"❌ Failed to close aiogram bot: {err}")

            self._bot = None

        self._session = None
        bot_logger.info("⛔ Aiogram client stopped")

    async def is_connected(self) -> bool:
        """
        Проверка подключения к Telegram.

        Returns:
            bool: True если бот подключен и работает
        """
        if not self._bot or not self._is_running:
            return False
        try:
            await self._bot.get_me()
            return True
        except TelegramAPIError:
            return False
        except Exception:
            return False

    async def get_status(self) -> dict[str, Any]:
        """
        Получение статуса клиента.

        Returns:
            dict: Информация о состоянии клиента
        """
        connected = False
        bot_id = None

        try:
            if self._bot and self._is_running:
                connected = await self.is_connected()
        except Exception:
            pass

        if self._bot:
            try:
                me = await self._bot.get_me()
                bot_id = me.id
            except Exception:
                if hasattr(self._bot, "id") and self._bot.id:
                    bot_id = self._bot.id

        return {
            "initialized": self._initialized,
            "is_running": self._is_running,
            "connected": connected,
            "client_type": self.client_type,
            "bot_id": bot_id,
        }

    async def send_message(self, chat_id: int, text: str, **kwargs: Any) -> dict[str, Any]:
        """
        Отправка сообщения через Aiogram.

        Args:
            chat_id: ID чата в Telegram
            text: Текст сообщения
            **kwargs: Дополнительные параметры Aiogram (parse_mode, reply_to, и т.д.)

        Returns:
            dict: Результат отправки с полями success, message_id, chat_id, date, error
        """
        if not self._bot:
            return {"success": False, "error": "Bot not initialized", "chat_id": chat_id}

        try:
            message = await self._bot.send_message(chat_id, text, **kwargs)
            return {
                "success": True,
                "message_id": message.message_id,
                "chat_id": chat_id,
                "date": message.date.isoformat() if message.date else None,
            }
        except TelegramAPIError as err:
            bot_logger.error(f"❌ Telegram API error sending message to {chat_id}: {err}")
            return {
                "success": False,
                "error": str(err),
                "chat_id": chat_id,
            }
        except Exception as err:
            bot_logger.error(f"❌ Failed to send message to {chat_id}: {err}")
            return {
                "success": False,
                "error": str(err),
                "chat_id": chat_id,
            }

    async def get_me(self) -> dict[str, Any]:
        """
        Получение информации о боте.

        Returns:
            dict: Информация о боте (id, username, first_name, и т.д.)

        Raises:
            RuntimeError: Если бот не инициализирован
            TelegramAPIError: При ошибках API
            Exception: При неожиданных ошибках
        """
        if not self._bot:
            raise RuntimeError("Bot not initialized")

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
        except TelegramAPIError as err:
            bot_logger.error(f"❌ Failed to get bot info: {err}")
            raise
        except Exception as err:
            bot_logger.error(f"❌ Unexpected error getting bot info: {err}")
            raise

    @property
    def client_type(self) -> str:
        """Тип клиента (bot)."""
        return "bot"

    @property
    def is_initialized(self) -> bool:
        """Проверка инициализации клиента."""
        return self._initialized

    @property
    def is_running(self) -> bool:
        """Проверка запуска клиента."""
        return self._is_running

    @property
    def bot(self) -> Bot | None:
        """Получение экземпляра Aiogram Bot."""
        return self._bot


__all__ = ["AiogramClient"]
