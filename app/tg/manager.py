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
from ..db import ChatRepository, UserRepository, db_manager
from ..exceptions import log_exceptions
from ..logger import tg_logger
from ..middlewares.tg.database import DatabaseMiddleware
from ..middlewares.tg.error_handler import ErrorHandlerMiddleware
from ..middlewares.tg.logging import ChatActivityMiddleware, LoggingMiddleware
from ..middlewares.tg.rate_limit import RateLimitMiddleware
from ..middlewares.tg.throttling import ThrottlingMiddleware
from ..models import MessageType
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


def ensure_initialized(func: Callable[..., Awaitable[R]]) -> Callable[..., Awaitable[R]]:
    """Декоратор для автоматической инициализации менеджера"""

    @wraps(func)
    async def wrapper(self: Any, *args: Any, **kwargs: Any) -> R:
        if not self._initialized:
            await self.initialize()
        return await func(self, *args, **kwargs)

    return cast("Callable[..., Awaitable[R]]", wrapper)


class TelegramManager:
    """Главный менеджер для управления Telegram клиентами и сервисами"""

    # ==================== ИНИЦИАЛИЗАЦИЯ ====================

    def __init__(self) -> None:
        # === Клиенты ===
        self._aiogram_client: AiogramClient = AiogramClient()
        self._telethon_client: TelethonClient = TelethonClient()

        # === Сервис сообщений ===
        self._message_service: UnifiedMessageService = UnifiedMessageService(
            self._aiogram_client, self._telethon_client
        )

        # === Сервисы Aiogram ===
        self._bot_service: AiogramBotService = AiogramBotService(self._aiogram_client)

        # === Сервисы Telethon ===
        self._chat_service: TelethonChatService = TelethonChatService(self._telethon_client)
        self._user_service: TelethonUserService = TelethonUserService(self._telethon_client)

        # === Сервис синхронизации ===
        self._sync_service: SyncService = SyncService(self._telethon_client)

        # === Состояние ===
        self._initialized: bool = False
        self._is_running: bool = False
        self._tasks: list[asyncio.Task] = []
        self._stop_event: asyncio.Event = asyncio.Event()
        self._main_loop: asyncio.AbstractEventLoop | None = None

        # Кеш команд для пользователей
        self._user_commands_cache: dict[int, list[dict[str, str]]] = {}

        tg_logger.debug(f"✅ Telegram Manager instance created (account_type={settings.TELEGRAM_ACCOUNT_TYPE})")

    # ==================== ПУБЛИЧНЫЕ СВОЙСТВА ====================

    @property
    def aiogram_client(self) -> AiogramClient:
        """Получение Aiogram клиента"""
        return self._aiogram_client

    @property
    def telethon_client(self) -> TelethonClient:
        """Получение Telethon клиента"""
        return self._telethon_client

    @property
    def message_service(self) -> UnifiedMessageService:
        """Получение сервиса сообщений"""
        return self._message_service

    @property
    def bot_service(self) -> AiogramBotService:
        """Получение сервиса бота"""
        return self._bot_service

    @property
    def chat_service(self) -> TelethonChatService:
        """Получение сервиса чатов"""
        return self._chat_service

    @property
    def user_service(self) -> TelethonUserService:
        """Получение сервиса пользователей"""
        return self._user_service

    @property
    def sync_service(self) -> SyncService:
        """Получение сервиса синхронизации"""
        return self._sync_service

    # ==================== СВОЙСТВА ДЛЯ ОБРАТНОЙ СОВМЕСТИМОСТИ ====================

    @property
    def _bot(self) -> Bot | None:
        """Получение Aiogram Bot (для обратной совместимости)"""
        return self._aiogram_client.bot

    @property
    def _client(self) -> TelegramClient | None:
        """Получение Telethon Client (для обратной совместимости)"""
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
        message_thread_id: int | None = None,  # <-- ДОБАВЛЕНО: поддержка топиков
        **_kwargs: Any,
    ) -> dict[str, Any]:
        """
        Отправка сообщения в Telegram с сохранением в БД и поддержкой времени жизни.

        Args:
            chat_id: ID чата
            text: Текст сообщения
            message_type: Тип сообщения
            delete_message_id: ID сообщения для удаления
            delete_by_type: Тип для очистки предыдущих сообщений
            exclude_message_types: Типы для исключения из очистки
            parse_mode: Режим парсинга (HTML, Markdown, MarkdownV2)
            disable_web_page_preview: Отключить предпросмотр ссылок
            disable_notification: Отключить уведомление
            protect_content: Защитить содержимое от пересылки
            reply_to_message_id: ID сообщения, на которое отвечаем
            reply_markup: Клавиатура
            user_id: ID пользователя
            user_first_name: Имя пользователя
            user_last_name: Фамилия пользователя
            user_username: Username пользователя
            user_is_bot: Является ли пользователь ботом
            user_phone: Телефон пользователя
            user_group_id: ID группы пользователя
            lifetime_seconds: Время жизни сообщения в секундах
            allow_sender: Разрешить отправку от имени пользователя
            message_thread_id: ID топика для отправки (для супергрупп)

        Returns:
            Dict[str, Any]: Результат отправки
        """
        return await self._message_service.send_message(
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

        Args:
            event: Объект Message или CallbackQuery
            text: Текст ответа
            message_type: Тип сообщения
            delete_by_type: Тип для очистки предыдущих сообщений
            exclude_message_types: Типы для исключения из очистки
            parse_mode: Режим парсинга
            reply_markup: Клавиатура
            show_alert: Показывать как всплывающее окно (только для callback)
            lifetime_seconds: Время жизни сообщения
            delete_original: Удалить исходное сообщение
            message_thread_id: ID топика для отправки
            **kwargs: Дополнительные параметры

        Returns:
            Dict[str, Any]: Результат отправки
        """
        return await self._message_service.send_answer(
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
        """Отправка фото с сохранением в БД"""
        return await self._message_service.send_photo(
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
        Метод для отправки toast-уведомлений.

        Работает с:
        - Message: отправляет временное сообщение и удаляет его через duration секунд
        - CallbackQuery: показывает всплывающее уведомление (toast)
        - Если event не передан, но указан chat_id - отправляет временное сообщение в чат

        Args:
            event: Объект Message или CallbackQuery (опционально)
            text: Текст уведомления
            show_alert: Показывать как всплывающее окно (только для CallbackQuery)
            duration: Время жизни сообщения в секундах (только для Message)
            chat_id: ID чата (используется, если event не передан)
            message_thread_id: ID топика для отправки
        """
        try:
            # Обработка CallbackQuery
            if isinstance(event, CallbackQuery):
                try:
                    await event.answer(text=text, show_alert=show_alert)
                    tg_logger.debug(f"✅ Toast sent to callback: {text[:50]}...")
                except Exception as e:
                    tg_logger.warning(f"⚠️ Failed to show toast for callback: {e}")
                return

            # Обработка Message
            if isinstance(event, Message):
                try:
                    sent_msg = await event.answer(text=text)
                    await asyncio.sleep(duration)
                    await sent_msg.delete()
                    tg_logger.debug(f"✅ Toast sent to message: {text[:50]}...")
                except Exception as e:
                    tg_logger.warning(f"⚠️ Failed to show toast for message: {e}")
                return

            # Отправка в чат без события
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
                        tg_logger.debug(f"✅ Toast sent to chat {chat_id}: {text[:50]}...")
                    else:
                        tg_logger.warning(f"⚠️ Failed to send toast to chat {chat_id}: {result.get('error')}")
                except Exception as e:
                    tg_logger.warning(f"⚠️ Failed to send toast to chat {chat_id}: {e}")
                return

            # Ничего не передано
            tg_logger.warning("⚠️ Cannot send toast: no event or chat_id provided")

        except Exception as e:
            tg_logger.warning(f"⚠️ Failed to send toast: {e}")

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
        """Редактирование сообщения"""
        return await self._message_service.edit_message(
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
        """Редактирование сообщения из callback"""
        return await self._message_service.edit_callback_message(
            callback=callback,
            text=text,
            parse_mode=parse_mode,
            reply_markup=reply_markup,
            message_thread_id=message_thread_id,
            **kwargs,
        )

    @ensure_initialized
    async def delete_message_by_id(self, chat_id: int, message_id: int) -> dict[str, Any]:
        """Удаление сообщения с отметкой в БД"""
        return await self._message_service.delete_message_by_id(chat_id, message_id)

    @ensure_initialized
    async def delete_messages_by_type(
        self, *, chat_id: int, message_types: list[MessageType] | None = None, deleted_by_type: str = "cleanup"
    ) -> None:
        """Очистка всех предыдущих сообщений"""
        try:
            result = await self._message_service.delete_messages(
                chat_id=chat_id,
                message_types=message_types,
                delete_by_type=deleted_by_type,
            )

            if result.get("marked_deleted", 0) > 0:
                tg_logger.debug(
                    f"🧹 Cleaned {result['marked_deleted']} messages in chat {chat_id} by type {message_types}"
                )

        except Exception as e:
            tg_logger.error(f"❌ Failed to cleanup messages: {e}", exc_info=True)

    @ensure_initialized
    async def delete_message_by_link(self, message: Message) -> None:
        """Удаление сообщения с командой через message_service"""
        try:
            await self._message_service.delete_message_by_id(chat_id=message.chat.id, message_id=message.message_id)
            tg_logger.debug(f"🗑️ Deleted command message {message.message_id}")
        except Exception as e:
            tg_logger.debug(f"ℹ️ Could not delete command message: {e}")

    # ==================== РАССЫЛКА ====================

    @log_exceptions(tg_logger)
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

        Args:
            text: Текст сообщения
            parse_mode: Режим парсинга
            disable_web_page_preview: Отключить предпросмотр ссылок
            chat_types: Типы чатов для рассылки
            exclude_chat_ids: ID чатов для исключения
            only_active: Только активные чаты
            sender_user_id: ID отправителя
            sender_first_name: Имя отправителя
            sender_username: Username отправителя
            progress_callback: Callback для прогресса
            message_thread_id: ID топика для отправки
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
                chats = await ChatRepository.get_chats(session, is_active=only_active)

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

                tg_logger.info(f"📊 Broadcasting to {total_chats} chats")

                success_count = 0
                failed_chats = []

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
                            tg_logger.debug(f"✅ Broadcast to chat {chat.FID} successful")
                        else:
                            error = result.get("error", "Unknown error")
                            tg_logger.warning(f"⚠️ Broadcast to chat {chat.FID} failed: {error}")
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
                        tg_logger.error(f"❌ Broadcast to chat {chat.FID} failed: {e}")
                        failed_chats.append(
                            {
                                "chat_id": chat.FID,
                                "title": chat.FTitle or f"Chat {chat.FID}",
                                "error": str(e),
                            }
                        )

                tg_logger.info(f"✅ Broadcast completed: {success_count}/{total_chats} successful")

                return {
                    "success": True,
                    "total": total_chats,
                    "successful": success_count,
                    "failed": len(failed_chats),
                    "failed_chats": failed_chats[:10],
                }

        except Exception as e:
            tg_logger.error(f"❌ Broadcast failed: {e}", exc_info=True)
            return {
                "success": False,
                "error": str(e),
                "total": 0,
                "successful": 0,
                "failed": 0,
                "failed_chats": [],
            }

    # ==================== ЖИЗНЕННЫЙ ЦИКЛ ====================

    @log_exceptions(tg_logger)
    async def initialize(self) -> None:
        """Инициализация всех клиентов и сервисов"""
        if self._initialized:
            tg_logger.warning("⚠️ Telegram Manager already initialized")
            return

        tg_logger.debug("🚀 Telegram Manager initializing...")

        self._main_loop = self._get_main_loop()

        await self._aiogram_client.initialize()

        is_bot = settings.is_bot_account
        await self._telethon_client.initialize(is_bot=is_bot)

        await self._message_service.initialize()
        await self._bot_service.initialize()
        await self._chat_service.initialize()
        await self._user_service.initialize()
        await self._sync_service.initialize()

        self._initialized = True
        tg_logger.info(f"✅ Telegram Manager initialized (account_type={'bot' if is_bot else 'user'})")

    @log_exceptions(tg_logger)
    async def start(self) -> None:
        """Запуск всех клиентов и сервисов"""
        if self._is_running:
            tg_logger.warning("⚠️ Telegram Manager already running")
            return

        if not self._initialized:
            await self.initialize()

        tg_logger.debug("🚀 Telegram Manager starting...")
        self._is_running = True
        self._stop_event.clear()

        dp = await self._setup_aiogram()
        await self._setup_telethon()

        self._tasks = [
            asyncio.create_task(self._run_aiogram(dp), name="aiogram_bot"),
            asyncio.create_task(self._run_telethon(), name="telethon_client"),
        ]

        tg_logger.info("✅ Telegram Manager started successfully")

        await self._wait_for_completion()

    @log_exceptions(tg_logger)
    async def stop(self) -> None:
        """Остановка всех клиентов и сервисов"""
        if not self._is_running:
            tg_logger.warning("⚠️ Telegram Manager not running")
            return

        tg_logger.debug("🚀 Telegram Manager stopping...")
        self._is_running = False
        self._stop_event.set()

        for task in self._tasks:
            if not task.done():
                task.cancel()

        if self._tasks:
            with contextlib.suppress(asyncio.CancelledError):
                await asyncio.gather(*self._tasks, return_exceptions=True)
            self._tasks.clear()

        try:
            await self._aiogram_client.stop()
        except Exception as e:
            tg_logger.error(f"❌ Error stopping aiogram: {e}")

        try:
            await self._telethon_client.stop()
        except Exception as e:
            tg_logger.error(f"❌ Error stopping telethon: {e}")

        tg_logger.info("⛔ Telegram Manager stopped")

    @log_exceptions(tg_logger)
    async def restart(self) -> None:
        """Перезапуск менеджера"""
        tg_logger.info("🔄 Telegram Manager restarting...")
        await self.stop()
        await asyncio.sleep(1)
        await self.start()
        tg_logger.info("✅ Telegram Manager restarted")

    def _get_main_loop(self) -> asyncio.AbstractEventLoop:
        """Получение главного event loop"""
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
        """Настройка Aiogram"""
        await self._setup_dynamic_commands()

        dp = Dispatcher()

        dp.update.middleware(LoggingMiddleware())
        dp.update.middleware(ChatActivityMiddleware(db_manager))
        dp.update.middleware(DatabaseMiddleware())
        dp.update.middleware(ErrorHandlerMiddleware())

        from ..middlewares.tg.commands import DynamicCommandsMiddleware

        dp.update.middleware(DynamicCommandsMiddleware())

        from .handlers.aiogram.auth import auth_middleware

        dp.update.middleware(auth_middleware)

        dp.update.middleware(
            RateLimitMiddleware(
                limit=getattr(settings, "TG_RATE_LIMIT", 10),
                period=60,
                command_limit=getattr(settings, "TG_COMMAND_LIMIT", 5),
                command_period=10,
                whitelist=getattr(settings, "ADMIN_IDS", []),
            )
        )

        dp.update.middleware(ThrottlingMiddleware(default_throttle=0.5))

        router = setup_aiogram_handlers()
        dp.include_router(router)

        dp.startup.register(partial(self._on_aiogram_startup))
        dp.shutdown.register(self._on_aiogram_shutdown)

        return dp

    async def _setup_telethon(self) -> None:
        """Настройка Telethon"""
        client = self._telethon_client.client
        if client:
            setup_telethon_handlers(client)
            tg_logger.debug("✅ Telethon handlers configured")
        else:
            tg_logger.warning("⚠️ Telethon client not available, skipping handlers setup")

    # ==================== ЗАПУСК КЛИЕНТОВ ====================

    async def _run_aiogram(self, dp: Dispatcher) -> None:
        """Запуск Aiogram бота с авто-переподключением"""
        bot = self._aiogram_client.bot

        max_retries = getattr(settings, "TELEGRAM_MAX_RETRIES", 5)
        retry_delay = getattr(settings, "TELEGRAM_RETRY_DELAY", 5)
        retry_count = 0

        while self._is_running:
            try:
                tg_logger.debug("🔄 Aiogram starting polling...")
                await dp.start_polling(
                    bot,
                    allowed_updates=["message", "callback_query", "chat_member", "my_chat_member"],
                    skip_updates=True,
                    polling_timeout=30,
                )
                tg_logger.debug("⏹️ Aiogram polling finished")
                break

            except asyncio.CancelledError:
                tg_logger.warning("⛔ Aiogram cancelled")
                raise

            except (TelegramNetworkError, TelegramAPIError) as err:
                retry_count += 1
                tg_logger.error(f"❌ Aiogram error (attempt {retry_count}/{max_retries}): {err}")

                if retry_count >= max_retries:
                    tg_logger.error("❌ Aiogram max retries reached")
                    raise

                tg_logger.info(f"🔄 Aiogram reconnecting in {retry_delay}s...")
                await asyncio.sleep(retry_delay)
                retry_delay = min(retry_delay * 2, 60)

            except Exception as e:
                error_str = str(e)
                if "ServerDisconnectedError" in error_str or "Server disconnected" in error_str:
                    tg_logger.warning("⚠️ Server disconnected, retrying...")
                    await asyncio.sleep(2)
                    continue
                tg_logger.error(f"❌ Aiogram unexpected error: {e}", exc_info=True)
                await asyncio.sleep(10)

    async def _run_telethon(self) -> None:
        """Запуск Telethon клиента"""
        try:
            await self._telethon_client.start()

            heartbeat_counter = 0
            while self._is_running:
                try:
                    if not await self._telethon_client.is_connected():
                        tg_logger.warning("⚠️ Telethon client disconnected, reconnecting...")
                        await self._telethon_client.start()
                        continue

                    await asyncio.sleep(30)
                    heartbeat_counter += 1

                    if heartbeat_counter % 10 == 0:
                        tg_logger.debug(f"🔄 Telethon heartbeat #{heartbeat_counter}")

                        status = await self._sync_service.get_status()
                        if status.get("client_available"):
                            tg_logger.debug(f"✅ Telethon sync status: {status}")

                except asyncio.CancelledError:
                    tg_logger.warning("⛔ Telethon cancelled")
                    raise
                except Exception as e:
                    tg_logger.error(f"❌ Telethon heartbeat error: {e}")
                    await asyncio.sleep(10)

        except asyncio.CancelledError:
            tg_logger.debug("ℹ️ Telethon task cancelled")
            raise
        except Exception as e:
            tg_logger.error(f"❌ Telethon error: {e}", exc_info=True)
            raise

    async def _wait_for_completion(self) -> None:
        """Ожидание завершения задач или сигнала остановки"""
        try:
            stop_task = asyncio.create_task(self._stop_event.wait())

            done, pending = await asyncio.wait(self._tasks + [stop_task], return_when=asyncio.FIRST_COMPLETED)

            for task in done:
                if task in self._tasks:
                    task_name = task.get_name()

                    if task.cancelled():
                        tg_logger.debug(f"ℹ️ Task cancelled: {task_name}")
                    elif task.exception():
                        try:
                            await task
                        except Exception as e:
                            tg_logger.error(f"❌ Task failed ({task_name}): {e}", exc_info=True)
                    else:
                        tg_logger.info(f"✅ Task completed: {task_name}")

            for task in pending:
                if task != stop_task and not task.done():
                    tg_logger.info(f"⛔ Cancelling task: {task.get_name()}")
                    task.cancel()

            if pending:
                await asyncio.gather(*pending, return_exceptions=True)

        except asyncio.CancelledError:
            tg_logger.warning("⛔ Wait for completion cancelled")
            raise

    # ==================== КОЛБЭКИ ====================

    async def _on_aiogram_startup(self, bot: Bot) -> None:
        """Обработчик запуска Aiogram"""
        tg_logger.info("✅ Aiogram bot started")

        await self._message_service.delete_messages(
            exclude_message_types=[MessageType.USER_REQUEST],
            delete_by_type="startup_cleanup",
        )

        if not settings.ADMIN_IDS:
            tg_logger.debug("ℹ️ No ADMIN_IDS configured, skipping startup notification")
            return

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
                    tg_logger.info(
                        f"✅ Startup message sent to admin {admin_id} (message_id={result.get('message_id')})"
                    )
                else:
                    tg_logger.warning(f"⚠️ Failed to send startup message to admin {admin_id}: {result.get('error')}")
            except Exception as e:
                tg_logger.warning(f"⚠️ Failed to notify admin {admin_id}: {e}")

    @staticmethod
    async def _on_aiogram_shutdown() -> None:
        """Обработчик остановки Aiogram"""
        tg_logger.info("⛔ Aiogram bot shutting down")

    # ==================== РАБОТА С КОМАНДАМИ ====================

    @staticmethod
    def get_public_commands() -> list[dict[str, str]]:
        """Базовые команды (доступны без авторизации)"""
        return [
            {"command": "/start", "description": "Начало работы / Авторизация"},
            {"command": "/help", "description": "Помощь"},
            {"command": "/debug_commands", "description": "🔍 Отладка команд"},
        ]

    @staticmethod
    def get_auth_commands() -> list[dict[str, str]]:
        """Команды, требующие авторизации (видны всем авторизованным пользователям)"""
        return [
            {"command": "/actions", "description": "Меню действий"},
            {"command": "/automation", "description": "Меню автоматизации"},
            {"command": "/stats", "description": "Статистика"},
            {"command": "/id", "description": "Мой ID"},
            {"command": "/logout", "description": "Выйти из системы"},
        ]

    @staticmethod
    def get_admin_commands() -> list[dict[str, str]]:
        """Админ-команды (видны только администраторам)"""
        return [
            {"command": "/sync", "description": "Синхронизация (админ)"},
            {"command": "/broadcast", "description": "Рассылка (админ)"},
            {"command": "/delete", "description": "Удалить сообщение (админ)"},
            {"command": "/admins", "description": "Список админов (админ)"},
            {"command": "/add_admin", "description": "Добавить админа (админ)"},
            {"command": "/remove_admin", "description": "Удалить админа (админ)"},
            {"command": "/groups", "description": "Группы действий (админ)"},
        ]

    def _get_commands_for_user(self, user_id: int, is_admin: bool = False) -> list[dict[str, str]]:
        """Получение списка команд для пользователя"""
        commands = self.get_public_commands().copy()

        is_authorized = self.is_user_in_cache(user_id)

        if is_authorized:
            commands.extend(self.get_auth_commands())

        if is_admin:
            commands.extend(self.get_admin_commands())

        return commands

    async def update_user_commands(self, user_id: int, is_admin: bool = False) -> None:
        """Обновление команд для конкретного пользователя"""
        try:
            if not self._aiogram_client.bot:
                return

            commands = self._get_commands_for_user(user_id, is_admin)

            self._user_commands_cache[user_id] = commands

            success = await self._bot_service.set_commands(commands)
            if success:
                tg_logger.debug(f"✅ Commands updated for user {user_id}: {len(commands)} commands")

        except Exception as e:
            tg_logger.warning(f"⚠️ Failed to update commands for user {user_id}: {e}")

    async def reset_user_commands(self, user_id: int) -> None:
        """Сброс команд пользователя до базовых"""
        try:
            if not self._aiogram_client.bot:
                return

            self._user_commands_cache.pop(user_id, None)

            commands = self.get_public_commands()
            await self._bot_service.set_commands(commands)

            tg_logger.debug(f"✅ Commands reset for user {user_id}")

        except Exception as e:
            tg_logger.warning(f"⚠️ Failed to reset commands for user {user_id}: {e}")

    async def _setup_dynamic_commands(self) -> None:
        """Динамическая установка команд бота"""
        try:
            if not self._aiogram_client.bot:
                return

            public_commands = self.get_public_commands()
            await self._bot_service.set_commands(public_commands)

            for admin_id in getattr(settings, "ADMIN_IDS", []):
                try:
                    await self.update_user_commands(admin_id, is_admin=True)
                except Exception as e:
                    tg_logger.warning(f"⚠️ Failed to set commands for admin {admin_id}: {e}")

            # Обновление команд для всех авторизованных пользователей
            async with db_manager.get_session() as session:
                authorized_users = await UserRepository.get_authorized_users(session)
                for user in authorized_users:
                    try:
                        is_admin = user.FID in getattr(settings, "ADMIN_IDS", [])
                        await self.update_user_commands(user.FID, is_admin)
                    except Exception as e:
                        tg_logger.warning(f"⚠️ Failed to set commands for user {user.FID}: {e}")

            tg_logger.info("✅ Dynamic commands configured")

        except Exception as e:
            tg_logger.error(f"❌ Failed to setup dynamic commands: {e}", exc_info=True)

    # ==================== РАБОТА С КЕШЕМ КОМАНД ====================

    def is_user_in_cache(self, user_id: int) -> bool:
        """Проверка, есть ли пользователь в кеше команд"""
        return user_id in self._user_commands_cache

    @ensure_initialized
    async def is_user_authorized(self, user_id: int) -> bool:
        """Публичный метод для проверки авторизации пользователя"""
        return await self._is_user_authorized(user_id)

    def get_user_commands(self, user_id: int) -> list[dict[str, str]] | None:
        """Получение кешированных команд пользователя"""
        return self._user_commands_cache.get(user_id)

    def clear_user_cache(self, user_id: int) -> None:
        """Очистка кеша команд для пользователя"""
        self._user_commands_cache.pop(user_id, None)
        tg_logger.debug(f"🧹 Cache cleared for user {user_id}")

    def get_cache_stats(self) -> dict[str, Any]:
        """Получение статистики кеша команд"""
        return {
            "total_users": len(self._user_commands_cache),
            "user_ids": list(self._user_commands_cache.keys()),
        }

    @staticmethod
    async def _is_user_authorized(user_id: int) -> bool:
        """Внутренний метод для проверки авторизации пользователя"""
        try:
            async with db_manager.get_session() as session:
                user = await UserRepository.get_user_by_id(session, user_id)
                return user is not None and user.avanpost_user is not None
        except Exception as e:
            tg_logger.debug(f"⚠️ Failed to check user authorization: {e}")
            return False

    # ==================== РАБОТА С БОТОМ ====================

    @ensure_initialized
    async def get_bot_info(self) -> dict[str, Any]:
        """Получение информации о боте через AiogramBotService"""
        return await self._bot_service.get_me()

    async def is_bot_in_chat(self, chat_id: int) -> bool:
        """Проверка, находится ли бот в чате"""
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
                tg_logger.debug(f"✅ Bot is in chat {chat_id} (status: {status_str})")
            else:
                tg_logger.debug(f"⏭️ Bot not in chat {chat_id} (status: {status_str})")

            return is_in_chat

        except Exception as e:
            error_str = str(e).lower()
            if "bot is not a member" in error_str or "user not found" in error_str:
                tg_logger.debug(f"⏭️ Bot not in chat {chat_id}")
            else:
                tg_logger.debug(f"⚠️ Error checking bot in chat {chat_id}: {e}")
            return False

    # ==================== СИНХРОНИЗАЦИЯ ====================

    @log_exceptions(tg_logger)
    @ensure_initialized
    async def sync_chat(self, chat_id: int, session: AsyncSession | None = None, force: bool = False) -> dict[str, Any]:
        """Синхронизация чата"""
        if session is None:
            async with db_manager.get_session() as sess:
                return await self._sync_service.sync_chat_members(chat_id=chat_id, session=sess, force=force)

        return await self._sync_service.sync_chat_members(chat_id=chat_id, session=session, force=force)

    @log_exceptions(tg_logger)
    @ensure_initialized
    async def sync_all_chats(
        self, force: bool = False, max_chats: int | None = None, chat_types: list[str] | None = None
    ) -> dict[str, Any]:
        """Синхронизация всех чатов"""
        async with db_manager.get_session() as session:
            return await self._sync_service.sync_all_chats(
                session=session, force=force, max_chats=max_chats, chat_types=chat_types
            )

    @ensure_initialized
    async def clear_sync_cache(self, chat_id: int | None = None) -> None:
        """Очистка кеша синхронизации"""
        await self._sync_service.clear_cache(chat_id)

    @ensure_initialized
    async def reset_sync_metrics(self) -> None:
        """Сброс метрик синхронизации"""
        await self._sync_service.reset_metrics()

    # ==================== СТАТУС И ЗДОРОВЬЕ ====================

    @log_exceptions(tg_logger)
    async def get_status(self) -> dict[str, Any]:
        """Получение статуса менеджера"""
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
            tg_logger.debug("get_status cancelled")
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
            tg_logger.error(f"Failed to get aiogram status: {e}")
            aiogram_status = {"error": str(e)}

        try:
            telethon_status = await asyncio.shield(self._telethon_client.get_status())
        except asyncio.CancelledError:
            tg_logger.debug("get_status cancelled")
            telethon_status = {"initialized": False, "is_running": False}
        except Exception as e:
            tg_logger.error(f"Failed to get telethon status: {e}")
            telethon_status = {"error": str(e)}

        try:
            sync_status = await asyncio.shield(self._sync_service.get_status())
        except asyncio.CancelledError:
            tg_logger.debug("get_status cancelled")
            sync_status = {"initialized": False}
        except Exception as e:
            tg_logger.error(f"Failed to get sync status: {e}")
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

    @log_exceptions(tg_logger)
    async def health_check(self) -> dict[str, bool]:
        """Проверка здоровья всех компонентов"""
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
        """Представление для отладки"""
        status = "running" if self._is_running else "stopped"
        initialized = "✓" if self._initialized else "✗"
        return (
            f"<TelegramManager "
            f"status={status} "
            f"initialized={initialized} "
            f"account_type={settings.TELEGRAM_ACCOUNT_TYPE} "
            f"tasks={len(self._tasks)}>"
        )


tg_manager = TelegramManager()

# Функции-обертки для доступа к методам класса


def get_public_commands() -> list[dict[str, str]]:
    """Получение публичных команд (функция-обертка)"""
    return TelegramManager.get_public_commands()


def get_auth_commands() -> list[dict[str, str]]:
    """Получение команд для авторизованных пользователей (функция-обертка)"""
    return TelegramManager.get_auth_commands()


def get_admin_commands() -> list[dict[str, str]]:
    """Получение административных команд (функция-обертка)"""
    return TelegramManager.get_admin_commands()


__all__ = [
    "TelegramManager",
    "tg_manager",
    # Публичные методы для работы с командами
    "get_public_commands",
    "get_auth_commands",
    "get_admin_commands",
]
