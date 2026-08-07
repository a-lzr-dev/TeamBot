from .aiogram import (
    admin_router,
    chat_router,
    commands_router,
    setup_aiogram_handlers,
)
from .telethon import (
    handle_chat_action,
    handle_deleted_message,
    handle_edited_message,
    handle_new_message,
    handle_user_update,
    setup_telethon_handlers,
)

__all__ = [
    # Aiogram
    "admin_router",
    "chat_router",
    "commands_router",
    "setup_aiogram_handlers",
    # Telethon
    "handle_chat_action",
    "handle_deleted_message",
    "handle_edited_message",
    "handle_new_message",
    "handle_user_update",
    "setup_telethon_handlers",
]
