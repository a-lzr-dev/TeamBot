from datetime import timedelta
from typing import TYPE_CHECKING, Any

from aiogram.enums import ParseMode
from aiogram.exceptions import TelegramAPIError
from aiogram.types import BufferedInputFile, CallbackQuery, InputFile, Message
from sqlalchemy.ext.asyncio import AsyncSession

from ...db import ChatRepository, MessageRepository, UserRepository, db_manager
from ...exceptions import log_exceptions
from ...logger import tg_logger
from ...models import ChatMessageModel, MessageSource, MessageType, datetime_now
from ..clients import AiogramClient, TelethonClient
from .base import BaseService

if TYPE_CHECKING:
    from ...tg import TelegramManager


def get_tg_manager() -> "TelegramManager":
    """Получение глобального tg_manager"""
    from ...tg import tg_manager

    return tg_manager


class UnifiedMessageService(BaseService):
    """Сервис для отправки сообщений через Aiogram и Telethon"""

    def __init__(self, aiogram_client: AiogramClient, telethon_client: TelethonClient) -> None:
        self._aiogram_client = aiogram_client
        self._telethon_client = telethon_client
        self._bot = None
        self._telethon = None
        self._initialized = False
        self._db = db_manager

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
        tg_logger.info("✅ Unified Message Service initialized")

    # ==================== ОСНОВНЫЕ МЕТОДЫ ОТПРАВКИ ====================

    @log_exceptions(tg_logger)
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
        **kwargs: Any,
    ) -> dict[str, Any]:
        """Отправка сообщения через оптимальный клиент"""
        if not self._initialized:
            await self.initialize()

        if message_type is None:
            message_type = MessageType.BOT_RESPONSE

        # Чистка сообщений
        if delete_message_id:
            await self.delete_message_by_id(chat_id=chat_id, message_id=delete_message_id)

        if delete_by_type or exclude_message_types:
            # Передаем delete_by_type только если он не None
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
                    **kwargs,
                )

                if result.get("success"):
                    client_used = "aiogram"
                    tg_logger.debug(f"✅ Message sent via Aiogram to {chat_id}")
            except Exception as e:
                tg_logger.warning(f"⚠️ Aiogram send failed: {e}, trying Telethon...")

        # 2. Fallback через Telethon
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
                    tg_logger.debug(f"✅ Message sent via Telethon to {chat_id}")
            except Exception as e:
                tg_logger.error(f"❌ Telethon send failed: {e}")

        if not client_used or not result or not result.get("success"):
            return {
                "success": False,
                "error": "No clients available or all failed",
                "chat_id": chat_id,
            }

        # Сохранение в БД
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
            )

        return {
            "success": True,
            "message_id": result["message_id"],
            "chat_id": chat_id,
            "client": client_used,
            "message": result.get("message"),
        }

    @log_exceptions(tg_logger)
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
        **kwargs: Any,
    ) -> dict[str, Any]:
        """
        Универсальный ответ на событие (сообщение или callback).

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
            **kwargs: Дополнительные параметры

        Returns:
            Dict[str, Any]: Результат отправки
        """
        if not self._initialized:
            await self.initialize()

        # Определение типа события
        is_message = isinstance(event, Message)
        is_callback = isinstance(event, CallbackQuery)

        if not is_message and not is_callback:
            return {
                "success": False,
                "error": f"Unsupported event type: {type(event).__name__}",
                "chat_id": None,
            }

        # Извлечение данных из события
        user = None
        chat_id = 0
        original_message_id = None

        if is_message:
            user = event.from_user
            if event.chat:
                chat_id = event.chat.id
            original_message_id = event.message_id
        elif is_callback:
            user = event.from_user
            if event.message and event.message.chat:
                chat_id = event.message.chat.id
                original_message_id = event.message.message_id

        if not user:
            return {"success": False, "error": "No user in event", "chat_id": chat_id}

        if chat_id == 0:
            return {"success": False, "error": "No chat_id in event", "chat_id": None}

        # Ответ на callback (если нужно)
        if is_callback:
            try:
                # Всегда отвечаем на callback, чтобы скрыть "часики"
                await event.answer()
                # Если нужно показать alert, передаем show_alert
                if show_alert:
                    await event.answer(text="", show_alert=True)
            except Exception as e:
                tg_logger.debug(f"⚠️ Failed to answer callback: {e}")

        # Подготовка данных пользователя
        user_data = self._prepare_user_data(
            user_id=user.id,
            first_name=user.first_name,
            last_name=user.last_name,
            username=user.username,
            is_bot=user.is_bot,
        )

        # Определяем ID сообщения для удаления
        delete_message_id = None
        if delete_original and original_message_id:
            delete_message_id = original_message_id

        # Отправка сообщения
        return await self.send_message(
            chat_id=chat_id,
            text=text,
            message_type=message_type,
            delete_message_id=delete_message_id,
            delete_by_type=delete_by_type,
            exclude_message_types=exclude_message_types,
            parse_mode=parse_mode,
            reply_markup=reply_markup,
            reply_to_message_id=original_message_id if is_message else None,
            lifetime_seconds=lifetime_seconds,
            **user_data,
            **kwargs,
        )

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
        """Отправка через Aiogram"""
        if not self._bot:
            return {"success": False, "error": "Bot not available", "chat_id": kwargs.get("chat_id")}

        try:
            parse_mode = self._normalize_parse_mode(kwargs.get("parse_mode"))
            message = await self._bot.send_message(
                chat_id=kwargs["chat_id"],
                text=kwargs["text"],
                parse_mode=parse_mode,
                disable_web_page_preview=kwargs.get("disable_web_page_preview", False),
                disable_notification=kwargs.get("disable_notification", False),
                protect_content=kwargs.get("protect_content", False),
                reply_to_message_id=kwargs.get("reply_to_message_id"),
                reply_markup=kwargs.get("reply_markup"),
                **{k: v for k, v in kwargs.items() if k not in self._AIAGRAM_IGNORED_PARAMS},
            )

            return {
                "success": True,
                "message_id": message.message_id,
                "chat_id": kwargs["chat_id"],
                "date": message.date.isoformat() if message.date else None,
                "message": message,
            }

        except TelegramAPIError as e:
            error_str = str(e).lower()
            if "message to be replied not found" in error_str:
                kwargs["reply_to_message_id"] = None
                return await self._send_via_aiogram(**kwargs)
            return {"success": False, "error": str(e), "chat_id": kwargs["chat_id"]}

    async def _send_via_telethon(self, **kwargs: Any) -> dict[str, Any]:
        """Отправка через Telethon"""
        if not self._telethon:
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

            result = await self._telethon.send_message(
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
        """Сохранение сообщения в БД"""
        try:
            async with self._db.get_session() as session:
                user_id = kwargs.get("user_id")
                if user_id:
                    await self._ensure_user_exists(
                        session=session,
                        user_id=user_id,
                        first_name=kwargs.get("user_first_name"),
                        last_name=kwargs.get("user_last_name"),
                        username=kwargs.get("user_username"),
                        is_bot=kwargs.get("user_is_bot", False),
                        phone=kwargs.get("user_phone"),
                        chat_id=kwargs.get("chat_id"),
                        group_id=kwargs.get("user_group_id"),
                    )

                lifetime_seconds = kwargs.get("lifetime_seconds")
                message_type = kwargs.get("message_type")
                if lifetime_seconds is None and message_type not in (
                    MessageType.USER_REQUEST,
                    MessageType.BOT_RESPONSE,
                ):
                    from ... import settings

                    lifetime_seconds = getattr(settings, "BOT_MESSAGE_LIFETIME_SECONDS", 300)

                expires_at = None
                if lifetime_seconds:
                    expires_at = datetime_now() + timedelta(seconds=lifetime_seconds)

                message = ChatMessageModel(
                    FID=kwargs["message_id"],
                    FK_Chat=kwargs["chat_id"],
                    FK_User=kwargs.get("user_id"),
                    FK_MessageType=message_type,
                    FText=kwargs["text"][:4096],
                    FSource=MessageSource.BOT,
                    FDateSent=datetime_now(),
                    FFlagReply=bool(kwargs.get("reply_to_message_id")),
                    FFlagDeleted=False,
                    FLifetimeSeconds=lifetime_seconds,
                    FExpiresAt=expires_at,
                )

                session.add(message)
                await session.commit()
                return message

        except Exception as e:
            tg_logger.error(f"❌ Failed to save message: {e}")
            return None

    async def _mark_message_deleted(self, chat_id: int, message_id: int, deleted_by_type: str) -> None:
        """Отметка сообщения как удаленного в БД"""
        try:
            async with self._db.get_session() as session:
                await ChatRepository.mark_message_deleted(
                    session=session,
                    message_id=message_id,
                    chat_id=chat_id,
                    deleted_by_type=deleted_by_type,
                )
        except Exception as e:
            tg_logger.warning(f"⚠️ Failed to mark message {message_id} as deleted: {e}")

    @staticmethod
    async def _ensure_user_exists(session: AsyncSession, **kwargs: Any) -> Any:
        """Проверка/создание пользователя"""
        return await UserRepository.save_user(
            session=session,
            user_id=kwargs["user_id"],
            first_name=kwargs.get("first_name"),
            last_name=kwargs.get("last_name"),
            username=kwargs.get("username"),
            is_bot=kwargs.get("is_bot", False),
            phone=kwargs.get("phone"),
            avanpost_id=kwargs.get("user_id"),
            chat_id=kwargs.get("chat_id"),
            avanpost_group_id=kwargs.get("group_id"),
        )

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

    # ==================== РЕДАКТИРОВАНИЕ И УДАЛЕНИЕ ====================

    @log_exceptions(tg_logger)
    async def edit_message(
        self,
        chat_id: int,
        message_id: int,
        text: str,
        parse_mode: str | ParseMode | None = None,
        reply_markup: Any = None,
        **kwargs: Any,
    ) -> dict[str, Any]:
        """Редактирование сообщения"""
        if not self._bot:
            return {"success": False, "error": "Bot not initialized"}

        try:
            parse_mode = self._normalize_parse_mode(parse_mode)
            message = await self._bot.edit_message_text(
                chat_id=chat_id,
                message_id=message_id,
                text=text,
                parse_mode=parse_mode,
                reply_markup=reply_markup,
                **kwargs,
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
            tg_logger.error(f"❌ Failed to edit message: {e}")
            return {"success": False, "error": str(e), "chat_id": chat_id, "message_id": message_id}

    async def edit_callback_message(
        self,
        callback: CallbackQuery,
        text: str,
        parse_mode: str | ParseMode | None = None,
        reply_markup: Any = None,
        **kwargs: Any,
    ) -> dict[str, Any]:
        """Редактирование сообщения из callback"""
        tg_manager = get_tg_manager()

        if not callback.message or not callback.message.chat:
            return {"success": False, "error": "No message in callback"}

        tg_logger.debug(
            f"📝 Editing callback message: chat={callback.message.chat.id}, msg={callback.message.message_id}"
        )
        tg_logger.debug(f"📝 New text: {text[:100]}...")

        await tg_manager.send_toast(event=callback)

        result = await self.edit_message(
            chat_id=callback.message.chat.id,
            message_id=callback.message.message_id,
            text=text,
            parse_mode=parse_mode,
            reply_markup=reply_markup,
            **kwargs,
        )
        tg_logger.debug(f"📝 Edit result: {result}")
        return result

    @log_exceptions(tg_logger)
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
                tg_logger.debug(f"⚠️ Aiogram delete failed: {e}")

        if not client_used and self._telethon:
            try:
                await self._telethon.delete_messages(chat_id, [message_id])
                result = {"success": True, "chat_id": chat_id, "message_id": message_id}
                client_used = "telethon"
            except Exception as e:
                tg_logger.error(f"❌ Telethon delete failed: {e}")

        if not result or not result.get("success"):
            return {"success": False, "error": "No clients available", "chat_id": chat_id, "message_id": message_id}

        await self._mark_message_deleted(chat_id, message_id, client_used or "system")
        return result

    @log_exceptions(tg_logger)
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
                old_messages = await MessageRepository.get_messages_by_filter(
                    session=session,
                    chat_id=chat_id,
                    before_minutes=before_minutes,
                    message_types=message_types,
                    exclude_message_types=exclude_message_types,
                )

                result["total_found"] = len(old_messages)

                if not old_messages:
                    tg_logger.debug("ℹ️ No old messages to clean up")
                    return result

                from collections import defaultdict

                messages_by_chat: dict[int, list[ChatMessageModel]] = defaultdict(list)
                for msg in old_messages:
                    messages_by_chat[msg.FK_Chat].append(msg)

                total_marked = 0
                total_kept = 0
                total_telegram_deleted = 0

                for chat_id, messages in messages_by_chat.items():
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
                                delete_result = await self.delete_message_by_id(chat_id=chat_id, message_id=msg_id)
                                if delete_result.get("success"):
                                    total_telegram_deleted += 1
                            except Exception as e:
                                tg_logger.warning(f"⚠️ Error deleting message {msg_id}: {e}")

                        deleted = await MessageRepository.mark_messages_deleted_by_ids(
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
                    tg_logger.info(
                        f"🧹 Cleaned up {total_marked} old messages "
                        f"(types: {types_str}{excluded_str}, "
                        f"kept {total_kept}, "
                        f"telegram_deleted: {total_telegram_deleted}, "
                        f"found {len(old_messages)}, chats: {len(messages_by_chat)})"
                    )

                return result

        except Exception as e:
            tg_logger.error(f"❌ Failed to cleanup old messages: {e}", exc_info=True)
            return result

    @log_exceptions(tg_logger)
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
        **kwargs: Any,
    ) -> dict[str, Any]:
        """Отправка фото"""
        if not self._bot:
            return {"success": False, "error": "Bot not initialized"}

        if message_type is None:
            message_type = MessageType.BOT_RESPONSE

        try:
            if isinstance(photo, bytes):
                photo = BufferedInputFile(photo, filename=filename or "photo.jpg")

            parse_mode = self._normalize_parse_mode(parse_mode)

            message = await self._bot.send_photo(
                chat_id=chat_id,
                photo=photo,
                caption=caption,
                parse_mode=parse_mode,
                reply_markup=reply_markup,
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
                    **kwargs,
                )

            return {
                "success": True,
                "message_id": message.message_id,
                "chat_id": chat_id,
                "message": message,
            }

        except Exception as e:
            tg_logger.error(f"❌ Failed to send photo: {e}")
            return {"success": False, "error": str(e), "chat_id": chat_id}

    # ==================== СТАТУС ====================

    async def get_status(self) -> dict[str, Any]:
        return {
            "initialized": self._initialized,
            "aiogram_available": bool(self._bot),
            "telethon_available": bool(self._telethon),
            "service": "unified_message",
        }

    async def health_check(self) -> bool:
        if not self._initialized:
            return False
        try:
            if self._bot:
                await self._bot.get_me()
            return True
        except Exception:
            return False

    _AIAGRAM_IGNORED_PARAMS = {
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
    }


__all__ = ["UnifiedMessageService"]
