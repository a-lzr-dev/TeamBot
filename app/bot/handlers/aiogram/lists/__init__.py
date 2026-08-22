from .carrier_orders import router as carrier_orders_router
from .carrier_orders import show_carrier_orders_list
from .chats import router as chats_router
from .chats import show_chats_list
from .contacts import router as contacts_router
from .contacts import show_contacts_list
from .orders import router as orders_router
from .orders import show_orders_list
from .users import back_to_users, show_users_list
from .users import router as users_router
from .vehicles import router as vehicles_router
from .vehicles import show_vehicles_list

__all__ = [
    # Роутеры
    "carrier_orders_router",
    "chats_router",
    "contacts_router",
    "orders_router",
    "users_router",
    "vehicles_router",
    # Функции отображения
    "show_carrier_orders_list",
    "show_chats_list",
    "show_contacts_list",
    "show_orders_list",
    "show_users_list",
    "back_to_users",
    "show_vehicles_list",
]
