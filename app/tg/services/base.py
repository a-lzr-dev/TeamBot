from abc import ABC, abstractmethod
from typing import Any


class BaseService(ABC):
    """Базовый класс для всех сервисов"""

    @abstractmethod
    async def initialize(self) -> None:
        """Инициализация сервиса"""
        pass

    @abstractmethod
    async def get_status(self) -> dict[str, Any]:
        """Получение статуса сервиса"""
        pass

    @abstractmethod
    async def health_check(self) -> bool:
        """Проверка здоровья сервиса"""
        pass


__all__ = ["BaseService"]
