from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .manager import TelegramManager


def get_tg_manager() -> "TelegramManager":
    """Получение экземпляра TelegramManager"""
    from .manager import tg_manager

    if tg_manager is None:
        raise RuntimeError("TelegramManager is not initialized")
    return tg_manager


__all__ = ["get_tg_manager"]
