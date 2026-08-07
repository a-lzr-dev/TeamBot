from abc import ABC, abstractmethod
from typing import Any


class BaseTelegramClient(ABC):
    """Базовый класс для Telegram клиентов"""

    @abstractmethod
    async def initialize(self, *args: Any, **kwargs: Any) -> None:
        """Инициализация клиента"""
        pass

    @abstractmethod
    async def start(self) -> None:
        """Запуск клиента"""
        pass

    @abstractmethod
    async def stop(self) -> None:
        """Остановка клиента"""
        pass

    @abstractmethod
    async def is_connected(self) -> bool:
        """Проверка подключения"""
        pass

    @abstractmethod
    async def get_status(self) -> dict[str, Any]:
        """Получение статуса клиента"""
        pass

    @abstractmethod
    async def send_message(self, chat_id: int, text: str, **kwargs: Any) -> dict[str, Any]:
        """Отправка сообщения"""
        pass

    @abstractmethod
    async def get_me(self) -> dict[str, Any]:
        """Получение информации о текущем пользователе"""
        pass

    @property
    @abstractmethod
    def client_type(self) -> str:
        """Получение типа клиента"""
        pass

    @property
    @abstractmethod
    def is_initialized(self) -> bool:
        """Проверка инициализации клиента"""
        pass

    @property
    @abstractmethod
    def is_running(self) -> bool:
        """Проверка запуска клиента"""
        pass

    async def health_check(self) -> bool:
        """Проверка здоровья клиента"""
        try:
            return await self.is_connected()
        except Exception:
            return False

    async def __aenter__(self) -> "BaseTelegramClient":
        """Поддержка async context manager"""
        await self.start()
        return self

    async def __aexit__(
        self, exc_type: type[BaseException] | None, exc_val: BaseException | None, exc_tb: Any | None
    ) -> None:
        """Поддержка async context manager"""
        await self.stop()


__all__ = ["BaseTelegramClient"]
