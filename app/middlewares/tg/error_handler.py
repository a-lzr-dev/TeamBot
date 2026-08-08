from collections.abc import Awaitable, Callable
from typing import Any

from aiogram import BaseMiddleware
from aiogram.exceptions import TelegramAPIError
from aiogram.types import CallbackQuery, Message, TelegramObject

from ...logger import tg_logger


class ErrorHandlerMiddleware(BaseMiddleware):
    """Middleware для обработки ошибок в обработчиках Telegram"""

    async def __call__(
        self,
        handler: Callable[[TelegramObject, dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: dict[str, Any],
    ) -> Any:
        """Обработка входящего события с перехватом ошибок"""
        try:
            return await handler(event, data)
        except Exception as e:
            tg_logger.error(f"❌ Handler error: {e}", exc_info=True)

            from ...services import error_service

            # Определяем user_id и chat_id для контекста
            user_id = None
            chat_id = None

            if isinstance(event, Message):
                if event.from_user:
                    user_id = event.from_user.id
                if event.chat:
                    chat_id = event.chat.id
            elif isinstance(event, CallbackQuery):
                if event.from_user:
                    user_id = event.from_user.id
                if event.message and event.message.chat:
                    chat_id = event.message.chat.id

            # Логирование ошибки через существующий метод
            await error_service.log_error(
                error=e,
                component="telegram_middleware",
                user_id=user_id,
                chat_id=chat_id,
                category="handler_error",
                context={
                    "event_type": type(event).__name__,
                    "event_data": self._get_event_summary(event),
                },
                session=data.get("session"),
            )

            # Отправка ответа пользователю
            await self._send_error_response(event, e)
            raise

    @staticmethod
    def _get_event_summary(event: TelegramObject) -> dict[str, Any]:
        """Получение краткой информации о событии для контекста"""
        summary: dict[str, Any] = {"type": type(event).__name__}

        if isinstance(event, Message):
            summary["message_id"] = event.message_id
            if event.text:
                summary["text"] = event.text[:100]
            elif event.caption:
                summary["caption"] = event.caption[:100]
            summary["content_type"] = str(event.content_type) if hasattr(event, "content_type") else None

        elif isinstance(event, CallbackQuery):
            summary["callback_id"] = event.id
            summary["data"] = event.data[:100] if event.data else None
            if event.message:
                summary["message_id"] = event.message.message_id

        return summary

    @staticmethod
    async def _send_error_response(event: TelegramObject, _: Exception) -> None:
        """Отправка ответа пользователю об ошибке"""
        try:
            if isinstance(event, Message):
                await event.answer("❌ Произошла ошибка при обработке запроса.\nАдминистратор уже уведомлен.")
            elif isinstance(event, CallbackQuery):
                await event.answer("❌ Произошла ошибка. Попробуйте позже.", show_alert=True)
        except TelegramAPIError:
            tg_logger.warning("⚠️ Could not send error notification to user")


__all__ = [
    "ErrorHandlerMiddleware",
]
