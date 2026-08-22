from .chat_details import router as chat_details_router
from .chat_details import show_chat_details
from .chat_message_menu import router as chat_message_menu_router

__all__ = [
    # Роутеры
    "chat_details_router",
    "chat_message_menu_router",
    # Функции отображения
    "show_chat_details",
]
