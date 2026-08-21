"""
Модуль зависимостей для получения экземпляра менеджера бота.

Этот модуль предоставляет функцию для получения глобального экземпляра
BotManager через систему зависимостей.
"""

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    # Импорт только для проверки типов, чтобы избежать циклических зависимостей
    from .manager import BotManager


def get_bot_manager() -> "BotManager":
    """
    Зависимость для получения экземпляра менеджера Telegram бота.

    Возвращает глобальный экземпляр BotManager, реализованный как синглтон.
    Используется для управления жизненным циклом бота и выполнения операций
    с Telegram API.

    Returns:
        BotManager: Экземпляр менеджера бота
    """
    from .manager import bot_manager

    if bot_manager is None:
        raise RuntimeError("TelegramManager is not initialized")
    return bot_manager


__all__ = ["get_bot_manager"]
