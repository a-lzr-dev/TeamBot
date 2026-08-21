from .carrier_orders import router as carrier_orders_router
from .carrier_orders import show_carrier_orders_list
from .chat_details import router as chat_details_router
from .chat_details import show_chat_details
from .chats import router as chats_router
from .chats import show_chats_list
from .orders import router as orders_router
from .orders import show_orders_list
from .vehicles import router as vehicles_router
from .vehicles import show_vehicles_list

__all__ = [
    # Роутеры
    "carrier_orders_router",
    "chat_details_router",
    "chats_router",
    "orders_router",
    "vehicles_router",
    # Функции отображения
    "show_carrier_orders_list",
    "show_chat_details",
    "show_chats_list",
    "show_orders_list",
    "show_vehicles_list",
]
