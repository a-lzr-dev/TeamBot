from aiogram import Router

from .actions import router as actions_router
from .admin import router as admin_router
from .auth import _auth_cache
from .auth import router as auth_router
from .automation import router as automation_router
from .chat import router as chat_router
from .commands import router as commands_router
from .users import router as users_router


def setup_aiogram_handlers() -> Router:
    """Настройка всех aiogram обработчиков"""
    router = Router()
    router.include_router(auth_router)
    router.include_router(chat_router)
    router.include_router(commands_router)
    router.include_router(admin_router)
    router.include_router(actions_router)
    router.include_router(users_router)
    router.include_router(automation_router)
    return router


__all__ = [
    "chat_router",
    "commands_router",
    "admin_router",
    "actions_router",
    "users_router",
    "auth_router",
    "automation_router",
    "setup_aiogram_handlers",
    "_auth_cache",
]
