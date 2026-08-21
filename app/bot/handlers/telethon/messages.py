from typing import TYPE_CHECKING

from aiogram.enums import ContentType
from telethon import TelegramClient, events

from ....config import settings
from ....core.converters import chat_type_from_telethon, user_info_from_telethon
from ....db.manager import db_manager
from ....db.repositories import ChatRepository, MessageRepository, UserRepository
from ....exceptions import log_exceptions
from ....logger import bot_logger
from ....models import (
    ErrorCategory,
    MessageSource,
    MessageType,
    datetime_now,
)
from ...utils import message_info_from_telethon, save_media_info_to_model

if TYPE_CHECKING:
    from telethon.tl.types import TypeMessage

# Репозитории (создаем один раз на уровне модуля)
_user_repo = UserRepository()
_chat_repo = ChatRepository()
_message_repo = MessageRepository()


@log_exceptions(bot_logger)
async def handle_new_message(event: events.NewMessage.Event, client: TelegramClient) -> None:
    """Обработчик новых сообщений через Telethon"""
    bot_logger.debug("handle_new_message")

    message: TypeMessage | None = event.message

    if not message:
        return
    try:
        me = await client.get_me()
        if message.sender_id == me.id:
            bot_logger.debug(f"⏭️ Skipping bot's own message {message.id}")
            return
    except Exception:
        pass

    has_content = (
        message.text
        or getattr(message, "caption", None)
        or message.photo
        or message.document
        or message.video
        or message.audio
        or message.voice
        or message.sticker
        or getattr(message, "gif", None)
        or message.contact
        or getattr(message, "location", None)
        or message.poll
    )

    if not has_content:
        return

    bot_logger.debug(f"📩 New message from {message.sender_id} in chat {message.chat_id}")

    chat_created = False
    async with db_manager.get_session() as session:
        try:
            # Проверка существования чата через репозиторий
            existing_chat = await _chat_repo.get_chat_by_id(session, message.chat_id)

            if existing_chat is None:
                bot_logger.info(f"🆕 Creating new chat {message.chat_id} in database")

                chat_entity = await client.get_entity(message.chat_id)
                chat_type = chat_type_from_telethon(chat_entity)

                from ....core.converters import chat_type_to_str

                await _chat_repo.save_chat(
                    session=session,
                    chat_id=message.chat_id,
                    chat_type=chat_type_to_str(chat_type),
                    title=getattr(chat_entity, "title", None),
                    is_active=True,
                )

                chat_created = True
                bot_logger.debug(f"✅ Chat {message.chat_id} created and committed")
            else:
                bot_logger.debug(f"✅ Chat {message.chat_id} already exists")

        except Exception as err:
            bot_logger.error(f"❌ Failed to create/find chat: {err}", exc_info=True)
            await session.rollback()
            return

    async with db_manager.get_session() as session:
        try:
            user_id = message.sender_id
            is_valid_user = user_id is not None and user_id > 0

            if is_valid_user:
                try:
                    sender = await client.get_entity(user_id)
                    user_info = user_info_from_telethon(sender)

                    await _user_repo.save_user(
                        session=session,
                        user_id=user_info["user_id"],
                        is_bot=user_info["is_bot"],
                        first_name=user_info["first_name"] or "",
                        last_name=user_info["last_name"],
                        username=user_info["username"] or f"user_{user_info['user_id']}",
                    )
                except Exception as err:
                    bot_logger.warning(f"⚠️ Failed to save sender {user_id}: {err}")
                    user_id = None
            else:
                bot_logger.debug(f"ℹ️ Skipping sender save for non-user ID: {user_id}")
                user_id = None

            # Проверка существования сообщения через репозиторий
            existing_message = await _message_repo.get_message_by_id(session, message.id)
            if existing_message:
                if existing_message.FFlagDeleted:
                    bot_logger.debug(f"⏭️ Message {message.id} already marked as deleted, skipping")
                    return

                # Обновление существующего сообщения через репозиторий
                message_text = message.text or getattr(message, "caption", None) or ""
                edit_date = message.edit_date.replace(tzinfo=None) if message.edit_date else None

                await _message_repo.update_message(
                    session=session,
                    message_id=message.id,
                    text=message_text,
                    edit_date=edit_date,
                )
                await session.commit()
                bot_logger.debug(f"✅ Message {message.id} updated in database")
                return

            # Определение типа содержимого
            message_info = message_info_from_telethon(message)
            media_type_str = message_info.get("media_type", "unknown")

            content_type = ContentType.TEXT
            if media_type_str == "photo":
                content_type = ContentType.PHOTO
            elif media_type_str == "video":
                content_type = ContentType.VIDEO
            elif media_type_str == "audio":
                content_type = ContentType.AUDIO
            elif media_type_str == "document":
                content_type = ContentType.DOCUMENT
            elif media_type_str == "voice":
                content_type = ContentType.VOICE
            elif media_type_str == "sticker":
                content_type = ContentType.STICKER
            elif media_type_str == "animation":
                content_type = ContentType.ANIMATION
            elif media_type_str == "contact":
                content_type = ContentType.CONTACT
            elif media_type_str == "location":
                content_type = ContentType.LOCATION
            elif media_type_str == "poll":
                content_type = ContentType.POLL

            message_text = ""
            if hasattr(message, "text") and message.text:
                message_text = message.text
            elif hasattr(message, "caption") and message.caption:
                message_text = message.caption
            elif hasattr(message, "poll") and message.poll:
                message_text = getattr(message.poll, "question", "")

            # Получение времени жизни из настроек
            lifetime_seconds = settings.MESSAGE_LIFETIME_DEFAULT_SECONDS

            chat_message = await _message_repo.create_message(
                session=session,
                message_id=message.id,
                chat_id=message.chat_id,
                user_id=user_id,
                message_type=MessageType.USER_REQUEST,
                text=message_text,
                source=MessageSource.USER,
                reply_to_message_id=message.reply_to_msg_id if hasattr(message, "reply_to_msg_id") else None,
                content_type=content_type,
                lifetime_seconds=lifetime_seconds,
                is_forwarded=bool(message.forward),
                is_reply=bool(message.reply_to),
            )

            # Сохранение медиа-информации (если есть)
            save_media_info_to_model(chat_message, message)

            await session.commit()

            bot_logger.debug(f"✅ Message {message.id} saved to database with lifetime {lifetime_seconds}s")

        except Exception as err:
            bot_logger.error(f"❌ Failed to save message: {err}", exc_info=True)
            await session.rollback()

            from ....services.error_service import error_service

            await error_service.log_error(
                error=err,
                chat_id=message.chat_id,
                user_id=user_id if user_id and user_id > 0 else None,
                message_id=message.id,
                category=ErrorCategory.TASK_EXECUTION,
                context={
                    "event_type": "new_message",
                    "has_text": bool(message.text or getattr(message, "caption", None)),
                    "has_media": bool(message.photo or message.document),
                    "chat_created": chat_created,
                    "sender_id": message.sender_id,
                    "is_valid_user": is_valid_user,
                },
                session=session,
            )


@log_exceptions(bot_logger)
async def handle_edited_message(event: events.MessageEdited.Event, _: TelegramClient) -> None:
    """Обработчик редактирования сообщения"""
    bot_logger.debug("handle_edited_message")

    message: TypeMessage | None = event.message

    if not message:
        return

    bot_logger.debug(f"📝 Message {message.id} edited in chat {message.chat_id}")

    async with db_manager.get_session() as session:
        try:
            # Получение сообщения через репозиторий
            db_message = await _message_repo.get_message_by_id(session, message.id)

            if db_message:
                # Не обновляем удаленные сообщения
                if db_message.FFlagDeleted:
                    bot_logger.debug(f"⏭️ Message {message.id} is deleted, skipping edit")
                    return

                message_text = ""
                if hasattr(message, "text") and message.text:
                    message_text = message.text
                elif hasattr(message, "caption") and message.caption:
                    message_text = message.caption

                db_message.FText = message_text
                db_message.FDateEdited = message.edit_date.replace(tzinfo=None) if message.edit_date else None

                await session.commit()
                bot_logger.debug(f"✅ Message {message.id} updated in database")
            else:
                bot_logger.warning(f"⚠️ Message {message.id} not found in database for edit")

        except Exception as err:
            bot_logger.error(f"❌ Failed to handle edited message: {err}", exc_info=True)
            await session.rollback()

            # Локальный импорт для избежания циклических зависимостей
            from ....services.error_service import error_service

            await error_service.log_error(
                error=err,
                chat_id=message.chat_id,
                user_id=message.sender_id if message.sender_id and message.sender_id > 0 else None,
                message_id=message.id,
                category=ErrorCategory.TASK_EXECUTION,
                context={"event_type": "edited_message"},
                session=session,
            )


@log_exceptions(bot_logger)
async def handle_deleted_message(event: events.MessageDeleted.Event) -> None:
    """Обработчик удаления сообщения"""
    bot_logger.debug("handle_deleted_message")

    if not event.deleted_ids:
        return

    bot_logger.info(f"🗑️ {len(event.deleted_ids)} messages deleted in chat {event.chat_id}")

    async with db_manager.get_session() as session:
        try:
            # Определение, какое сообщение вызвало удаление
            deleted_by_message_id = None
            deleted_by_type = "system"

            # Попытка определения, что вызвало удаление
            if hasattr(event, "action") and event.action:
                if hasattr(event.action, "message_id"):
                    deleted_by_message_id = event.action.message_id
                    deleted_by_type = "user"
                elif hasattr(event.action, "by_id"):
                    deleted_by_type = "admin"

            deleted_count = 0
            for msg_id in event.deleted_ids:
                # Получение сообщения через репозиторий
                db_message = await _message_repo.get_message_by_id(session, msg_id)
                if db_message and not db_message.FFlagDeleted:
                    db_message.FFlagDeleted = True
                    db_message.FDateDeleted = datetime_now()
                    db_message.FK_DeletedByMessage = deleted_by_message_id
                    db_message.FDeletedByType = deleted_by_type
                    deleted_count += 1
                    bot_logger.debug(f"✅ Marked message {msg_id} as deleted (by {deleted_by_type})")

            await session.commit()
            bot_logger.info(f"✅ Marked {deleted_count} messages as deleted in chat {event.chat_id}")

        except Exception as err:
            bot_logger.error(f"❌ Failed to mark deleted messages: {err}", exc_info=True)
            await session.rollback()

            # Локальный импорт для избежания циклических зависимостей
            from ....services.error_service import error_service

            await error_service.log_error(
                error=err,
                chat_id=event.chat_id,
                category=ErrorCategory.TASK_EXECUTION,
                context={
                    "event_type": "message_deleted",
                    "message_ids": event.deleted_ids[:10],
                    "deleted_count": len(event.deleted_ids),
                },
                session=session,
            )


__all__ = [
    "handle_new_message",
    "handle_edited_message",
    "handle_deleted_message",
]
