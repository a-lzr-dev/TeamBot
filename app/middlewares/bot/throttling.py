"""
Middleware для ограничения частоты обработки запросов (анти-флуд).

Назначение:
    Защита бота от флуда путём ограничения частоты обработки сообщений
    и callback'ов от одного пользователя.

Основные функции:
    1. Ограничение частоты запросов (throttling) с настраиваемой задержкой
    2. Обнаружение и блокировка burst-запросов (серии быстрых запросов)
    3. Белый список для доверенных пользователей
    4. Игнорирование ботов
    5. Отправка предупреждений при превышении лимита
    6. Статистика использования

Технические особенности:
    - Интеграция с Aiogram через BaseMiddleware
    - In-memory хранение состояния пользователей
    - Поддержка burst-лимитов для защиты от спама
    - Автоматический сброс счётчиков по истечении периода

Архитектура:
    - Реализует интерфейс BaseMiddleware от Aiogram
    - Использует dataclass ThrottleEntry для хранения состояния
    - Поддерживает настраиваемые параметры через конструктор
"""

import time
from collections import defaultdict
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any

from aiogram import BaseMiddleware
from aiogram.exceptions import TelegramAPIError
from aiogram.types import CallbackQuery, Message, TelegramObject

from ...logger import bot_logger
from .utils import get_user

# ============================================================
# 1. КЛАСС ДЛЯ ХРАНЕНИЯ СОСТОЯНИЯ ПОЛЬЗОВАТЕЛЯ
# ============================================================


@dataclass
class ThrottleEntry:
    """
    Запись о последнем обращении пользователя.

    Attributes:
        last_time (float): Время последней обработки запроса
        count (int): Количество запросов за текущий период
        first_time (float): Время первого запроса в текущем периоде
    """

    last_time: float = field(default_factory=time.time)
    count: int = 0
    first_time: float = field(default_factory=time.time)


# ============================================================
# 2. КЛАСС MIDDLEWARE ДЛЯ ОГРАНИЧЕНИЯ ЧАСТОТЫ
# ============================================================


class ThrottlingMiddleware(BaseMiddleware):
    """
    Middleware для ограничения частоты обработки (анти-флуд).

    Ограничивает частоту обработки сообщений и callback'ов от одного
    пользователя с помощью двух механизмов:
    1. Throttling — минимальная задержка между запросами
    2. Burst limit — максимальное количество быстрых запросов

    Пример использования в Aiogram:
        dp.update.outer_middleware(
            ThrottlingMiddleware(
                default_throttle=0.5,
                burst_limit=5,
                burst_period=5.0,
                whitelist=[123456789],
                ignore_bots=True,
                send_warning=True
            )
        )

    Attributes:
        default_throttle (float): Минимальное время между обработками (сек)
        burst_limit (int | None): Максимальное количество быстрых запросов
        burst_period (float): Период для burst-запросов (сек)
        whitelist (list): Список ID пользователей без ограничений
        ignore_bots (bool): Игнорировать запросы от ботов
        send_warning (bool): Отправлять предупреждение при throttling
        warning_message (str): Текст предупреждения
        _last_processed (dict[int, ThrottleEntry]): Хранилище состояния пользователей
    """

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
        """
        Инициализация middleware throttling.

        Args:
            default_throttle: Минимальное время между обработками (сек)
            burst_limit: Максимальное количество быстрых запросов
            burst_period: Период для burst-запросов (сек)
            whitelist: Список ID пользователей без ограничений
            ignore_bots: Игнорировать запросы от ботов
            send_warning: Отправлять предупреждение при throttling
            warning_message: Текст предупреждения
        """
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

    # ============================================================
    # 2.1. ОСНОВНОЙ МЕТОД ОБРАБОТКИ СОБЫТИЯ
    # ============================================================

    async def __call__(
        self,
        handler: Callable[[TelegramObject, dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: dict[str, Any],
    ) -> Any:
        """
        Основной метод обработки события с проверкой throttling.

        Args:
            handler: Функция-обработчик события
            event: Объект события (Message, CallbackQuery и т.д.)
            data: Данные контекста для передачи обработчику

        Returns:
            Any: Результат выполнения обработчика или None при throttling

        Flow:
            1. Проверка типа события (только Message и CallbackQuery)
            2. Получение пользователя
            3. Проверка, является ли пользователь ботом
            4. Проверка белого списка
            5. Проверка throttling (минимальная задержка)
            6. Проверка burst-лимита (серия быстрых запросов)
            7. Обновление состояния пользователя
            8. Вызов обработчика
        """
        # 1. Проверка типа события
        if not isinstance(event, Message | CallbackQuery):
            return await handler(event, data)

        # 2. Получение пользователя
        user = get_user(event)
        if user is None:
            return await handler(event, data)

        # 3. Игнорирование ботов
        if self.ignore_bots and getattr(user, "is_bot", False):
            return await handler(event, data)

        user_id = user.id

        # 4. Пропуск пользователей из белого списка
        if user_id in self.whitelist:
            return await handler(event, data)

        current_time = time.time()
        entry = self._last_processed[user_id]

        # 5. Проверка throttling (минимальная задержка)
        if self._is_throttled(entry, current_time):
            await self._handle_throttled(event, user_id)
            return None

        # 6. Проверка burst-лимита (серия быстрых запросов)
        if self.burst_limit is not None and self._is_burst_exceeded(entry, current_time):
            await self._handle_throttled(event, user_id, is_burst=True)
            return None

        # 7. Обновление времени последней обработки
        entry.last_time = current_time
        entry.count += 1

        # Сброс счётчика, если прошло больше burst_period
        if current_time - entry.first_time > self.burst_period:
            entry.count = 1
            entry.first_time = current_time

        # 8. Вызов обработчика
        return await handler(event, data)

    # ============================================================
    # 2.2. ПРОВЕРКИ ЛИМИТОВ
    # ============================================================

    def _is_throttled(self, entry: ThrottleEntry, current_time: float) -> bool:
        """
        Проверка, нужно ли применять throttling.

        Args:
            entry: Запись состояния пользователя
            current_time: Текущее время

        Returns:
            bool: True если нужно применить throttling
        """
        return current_time - entry.last_time < self.default_throttle

    def _is_burst_exceeded(self, entry: ThrottleEntry, current_time: float) -> bool:
        """
        Проверка, превышен ли burst-лимит.

        Args:
            entry: Запись состояния пользователя
            current_time: Текущее время

        Returns:
            bool: True если превышен burst-лимит
        """
        if self.burst_limit is None:
            return False

        # Сброс счётчика, если прошло больше burst_period
        if current_time - entry.first_time > self.burst_period:
            entry.count = 0
            entry.first_time = current_time
            return False

        return entry.count >= self.burst_limit

    # ============================================================
    # 2.3. ОБРАБОТКА THROTTLED ЗАПРОСА
    # ============================================================

    async def _handle_throttled(self, event: TelegramObject, user_id: int, is_burst: bool = False) -> None:
        """
        Обработка throttled запроса.

        Args:
            event: Объект события
            user_id: ID пользователя
            is_burst: Является ли запрос burst-запросом
        """
        bot_logger.debug(f"⏳ Throttling {'burst ' if is_burst else ''}user {user_id}")

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
                bot_logger.warning(f"⚠️ Could not send throttling warning: {e}")

    # ============================================================
    # 2.4. СТАТИСТИКА И УПРАВЛЕНИЕ
    # ============================================================

    def get_stats(self) -> dict[str, Any]:
        """
        Получение статистики throttling.

        Returns:
            dict[str, Any]: Статистика с полями:
                - total_users: Всего пользователей в хранилище
                - active_users: Активных пользователей (за последние 60 сек)
                - throttle_threshold: Порог задержки
                - burst_limit: Лимит burst-запросов
                - burst_period: Период burst-запросов
        """
        current_time = time.time()
        active_users_count = 0

        # Подсчёт активных пользователей (обращались за последние 60 секунд)
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
        """
        Сброс throttling для пользователя.

        Args:
            user_id: ID пользователя
        """
        if user_id in self._last_processed:
            del self._last_processed[user_id]
            bot_logger.info(f"✅ Throttling reset for user {user_id}")


__all__ = ["ThrottlingMiddleware"]
