import time
from collections.abc import Awaitable, Callable
from typing import Any

from aiogram import BaseMiddleware
from aiogram.exceptions import TelegramAPIError
from aiogram.types import CallbackQuery, Message, TelegramObject

from ...config import settings
from ...core import RateLimitConfig, RateLimitScope, rate_limit_manager
from ...logger import tg_logger
from .utils import get_user_id


class RateLimitMiddleware(BaseMiddleware):
    """Middleware для ограничения частоты запросов в Telegram"""

    def __init__(
        self,
        limit: int | None = None,
        period: int | None = None,
        command_limit: int | None = None,
        command_period: int = 10,
        whitelist: list[int] | None = None,
        component: str = "tg",
        send_warning: bool = True,
        warning_message: str = "⏳ Слишком много запросов. Пожалуйста, подождите немного.",
    ) -> None:
        super().__init__()

        self.component = component
        self.command_limit = command_limit or (limit or 5)
        self.command_period = command_period

        # Приводим whitelist к правильному типу
        if whitelist is not None:
            self.whitelist: list[int] = whitelist
        else:
            admin_ids = getattr(settings, "ADMIN_IDS", [])
            if isinstance(admin_ids, list):
                self.whitelist = [int(x) for x in admin_ids if isinstance(x, int)]
            else:
                self.whitelist = []

        self.send_warning = send_warning
        self.warning_message = warning_message

        # Получаем значения с правильными типами
        tg_rate_limit: int = getattr(settings, "TG_RATE_LIMIT", 10)
        tg_command_limit: int = getattr(settings, "TG_COMMAND_LIMIT", 5)

        # Регистрируем Telegram scope
        config = RateLimitConfig(
            limit=limit if limit is not None else tg_rate_limit,
            period=period if period is not None else 60,
            whitelist=self.whitelist,  # type: ignore[arg-type]  # list[int] совместим с list[int | str]
        )
        rate_limit_manager.register_scope(RateLimitScope.TELEGRAM, config)

        # Регистрируем Command scope (отдельный лимитер для команд)
        command_config = RateLimitConfig(
            limit=command_limit if command_limit is not None else tg_command_limit,
            period=command_period,
            whitelist=self.whitelist,  # type: ignore[arg-type]
        )
        rate_limit_manager.register_scope(RateLimitScope.COMMAND, command_config)

        self._limiter = rate_limit_manager

    async def __call__(
        self,
        handler: Callable[[TelegramObject, dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: dict[str, Any],
    ) -> Any:
        """Проверка лимита запросов"""
        # Проверка только сообщений и callback
        if not isinstance(event, Message | CallbackQuery):
            return await handler(event, data)

        user_id = get_user_id(event)
        if user_id is None:
            return await handler(event, data)

        # Пропуск пользователей из белого списка
        if user_id in self.whitelist:
            return await handler(event, data)

        # Определение типа запроса (команда или обычный)
        is_command = isinstance(event, Message) and event.text is not None and event.text.startswith("/")

        # Выбор scope
        scope = RateLimitScope.COMMAND if is_command else RateLimitScope.TELEGRAM
        key = f"user_{user_id}"

        # Контекст для проверки
        context = {"user_id": user_id, "is_command": is_command, "chat_id": self._get_chat_id(event)}

        # Проверка лимита
        if not rate_limit_manager.is_allowed(scope, key, context=context):
            tg_logger.warning(
                f"Rate limit exceeded for user {user_id}",
                component=self.component,
                user_id=user_id,
                extra={"is_command": is_command},
            )

            # Отправка предупреждения
            if self.send_warning:
                await self._send_warning(event, user_id, scope, is_command)

            return None

        return await handler(event, data)

    async def _send_warning(self, event: TelegramObject, user_id: int, scope: RateLimitScope, is_command: bool) -> None:
        """Отправка предупреждения пользователю"""
        key = f"user_{user_id}"
        remaining = rate_limit_manager.get_remaining(scope, key)
        reset_time = rate_limit_manager.get_reset_time(scope, key)

        # Получаем информацию о блокировке
        entry_info = None
        limiter = rate_limit_manager.get_limiter(scope)
        if limiter:
            entry_info = limiter.get_entry_info(key)

        is_blocked = entry_info.get("is_blocked", False) if entry_info else False

        # Формирование сообщения
        if is_blocked:
            if reset_time:
                remaining_seconds = int(reset_time - time.time())
                if remaining_seconds > 0:
                    minutes = remaining_seconds // 60
                    seconds = remaining_seconds % 60

                    if minutes > 0:
                        message = f"⛔ Вы заблокированы. Осталось {minutes} мин {seconds} сек."
                    else:
                        message = f"⛔ Вы заблокированы. Осталось {seconds} сек."
                else:
                    message = "⛔ Вы заблокированы. Попробуйте позже."
            else:
                message = "⛔ Вы заблокированы за чрезмерную активность."
        else:
            if is_command:
                # Используем публичный метод для получения конфигурации
                config = rate_limit_manager.get_config(RateLimitScope.COMMAND)
                period = config.period if config else self.command_period

                message = f"⏳ Слишком много команд.\nОсталось запросов: {remaining}\nПопробуйте через {period} секунд."
            else:
                message = self.warning_message

        # Отправка сообщения
        try:
            if isinstance(event, Message):
                await event.answer(message)
            elif isinstance(event, CallbackQuery):
                await event.answer(message, show_alert=False)
        except TelegramAPIError as e:
            tg_logger.warning(f"Could not send rate limit warning: {e}", component=self.component, user_id=user_id)

    @staticmethod
    def _get_chat_id(event: TelegramObject) -> int | None:
        """Получение ID чата из события"""
        if isinstance(event, Message):
            # Явно приводим к int
            chat_id = event.chat.id
            return int(chat_id) if chat_id is not None else None
        elif isinstance(event, CallbackQuery) and event.message:
            # Явно приводим к int
            chat_id = event.message.chat.id
            return int(chat_id) if chat_id is not None else None
        return None

    def get_stats(self) -> dict[str, Any]:
        """Получение статистики ограничителя"""
        return {
            "general": rate_limit_manager.get_stats(RateLimitScope.TELEGRAM),
            "commands": rate_limit_manager.get_stats(RateLimitScope.COMMAND),
            "whitelist_size": len(self.whitelist),
        }

    def reset_user(self, user_id: int) -> None:
        """Сброс ограничений для пользователя"""
        key = f"user_{user_id}"
        rate_limit_manager.reset_key(RateLimitScope.TELEGRAM, key)
        rate_limit_manager.reset_key(RateLimitScope.COMMAND, key)

        tg_logger.info(f"Rate limits reset for user {user_id}", component=self.component, user_id=user_id)


__all__ = ["RateLimitMiddleware"]
