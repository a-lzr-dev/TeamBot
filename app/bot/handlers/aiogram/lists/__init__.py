"""
Обработчики списков для подменю (заказы, чаты, транспорт)
Используют универсальные компоненты из bot/callbacks/generic
"""

from .chats import router as chats_router
from .chats import show_chats_list
from .orders import router as orders_router
from .orders import show_orders_list
from .vehicles import router as vehicles_router
from .vehicles import show_vehicles_list

# Экспортируем все роутеры и функции
__all__ = [
    # Роутеры
    "chats_router",
    "orders_router",
    "vehicles_router",
    # Функции отображения
    "show_chats_list",
    "show_orders_list",
    "show_vehicles_list",
]
