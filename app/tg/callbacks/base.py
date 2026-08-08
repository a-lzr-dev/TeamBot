from abc import ABC, abstractmethod
from typing import Any

from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery

from ...tg.dependencies import get_tg_manager


class BaseCallbackHandler(ABC):
    """Базовый класс для обработчиков колбэков"""

    def __init__(self, prefix: str) -> None:
        self.prefix = prefix

    @abstractmethod
    async def handle(self, callback: CallbackQuery, state: FSMContext, **kwargs: Any) -> Any:
        """Обработка колбэка"""
        pass

    def get_callback_data(self, *args: Any, **kwargs: Any) -> str:
        """Формирование callback_data"""
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
        """Парсинг callback_data"""
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
    """Утилитный класс для работы с колбэками"""

    @staticmethod
    async def answer(callback: CallbackQuery, text: str | None = None, show_alert: bool = False) -> None:
        """Ответ на колбэк"""
        tg_manager = get_tg_manager()
        await tg_manager.send_toast(text=text or "", event=callback, show_alert=show_alert)

    @staticmethod
    def parse_callback(callback_data: str, prefix: str) -> dict[str, Any]:
        """Парсинг callback_data"""
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
        """Проверка, принадлежит ли колбэк префиксу"""
        return callback_data.startswith(prefix)


callback_handler = CallbackHandler()
