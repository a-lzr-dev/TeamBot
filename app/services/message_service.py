from datetime import timedelta
from typing import Any

from aiogram.enums import ParseMode
from aiogram.exceptions import TelegramAPIError
from aiogram.types import BufferedInputFile, CallbackQuery, InputFile, Message
from sqlalchemy.ext.asyncio import AsyncSession

from app.bot.clients import AiogramClient, TelethonClient
from app.bot.dependencies import get_bot_manager
from app.config import settings
from app.core.services.base import BaseService
from app.db import ChatRepository, MessageRepository, UserRepository, db_manager
from app.exceptions import log_exceptions
from app.logger import bot_logger
from app.models import (
    ChatMessageModel,
    ChatModel,
    MessageSource,
    MessageType,
    UserModel,
    datetime_now,
)


class UnifiedMessageService(BaseService):
    """Сервис для отправки сообщений через Aiogram и Telethon"""

    def __init__(self, aiogram_client: AiogramClient, telethon_client: TelethonClient) -> None:
        self._aiogram_client = aiogram_client
        self._telethon_client = telethon_client
        self._bot: Any | None = None
        self._telethon: Any | None = None
        self._initialized = False
        self._db = db_manager

        # Репозитории
        self._message_repo = MessageRepository()
        self._chat_repo = ChatRepository()
        self._user_repo = UserRepository()

    async def initialize(self) -> None:
        """Инициализация сервиса"""
        if self._initialized:
            return

        if not self._aiogram_client.bot:
            await self._aiogram_client.initialize()
        self._bot = self._aiogram_client.bot

        if not self._telethon_client.client:
            await self._telethon_client.initialize()
        self._telethon = self._telethon_client.client

        self._initialized = True
        bot_logger.info("✅ Unified Message Service initialized")

    # ==================== ОСНОВНЫЕ МЕТОДЫ ОТПРАВКИ ====================

    @log_exceptions(bot_logger)
    async def send_message(
        self,
        *,
        chat_id: int,
        text: str,
        message_type: MessageType | None = None,
        delete_message_id: int | None = None,
        delete_by_type: str | None = None,
        exclude_message_types: list[MessageType] | None = None,
        parse_mode: str | ParseMode | None = None,
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
        **kwargs: Any,
    ) -> dict[str, Any]:
        """
        Отправка сообщения через оптимальный клиент с поддержкой топиков.
        """
        if not self._initialized:
            await self.initialize()

        if message_type is None:
            message_type = MessageType.BOT_RESPONSE

        # Чистка сообщений
        if delete_message_id:
            await self.delete_message_by_id(chat_id=chat_id, message_id=delete_message_id)

        if delete_by_type or exclude_message_types:
            delete_type = delete_by_type if delete_by_type is not None else "cleanup"
            await self.delete_messages(
                chat_id=chat_id,
                message_types=[message_type] if delete_by_type else None,
                delete_by_type=delete_type,
                exclude_message_types=exclude_message_types,
            )

        result = None
        client_used = None

        # 1. Попытка отправки через Aiogram
        if self._bot:
            try:
                result = await self._send_via_aiogram(
                    chat_id=chat_id,
                    text=text,
                    parse_mode=parse_mode,
                    disable_web_page_preview=disable_web_page_preview,
                    disable_notification=disable_notification,
                    protect_content=protect_content,
                    reply_to_message_id=reply_to_message_id,
                    reply_markup=reply_markup,
                    message_thread_id=message_thread_id,
                    **kwargs,
                )

                if result.get("success"):
                    client_used = "aiogram"
                    bot_logger.debug(f"✅ Message sent via Aiogram to {chat_id}")
            except Exception as e:
                bot_logger.warning(f"⚠️ Aiogram send failed: {e}, trying Telethon...")

        # 2. Fallback через Telethon (если разрешено и клиент доступен)
        if not client_used and allow_sender and self._telethon:
            try:
                result = await self._send_via_telethon(
                    chat_id=chat_id,
                    text=text,
                    parse_mode=parse_mode,
                    disable_notification=disable_notification,
                    reply_to_message_id=reply_to_message_id,
                    **kwargs,
                )

                if result.get("success"):
                    client_used = "telethon"
                    bot_logger.debug(f"✅ Message sent via Telethon to {chat_id}")
            except Exception as e:
                bot_logger.error(f"❌ Telethon send failed: {e}")

        if not client_used or not result or not result.get("success"):
            return {
                "success": False,
                "error": "No clients available or all failed",
                "chat_id": chat_id,
            }

        # Сохранение в БД через репозиторий
        if result.get("message_id"):
            await self._save_message(
                chat_id=chat_id,
                message_id=result["message_id"],
                message_type=message_type,
                text=text,
                parse_mode=parse_mode,
                reply_to_message_id=reply_to_message_id,
                client=client_used,
                lifetime_seconds=lifetime_seconds,
                user_id=user_id,
                user_first_name=user_first_name,
                user_last_name=user_last_name,
                user_username=user_username,
                user_is_bot=user_is_bot,
                user_phone=user_phone,
                user_group_id=user_group_id,
                caption=kwargs.get("caption"),
                content_type=kwargs.get("content_type"),
                file_id=kwargs.get("file_id"),
                file_unique_id=kwargs.get("file_unique_id"),
                file_size=kwargs.get("file_size"),
                mime_type=kwargs.get("mime_type"),
                command=kwargs.get("command"),
                command_args=kwargs.get("command_args"),
                category=kwargs.get("category"),
                is_forwarded=kwargs.get("is_forwarded", False),
            )

        return {
            "success": True,
            "message_id": result["message_id"],
            "chat_id": chat_id,
            "client": client_used,
            "message": result.get("message"),
        }

    @log_exceptions(bot_logger)
    async def send_answer(
        self,
        event: Message | CallbackQuery,
        text: str,
        message_type: MessageType | None = None,
        delete_by_type: str | None = None,
        exclude_message_types: list[MessageType] | None = None,
        parse_mode: str | ParseMode | None = None,
        reply_markup: Any = None,
        show_alert: bool = False,
        lifetime_seconds: int | None = None,
        delete_original: bool = False,
        message_thread_id: int | None = None,
        **kwargs: Any,
    ) -> dict[str, Any]:
        """
        Универсальный ответ на событие (сообщение или callback).
        """
        if not self._initialized:
            await self.initialize()

        # Обработка Message
        if isinstance(event, Message):
            user = event.from_user
            if not user:
                return {"success": False, "error": "No user in event", "chat_id": None}

            chat_id = event.chat.id if event.chat else 0
            if chat_id == 0:
                return {"success": False, "error": "No chat_id in event", "chat_id": None}

            original_message_id = event.message_id

            # Подготовка данных пользователя
            user_data = self._prepare_user_data(
                user_id=user.id,
                first_name=user.first_name,
                last_name=user.last_name,
                username=user.username,
                is_bot=user.is_bot,
            )

            delete_message_id = original_message_id if delete_original else None

            return await self.send_message(
                chat_id=chat_id,
                text=text,
                message_type=message_type,
                delete_message_id=delete_message_id,
                delete_by_type=delete_by_type,
                exclude_message_types=exclude_message_types,
                parse_mode=parse_mode,
                reply_markup=reply_markup,
                reply_to_message_id=original_message_id,
                lifetime_seconds=lifetime_seconds,
                message_thread_id=message_thread_id,
                **user_data,
                **kwargs,
            )

        # Обработка CallbackQuery
        if isinstance(event, CallbackQuery):
            user = event.from_user
            if not user:
                return {"success": False, "error": "No user in event", "chat_id": None}

            chat_id = 0
            original_message_id = None

            if event.message and event.message.chat:
                chat_id = event.message.chat.id
                original_message_id = event.message.message_id

            if chat_id == 0:
                return {"success": False, "error": "No chat_id in event", "chat_id": None}

            # Ответ на callback
            try:
                await event.answer(text="")
                if show_alert:
                    await event.answer(text="", show_alert=True)
            except Exception as e:
                bot_logger.debug(f"⚠️ Failed to answer callback: {e}")

            # Подготовка данных пользователя
            user_data = self._prepare_user_data(
                user_id=user.id,
                first_name=user.first_name,
                last_name=user.last_name,
                username=user.username,
                is_bot=user.is_bot,
            )

            delete_message_id = original_message_id if delete_original else None

            return await self.send_message(
                chat_id=chat_id,
                text=text,
                message_type=message_type,
                delete_message_id=delete_message_id,
                delete_by_type=delete_by_type,
                exclude_message_types=exclude_message_types,
                parse_mode=parse_mode,
                reply_markup=reply_markup,
                reply_to_message_id=None,
                lifetime_seconds=lifetime_seconds,
                message_thread_id=message_thread_id,
                **user_data,
                **kwargs,
            )

        # Неподдерживаемый тип
        return {
            "success": False,
            "error": f"Unsupported event type: {type(event).__name__}",
            "chat_id": None,
        }

    # ==================== ПРИВАТНЫЕ МЕТОДЫ ====================

    @staticmethod
    def _prepare_user_data(
        user_id: int,
        first_name: str | None = None,
        last_name: str | None = None,
        username: str | None = None,
        is_bot: bool = False,
        phone: str | None = None,
        group_id: int | None = None,
    ) -> dict[str, Any]:
        """Подготовка данных пользователя для отправки."""
        return {
            "user_id": user_id,
            "user_first_name": first_name,
            "user_last_name": last_name,
            "user_username": username,
            "user_is_bot": is_bot,
            "user_phone": phone,
            "user_group_id": group_id,
        }

    async def _send_via_aiogram(self, **kwargs: Any) -> dict[str, Any]:
        """Отправка через Aiogram с поддержкой топиков"""
        bot = self._bot
        if bot is None:
            return {"success": False, "error": "Bot not available", "chat_id": kwargs.get("chat_id")}

        try:
            parse_mode = self._normalize_parse_mode(kwargs.get("parse_mode"))
            message_thread_id = kwargs.get("message_thread_id")

            bot_logger.debug(
                f"🔍 [_send_via_aiogram] chat_id={kwargs['chat_id']}, message_thread_id={message_thread_id}"
            )
            bot_logger.debug(f"🔍 [_send_via_aiogram] text preview: {kwargs['text'][:100]}...")

            message = await bot.send_message(
                chat_id=kwargs["chat_id"],
                text=kwargs["text"],
                parse_mode=parse_mode,
                disable_web_page_preview=kwargs.get("disable_web_page_preview", False),
                disable_notification=kwargs.get("disable_notification", False),
                protect_content=kwargs.get("protect_content", False),
                reply_to_message_id=kwargs.get("reply_to_message_id"),
                reply_markup=kwargs.get("reply_markup"),
                message_thread_id=message_thread_id,
                **{k: v for k, v in kwargs.items() if k not in self._AIOGRAM_IGNORED_PARAMS},
            )

            bot_logger.debug(f"✅ [_send_via_aiogram] SUCCESS! message_id={message.message_id}")

            return {
                "success": True,
                "message_id": message.message_id,
                "chat_id": kwargs["chat_id"],
                "date": message.date.isoformat() if message.date else None,
                "message": message,
            }

        except TelegramAPIError as e:
            error_str = str(e).lower()
            bot_logger.error(f"❌ [_send_via_aiogram] TelegramAPIError: {e}")

            if "message to be replied not found" in error_str:
                kwargs["reply_to_message_id"] = None
                return await self._send_via_aiogram(**kwargs)
            return {"success": False, "error": str(e), "chat_id": kwargs["chat_id"]}

    async def _send_via_telethon(self, **kwargs: Any) -> dict[str, Any]:
        """Отправка через Telethon"""
        telethon = self._telethon
        if telethon is None:
            return {"success": False, "error": "Telethon client not available"}

        try:
            parse_mode = kwargs.get("parse_mode")
            if parse_mode:
                if parse_mode == "HTML":
                    parse_mode = "html"
                elif parse_mode == "MARKDOWN":
                    parse_mode = "markdown"
                elif parse_mode == "MARKDOWN_V2":
                    parse_mode = "MarkdownV2"

            result = await telethon.send_message(
                kwargs["chat_id"],
                kwargs["text"],
                parse_mode=parse_mode,
                silent=kwargs.get("disable_notification", False),
                reply_to=kwargs.get("reply_to_message_id"),
            )

            return {
                "success": True,
                "message_id": result.id,
                "chat_id": kwargs["chat_id"],
                "date": result.date.isoformat() if result.date else None,
            }

        except Exception as e:
            return {"success": False, "error": str(e), "chat_id": kwargs["chat_id"]}

    async def _save_message(self, **kwargs: Any) -> ChatMessageModel | None:
        """
        Сохранение сообщения в БД через репозиторий.
        Автоматически создает чат и пользователя при необходимости.
        """
        try:
            async with self._db.get_session() as session:
                chat_id = kwargs.get("chat_id")
                user_id = kwargs.get("user_id")

                if chat_id is None:
                    bot_logger.error("❌ Cannot save message: chat_id is None")
                    return None

                chat_id_int = int(chat_id)

                # Проверка и создание чата при его отсутствии
                await self._ensure_chat_exists(session, chat_id_int)

                # Проверка и создание/обновление пользователя
                if user_id:
                    await self._ensure_user_exists(session, **kwargs)

                # Подготовка данных для создания сообщения
                message_type = kwargs.get("message_type") or MessageType.BOT_RESPONSE
                lifetime_seconds = kwargs.get("lifetime_seconds")
                expires_at = kwargs.get("expires_at")

                # Проверка времени жизни
                if lifetime_seconds is None and message_type not in (
                    MessageType.USER_REQUEST,
                    MessageType.BOT_RESPONSE,
                ):
                    lifetime_seconds = getattr(settings, "BOT_MESSAGE_LIFETIME_SECONDS", 300)

                if lifetime_seconds and expires_at is None:
                    expires_at = datetime_now() + timedelta(seconds=lifetime_seconds)

                # ИСПОЛЬЗУЕМ MessageRepository ДЛЯ СОЗДАНИЯ СООБЩЕНИЯ
                message = await self._message_repo.create_message(
                    session=session,
                    message_id=kwargs["message_id"],
                    chat_id=chat_id_int,
                    user_id=user_id,
                    message_type=message_type,
                    text=kwargs.get("text"),
                    caption=kwargs.get("caption"),
                    source=MessageSource.BOT,
                    reply_to_message_id=kwargs.get("reply_to_message_id"),
                    lifetime_seconds=lifetime_seconds,
                    expires_at=expires_at,
                    command=kwargs.get("command"),
                    command_args=kwargs.get("command_args"),
                    category=kwargs.get("category"),
                    content_type=kwargs.get("content_type"),
                    file_id=kwargs.get("file_id"),
                    file_unique_id=kwargs.get("file_unique_id"),
                    file_size=kwargs.get("file_size"),
                    mime_type=kwargs.get("mime_type"),
                    is_forwarded=kwargs.get("is_forwarded", False),
                    is_reply=bool(kwargs.get("reply_to_message_id")),
                )

                await session.commit()

                bot_logger.debug(
                    f"✅ Message {message.FID} saved to database (chat={chat_id_int}, type={message_type})"
                )
                return message

        except Exception as e:
            bot_logger.error(f"❌ Failed to save message: {e}", exc_info=True)
            return None

    async def _ensure_chat_exists(self, session: AsyncSession, chat_id: int) -> ChatModel | None:
        """
        Проверка и создание чата при его отсутствии через ChatRepository.
        """
        try:
            # ИСПОЛЬЗУЕМ ChatRepository ДЛЯ ПРОВЕРКИ СУЩЕСТВОВАНИЯ ЧАТА
            chat = await self._chat_repo.get_chat_by_id(session, chat_id)
            if chat:
                return chat

            bot_logger.warning(f"⚠️ Chat {chat_id} not found in DB, creating...")

            # Получение информации о чате из Telegram
            chat_type_str = "private"
            title = f"Chat {chat_id}"
            is_active = True

            if self._bot:
                try:
                    chat_info = await self._bot.get_chat(chat_id)
                    from ..core.converters import chat_type_from_aiogram, chat_type_to_str

                    chat_type = chat_type_from_aiogram(chat_info)
                    chat_type_str = chat_type_to_str(chat_type)
                    title = chat_info.title or f"Chat {chat_id}"

                    # Проверка, активен ли чат
                    try:
                        me = await self._bot.get_me()
                        member = await self._bot.get_chat_member(chat_id, me.id)
                        status = member.status.value if hasattr(member.status, "value") else str(member.status)
                        is_active = status not in ["left", "kicked"]
                    except Exception:
                        is_active = True

                except Exception as e:
                    bot_logger.warning(f"⚠️ Could not fetch chat info for {chat_id}: {e}")
                    if chat_id < 0:
                        chat_type_str = "supergroup"

            # ИСПОЛЬЗУЕМ ChatRepository ДЛЯ СОЗДАНИЯ ЧАТА
            chat = await self._chat_repo.save_chat(
                session=session,
                chat_id=chat_id,
                chat_type=chat_type_str,
                title=title,
                is_active=is_active,
            )
            await session.flush()
            bot_logger.info(f"✅ Chat {chat_id} created automatically (type={chat_type_str}, title={title})")
            return chat

        except Exception as e:
            bot_logger.error(f"❌ Failed to create chat {chat_id}: {e}")
            return None

    async def _ensure_user_exists(self, session: AsyncSession, **kwargs: Any) -> UserModel | None:
        """
        Проверка и создание/обновление пользователя через UserRepository.
        """
        try:
            user_id = kwargs.get("user_id")
            if not user_id:
                return None

            # ИСПОЛЬЗУЕМ UserRepository ДЛЯ ПОЛУЧЕНИЯ ПОЛЬЗОВАТЕЛЯ
            user = await self._user_repo.get_user_by_id(session, user_id)

            if user:
                # Обновление существующего пользователя
                updated = False
                if kwargs.get("user_first_name") and user.FFirstName != kwargs.get("user_first_name"):
                    user.FFirstName = kwargs.get("user_first_name")
                    updated = True
                if kwargs.get("user_last_name") and user.FLastName != kwargs.get("user_last_name"):
                    user.FLastName = kwargs.get("user_last_name")
                    updated = True
                if kwargs.get("user_username") and user.FUserName != kwargs.get("user_username"):
                    user.FUserName = kwargs.get("user_username") or ""
                    updated = True
                if kwargs.get("user_phone") and user.FPhone != kwargs.get("user_phone"):
                    user.FPhone = kwargs.get("user_phone")
                    updated = True

                if updated:
                    user.FDateUpdated = datetime_now()
                    await session.flush()
                    bot_logger.debug(f"✅ User {user_id} updated")
                return user

            # ИСПОЛЬЗУЕМ UserRepository ДЛЯ СОЗДАНИЯ НОВОГО ПОЛЬЗОВАТЕЛЯ
            user = await self._user_repo.save_user(
                session=session,
                user_id=user_id,
                first_name=kwargs.get("user_first_name"),
                last_name=kwargs.get("user_last_name"),
                username=kwargs.get("user_username"),
                is_bot=kwargs.get("user_is_bot", False),
                phone=kwargs.get("user_phone"),
                chat_id=kwargs.get("chat_id"),
            )
            await session.flush()
            bot_logger.debug(f"✅ User {user_id} created automatically")
            return user

        except Exception as e:
            bot_logger.error(f"❌ Failed to ensure user exists: {e}")
            return None

    @staticmethod
    def _normalize_parse_mode(parse_mode: str | ParseMode | None) -> ParseMode | None:
        """Нормализация режима парсинга"""
        if parse_mode is None:
            return None

        if isinstance(parse_mode, ParseMode):
            return parse_mode

        if isinstance(parse_mode, str):
            upper = parse_mode.upper()
            mapping = {
                "HTML": ParseMode.HTML,
                "MARKDOWN": ParseMode.MARKDOWN,
                "MARKDOWN_V2": ParseMode.MARKDOWN_V2,
            }
            return mapping.get(upper)

        return None

    async def _mark_message_deleted(self, chat_id: int, message_id: int, deleted_by_type: str) -> None:
        """Отметка сообщения как удаленного в БД через ChatRepository"""
        try:
            async with self._db.get_session() as session:
                # ИСПОЛЬЗУЕМ ChatRepository ДЛЯ ОТМЕТКИ СООБЩЕНИЯ КАК УДАЛЕННОГО
                await self._chat_repo.deactivate_missing_chat_message(
                    session=session,
                    message_id=message_id,
                    chat_id=chat_id,
                    deleted_by_type=deleted_by_type,
                )
        except Exception as e:
            bot_logger.warning(f"⚠️ Failed to mark message {message_id} as deleted: {e}")

    # ==================== РЕДАКТИРОВАНИЕ И УДАЛЕНИЕ ====================

    @log_exceptions(bot_logger)
    async def edit_message(
        self,
        chat_id: int,
        message_id: int,
        text: str,
        parse_mode: str | ParseMode | None = None,
        reply_markup: Any = None,
        **kwargs: Any,
    ) -> dict[str, Any]:
        """
        Редактирование сообщения.

        Важно: message_thread_id не передается в edit_message_text,
        так как сообщение уже находится в топике и его ID уникален в рамках чата.
        """
        from ..bot.dependencies import get_bot_manager

        bot_manager = get_bot_manager()
        bot = bot_manager.aiogram_client.bot

        if bot is None:
            return {"success": False, "error": "Bot not initialized"}

        try:
            edit_kwargs = kwargs.copy()
            edit_kwargs.pop("message_thread_id", None)

            normalized_parse_mode = self._normalize_parse_mode(parse_mode)

            message = await bot.edit_message_text(
                chat_id=chat_id,
                message_id=message_id,
                text=text,
                parse_mode=normalized_parse_mode,
                reply_markup=reply_markup,
                **edit_kwargs,
            )

            # Обновление сообщения в БД через репозиторий
            if message:
                edit_date = message.date.replace(tzinfo=None) if message.date else None
                await self._update_message_in_db(
                    message_id=message_id,
                    text=text,
                    edit_date=edit_date,
                )

            return {
                "success": True,
                "message_id": message.message_id if message else message_id,
                "chat_id": chat_id,
                "message": message,
            }

        except TelegramAPIError as e:
            error_str = str(e).lower()
            if "message is not modified" in error_str:
                return {"success": True, "message_id": message_id, "chat_id": chat_id, "not_modified": True}
            bot_logger.error(f"❌ Failed to edit message: {e}")
            return {"success": False, "error": str(e), "chat_id": chat_id, "message_id": message_id}

    async def _update_message_in_db(
        self,
        message_id: int,
        text: str | None = None,
        caption: str | None = None,
        edit_date: Any = None,
    ) -> None:
        """Обновление сообщения в БД через MessageRepository"""
        try:
            async with self._db.get_session() as session:
                # ИСПОЛЬЗУЕМ MessageRepository ДЛЯ ОБНОВЛЕНИЯ СООБЩЕНИЯ
                await self._message_repo.update_message(
                    session=session,
                    message_id=message_id,
                    text=text,
                    caption=caption,
                    edit_date=edit_date,
                )
        except Exception as e:
            bot_logger.warning(f"⚠️ Failed to update message {message_id} in DB: {e}")

    @log_exceptions(bot_logger)
    async def edit_callback_message(
        self,
        callback: CallbackQuery,
        text: str,
        parse_mode: str | ParseMode | None = None,
        reply_markup: Any = None,
        **kwargs: Any,
    ) -> dict[str, Any]:
        """Редактирование сообщения из callback"""
        bot_manager = get_bot_manager()

        if not callback.message or not callback.message.chat:
            return {"success": False, "error": "No message in callback"}

        bot_logger.debug(
            f"📝 Editing callback message: chat={callback.message.chat.id}, msg={callback.message.message_id}"
        )
        bot_logger.debug(f"📝 New text: {text[:100]}...")

        await bot_manager.send_toast(event=callback)

        result = await self.edit_message(
            chat_id=callback.message.chat.id,
            message_id=callback.message.message_id,
            text=text,
            parse_mode=parse_mode,
            reply_markup=reply_markup,
            **kwargs,
        )
        bot_logger.debug(f"📝 Edit result: {result}")
        return result

    @log_exceptions(bot_logger)
    async def delete_message_by_id(self, chat_id: int, message_id: int) -> dict[str, Any]:
        """Удаление сообщения"""
        result = None
        client_used = None

        if self._bot:
            try:
                await self._bot.delete_message(chat_id=chat_id, message_id=message_id)
                result = {"success": True, "chat_id": chat_id, "message_id": message_id}
                client_used = "aiogram"
            except Exception as e:
                bot_logger.debug(f"⚠️ Aiogram delete failed: {e}")

        if not client_used and self._telethon:
            try:
                await self._telethon.delete_messages(chat_id, [message_id])
                result = {"success": True, "chat_id": chat_id, "message_id": message_id}
                client_used = "telethon"
            except Exception as e:
                bot_logger.error(f"❌ Telethon delete failed: {e}")

        if not result or not result.get("success"):
            return {"success": False, "error": "No clients available", "chat_id": chat_id, "message_id": message_id}

        await self._mark_message_deleted(chat_id, message_id, client_used or "system")
        return result

    @log_exceptions(bot_logger)
    async def delete_messages(
        self,
        chat_id: int | None = None,
        before_minutes: int = 0,
        keep_last_per_chat: int = 0,
        message_types: list[MessageType] | None = None,
        exclude_message_types: list[MessageType] | None = None,
        delete_by_type: str = "cleanup",
    ) -> dict[str, int]:
        """Очистка старых сообщений"""
        result = {
            "marked_deleted": 0,
            "kept": 0,
            "total_found": 0,
            "chats_processed": 0,
            "telegram_deleted": 0,
        }

        try:
            async with self._db.get_session() as session:
                # ИСПОЛЬЗУЕМ MessageRepository ДЛЯ ПОЛУЧЕНИЯ СТАРЫХ СООБЩЕНИЙ
                old_messages = await self._message_repo.get_messages_by_filter(
                    session=session,
                    chat_id=chat_id,
                    before_minutes=before_minutes,
                    message_types=message_types,
                    exclude_message_types=exclude_message_types,
                )

                result["total_found"] = len(old_messages)

                if not old_messages:
                    bot_logger.debug("ℹ️ No old messages to clean up")
                    return result

                from collections import defaultdict

                messages_by_chat: dict[int, list[ChatMessageModel]] = defaultdict(list)
                for msg in old_messages:
                    messages_by_chat[msg.FK_Chat].append(msg)

                total_marked = 0
                total_kept = 0
                total_telegram_deleted = 0

                for chat_id_loop, messages in messages_by_chat.items():
                    messages_sorted = sorted(messages, key=lambda m: m.FDateSent, reverse=True)
                    msg_ids = [m.FID for m in messages_sorted]

                    if 0 < keep_last_per_chat < len(msg_ids):
                        ids_to_delete = msg_ids[keep_last_per_chat:]
                        to_keep = msg_ids[:keep_last_per_chat]
                        total_kept += len(to_keep)
                    else:
                        ids_to_delete = msg_ids

                    if ids_to_delete:
                        for msg_id in ids_to_delete:
                            try:
                                delete_result = await self.delete_message_by_id(chat_id=chat_id_loop, message_id=msg_id)
                                if delete_result.get("success"):
                                    total_telegram_deleted += 1
                            except Exception as e:
                                bot_logger.warning(f"⚠️ Error deleting message {msg_id}: {e}")

                        # ИСПОЛЬЗУЕМ MessageRepository ДЛЯ ОТМЕТКИ СООБЩЕНИЙ КАК УДАЛЕННЫХ
                        deleted = await self._message_repo.mark_messages_deleted_by_ids(
                            session=session, message_ids=ids_to_delete, deleted_by_type=delete_by_type
                        )
                        total_marked += deleted

                result["marked_deleted"] = total_marked
                result["kept"] = total_kept
                result["telegram_deleted"] = total_telegram_deleted
                result["chats_processed"] = len(messages_by_chat)

                if total_marked > 0:
                    types_str = ", ".join([t.value for t in message_types]) if message_types else "ALL"
                    excluded_str = f", excluded: {len(exclude_message_types)} types" if exclude_message_types else ""
                    bot_logger.info(
                        f"🧹 Cleaned up {total_marked} old messages "
                        f"(types: {types_str}{excluded_str}, "
                        f"kept {total_kept}, "
                        f"telegram_deleted: {total_telegram_deleted}, "
                        f"found {len(old_messages)}, chats: {len(messages_by_chat)})"
                    )

                return result

        except Exception as e:
            bot_logger.error(f"❌ Failed to cleanup old messages: {e}", exc_info=True)
            return result

    @log_exceptions(bot_logger)
    async def send_photo(
        self,
        *,
        chat_id: int,
        photo: bytes | str | InputFile,
        message_type: MessageType | None = None,
        caption: str | None = None,
        parse_mode: str | ParseMode | None = None,
        filename: str | None = None,
        reply_markup: Any = None,
        lifetime_seconds: int | None = None,
        message_thread_id: int | None = None,
        **kwargs: Any,
    ) -> dict[str, Any]:
        """Отправка фото с поддержкой топиков"""
        bot = self._bot
        if bot is None:
            return {"success": False, "error": "Bot not initialized"}

        if message_type is None:
            message_type = MessageType.BOT_RESPONSE

        try:
            if isinstance(photo, bytes):
                photo = BufferedInputFile(photo, filename=filename or "photo.jpg")

            normalized_parse_mode = self._normalize_parse_mode(parse_mode)

            message = await bot.send_photo(
                chat_id=chat_id,
                photo=photo,
                caption=caption,
                parse_mode=normalized_parse_mode,
                reply_markup=reply_markup,
                message_thread_id=message_thread_id,
                **kwargs,
            )

            if message and message.message_id:
                await self._save_message(
                    chat_id=chat_id,
                    message_id=message.message_id,
                    message_type=message_type,
                    text=caption or f"[Photo: {filename}]",
                    parse_mode=parse_mode,
                    client="aiogram",
                    lifetime_seconds=lifetime_seconds,
                    caption=caption,
                    content_type=message.content_type if hasattr(message, "content_type") else None,
                    **kwargs,
                )

            return {
                "success": True,
                "message_id": message.message_id,
                "chat_id": chat_id,
                "message": message,
            }

        except Exception as e:
            bot_logger.error(f"❌ Failed to send photo: {e}")
            return {"success": False, "error": str(e), "chat_id": chat_id}

    # ==================== СТАТУС ====================

    async def get_status(self) -> dict[str, Any]:
        """Получение статуса сервиса"""
        return {
            "initialized": self._initialized,
            "aiogram_available": bool(self._bot),
            "telethon_available": bool(self._telethon),
            "service": "unified_message",
        }

    async def health_check(self) -> bool:
        """Проверка здоровья сервиса"""
        if not self._initialized:
            return False
        try:
            if self._bot:
                await self._bot.get_me()
            return True
        except Exception:
            return False

    _AIOGRAM_IGNORED_PARAMS = {
        "chat_id",
        "text",
        "parse_mode",
        "disable_web_page_preview",
        "disable_notification",
        "protect_content",
        "reply_to_message_id",
        "reply_markup",
        "message_type",
        "user_id",
        "user_first_name",
        "user_last_name",
        "user_username",
        "user_is_bot",
        "user_phone",
        "user_group_id",
        "lifetime_seconds",
        "clear_previous",
        "allow_sender",
        "message_thread_id",
        "caption",
        "content_type",
        "file_id",
        "file_unique_id",
        "file_size",
        "mime_type",
        "command",
        "command_args",
        "category",
        "is_forwarded",
    }


__all__ = ["UnifiedMessageService"]
