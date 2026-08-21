"""
Базовый абстрактный класс для Telegram клиентов.

Этот модуль определяет интерфейс, которому должны соответствовать
все реализации клиентов Telegram (Aiogram, Telethon и т.д.).

Основные компоненты:
    - BaseBotClient: Абстрактный базовый класс для Telegram клиентов

Функциональность:
    - Инициализация и запуск клиента
    - Отправка сообщений
    - Проверка состояния подключения
    - Получение информации о текущем пользователе
    - Поддержка async context manager
"""

from abc import ABC, abstractmethod
from typing import Any


class BaseBotClient(ABC):
    """
    Базовый абстрактный класс для Telegram клиентов.

    Определяет единый интерфейс для всех реализаций клиентов
    (Aiogram, Telethon, и т.д.), обеспечивая универсальность
    работы с разными библиотеками.

    Атрибуты:
        client_type (str): Тип клиента (aiogram, telethon, и т.д.)
        is_initialized (bool): Инициализирован ли клиент
        is_running (bool): Запущен ли клиент
    """

    @abstractmethod
    async def initialize(self, *args: Any, **kwargs: Any) -> None:
        """
        Инициализация клиента.

        Выполняет подготовку клиента к работе: создание сессии,
        настройка подключения, регистрация обработчиков.

        Args:
            *args: Позиционные аргументы
            **kwargs: Именованные аргументы
        """
        pass

    @abstractmethod
    async def start(self) -> None:
        """
        Запуск клиента.

        Устанавливает соединение с Telegram и начинает обработку событий.
        """
        pass

    @abstractmethod
    async def stop(self) -> None:
        """
        Остановка клиента.

        Закрывает соединение с Telegram и останавливает обработку событий.
        """
        pass

    @abstractmethod
    async def is_connected(self) -> bool:
        """
        Проверка подключения к Telegram.

        Returns:
            bool: True если клиент подключен к Telegram
        """
        pass

    @abstractmethod
    async def get_status(self) -> dict[str, Any]:
        """
        Получение статуса клиента.

        Returns:
            dict: Словарь с информацией о состоянии клиента
        """
        pass

    @abstractmethod
    async def send_message(self, chat_id: int, text: str, **kwargs: Any) -> dict[str, Any]:
        """
        Отправка сообщения в чат.

        Args:
            chat_id: ID чата в Telegram
            text: Текст сообщения
            **kwargs: Дополнительные параметры (parse_mode, reply_to, и т.д.)

        Returns:
            dict: Результат отправки с полями success, message_id, error
        """
        pass

    @abstractmethod
    async def get_me(self) -> dict[str, Any]:
        """
        Получение информации о текущем аккаунте.

        Returns:
            dict: Информация о пользователе (id, username, first_name, и т.д.)
        """
        pass

    @property
    @abstractmethod
    def client_type(self) -> str:
        """
        Получение типа клиента.

        Returns:
            str: Тип клиента (aiogram, telethon, и т.д.)
        """
        pass

    @property
    @abstractmethod
    def is_initialized(self) -> bool:
        """
        Проверка инициализации клиента.

        Returns:
            bool: True если клиент инициализирован
        """
        pass

    @property
    @abstractmethod
    def is_running(self) -> bool:
        """
        Проверка запуска клиента.

        Returns:
            bool: True если клиент запущен
        """
        pass

    async def health_check(self) -> bool:
        """
        Проверка здоровья клиента.

        Выполняет проверку подключения и возвращает статус.

        Returns:
            bool: True если клиент здоров и подключен
        """
        try:
            return await self.is_connected()
        except Exception:
            return False

    async def __aenter__(self) -> "BaseBotClient":
        """
        Поддержка async context manager.

        Автоматически запускает клиент при входе в контекст.

        Returns:
            BaseBotClient: Экземпляр клиента
        """
        await self.start()
        return self

    async def __aexit__(
        self, exc_type: type[BaseException] | None, exc_val: BaseException | None, exc_tb: Any | None
    ) -> None:
        """
        Поддержка async context manager.

        Автоматически останавливает клиент при выходе из контекста.

        Args:
            exc_type: Тип исключения (если было)
            exc_val: Значение исключения (если было)
            exc_tb: Трассировка исключения (если была)
        """
        await self.stop()


__all__ = ["BaseBotClient"]
