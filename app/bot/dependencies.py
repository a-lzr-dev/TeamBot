from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .manager import BotManager


def get_bot_manager() -> "BotManager":
    """Получение экземпляра TelegramManager"""
    from .manager import bot_manager

    if bot_manager is None:
        raise RuntimeError("TelegramManager is not initialized")
    return bot_manager


__all__ = ["get_bot_manager"]
