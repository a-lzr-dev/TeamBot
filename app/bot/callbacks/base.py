"""
Базовый модуль для обработчиков колбэков Telegram.

Этот модуль предоставляет базовые классы и утилиты для создания
обработчиков колбэков в Telegram боте.

Основные компоненты:
    - BaseCallbackHandler: Абстрактный базовый класс для обработчиков
    - CallbackHandler: Утилитный класс с вспомогательными методами

Функциональность:
    - Формирование callback_data с префиксами
    - Парсинг callback_data
    - Отправка ответов на колбэки
    - Проверка принадлежности колбэка определенному префиксу
"""

from abc import ABC, abstractmethod
from typing import Any

from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery

from ...bot.dependencies import get_bot_manager


class BaseCallbackHandler(ABC):
    """
    Базовый абстрактный класс для обработчиков колбэков.

    Предоставляет основную структуру для создания обработчиков
    с поддержкой префиксов и формированием callback_data.

    Атрибуты:
        prefix (str): Префикс для идентификации колбэков
    """

    def __init__(self, prefix: str) -> None:
        """
        Инициализация обработчика.

        Args:
            prefix: Префикс для идентификации колбэков
        """
        self.prefix = prefix

    @abstractmethod
    async def handle(self, callback: CallbackQuery, state: FSMContext, **kwargs: Any) -> Any:
        """
        Абстрактный метод обработки колбэка.

        Должен быть реализован в дочерних классах.

        Args:
            callback: CallbackQuery от пользователя
            state: Состояние FSM
            **kwargs: Дополнительные параметры

        Returns:
            Any: Результат обработки
        """
        pass

    def get_callback_data(self, *args: Any, **kwargs: Any) -> str:
        """
        Формирование callback_data с префиксом и параметрами.

        Собирает строку callback_data в формате:
        prefix_arg0_arg1_key1_value1_key2_value2

        Args:
            *args: Позиционные аргументы
            **kwargs: Именованные аргументы

        Returns:
            str: Сформированная строка callback_data
        """
        if not args and not kwargs:
            return self.prefix

        parts = [self.prefix]
        for arg in args:
            parts.append(str(arg))
        for key, value in kwargs.items():
            parts.append(f"{key}_{value}")

        return "_".join(parts)

    @staticmethod
    def parse_callback_data(callback_data: str, prefix: str) -> dict[str, Any]:
        """
        Парсинг callback_data в словарь.

        Извлекает параметры из строки callback_data.

        Args:
            callback_data: Строка callback_data для парсинга
            prefix: Префикс для проверки

        Returns:
            dict: Словарь с извлеченными параметрами
        """
        if not callback_data.startswith(prefix):
            return {}

        parts = callback_data.split("_")
        if len(parts) <= 1:
            return {}

        result = {}
        for i, part in enumerate(parts[1:]):
            if "_" in part:
                key, value = part.split("_", 1)
                result[key] = value
            else:
                result[f"arg_{i}"] = part

        return result


class CallbackHandler:
    """
    Утилитный класс для работы с колбэками.

    Предоставляет статические методы для:
    - Отправки ответов на колбэки
    - Парсинга callback_data
    - Проверки принадлежности колбэка префиксу
    """

    @staticmethod
    async def answer(callback: CallbackQuery, text: str | None = None, show_alert: bool = False) -> None:
        """
        Ответ на колбэк через Toast уведомление.

        Отправляет уведомление пользователю о результате обработки колбэка.

        Args:
            callback: CallbackQuery от пользователя
            text: Текст уведомления
            show_alert: Показывать как всплывающее окно
        """
        bot_manager = get_bot_manager()
        await bot_manager.send_toast(text=text or "", event=callback, show_alert=show_alert)

    @staticmethod
    def parse_callback(callback_data: str, prefix: str) -> dict[str, Any]:
        """
        Парсинг callback_data в словарь.

        Альтернативный метод парсинга с упрощенной логикой.

        Args:
            callback_data: Строка callback_data для парсинга
            prefix: Префикс для проверки

        Returns:
            dict: Словарь с извлеченными параметрами
        """
        if not callback_data.startswith(prefix):
            return {}

        parts = callback_data.split("_")
        if len(parts) <= 1:
            return {}

        # Если после префикса только одно значение
        if len(parts) == 2:
            return {"value": parts[1]}

        # Если несколько значений
        result = {}
        for i, part in enumerate(parts[1:]):
            if "_" in part:
                key, value = part.split("_", 1)
                result[key] = value
            else:
                result[f"arg_{i}"] = part

        return result

    @staticmethod
    def is_callback_for_prefix(callback_data: str, prefix: str) -> bool:
        """
        Проверка, принадлежит ли колбэк указанному префиксу.

        Args:
            callback_data: Строка callback_data
            prefix: Префикс для проверки

        Returns:
            bool: True если колбэк начинается с префикса
        """
        return callback_data.startswith(prefix)


callback_handler = CallbackHandler()
