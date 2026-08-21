"""
Менеджер бота - главный класс для управления клиентами и сервисами Telegram.

Отвечает за:
1. Инициализацию и управление жизненным циклом Aiogram и Telethon клиентов
2. Координацию работы всех сервисов (сообщения, синхронизация, чаты, пользователи)
3. Управление динамическими командами для пользователей
4. Обработку сообщений и callback-запросов
5. Синхронизацию чатов и участников
"""

import asyncio
import contextlib
from collections.abc import Awaitable, Callable
from functools import partial, wraps
from typing import Any, TypeVar, cast

from aiogram import Bot, Dispatcher
from aiogram.exceptions import TelegramAPIError, TelegramNetworkError
from aiogram.types import CallbackQuery, Message
from sqlalchemy.ext.asyncio import AsyncSession
from telethon import TelegramClient

from ..config import settings
from ..db import ChatRepository, MessageRepository, ReminderRepository, UserRepository, db_manager
from ..db.repositories import StatsRepository
from ..logger import bot_logger
from ..middlewares.bot.database import DatabaseMiddleware
from ..middlewares.bot.error_handler import ErrorHandlerMiddleware
from ..middlewares.bot.logging import ChatActivityMiddleware, LoggingMiddleware
from ..middlewares.bot.rate_limit import RateLimitMiddleware
from ..middlewares.bot.throttling import ThrottlingMiddleware
from ..models import MessageType
from ..utils.decorators import log_exceptions
from .clients import AiogramClient, TelethonClient
from .handlers import setup_aiogram_handlers, setup_telethon_handlers
from .services import (
    AiogramBotService,
    SyncService,
    TelethonChatService,
    TelethonUserService,
    UnifiedMessageService,
)

R = TypeVar("R")


def ensure_initialized[R](func: Callable[..., Awaitable[R]]) -> Callable[..., Awaitable[R]]:
    """
    Декоратор для автоматической инициализации менеджера.

    Используется для методов, которые требуют, чтобы менеджер был инициализирован.
    Если менеджер не инициализирован, вызывает метод initialize() перед выполнением.

    Args:
        func: Асинхронная функция-обертка

    Returns:
        Callable[..., Awaitable[R]]: Обернутая функция с автоматической инициализацией
    """

    @wraps(func)
    async def wrapper(self: Any, *args: Any, **kwargs: Any) -> R:
        if not self._initialized:
            await self.initialize()
        return await func(self, *args, **kwargs)

    return cast("Callable[..., Awaitable[R]]", wrapper)


class BotManager:
    """
    Главный менеджер для управления клиентами и сервисами бота.

    Координирует работу всех компонентов Telegram бота:
    - Aiogram клиент для работы с Bot API
    - Telethon клиент для работы с User API (синхронизация чатов)
    - Сервисы для отправки сообщений, синхронизации, работы с чатами и пользователями
    - Динамические команды для разных пользователей
    - Жизненный цикл бота (запуск, остановка, перезапуск)
    """

    # ==================== ИНИЦИАЛИЗАЦИЯ ====================

    def __init__(self) -> None:
        """
        Инициализация менеджера бота.

        Создает все клиенты, сервисы и репозитории, необходимые для работы.
        Устанавливает начальное состояние (не инициализирован, не запущен).
        """
        # === Клиенты ===
        # Aiogram клиент для работы с Bot API (отправка сообщений, команды)
        self._aiogram_client: AiogramClient = AiogramClient()
        # Telethon клиент для работы с User API (синхронизация чатов, участников)
        self._telethon_client: TelethonClient = TelethonClient()

        # === Сервис сообщений ===
        # Унифицированный сервис для отправки сообщений через оба клиента
        self._message_service: UnifiedMessageService = UnifiedMessageService(
            self._aiogram_client, self._telethon_client
        )

        # === Сервисы Aiogram ===
        # Сервис для управления ботом (команды, информация о боте)
        self._bot_service: AiogramBotService = AiogramBotService(self._aiogram_client)

        # === Сервисы Telethon ===
        # Сервис для работы с чатами через Telethon
        self._chat_service: TelethonChatService = TelethonChatService(self._telethon_client)
        # Сервис для работы с пользователями через Telethon
        self._user_service: TelethonUserService = TelethonUserService(self._telethon_client)

        # === Сервис синхронизации ===
        # Сервис для синхронизации чатов и участников
        self._sync_service: SyncService = SyncService(self._telethon_client)

        # === Репозитории ===
        # Репозитории для работы с базой данных
        self._chat_repo = ChatRepository()
        self._user_repo = UserRepository()
        self._message_repo = MessageRepository()
        self._reminder_repo = ReminderRepository()
        self._stats_repo = StatsRepository()

        # === Состояние ===
        # Флаг инициализации менеджера
        self._initialized: bool = False
        # Флаг запуска менеджера
        self._is_running: bool = False
        # Список фоновых задач
        self._tasks: list[asyncio.Task] = []
        # Событие для остановки
        self._stop_event: asyncio.Event = asyncio.Event()
        # Главный event loop
        self._main_loop: asyncio.AbstractEventLoop | None = None

        # Кеш команд для пользователей
        # Хранит список команд для каждого пользователя (user_id -> commands)
        self._user_commands_cache: dict[int, list[dict[str, str]]] = {}

        bot_logger.debug(f"✅ Telegram Manager instance created (account_type={settings.TELEGRAM_ACCOUNT_TYPE})")

    # ==================== ПУБЛИЧНЫЕ СВОЙСТВА ====================

    @property
    def aiogram_client(self) -> AiogramClient:
        """Получение Aiogram клиента."""
        return self._aiogram_client

    @property
    def telethon_client(self) -> TelethonClient:
        """Получение Telethon клиента."""
        return self._telethon_client

    @property
    def message_service(self) -> UnifiedMessageService:
        """Получение сервиса сообщений."""
        return self._message_service

    @property
    def bot_service(self) -> AiogramBotService:
        """Получение сервиса бота."""
        return self._bot_service

    @property
    def chat_service(self) -> TelethonChatService:
        """Получение сервиса чатов."""
        return self._chat_service

    @property
    def user_service(self) -> TelethonUserService:
        """Получение сервиса пользователей."""
        return self._user_service

    @property
    def sync_service(self) -> SyncService:
        """Получение сервиса синхронизации."""
        return self._sync_service

    # ==================== СВОЙСТВА ДЛЯ ОБРАТНОЙ СОВМЕСТИМОСТИ ====================

    @property
    def _bot(self) -> Bot | None:
        """Получение Aiogram Bot (для обратной совместимости)."""
        return self._aiogram_client.bot

    @property
    def _client(self) -> TelegramClient | None:
        """Получение Telethon Client (для обратной совместимости)."""
        return self._telethon_client.client

    # ==================== МЕТОДЫ ДЛЯ РАБОТЫ С СООБЩЕНИЯМИ ====================

    @ensure_initialized
    async def send_message(
        self,
        *,
        chat_id: int,
        text: str,
        message_type: MessageType | None = None,
        delete_message_id: int | None = None,
        delete_by_type: str | None = None,
        exclude_message_types: list[MessageType] | None = None,
        parse_mode: str | None = None,
        disable_web_page_preview: bool = False,
        disable_notification: bool = False,
        protect_content: bool = False,
        reply_to_message_id: int | None = None,
        reply_markup: Any = None,
        user_id: int | None = None,
        user_first_name: str | None = None,
        user_last_name: str | None = None,
        user_username: str | None = None,
        user_is_bot: bool = False,
        user_phone: str | None = None,
        user_group_id: int | None = None,
        lifetime_seconds: int | None = None,
        allow_sender: bool = True,
        message_thread_id: int | None = None,
        **_kwargs: Any,
    ) -> dict[str, Any]:
        """
        Отправка сообщения в Telegram с сохранением в БД и поддержкой времени жизни.

        Использует унифицированный сервис сообщений, который автоматически выбирает
        оптимальный клиент (Aiogram или Telethon) для отправки.

        Args:
            chat_id: ID чата в Telegram
            text: Текст сообщения
            message_type: Тип сообщения (для категоризации в БД)
            delete_message_id: ID сообщения для удаления перед отправкой
            delete_by_type: Тип удаления для очистки старых сообщений
            exclude_message_types: Типы сообщений для исключения при очистке
            parse_mode: Режим парсинга (HTML, Markdown, MarkdownV2)
            disable_web_page_preview: Отключить предпросмотр ссылок
            disable_notification: Отключить уведомление
            protect_content: Защитить содержимое от пересылки
            reply_to_message_id: ID сообщения, на которое отвечаем
            reply_markup: Клавиатура для сообщения
            user_id: ID пользователя (для сохранения в БД)
            user_first_name: Имя пользователя
            user_last_name: Фамилия пользователя
            user_username: Username пользователя
            user_is_bot: Является ли пользователь ботом
            user_phone: Телефон пользователя
            user_group_id: ID группы пользователя
            lifetime_seconds: Время жизни сообщения в секундах
            allow_sender: Разрешить отправку через Telethon
            message_thread_id: ID топика для отправки

        Returns:
            dict[str, Any]: Результат отправки с полями success, message_id, chat_id, client, error
        """
        return await self._message_service.send_message(  # type: ignore[no-any-return]
            chat_id=chat_id,
            text=text,
            message_type=message_type,
            delete_message_id=delete_message_id,
            delete_by_type=delete_by_type,
            exclude_message_types=exclude_message_types,
            parse_mode=parse_mode,
            disable_web_page_preview=disable_web_page_preview,
            disable_notification=disable_notification,
            protect_content=protect_content,
            reply_to_message_id=reply_to_message_id,
            reply_markup=reply_markup,
            user_id=user_id,
            user_first_name=user_first_name,
            user_last_name=user_last_name,
            user_username=user_username,
            user_is_bot=user_is_bot,
            user_phone=user_phone,
            user_group_id=user_group_id,
            lifetime_seconds=lifetime_seconds,
            allow_sender=allow_sender,
            message_thread_id=message_thread_id,
        )

    @ensure_initialized
    async def send_answer(
        self,
        event: Message | CallbackQuery,
        text: str,
        message_type: MessageType | None = None,
        delete_by_type: str | None = None,
        exclude_message_types: list[MessageType] | None = None,
        parse_mode: str | None = None,
        reply_markup: Any = None,
        show_alert: bool = False,
        lifetime_seconds: int | None = None,
        delete_original: bool = True,
        message_thread_id: int | None = None,
        **kwargs: Any,
    ) -> dict[str, Any]:
        """
        Ответ на событие (сообщение или callback).

        Универсальный метод для ответа на любые события от пользователя.
        Автоматически определяет тип события и выбирает правильный способ отправки.

        Args:
            event: Событие (Message или CallbackQuery)
            text: Текст ответа
            message_type: Тип сообщения
            delete_by_type: Тип удаления для очистки
            exclude_message_types: Типы для исключения
            parse_mode: Режим парсинга
            reply_markup: Клавиатура
            show_alert: Показывать alert для callback
            lifetime_seconds: Время жизни сообщения
            delete_original: Удалять оригинальное сообщение
            message_thread_id: ID топика
            **kwargs: Дополнительные параметры

        Returns:
            dict[str, Any]: Результат отправки
        """
        return await self._message_service.send_answer(  # type: ignore[no-any-return]
            event=event,
            text=text,
            message_type=message_type,
            delete_by_type=delete_by_type,
            exclude_message_types=exclude_message_types,
            parse_mode=parse_mode,
            reply_markup=reply_markup,
            show_alert=show_alert,
            lifetime_seconds=lifetime_seconds,
            delete_original=delete_original,
            message_thread_id=message_thread_id,
            **kwargs,
        )

    @ensure_initialized
    async def send_photo(
        self,
        *,
        chat_id: int,
        photo: bytes | str | Any,
        message_type: MessageType | None = None,
        caption: str | None = None,
        parse_mode: str | None = None,
        filename: str | None = None,
        reply_markup: Any = None,
        lifetime_seconds: int | None = None,
        message_thread_id: int | None = None,
        **kwargs: Any,
    ) -> dict[str, Any]:
        """
        Отправка фото с сохранением в БД.

        Args:
            chat_id: ID чата
            photo: Фото (bytes, путь или InputFile)
            message_type: Тип сообщения
            caption: Подпись к фото
            parse_mode: Режим парсинга
            filename: Имя файла
            reply_markup: Клавиатура
            lifetime_seconds: Время жизни
            message_thread_id: ID топика
            **kwargs: Дополнительные параметры

        Returns:
            dict[str, Any]: Результат отправки
        """
        return await self._message_service.send_photo(  # type: ignore[no-any-return]
            chat_id=chat_id,
            photo=photo,
            message_type=message_type,
            caption=caption,
            parse_mode=parse_mode,
            filename=filename,
            reply_markup=reply_markup,
            lifetime_seconds=lifetime_seconds,
            message_thread_id=message_thread_id,
            **kwargs,
        )

    @ensure_initialized
    async def send_toast(
        self,
        event: Message | CallbackQuery | None = None,
        text: str = "⏳ Обработка...",
        show_alert: bool = False,
        duration: int = 1,
        chat_id: int | None = None,
        message_thread_id: int | None = None,
        **kwargs: Any,
    ) -> None:
        """
        Отправка toast-уведомления (временное сообщение).

        Поддерживает различные типы событий:
        - CallbackQuery: показывает toast через answer()
        - Message: отправляет временное сообщение и удаляет его через duration секунд
        - chat_id: отправляет сообщение с временем жизни

        Args:
            event: Событие (Message или CallbackQuery)
            text: Текст toast
            show_alert: Показывать alert для callback
            duration: Время жизни в секундах
            chat_id: ID чата (если нет event)
            message_thread_id: ID топика
            **kwargs: Дополнительные параметры
        """
        try:
            # Обработка CallbackQuery
            if isinstance(event, CallbackQuery):
                try:
                    await event.answer(text=text, show_alert=show_alert)
                    bot_logger.debug(f"✅ Toast sent to callback: {text[:50]}...")
                except Exception as e:
                    bot_logger.warning(f"⚠️ Failed to show toast for callback: {e}")
                return

            # Обработка Message
            if isinstance(event, Message):
                try:
                    sent_msg = await event.answer(text=text)
                    await asyncio.sleep(duration)
                    await sent_msg.delete()
                    bot_logger.debug(f"✅ Toast sent to message: {text[:50]}...")
                except Exception as e:
                    bot_logger.warning(f"⚠️ Failed to show toast for message: {e}")
                return

            # Отправка по chat_id
            if chat_id is not None:
                try:
                    result = await self.send_message(
                        chat_id=chat_id,
                        text=text,
                        message_type=MessageType.SYSTEM_STATUS,
                        parse_mode="Markdown",
                        lifetime_seconds=duration,
                        disable_notification=True,
                        message_thread_id=message_thread_id,
                        **kwargs,
                    )

                    if result.get("success"):
                        bot_logger.debug(f"✅ Toast sent to chat {chat_id}: {text[:50]}...")
                    else:
                        bot_logger.warning(f"⚠️ Failed to send toast to chat {chat_id}: {result.get('error')}")
                except Exception as e:
                    bot_logger.warning(f"⚠️ Failed to send toast to chat {chat_id}: {e}")
                return

            bot_logger.warning("⚠️ Cannot send toast: no event or chat_id provided")

        except Exception as e:
            bot_logger.warning(f"⚠️ Failed to send toast: {e}")

    @ensure_initialized
    async def edit_message(
        self,
        chat_id: int,
        message_id: int,
        text: str,
        parse_mode: str | None = None,
        reply_markup: Any = None,
        message_thread_id: int | None = None,
        **kwargs: Any,
    ) -> dict[str, Any]:
        """
        Редактирование сообщения.

        Args:
            chat_id: ID чата
            message_id: ID сообщения
            text: Новый текст
            parse_mode: Режим парсинга
            reply_markup: Новая клавиатура
            message_thread_id: ID топика (не используется, т.к. сообщение уже в топике)
            **kwargs: Дополнительные параметры

        Returns:
            dict[str, Any]: Результат редактирования
        """
        return await self._message_service.edit_message(  # type: ignore[no-any-return]
            chat_id=chat_id,
            message_id=message_id,
            text=text,
            parse_mode=parse_mode,
            reply_markup=reply_markup,
            message_thread_id=message_thread_id,
            **kwargs,
        )

    @ensure_initialized
    async def edit_callback_message(
        self,
        callback: CallbackQuery,
        text: str,
        parse_mode: str | None = None,
        reply_markup: Any = None,
        message_thread_id: int | None = None,
        **kwargs: Any,
    ) -> dict[str, Any]:
        """
        Редактирование сообщения из callback.

        Args:
            callback: CallbackQuery
            text: Новый текст
            parse_mode: Режим парсинга
            reply_markup: Новая клавиатура
            message_thread_id: ID топика
            **kwargs: Дополнительные параметры

        Returns:
            dict[str, Any]: Результат редактирования
        """
        return await self._message_service.edit_callback_message(  # type: ignore[no-any-return]
            callback=callback,
            text=text,
            parse_mode=parse_mode,
            reply_markup=reply_markup,
            message_thread_id=message_thread_id,
            **kwargs,
        )

    @ensure_initialized
    async def delete_message_by_id(self, chat_id: int, message_id: int) -> dict[str, Any]:
        """
        Удаление сообщения с отметкой в БД.

        Args:
            chat_id: ID чата
            message_id: ID сообщения

        Returns:
            dict[str, Any]: Результат удаления
        """
        return await self._message_service.delete_message_by_id(chat_id, message_id)  # type: ignore[no-any-return]

    @ensure_initialized
    async def delete_messages_by_type(
        self, *, chat_id: int, message_types: list[MessageType] | None = None, deleted_by_type: str = "cleanup"
    ) -> None:
        """
        Очистка сообщений по типу.

        Args:
            chat_id: ID чата
            message_types: Типы сообщений для удаления
            deleted_by_type: Тип удаления
        """
        try:
            result = await self._message_service.delete_messages(
                chat_id=chat_id,
                message_types=message_types,
                delete_by_type=deleted_by_type,
            )

            if result.get("marked_deleted", 0) > 0:
                bot_logger.debug(
                    f"🧹 Cleaned {result['marked_deleted']} messages in chat {chat_id} by type {message_types}"
                )

        except Exception as e:
            bot_logger.error(f"❌ Failed to cleanup messages: {e}", exc_info=True)

    @ensure_initialized
    async def delete_message_by_link(self, message: Message) -> None:
        """
        Удаление сообщения с командой через message_service.

        Args:
            message: Сообщение для удаления
        """
        try:
            await self._message_service.delete_message_by_id(chat_id=message.chat.id, message_id=message.message_id)
            bot_logger.debug(f"🗑️ Deleted command message {message.message_id}")
        except Exception as e:
            bot_logger.debug(f"ℹ️ Could not delete command message: {e}")

    # ==================== РАССЫЛКА ====================

    @log_exceptions(bot_logger)
    @ensure_initialized
    async def broadcast_message(
        self,
        text: str,
        parse_mode: str = "HTML",
        disable_web_page_preview: bool = True,
        chat_types: list[str] | None = None,
        exclude_chat_ids: list[int] | None = None,
        only_active: bool = True,
        sender_user_id: int | None = None,
        sender_first_name: str | None = None,
        sender_username: str | None = None,
        progress_callback: Callable[[int, int], Awaitable[None]] | None = None,
        message_thread_id: int | None = None,
    ) -> dict[str, Any]:
        """
        Рассылка сообщения во все активные чаты.

        Отправляет сообщение во все чаты, где присутствует бот.
        Поддерживает фильтрацию по типам чатов и исключение отдельных чатов.

        Args:
            text: Текст сообщения
            parse_mode: Режим парсинга
            disable_web_page_preview: Отключить предпросмотр
            chat_types: Типы чатов для отправки
            exclude_chat_ids: ID чатов для исключения
            only_active: Только активные чаты
            sender_user_id: ID отправителя (для сохранения в БД)
            sender_first_name: Имя отправителя
            sender_username: Username отправителя
            progress_callback: Callback для прогресса
            message_thread_id: ID топика

        Returns:
            dict[str, Any]: Результат рассылки с количеством успешных/неудачных отправок
        """
        if not self._aiogram_client.bot:
            return {
                "success": False,
                "error": "Bot not initialized",
                "total": 0,
                "successful": 0,
                "failed": 0,
                "failed_chats": [],
            }

        try:
            async with db_manager.get_session() as session:
                chats = await self._chat_repo.get_chats(session, is_active=only_active)

                if chat_types:
                    chats = [c for c in chats if c.FType.value in chat_types]

                if exclude_chat_ids:
                    chats = [c for c in chats if c.FID not in exclude_chat_ids]

                total_chats = len(chats)

                if total_chats == 0:
                    return {
                        "success": True,
                        "total": 0,
                        "successful": 0,
                        "failed": 0,
                        "message": "No active chats found",
                        "failed_chats": [],
                    }

                bot_logger.info(f"📊 Broadcasting to {total_chats} chats")

                success_count = 0
                failed_chats: list[dict[str, Any]] = []

                for idx, chat in enumerate(chats, 1):
                    try:
                        result = await self.send_message(
                            chat_id=chat.FID,
                            text=text,
                            parse_mode=parse_mode,
                            disable_web_page_preview=disable_web_page_preview,
                            message_type=MessageType.BROADCAST_MESSAGE,
                            user_id=sender_user_id,
                            user_first_name=sender_first_name,
                            user_username=sender_username,
                            message_thread_id=message_thread_id,
                        )

                        if result.get("success"):
                            success_count += 1
                            bot_logger.debug(f"✅ Broadcast to chat {chat.FID} successful")
                        else:
                            error = result.get("error", "Unknown error")
                            bot_logger.warning(f"⚠️ Broadcast to chat {chat.FID} failed: {error}")
                            failed_chats.append(
                                {
                                    "chat_id": chat.FID,
                                    "title": chat.FTitle or f"Chat {chat.FID}",
                                    "error": error,
                                }
                            )

                        if progress_callback:
                            await progress_callback(idx, total_chats)

                        await asyncio.sleep(0.05)

                    except Exception as e:
                        bot_logger.error(f"❌ Broadcast to chat {chat.FID} failed: {e}")
                        failed_chats.append(
                            {
                                "chat_id": chat.FID,
                                "title": chat.FTitle or f"Chat {chat.FID}",
                                "error": str(e),
                            }
                        )

                bot_logger.info(f"✅ Broadcast completed: {success_count}/{total_chats} successful")

                return {
                    "success": True,
                    "total": total_chats,
                    "successful": success_count,
                    "failed": len(failed_chats),
                    "failed_chats": failed_chats[:10],
                }

        except Exception as e:
            bot_logger.error(f"❌ Broadcast failed: {e}", exc_info=True)
            return {
                "success": False,
                "error": str(e),
                "total": 0,
                "successful": 0,
                "failed": 0,
                "failed_chats": [],
            }

    # ==================== ЖИЗНЕННЫЙ ЦИКЛ ====================

    @log_exceptions(bot_logger)
    async def initialize(self) -> None:
        """
        Инициализация всех клиентов и сервисов.

        Выполняется один раз при первом запуске.
        Инициализирует Aiogram, Telethon и все сервисы.
        """
        if self._initialized:
            bot_logger.warning("⚠️ Telegram Manager already initialized")
            return

        bot_logger.debug("🚀 Telegram Manager initializing...")

        # Сохраняем главный event loop
        self._main_loop = self._get_main_loop()

        # Инициализация Aiogram клиента
        await self._aiogram_client.initialize()

        # Инициализация Telethon клиента (с учетом типа аккаунта)
        is_bot = settings.is_bot_account
        await self._telethon_client.initialize(is_bot=is_bot)

        # Инициализация всех сервисов
        await self._message_service.initialize()
        await self._bot_service.initialize()
        await self._chat_service.initialize()
        await self._user_service.initialize()
        await self._sync_service.initialize()

        self._initialized = True
        bot_logger.info(f"✅ Telegram Manager initialized (account_type={'bot' if is_bot else 'user'})")

    @log_exceptions(bot_logger)
    async def start(self) -> None:
        """
        Запуск всех клиентов и сервисов.

        Настраивает обработчики, запускает Aiogram и Telethon клиенты.
        """
        if self._is_running:
            bot_logger.warning("⚠️ Telegram Manager already running")
            return

        if not self._initialized:
            await self.initialize()

        bot_logger.debug("🚀 Telegram Manager starting...")
        self._is_running = True
        self._stop_event.clear()

        # Настройка Aiogram (команды, middleware, обработчики)
        dp = await self._setup_aiogram()

        # Настройка Telethon (обработчики событий)
        await self._setup_telethon()

        # Запуск фоновых задач
        self._tasks = [
            asyncio.create_task(self._run_aiogram(dp), name="aiogram_bot"),
            asyncio.create_task(self._run_telethon(), name="telethon_client"),
        ]

        bot_logger.info("✅ Telegram Manager started successfully")

        # Ожидание завершения задач или сигнала остановки
        await self._wait_for_completion()

    @log_exceptions(bot_logger)
    async def stop(self) -> None:
        """
        Остановка всех клиентов и сервисов.

        Корректно завершает все задачи и закрывает клиенты.
        """
        if not self._is_running:
            bot_logger.warning("⚠️ Telegram Manager not running")
            return

        bot_logger.debug("🚀 Telegram Manager stopping...")
        self._is_running = False
        self._stop_event.set()

        # Отмена всех фоновых задач
        for task in self._tasks:
            if not task.done():
                task.cancel()

        if self._tasks:
            with contextlib.suppress(asyncio.CancelledError):
                await asyncio.gather(*self._tasks, return_exceptions=True)
            self._tasks.clear()

        # Остановка Aiogram клиента
        try:
            await self._aiogram_client.stop()
        except Exception as e:
            bot_logger.error(f"❌ Error stopping aiogram: {e}")

        # Остановка Telethon клиента
        try:
            await self._telethon_client.stop()
        except Exception as e:
            bot_logger.error(f"❌ Error stopping telethon: {e}")

        bot_logger.info("⛔ Telegram Manager stopped")

    @log_exceptions(bot_logger)
    async def restart(self) -> None:
        """
        Перезапуск менеджера.

        Выполняет остановку и повторный запуск всех компонентов.
        """
        bot_logger.info("🔄 Telegram Manager restarting...")
        await self.stop()
        await asyncio.sleep(1)
        await self.start()
        bot_logger.info("✅ Telegram Manager restarted")

    def _get_main_loop(self) -> asyncio.AbstractEventLoop:
        """
        Получение главного event loop.

        Returns:
            asyncio.AbstractEventLoop: Главный event loop
        """
        if self._main_loop is not None and not self._main_loop.is_closed():
            return self._main_loop

        try:
            loop = asyncio.get_running_loop()
            self._main_loop = loop
            return loop
        except RuntimeError:
            loop = asyncio.get_event_loop()
            self._main_loop = loop
            return loop

    # ==================== НАСТРОЙКА AIOGRAM ====================

    async def _setup_aiogram(self) -> Dispatcher:
        """
        Настройка Aiogram бота.

        Создает и настраивает Dispatcher с middleware и обработчиками.

        Returns:
            Dispatcher: Настроенный диспетчер Aiogram
        """
        # Настройка динамических команд
        await self._setup_dynamic_commands()

        # Создание диспетчера
        dp = Dispatcher()

        # Добавление middleware
        dp.update.middleware(LoggingMiddleware())
        dp.update.middleware(ChatActivityMiddleware(db_manager))
        dp.update.middleware(DatabaseMiddleware())
        dp.update.middleware(ErrorHandlerMiddleware())

        # Middleware для динамических команд
        from ..middlewares.bot.commands import DynamicCommandsMiddleware

        dp.update.middleware(DynamicCommandsMiddleware())

        # Middleware для авторизации
        from app.bot.handlers.aiogram.auth import auth_middleware

        dp.update.middleware(auth_middleware)

        # Middleware для rate limiting
        dp.update.middleware(
            RateLimitMiddleware(
                limit=getattr(settings, "BOT_RATE_LIMIT", 10),
                period=60,
                command_limit=getattr(settings, "BOT_COMMAND_LIMIT", 5),
                command_period=10,
                whitelist=getattr(settings, "ADMIN_IDS", []),
            )
        )

        # Middleware для throttling (анти-флуд)
        dp.update.middleware(ThrottlingMiddleware(default_throttle=0.5))

        # Подключение обработчиков
        router = setup_aiogram_handlers()
        dp.include_router(router)

        # Регистрация колбэков запуска и остановки
        dp.startup.register(partial(self._on_aiogram_startup))
        dp.shutdown.register(self._on_aiogram_shutdown)

        return dp

    async def _setup_telethon(self) -> None:
        """Настройка Telethon обработчиков."""
        client = self._telethon_client.client
        if client:
            setup_telethon_handlers(client)
            bot_logger.debug("✅ Telethon handlers configured")
        else:
            bot_logger.warning("⚠️ Telethon client not available, skipping handlers setup")

    # ==================== ЗАПУСК КЛИЕНТОВ ====================

    async def _run_aiogram(self, dp: Dispatcher) -> None:
        """
        Запуск Aiogram бота с автоматическим переподключением.

        Args:
            dp: Диспетчер Aiogram
        """
        max_retries = getattr(settings, "TELEGRAM_MAX_RETRIES", 5)
        retry_delay = getattr(settings, "TELEGRAM_RETRY_DELAY", 5)
        retry_count = 0

        while self._is_running:
            try:
                bot_logger.debug("🔄 Aiogram starting polling...")
                bot = self._aiogram_client.bot
                if not bot:
                    bot_logger.error("❌ Bot is None, cannot start polling")
                    return

                await dp.start_polling(
                    bot,
                    allowed_updates=["message", "callback_query", "chat_member", "my_chat_member"],
                    skip_updates=True,
                    polling_timeout=30,
                )
                bot_logger.debug("⏹️ Aiogram polling finished")
                break

            except asyncio.CancelledError:
                bot_logger.warning("⛔ Aiogram cancelled")
                raise

            except (TelegramNetworkError, TelegramAPIError) as err:
                retry_count += 1
                bot_logger.error(f"❌ Aiogram error (attempt {retry_count}/{max_retries}): {err}")

                if retry_count >= max_retries:
                    bot_logger.error("❌ Aiogram max retries reached")
                    raise

                bot_logger.info(f"🔄 Aiogram reconnecting in {retry_delay}s...")
                await asyncio.sleep(retry_delay)
                retry_delay = min(retry_delay * 2, 60)

            except Exception as e:
                error_str = str(e)
                if "ServerDisconnectedError" in error_str or "Server disconnected" in error_str:
                    bot_logger.warning("⚠️ Server disconnected, retrying...")
                    await asyncio.sleep(2)
                    continue
                bot_logger.error(f"❌ Aiogram unexpected error: {e}", exc_info=True)
                await asyncio.sleep(10)

    async def _run_telethon(self) -> None:
        """Запуск Telethon клиента с поддержкой heartbeat."""
        try:
            await self._telethon_client.start()

            heartbeat_counter = 0
            while self._is_running:
                try:
                    if not await self._telethon_client.is_connected():
                        bot_logger.warning("⚠️ Telethon client disconnected, reconnecting...")
                        await self._telethon_client.start()
                        continue

                    await asyncio.sleep(30)
                    heartbeat_counter += 1

                    if heartbeat_counter % 10 == 0:
                        bot_logger.debug(f"🔄 Telethon heartbeat #{heartbeat_counter}")

                        status = await self._sync_service.get_status()
                        if status.get("client_available"):
                            bot_logger.debug(f"✅ Telethon sync status: {status}")

                except asyncio.CancelledError:
                    bot_logger.warning("⛔ Telethon cancelled")
                    raise
                except Exception as e:
                    bot_logger.error(f"❌ Telethon heartbeat error: {e}")
                    await asyncio.sleep(10)

        except asyncio.CancelledError:
            bot_logger.debug("ℹ️ Telethon task cancelled")
            raise
        except Exception as e:
            bot_logger.error(f"❌ Telethon error: {e}", exc_info=True)
            raise

    async def _wait_for_completion(self) -> None:
        """
        Ожидание завершения задач или сигнала остановки.

        Обрабатывает завершение фоновых задач и корректно отменяет их при остановке.
        """
        try:
            stop_task = asyncio.create_task(self._stop_event.wait())

            done, pending = await asyncio.wait(self._tasks + [stop_task], return_when=asyncio.FIRST_COMPLETED)

            for task in done:
                if task in self._tasks:
                    task_name = task.get_name()

                    if task.cancelled():
                        bot_logger.debug(f"ℹ️ Task cancelled: {task_name}")
                    elif task.exception():
                        try:
                            await task
                        except Exception as e:
                            bot_logger.error(f"❌ Task failed ({task_name}): {e}", exc_info=True)
                    else:
                        bot_logger.info(f"✅ Task completed: {task_name}")

            for task in pending:
                if task != stop_task and not task.done():
                    bot_logger.info(f"⛔ Cancelling task: {task.get_name()}")
                    task.cancel()

            if pending:
                await asyncio.gather(*pending, return_exceptions=True)

        except asyncio.CancelledError:
            bot_logger.warning("⛔ Wait for completion cancelled")
            raise

    # ==================== КОЛБЭКИ ====================

    async def _on_aiogram_startup(self, bot: Bot) -> None:
        """
        Обработчик запуска Aiogram.

        Отправляет уведомление администраторам о запуске бота.

        Args:
            bot: Экземпляр Aiogram Bot
        """
        bot_logger.info("✅ Aiogram bot started")

        # Очистка старых сообщений при запуске
        await self._message_service.delete_messages(
            exclude_message_types=[MessageType.USER_REQUEST],
            delete_by_type="startup_cleanup",
        )

        if not settings.ADMIN_IDS:
            bot_logger.debug("ℹ️ No ADMIN_IDS configured, skipping startup notification")
            return

        # Отправка уведомления администраторам
        for admin_id in settings.ADMIN_IDS:
            try:
                text = "🤖 Бот запущен и готов к работе!"

                try:
                    admin_info = await bot.get_chat(admin_id)
                    admin_name = admin_info.first_name
                    admin_username = admin_info.username
                except Exception:
                    admin_name = None
                    admin_username = None

                result = await self._message_service.send_message(
                    chat_id=admin_id,
                    text=text,
                    message_type=MessageType.SYSTEM_STATUS,
                    exclude_message_types=[MessageType.USER_REQUEST],
                    parse_mode="HTML",
                    user_id=admin_id,
                    user_first_name=admin_name,
                    user_username=admin_username,
                )

                if result.get("success"):
                    bot_logger.info(
                        f"✅ Startup message sent to admin {admin_id} (message_id={result.get('message_id')})"
                    )
                else:
                    bot_logger.warning(f"⚠️ Failed to send startup message to admin {admin_id}: {result.get('error')}")
            except Exception as e:
                bot_logger.warning(f"⚠️ Failed to notify admin {admin_id}: {e}")

    @staticmethod
    async def _on_aiogram_shutdown() -> None:
        """Обработчик остановки Aiogram."""
        bot_logger.info("⛔ Aiogram bot shutting down")

    # ==================== РАБОТА С КОМАНДАМИ ====================

    @staticmethod
    def get_public_commands() -> list[dict[str, str]]:
        """
        Базовые команды (доступны без авторизации).

        Returns:
            list[dict[str, str]]: Список публичных команд
        """
        return [
            {"command": "/start", "description": "🚀 Начало работы / Авторизация"},
            {"command": "/help", "description": "❓ Помощь"},
            {"command": "/debug_commands", "description": "🔍 Отладка команд"},
        ]

    @staticmethod
    def get_auth_commands() -> list[dict[str, str]]:
        """
        Команды, требующие авторизации (видны всем авторизованным пользователям).

        Returns:
            list[dict[str, str]]: Список команд для авторизованных пользователей
        """
        return [
            {"command": "/actions", "description": "📋 Меню действий"},
            {"command": "/automation", "description": "🤖 Меню автоматизации"},
            {"command": "/stats", "description": "📊 Статистика"},
            {"command": "/id", "description": "🆔 Мой ID"},
            {"command": "/logout", "description": "🚪 Выйти из системы"},
        ]

    @staticmethod
    def get_admin_commands() -> list[dict[str, str]]:
        """
        Административные команды (видны только администраторам).

        Returns:
            list[dict[str, str]]: Список административных команд
        """
        return [
            {"command": "/users", "description": "👥 Пользователи (админ)"},
            {"command": "/broadcast", "description": "📢 Рассылка (админ)"},
            {"command": "/delete", "description": "🗑️ Удалить сообщение (админ)"},
            {"command": "/sync", "description": "🔄 Меню синхронизации (админ)"},
            {"command": "/sync_chats", "description": "💬 Синхр. чатов (админ)"},
            {"command": "/sync_base", "description": "📚 Синхр. справочников (админ)"},
            {"command": "/sync_contacts", "description": "📇 Синхр. контактов (админ)"},
            {"command": "/sync_user", "description": "👤 Синхр. пользователя (админ)"},
            {"command": "/sync_all_users", "description": "👥 Синхр. всех пользователей (админ)"},
            {"command": "/sync_all_vehicles", "description": "🚗 Синхр. пользователей ТС (админ)"},
            {"command": "/sync_light", "description": "⚡ Стандартная синхр. (админ)"},
            {"command": "/sync_force", "description": "💪 Полная синхр. Force (админ)"},
            {"command": "/admins", "description": "👑 Список админов (админ)"},
            {"command": "/add_admin", "description": "➕ Добавить админа (админ)"},
            {"command": "/remove_admin", "description": "➖Удалить админа (админ)"},
        ]

    def _get_commands_for_user(self, user_id: int, is_admin: bool = False) -> list[dict[str, str]]:
        """
        Получение списка команд для пользователя.

        Args:
            user_id: ID пользователя
            is_admin: Является ли пользователь администратором

        Returns:
            list[dict[str, str]]: Список команд для пользователя
        """
        commands = self.get_public_commands().copy()

        is_authorized = self.is_user_in_cache(user_id)

        if is_authorized:
            commands.extend(self.get_auth_commands())

        if is_admin:
            commands.extend(self.get_admin_commands())

        return commands

    async def update_user_commands(self, user_id: int, is_admin: bool = False) -> None:
        """
        Обновление команд для конкретного пользователя.

        Args:
            user_id: ID пользователя
            is_admin: Является ли пользователь администратором
        """
        try:
            if not self._aiogram_client.bot:
                return

            commands = self._get_commands_for_user(user_id, is_admin)

            # Сохранение в кеш
            self._user_commands_cache[user_id] = commands

            # Установка команд через сервис бота
            success = await self._bot_service.set_commands(commands)
            if success:
                bot_logger.debug(f"✅ Commands updated for user {user_id}: {len(commands)} commands")

        except Exception as e:
            bot_logger.warning(f"⚠️ Failed to update commands for user {user_id}: {e}")

    async def reset_user_commands(self, user_id: int) -> None:
        """
        Сброс команд пользователя до базовых.

        Args:
            user_id: ID пользователя
        """
        try:
            if not self._aiogram_client.bot:
                return

            # Удаление из кеша
            self._user_commands_cache.pop(user_id, None)

            # Установка публичных команд
            commands = self.get_public_commands()
            await self._bot_service.set_commands(commands)

            bot_logger.debug(f"✅ Commands reset for user {user_id}")

        except Exception as e:
            bot_logger.warning(f"⚠️ Failed to reset commands for user {user_id}: {e}")

    async def _setup_dynamic_commands(self) -> None:
        """
        Динамическая установка команд бота.

        Устанавливает публичные команды для всех пользователей
        и персональные команды для авторизованных пользователей и администраторов.
        """
        try:
            if not self._aiogram_client.bot:
                return

            # Установка публичных команд (для всех)
            public_commands = self.get_public_commands()
            await self._bot_service.set_commands(public_commands)

            # Установка команд для администраторов
            for admin_id in getattr(settings, "ADMIN_IDS", []):
                try:
                    await self.update_user_commands(admin_id, is_admin=True)
                except Exception as e:
                    bot_logger.warning(f"⚠️ Failed to set commands for admin {admin_id}: {e}")

            # Установка команд для авторизованных пользователей
            async with db_manager.get_session() as session:
                authorized_users = await self._user_repo.get_authorized_users(session)
                for user in authorized_users:
                    try:
                        is_admin = user.FID in getattr(settings, "ADMIN_IDS", [])
                        await self.update_user_commands(user.FID, is_admin)
                    except Exception as e:
                        bot_logger.warning(f"⚠️ Failed to set commands for user {user.FID}: {e}")

            bot_logger.info("✅ Dynamic commands configured")

        except Exception as e:
            bot_logger.error(f"❌ Failed to setup dynamic commands: {e}", exc_info=True)

    # ==================== РАБОТА С КЕШЕМ КОМАНД ====================

    def is_user_in_cache(self, user_id: int) -> bool:
        """
        Проверка, есть ли пользователь в кеше команд.

        Args:
            user_id: ID пользователя

        Returns:
            bool: True если пользователь есть в кеше
        """
        return user_id in self._user_commands_cache

    @ensure_initialized
    async def is_user_authorized(self, user_id: int) -> bool:
        """
        Публичный метод для проверки авторизации пользователя.

        Args:
            user_id: ID пользователя

        Returns:
            bool: True если пользователь авторизован
        """
        return await self._is_user_authorized(user_id)

    def get_user_commands(self, user_id: int) -> list[dict[str, str]] | None:
        """
        Получение кешированных команд пользователя.

        Args:
            user_id: ID пользователя

        Returns:
            list[dict[str, str]] | None: Список команд или None
        """
        return self._user_commands_cache.get(user_id)

    def clear_user_cache(self, user_id: int) -> None:
        """
        Очистка кеша команд для пользователя.

        Args:
            user_id: ID пользователя
        """
        self._user_commands_cache.pop(user_id, None)
        bot_logger.debug(f"🧹 Cache cleared for user {user_id}")

    def get_cache_stats(self) -> dict[str, Any]:
        """
        Получение статистики кеша команд.

        Returns:
            dict[str, Any]: Статистика кеша
        """
        return {
            "total_users": len(self._user_commands_cache),
            "user_ids": list(self._user_commands_cache.keys()),
        }

    @staticmethod
    async def _is_user_authorized(user_id: int) -> bool:
        """
        Внутренний метод для проверки авторизации пользователя.

        Args:
            user_id: ID пользователя

        Returns:
            bool: True если пользователь авторизован
        """
        try:
            async with db_manager.get_session() as session:
                return await UserRepository.is_user_authenticated(session, user_id)  # type: ignore[no-any-return]
        except Exception as e:
            bot_logger.debug(f"⚠️ Failed to check user authorization: {e}")
            return False

    # ==================== РАБОТА С БОТОМ ====================

    @ensure_initialized
    async def get_bot_info(self) -> dict[str, Any]:
        """
        Получение информации о боте через AiogramBotService.

        Returns:
            dict[str, Any]: Информация о боте
        """
        return await self._bot_service.get_me()  # type: ignore[no-any-return]

    async def is_bot_in_chat(self, chat_id: int) -> bool:
        """
        Проверка, находится ли бот в чате.

        Args:
            chat_id: ID чата

        Returns:
            bool: True если бот находится в чате
        """
        try:
            if not self._aiogram_client or not self._aiogram_client.bot:
                return False

            bot_info = await self._bot_service.get_me()
            if not bot_info:
                return False

            bot_id = bot_info.get("id")
            if not bot_id:
                return False

            member_info = await self._bot_service.get_chat_member(chat_id, bot_id)
            status_str = member_info.get("status", "unknown")

            is_in_chat = status_str not in ["left", "kicked"]

            if is_in_chat:
                bot_logger.debug(f"✅ Bot is in chat {chat_id} (status: {status_str})")
            else:
                bot_logger.debug(f"⏭️ Bot not in chat {chat_id} (status: {status_str})")

            return is_in_chat

        except Exception as e:
            error_str = str(e).lower()
            if "bot is not a member" in error_str or "user not found" in error_str:
                bot_logger.debug(f"⏭️ Bot not in chat {chat_id}")
            else:
                bot_logger.debug(f"⚠️ Error checking bot in chat {chat_id}: {e}")
            return False

    # ==================== СИНХРОНИЗАЦИЯ ====================

    @log_exceptions(bot_logger)
    @ensure_initialized
    async def sync_chat(self, chat_id: int, session: AsyncSession | None = None, force: bool = False) -> dict[str, Any]:
        """
        Синхронизация чата.

        Args:
            chat_id: ID чата
            session: Сессия БД (опционально)
            force: Принудительная синхронизация

        Returns:
            dict[str, Any]: Результат синхронизации
        """
        if session is None:
            async with db_manager.get_session() as sess:
                return await self._sync_service.sync_chat_members(chat_id=chat_id, session=sess, force=force)  # type: ignore[no-any-return]

        return await self._sync_service.sync_chat_members(chat_id=chat_id, session=session, force=force)  # type: ignore[no-any-return]

    @log_exceptions(bot_logger)
    @ensure_initialized
    async def sync_all_chats(
        self, force: bool = False, max_chats: int | None = None, chat_types: list[str] | None = None
    ) -> dict[str, Any]:
        """
        Синхронизация всех чатов.

        Args:
            force: Принудительная синхронизация
            max_chats: Максимальное количество чатов
            chat_types: Типы чатов для синхронизации

        Returns:
            dict[str, Any]: Результат синхронизации
        """
        async with db_manager.get_session() as session:
            return await self._sync_service.sync_all_chats(  # type: ignore[no-any-return]
                session=session, force=force, max_chats=max_chats, chat_types=chat_types
            )

    @ensure_initialized
    async def clear_sync_cache(self, chat_id: int | None = None) -> None:
        """
        Очистка кеша синхронизации.

        Args:
            chat_id: ID чата (если None - очистка всего кеша)
        """
        await self._sync_service.clear_cache(chat_id)

    @ensure_initialized
    async def reset_sync_metrics(self) -> None:
        """Сброс метрик синхронизации."""
        await self._sync_service.reset_metrics()

    # ==================== СТАТУС И ЗДОРОВЬЕ ====================

    @log_exceptions(bot_logger)
    async def get_status(self) -> dict[str, Any]:
        """
        Получение статуса менеджера.

        Returns:
            dict[str, Any]: Полный статус всех компонентов
        """
        if not self._is_running and not self._initialized:
            return {
                "is_running": self._is_running,
                "is_initialized": self._initialized,
                "account_type": settings.TELEGRAM_ACCOUNT_TYPE,
                "tasks_count": len(self._tasks),
                "aiogram": {"initialized": False, "is_running": False},
                "telethon": {"initialized": False, "is_running": False},
                "sync": {"initialized": False},
                "services": {},
            }

        try:
            aiogram_status = await asyncio.shield(self._aiogram_client.get_status())
        except asyncio.CancelledError:
            bot_logger.debug("get_status cancelled")
            return {
                "is_running": self._is_running,
                "is_initialized": self._initialized,
                "account_type": settings.TELEGRAM_ACCOUNT_TYPE,
                "tasks_count": len(self._tasks),
                "aiogram": {"initialized": False, "is_running": False},
                "telethon": {"initialized": False, "is_running": False},
                "sync": {"initialized": False},
                "services": {},
            }
        except Exception as e:
            bot_logger.error(f"Failed to get aiogram status: {e}")
            aiogram_status = {"error": str(e)}

        try:
            telethon_status = await asyncio.shield(self._telethon_client.get_status())
        except asyncio.CancelledError:
            bot_logger.debug("get_status cancelled")
            telethon_status = {"initialized": False, "is_running": False}
        except Exception as e:
            bot_logger.error(f"Failed to get telethon status: {e}")
            telethon_status = {"error": str(e)}

        try:
            sync_status = await asyncio.shield(self._sync_service.get_status())
        except asyncio.CancelledError:
            bot_logger.debug("get_status cancelled")
            sync_status = {"initialized": False}
        except Exception as e:
            bot_logger.error(f"Failed to get sync status: {e}")
            sync_status = {"error": str(e)}

        return {
            "is_running": self._is_running,
            "is_initialized": self._initialized,
            "account_type": settings.TELEGRAM_ACCOUNT_TYPE,
            "tasks_count": len(self._tasks),
            "aiogram": aiogram_status,
            "telethon": telethon_status,
            "sync": sync_status,
            "services": {
                "message": await self._message_service.get_status(),
                "bot": await self._bot_service.get_status(),
                "chat": await self._chat_service.get_status(),
                "user": await self._user_service.get_status(),
            },
            "cache": self.get_cache_stats(),
        }

    @log_exceptions(bot_logger)
    async def health_check(self) -> dict[str, bool]:
        """
        Проверка здоровья всех компонентов.

        Returns:
            dict[str, bool]: Результаты проверки здоровья
        """
        return {
            "manager_initialized": self._initialized,
            "manager_running": self._is_running,
            "aiogram": await self._aiogram_client.is_connected(),
            "telethon": await self._telethon_client.is_connected(),
            "message_service": await self._message_service.health_check(),
            "bot_service": await self._bot_service.health_check(),
            "chat_service": await self._chat_service.health_check(),
            "user_service": await self._user_service.health_check(),
            "sync_service": await self._sync_service.health_check(),
        }

    # ==================== MAGIC METHODS ====================

    def __repr__(self) -> str:
        """
        Строковое представление для отладки.

        Returns:
            str: Строковое представление менеджера
        """
        status = "running" if self._is_running else "stopped"
        initialized = "✓" if self._initialized else "✗"
        return (
            f"<TelegramManager "
            f"status={status} "
            f"initialized={initialized} "
            f"account_type={settings.TELEGRAM_ACCOUNT_TYPE} "
            f"tasks={len(self._tasks)}>"
        )


# ==================== ГЛОБАЛЬНЫЙ ЭКЗЕМПЛЯР ====================

bot_manager = BotManager()

# ==================== ФУНКЦИИ-ОБЕРТКИ ====================


def get_public_commands() -> list[dict[str, str]]:
    """
    Получение публичных команд (функция-обертка).

    Returns:
        list[dict[str, str]]: Список публичных команд
    """
    return BotManager.get_public_commands()


def get_auth_commands() -> list[dict[str, str]]:
    """
    Получение команд для авторизованных пользователей (функция-обертка).

    Returns:
        list[dict[str, str]]: Список команд для авторизованных пользователей
    """
    return BotManager.get_auth_commands()


def get_admin_commands() -> list[dict[str, str]]:
    """
    Получение административных команд (функция-обертка).

    Returns:
        list[dict[str, str]]: Список административных команд
    """
    return BotManager.get_admin_commands()


__all__ = [
    "bot_manager",
    "BotManager",
    # Публичные методы для работы с командами
    "get_public_commands",
    "get_auth_commands",
    "get_admin_commands",
]
