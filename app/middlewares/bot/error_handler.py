"""
Middleware для обработки ошибок в обработчиках Telegram бота.

Назначение:
    Централизованный перехват и обработка исключений во всех обработчиках
    Aiogram с логированием и уведомлением пользователя.

Основные функции:
    1. Перехват всех исключений в обработчиках
    2. Логирование ошибок через ErrorService с контекстом
    3. Отправка уведомления пользователю об ошибке
    4. Сбор информации о событии (Message или CallbackQuery)
    5. Проброс исключения после обработки

Технические особенности:
    - Интеграция с Aiogram через BaseMiddleware
    - Поддержка Message и CallbackQuery событий
    - Извлечение user_id и chat_id из события
    - Сбор краткой информации о событии для контекста
    - Безопасная отправка ответа пользователю

Архитектура:
    - Реализует интерфейс BaseMiddleware от Aiogram
    - Интегрируется с ErrorService для логирования
    - Использует bot_logger для логирования
"""

from collections.abc import Awaitable, Callable
from typing import Any

from aiogram import BaseMiddleware
from aiogram.exceptions import TelegramAPIError
from aiogram.types import CallbackQuery, Message, TelegramObject

from ...logger import bot_logger

# ============================================================
# 1. КЛАСС MIDDLEWARE ДЛЯ ОБРАБОТКИ ОШИБОК
# ============================================================


class ErrorHandlerMiddleware(BaseMiddleware):
    """
    Middleware для обработки ошибок в обработчиках Telegram.

    Перехватывает все исключения в обработчиках, логирует их через
    ErrorService и отправляет уведомление пользователю.

    Пример использования в Aiogram:
        dp.update.outer_middleware(ErrorHandlerMiddleware())

    Flow обработки ошибки:
        1. Перехват исключения
        2. Логирование с контекстом (user_id, chat_id, событие)
        3. Отправка уведомления пользователю
        4. Проброс исключения дальше
    """

    # ============================================================
    # 1.1. ОСНОВНОЙ МЕТОД ОБРАБОТКИ СОБЫТИЯ
    # ============================================================

    async def __call__(
        self,
        handler: Callable[[TelegramObject, dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: dict[str, Any],
    ) -> Any:
        """
        Основной метод обработки события с перехватом ошибок.

        Args:
            handler: Функция-обработчик события
            event: Объект события (Message, CallbackQuery и т.д.)
            data: Данные контекста для передачи обработчику

        Returns:
            Any: Результат выполнения обработчика

        Flow:
            1. Попытка выполнения обработчика
            2. При ошибке — логирование через ErrorService
            3. Отправка уведомления пользователю
            4. Проброс исключения
        """
        try:
            return await handler(event, data)

        except Exception as e:
            # 1. Логирование ошибки
            bot_logger.error(f"❌ Handler error: {e}", exc_info=True)

            from ...services import error_service

            # 2. Определение user_id и chat_id для контекста
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

            # 3. Логирование ошибки через ErrorService
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

            # 4. Отправка ответа пользователю
            await self._send_error_response(event, e)

            # 5. Проброс исключения
            raise

    # ============================================================
    # 1.2. ВСПОМОГАТЕЛЬНЫЕ МЕТОДЫ
    # ============================================================

    @staticmethod
    def _get_event_summary(event: TelegramObject) -> dict[str, Any]:
        """
        Получение краткой информации о событии для контекста.

        Args:
            event: Объект события (Message или CallbackQuery)

        Returns:
            dict[str, Any]: Краткая информация о событии
        """
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
        """
        Отправка ответа пользователю об ошибке.

        Args:
            event: Объект события (Message или CallbackQuery)
            _: Исключение (не используется, но сохраняется для совместимости)
        """
        try:
            if isinstance(event, Message):
                await event.answer("❌ Произошла ошибка при обработке запроса.\nАдминистратор уже уведомлен.")
            elif isinstance(event, CallbackQuery):
                await event.answer("❌ Произошла ошибка. Попробуйте позже.", show_alert=True)
        except TelegramAPIError:
            bot_logger.warning("⚠️ Could not send error notification to user")


__all__ = [
    "ErrorHandlerMiddleware",
]
