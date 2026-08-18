from collections.abc import Callable

from telethon import TelegramClient, events
from telethon.events import ChatAction, MessageDeleted, MessageEdited, NewMessage, UserUpdate

from ....logger import bot_logger
from .members import handle_chat_action, handle_user_update
from .messages import handle_deleted_message, handle_edited_message, handle_new_message


def setup_telethon_handlers(client: TelegramClient) -> list[Callable]:
    """Настройка всех telethon обработчиков"""
    handlers: list[Callable] = []

    @client.on(events.NewMessage(incoming=True))
    async def new_message_handler(event: NewMessage.Event) -> None:
        await handle_new_message(event, client)

    handlers.append(new_message_handler)

    @client.on(events.MessageEdited())
    async def edited_message_handler(event: MessageEdited.Event) -> None:
        await handle_edited_message(event, client)

    handlers.append(edited_message_handler)

    @client.on(events.MessageDeleted())
    async def deleted_message_handler(event: MessageDeleted.Event) -> None:
        await handle_deleted_message(event)

    handlers.append(deleted_message_handler)

    @client.on(events.ChatAction())
    async def chat_action_handler(event: ChatAction.Event) -> None:
        await handle_chat_action(event, client)

    handlers.append(chat_action_handler)

    @client.on(events.UserUpdate())
    async def user_update_handler(event: UserUpdate.Event) -> None:
        await handle_user_update(event)

    handlers.append(user_update_handler)

    bot_logger.info(f"✅ Telethon event handlers configured: {len(handlers)} handlers")

    return handlers


__all__ = [
    "handle_new_message",
    "handle_edited_message",
    "handle_deleted_message",
    "handle_chat_action",
    "handle_user_update",
    "setup_telethon_handlers",
]
