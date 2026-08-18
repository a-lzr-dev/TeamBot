import time
from collections.abc import Awaitable, Callable
from typing import Any

from aiogram import BaseMiddleware
from aiogram.types import CallbackQuery, Message, TelegramObject, Update

from ...db import DBManager
from ...db.repositories import ChatRepository, UserRepository
from ...logger import bot_logger
from .utils import get_chat_id, get_message_preview, get_user_id


class LoggingMiddleware(BaseMiddleware):
    """Middleware для логирования обновлений Bot-а"""

    def __init__(self, log_requests: bool = True, log_updates: bool = True, component: str = "bot") -> None:
        self.log_requests = log_requests
        self.log_updates = log_updates
        self.component = component
        super().__init__()

    async def __call__(
        self,
        handler: Callable[[TelegramObject, dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: dict[str, Any],
    ) -> Any:
        """Логирование входящих обновлений"""
        user_id = get_user_id(event)
        chat_id = get_chat_id(event)

        # Логирование обновления
        if self.log_updates:
            bot_logger.log_telegram_event(
                event_type=self._get_event_type(event),
                user_id=user_id,
                chat_id=chat_id,
                extra={
                    "update_id": self._get_update_id(event),
                    "message_preview": get_message_preview(event) if isinstance(event, Message) else None,
                },
            )

        # Замер времени выполнения
        start_time = time.time()

        try:
            result = await handler(event, data)

            # Логирование успешного выполнения
            if self.log_requests:
                duration_ms = (time.time() - start_time) * 1000
                bot_logger.info(
                    f"Handler completed: {self._get_event_type(event)}",
                    extra={"duration_ms": duration_ms, "user_id": user_id, "chat_id": chat_id},
                )

            return result

        except Exception as e:
            duration_ms = (time.time() - start_time) * 1000
            bot_logger.log_error(
                error=e,
                message=f"Handler failed: {self._get_event_type(event)}",
                extra={
                    "duration_ms": duration_ms,
                    "user_id": user_id,
                    "chat_id": chat_id,
                    "event_type": self._get_event_type(event),
                    "update_id": self._get_update_id(event),
                },
            )
            raise

    def _get_event_type(self, event: TelegramObject) -> str:
        """Определение типа события"""
        if isinstance(event, Message):
            if event.text and event.text.startswith("/"):
                return f"command_{event.text.split()[0]}"
            return f"message_{event.content_type.value if hasattr(event.content_type, 'value') else event.content_type}"
        if isinstance(event, CallbackQuery):
            return f"callback_{event.data[:20] if event.data else 'unknown'}"
        if isinstance(event, Update):
            return self._get_update_type(event)
        return type(event).__name__

    @staticmethod
    def _get_update_type(update: Update) -> str:
        """Определение типа обновления"""
        types = {
            "message": update.message,
            "edited_message": update.edited_message,
            "channel_post": update.channel_post,
            "edited_channel_post": update.edited_channel_post,
            "callback_query": update.callback_query,
            "inline_query": update.inline_query,
            "chat_member": update.chat_member,
            "my_chat_member": update.my_chat_member,
            "chat_join_request": update.chat_join_request,
        }
        for name, value in types.items():
            if value:
                return name
        return "unknown"

    @staticmethod
    def _get_update_id(event: TelegramObject) -> int | None:
        """Получение ID обновления"""
        if isinstance(event, Update):
            update_id = event.update_id
            if isinstance(update_id, int):
                return update_id
            return None
        return None


class ChatActivityMiddleware(BaseMiddleware):
    """Middleware для отслеживания активности в чатах"""

    def __init__(self, db_manager: DBManager, update_interval: int = 60, component: str = "bot") -> None:
        self.db_manager = db_manager
        self.update_interval = update_interval
        self.component = component
        self._last_updates: dict[int, float] = {}
        super().__init__()

    async def __call__(
        self,
        handler: Callable[[TelegramObject, dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: dict[str, Any],
    ) -> Any:
        """Обновление времени последней активности"""
        if isinstance(event, Message) and event.from_user and event.chat:
            chat_id = event.chat.id
            user = event.from_user

            current_time = time.time()
            last_update = self._last_updates.get(chat_id, 0)

            if current_time - last_update >= self.update_interval:
                try:
                    await self._update_activity(event, user)
                    self._last_updates[chat_id] = current_time
                except Exception as e:
                    bot_logger.log_error(
                        error=e,
                        message="Failed to update chat activity",
                        extra={"chat_id": chat_id, "user_id": user.id},
                    )

        return await handler(event, data)

    async def _update_activity(self, message: Message, user: Any) -> None:
        """
        Обновление активности пользователя и чата через репозитории.

        Args:
            message: Объект сообщения
            user: Объект пользователя (уже проверен на None)
        """
        from ...models import datetime_now

        now = datetime_now()
        user_id = user.id
        chat_id = message.chat.id

        async with self.db_manager.get_session() as session:
            try:
                # Обновление пользователя через репозиторий
                db_user = await UserRepository.get_user_by_id(session, user_id)
                if db_user:
                    # Обновляем только если данные изменились
                    if db_user.FFirstName != user.first_name:
                        db_user.FFirstName = user.first_name
                    if db_user.FLastName != user.last_name:
                        db_user.FLastName = user.last_name
                    if db_user.FUserName != user.username:
                        db_user.FUserName = user.username

                    # Обновляем время последней активности
                    db_user.FDateLastActivity = now

                    await session.flush()
                    bot_logger.debug(f"✅ User {user_id} activity updated")
                else:
                    # Создание пользователя, если его нет
                    await UserRepository.save_user(
                        session=session,
                        user_id=user_id,
                        chat_id=chat_id,
                        first_name=user.first_name,
                        last_name=user.last_name,
                        username=user.username,
                        is_bot=user.is_bot,
                    )
                    bot_logger.debug(f"✅ New user {user_id} created from activity")

                # Обновление чата через репозиторий
                chat = await ChatRepository.get_chat_by_id(session, chat_id)
                if chat:
                    chat.FDateUpdated = now
                    chat.FCountMessages = (chat.FCountMessages or 0) + 1

                    if message.chat.title and chat.FTitle != message.chat.title:
                        chat.FTitle = message.chat.title

                    await session.flush()
                    bot_logger.debug(f"✅ Chat {chat_id} activity updated")
                else:
                    # Создание чата, если его нет
                    from ...core.converters import chat_type_from_aiogram, chat_type_to_str

                    chat_type = chat_type_from_aiogram(message.chat)
                    chat_type_str = chat_type_to_str(chat_type)

                    await ChatRepository.save_chat(
                        session=session,
                        chat_id=chat_id,
                        chat_type=chat_type_str,
                        title=message.chat.title,
                        is_active=True,
                    )
                    bot_logger.debug(f"✅ New chat {chat_id} created from activity")

                await session.commit()

                bot_logger.debug(
                    f"Chat activity updated: chat={chat_id}, user={user_id}",
                    extra={"chat_id": chat_id, "user_id": user_id},
                )

            except Exception as e:
                bot_logger.error(f"❌ Failed to update activity: {e}", exc_info=True)
                await session.rollback()
                raise


__all__ = [
    "LoggingMiddleware",
    "ChatActivityMiddleware",
]
