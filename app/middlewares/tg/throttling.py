import time
from collections import defaultdict
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any

from aiogram import BaseMiddleware
from aiogram.exceptions import TelegramAPIError
from aiogram.types import CallbackQuery, Message, TelegramObject

from ...logger import tg_logger
from .utils import get_user


@dataclass
class ThrottleEntry:
    """Запись о последнем обращении пользователя"""

    last_time: float = field(default_factory=time.time)
    count: int = 0
    first_time: float = field(default_factory=time.time)


class ThrottlingMiddleware(BaseMiddleware):
    """Middleware для ограничения частоты обработки (анти-флуд)"""

    def __init__(
        self,
        default_throttle: float = 0.5,  # Минимальное время между обработками в секундах
        burst_limit: int | None = None,  # Максимальное количество "быстрых" запросов
        burst_period: float = 5.0,  # Период для burst-запросов
        whitelist: list | None = None,  # Список ID пользователей без ограничений
        ignore_bots: bool = True,  # Игнорирование ботов
        send_warning: bool = True,  # Отправка предупреждения при throttling
        warning_message: str = "⏳ Пожалуйста, подождите немного перед следующим запросом.",
    ) -> None:
        self.default_throttle = default_throttle
        self.burst_limit = burst_limit
        self.burst_period = burst_period
        self.whitelist = whitelist or []
        self.ignore_bots = ignore_bots
        self.send_warning = send_warning
        self.warning_message = warning_message

        # Хранилище: {user_id: ThrottleEntry}
        self._last_processed: dict[int, ThrottleEntry] = defaultdict(ThrottleEntry)

        super().__init__()

    async def __call__(
        self,
        handler: Callable[[TelegramObject, dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: dict[str, Any],
    ) -> Any:
        """Throttling обработчиков"""

        # Проверка только сообщений и callback от пользователей
        if not isinstance(event, Message | CallbackQuery):
            return await handler(event, data)

        # Получение пользователя
        user = get_user(event)
        if user is None:
            return await handler(event, data)

        # Игнорирование ботов
        if self.ignore_bots and getattr(user, "is_bot", False):
            return await handler(event, data)

        user_id = user.id

        # Пропуск пользователей из белого списка
        if user_id in self.whitelist:
            return await handler(event, data)

        current_time = time.time()
        entry = self._last_processed[user_id]

        # Проверка throttling
        if self._is_throttled(entry, current_time):
            await self._handle_throttled(event, user_id)
            return None

        # Проверка burst-лимит
        if self.burst_limit is not None and self._is_burst_exceeded(entry, current_time):
            await self._handle_throttled(event, user_id, is_burst=True)
            return None

        # Обновление времени последней обработки
        entry.last_time = current_time
        entry.count += 1

        # Сброс счетчика, если прошло больше burst_period
        if current_time - entry.first_time > self.burst_period:
            entry.count = 1
            entry.first_time = current_time

        return await handler(event, data)

    def _is_throttled(self, entry: ThrottleEntry, current_time: float) -> bool:
        """Проверка, нужно ли применять throttling"""
        return current_time - entry.last_time < self.default_throttle

    def _is_burst_exceeded(self, entry: ThrottleEntry, current_time: float) -> bool:
        """Проверка, превышен ли burst-лимит"""
        if self.burst_limit is None:
            return False

        # Сброс счетчика, если прошло больше burst_period
        if current_time - entry.first_time > self.burst_period:
            entry.count = 0
            entry.first_time = current_time
            return False

        return entry.count >= self.burst_limit

    async def _handle_throttled(self, event: TelegramObject, user_id: int, is_burst: bool = False) -> None:
        """Обработка throttled запроса"""
        tg_logger.debug(f"⏳ Throttling {'burst ' if is_burst else ''}user {user_id}")

        # Отправка предупреждения, если включено
        if self.send_warning:
            try:
                message = self.warning_message
                if is_burst and self.burst_limit is not None:
                    message = f"⏳ Слишком много быстрых запросов.\nПодождите {int(self.burst_period)} секунд."

                if isinstance(event, Message):
                    await event.answer(message)
                elif isinstance(event, CallbackQuery):
                    await event.answer(message, show_alert=False)
            except TelegramAPIError as e:
                tg_logger.warning(f"⚠️ Could not send throttling warning: {e}")

    def get_stats(self) -> dict[str, Any]:
        """Получение статистики throttling"""
        current_time = time.time()
        active_users_count = 0

        # Подсчет активных пользователей (обращались за последние 60 секунд)
        for entry in self._last_processed.values():
            if current_time - entry.last_time < 60:
                active_users_count += 1

        return {
            "total_users": len(self._last_processed),
            "active_users": active_users_count,
            "throttle_threshold": self.default_throttle,
            "burst_limit": self.burst_limit,
            "burst_period": self.burst_period,
        }

    def reset_user(self, user_id: int) -> None:
        """Сброс throttling для пользователя"""
        if user_id in self._last_processed:
            del self._last_processed[user_id]
            tg_logger.info(f"✅ Throttling reset for user {user_id}")


__all__ = ["ThrottlingMiddleware"]
