import datetime
from abc import ABC, abstractmethod
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession


class ISyncService(ABC):
    """Интерфейс сервиса синхронизации"""

    @abstractmethod
    async def sync_chat_members(self, chat_id: int, session: AsyncSession, force: bool = False) -> dict[str, Any]:
        """Синхронизация участников конкретного чата"""
        pass

    @abstractmethod
    async def sync_all_chats(
        self,
        session: AsyncSession,
        force: bool = False,
        max_chats: int | None = None,
        chat_types: list[str] | None = None,
    ) -> dict[str, Any]:
        """Синхронизация всех чатов"""
        pass

    @abstractmethod
    async def get_last_sync_time(self) -> datetime.datetime | None:
        """Получение времени последней синхронизации"""
        pass

    @abstractmethod
    async def get_status(self) -> dict[str, Any]:
        """Получение статуса сервиса"""
        pass

    @abstractmethod
    async def health_check(self) -> bool:
        """Проверка здоровья сервиса"""
        pass

    @abstractmethod
    async def clear_cache(self, chat_id: int | None = None) -> None:
        """Очистка кеша"""
        pass

    @abstractmethod
    async def reset_metrics(self) -> None:
        """Сброс метрик"""
        pass
