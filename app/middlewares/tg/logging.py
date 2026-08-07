import time
from collections.abc import Awaitable, Callable
from typing import Any

from aiogram import BaseMiddleware
from aiogram.types import CallbackQuery, Message, TelegramObject, Update

from ...db import DatabaseManager
from ...logger import tg_logger
from .utils import get_chat_id, get_message_preview, get_user_id


class LoggingMiddleware(BaseMiddleware):
    """Middleware для логирования Telegram обновлений"""

    def __init__(self, log_requests: bool = True, log_updates: bool = True, component: str = "tg") -> None:
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
            tg_logger.log_telegram_event(
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
                tg_logger.info(
                    f"Handler completed: {self._get_event_type(event)}",
                    extra={"duration_ms": duration_ms, "user_id": user_id, "chat_id": chat_id},
                )

            return result

        except Exception as e:
            duration_ms = (time.time() - start_time) * 1000
            tg_logger.log_error(
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
            return event.update_id  # type: ignore[no-any-return]
        return None


class ChatActivityMiddleware(BaseMiddleware):
    """Middleware для отслеживания активности в чатах"""

    def __init__(self, db_manager: DatabaseManager, update_interval: int = 60, component: str = "tg") -> None:
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

            current_time = time.time()
            last_update = self._last_updates.get(chat_id, 0)

            if current_time - last_update >= self.update_interval:
                try:
                    await self._update_activity(event)
                    self._last_updates[chat_id] = current_time
                except Exception as e:
                    tg_logger.log_error(
                        error=e,
                        message="Failed to update chat activity",
                        extra={"chat_id": chat_id, "user_id": event.from_user.id},
                    )

        return await handler(event, data)

    async def _update_activity(self, message: Message) -> None:
        """Обновление активности пользователя и чата"""
        from ...models import ChatModel, UserModel, datetime_now

        now = datetime_now()

        async with self.db_manager.get_session() as session:
            user = await session.get(UserModel, message.from_user.id)
            if user:
                user.FDateLastActivity = now
                if user.FFirstName != message.from_user.first_name:
                    user.FFirstName = message.from_user.first_name
                if user.FLastName != message.from_user.last_name:
                    user.FLastName = message.from_user.last_name
                if user.FUserName != message.from_user.username:
                    user.FUserName = message.from_user.username

            chat = await session.get(ChatModel, message.chat.id)
            if chat:
                chat.FDateUpdated = now
                chat.FCountMessages = (chat.FCountMessages or 0) + 1
                if message.chat.title and chat.FTitle != message.chat.title:
                    chat.FTitle = message.chat.title

            await session.commit()

            tg_logger.debug(
                f"Chat activity updated: chat={message.chat.id}, user={message.from_user.id}",
                extra={"chat_id": message.chat.id, "user_id": message.from_user.id},
            )


__all__ = [
    "LoggingMiddleware",
    "ChatActivityMiddleware",
]
