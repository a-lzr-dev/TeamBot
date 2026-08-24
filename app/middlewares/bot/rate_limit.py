"""
Middleware для ограничения частоты запросов в Telegram боте.

Назначение:
    Защита бота от чрезмерного количества запросов от пользователей
    путём ограничения частоты сообщений и команд.

Основные функции:
    1. Ограничение количества сообщений от одного пользователя
    2. Отдельное ограничение для команд (более строгое)
    3. Белый список для администраторов и доверенных пользователей
    4. Отправка предупреждений при превышении лимита
    5. Блокировка при многократном превышении лимита
    6. Сброс ограничений для пользователя

Технические особенности:
    - Интеграция с Aiogram через BaseMiddleware
    - Отдельные лимиты для обычных сообщений и команд
    - Использование rate_limit_manager для управления лимитами
    - Поддержка белого списка (администраторы)
    - Блокировка при превышении лимита

Безопасность:
    - Защита от спама и флуда
    - Индивидуальные лимиты для каждого пользователя
    - Автоматическая блокировка при злоупотреблениях
    - Возможность сброса лимитов администратором

Архитектура:
    - Реализует интерфейс BaseMiddleware от Aiogram
    - Интегрируется с rate_limit_manager
    - Использует RateLimitScope для разделения лимитов
"""

import time
from collections.abc import Awaitable, Callable
from typing import Any

from aiogram import BaseMiddleware
from aiogram.exceptions import TelegramAPIError
from aiogram.types import CallbackQuery, Message, TelegramObject

from ...config import settings
from ...core import RateLimitConfig, RateLimitScope, rate_limit_manager
from ...logger import bot_logger
from .utils import get_user_id

# ============================================================
# 1. КЛАСС MIDDLEWARE ДЛЯ ОГРАНИЧЕНИЯ ЗАПРОСОВ
# ============================================================


class RateLimitMiddleware(BaseMiddleware):
    """
    Middleware для ограничения частоты запросов бота.

    Ограничивает количество сообщений и команд от одного пользователя
    за определённый период времени.

    Пример использования в Aiogram:
        dp.update.outer_middleware(
            RateLimitMiddleware(
                limit=10,
                period=60,
                command_limit=5,
                command_period=10,
                whitelist=[123456789],
                send_warning=True
            )
        )

    Attributes:
        component (str): Имя компонента для логирования
        command_limit (int): Лимит команд за период
        command_period (int): Период для команд в секундах
        whitelist (list[int]): Список ID пользователей в белом списке
        send_warning (bool): Отправлять предупреждение при превышении
        warning_message (str): Текст предупреждения
        _limiter (RateLimitManager): Менеджер ограничений
    """

    def __init__(
        self,
        limit: int | None = None,
        period: int | None = None,
        command_limit: int | None = None,
        command_period: int = 10,
        whitelist: list[int] | None = None,
        component: str = "bot",
        send_warning: bool = True,
        warning_message: str = "⏳ Слишком много запросов. Пожалуйста, подождите немного.",
    ) -> None:
        """
        Инициализация middleware ограничения запросов.

        Args:
            limit: Максимальное количество запросов за период (общий)
            period: Период в секундах (общий)
            command_limit: Максимальное количество команд за период
            command_period: Период для команд в секундах
            whitelist: Список ID пользователей без ограничений
            component: Имя компонента для логирования
            send_warning: Отправлять предупреждение при превышении
            warning_message: Текст предупреждения
        """
        super().__init__()

        self.component = component
        self.command_limit = command_limit or (limit or 5)
        self.command_period = command_period
        self.send_warning = send_warning
        self.warning_message = warning_message

        # Приводим whitelist к правильному типу
        if whitelist is not None:
            self.whitelist: list[int] = whitelist
        else:
            admin_ids = getattr(settings, "ADMIN_IDS", [])
            if isinstance(admin_ids, list):
                self.whitelist = [int(x) for x in admin_ids if isinstance(x, int)]
            else:
                self.whitelist = []

        bot_rate_limit: int = getattr(settings, "BOT_RATE_LIMIT", 10)
        bot_command_limit: int = getattr(settings, "BOT_COMMAND_LIMIT", 5)

        # Регистрация Bot scope (общие сообщения)
        config = RateLimitConfig(
            limit=limit if limit is not None else bot_rate_limit,
            period=period if period is not None else 60,
            whitelist=self.whitelist,  # type: ignore[arg-type]
        )
        rate_limit_manager.register_scope(RateLimitScope.BOT, config)

        # Регистрация Command scope (отдельный лимитер для команд)
        command_config = RateLimitConfig(
            limit=command_limit if command_limit is not None else bot_command_limit,
            period=command_period,
            whitelist=self.whitelist,  # type: ignore[arg-type]
        )
        rate_limit_manager.register_scope(RateLimitScope.COMMAND, command_config)

        self._limiter = rate_limit_manager

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
        Основной метод обработки события с проверкой лимита.

        Args:
            handler: Функция-обработчик события
            event: Объект события (Message, CallbackQuery и т.д.)
            data: Данные контекста для передачи обработчику

        Returns:
            Any: Результат выполнения обработчика или None при блокировке

        Flow:
            1. Проверка типа события (только Message и CallbackQuery)
            2. Получение ID пользователя
            3. Проверка белого списка
            4. Определение типа запроса (команда или обычный)
            5. Выбор Scope и проверка лимита
            6. При превышении — отправка предупреждения
            7. Вызов обработчика
        """
        # 1. Проверка типа события (только сообщения и callback)
        if not isinstance(event, Message | CallbackQuery):
            return await handler(event, data)

        # 2. Получение ID пользователя
        user_id = get_user_id(event)
        if user_id is None:
            return await handler(event, data)

        # 3. Пропуск пользователей из белого списка
        if user_id in self.whitelist:
            return await handler(event, data)

        # 4. Определение типа запроса (команда или обычный)
        is_command = isinstance(event, Message) and event.text is not None and event.text.startswith("/")

        # 5. Выбор Scope
        scope = RateLimitScope.COMMAND if is_command else RateLimitScope.BOT
        key = f"user_{user_id}"

        # 6. Контекст для проверки
        context = {"user_id": user_id, "is_command": is_command, "chat_id": self._get_chat_id(event)}

        # 7. Проверка лимита
        if not rate_limit_manager.is_allowed(scope, key, context=context):
            bot_logger.warning(
                f"Rate limit exceeded for user {user_id}",
                component=self.component,
                user_id=user_id,
                extra={"is_command": is_command},
            )

            # 8. Отправка предупреждения
            if self.send_warning:
                await self._send_warning(event, user_id, scope, is_command)

            return None

        # 9. Вызов обработчика
        return await handler(event, data)

    # ============================================================
    # 1.2. ОТПРАВКА ПРЕДУПРЕЖДЕНИЯ
    # ============================================================

    async def _send_warning(self, event: TelegramObject, user_id: int, scope: RateLimitScope, is_command: bool) -> None:
        """
        Отправка предупреждения пользователю при превышении лимита.

        Args:
            event: Объект события
            user_id: ID пользователя
            scope: Scope ограничения (BOT или COMMAND)
            is_command: Является ли запрос командой
        """
        key = f"user_{user_id}"
        remaining = rate_limit_manager.get_remaining(scope, key)
        reset_time = rate_limit_manager.get_reset_time(scope, key)

        # Получение информации о блокировке
        entry_info = None
        limiter = rate_limit_manager.get_limiter(scope)
        if limiter:
            entry_info = limiter.get_entry_info(key)

        is_blocked = entry_info.get("is_blocked", False) if entry_info else False

        # Формирование сообщения в зависимости от состояния
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
            bot_logger.warning(f"Could not send rate limit warning: {e}", component=self.component, user_id=user_id)

    # ============================================================
    # 1.3. ВСПОМОГАТЕЛЬНЫЕ МЕТОДЫ
    # ============================================================

    @staticmethod
    def _get_chat_id(event: TelegramObject) -> int | None:
        """
        Получение ID чата из события.

        Args:
            event: Объект события

        Returns:
            int | None: ID чата или None
        """
        if isinstance(event, Message):
            chat_id = event.chat.id
            return int(chat_id) if chat_id is not None else None
        elif isinstance(event, CallbackQuery) and event.message:
            chat_id = event.message.chat.id
            return int(chat_id) if chat_id is not None else None
        return None

    # ============================================================
    # 1.4. УПРАВЛЕНИЕ ЛИМИТАМИ
    # ============================================================

    def get_stats(self) -> dict[str, Any]:
        """
        Получение статистики ограничителя.

        Returns:
            dict[str, Any]: Статистика по обоим Scope
        """
        return {
            "general": rate_limit_manager.get_stats(RateLimitScope.BOT),
            "commands": rate_limit_manager.get_stats(RateLimitScope.COMMAND),
            "whitelist_size": len(self.whitelist),
        }

    def reset_user(self, user_id: int) -> None:
        """
        Сброс ограничений для пользователя.

        Args:
            user_id: ID пользователя
        """
        key = f"user_{user_id}"
        rate_limit_manager.reset_key(RateLimitScope.BOT, key)
        rate_limit_manager.reset_key(RateLimitScope.COMMAND, key)

        bot_logger.info(f"Rate limits reset for user {user_id}", component=self.component, user_id=user_id)


__all__ = ["RateLimitMiddleware"]
