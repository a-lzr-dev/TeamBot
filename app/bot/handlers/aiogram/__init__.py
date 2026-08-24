from aiogram import Router

from .actions import router as actions_router
from .admin import router as admin_router
from .auth import router as auth_router
from .automation import router as automation_router
from .broadcast import router as broadcast_router
from .commands import router as commands_router
from .custom import (
    chat_details_router,
    chat_message_menu_router,
)
from .details import (
    contact_details_router,
)
from .lists import (
    carrier_orders_router,
    chats_router,
    contacts_router,
    orders_router,
    route_points_router,
    users_router,
    vehicles_router,
)
from .stats import router as stats_router
from .sync import router as sync_router


def setup_aiogram_handlers() -> Router:
    """Настройка всех Aiogram обработчиков.

    Создает корневой роутер и регистрирует в нем все дочерние роутеры
    для обработки сообщений, колбэков и команд.

    Returns:
        Router: Корневой роутер со всеми зарегистрированными обработчиками
    """
    router = Router()

    # Регистрация всех роутеров
    router.include_router(auth_router)  # Авторизация
    router.include_router(admin_router)  # Администрирование
    router.include_router(actions_router)  # Действия
    router.include_router(automation_router)  # Автоматизация
    router.include_router(broadcast_router)  # Рассылка
    router.include_router(commands_router)  # Остальные команды (/help, /id, /msg, и др.)
    router.include_router(stats_router)  # Статистика
    router.include_router(sync_router)  # Синхронизация

    # Списки
    router.include_router(chats_router)  # Список чатов (FK_Type=9)
    router.include_router(contacts_router)  # Список контактов (FK_Type=6)
    router.include_router(orders_router)  # Список заказов заказчиков (FK_Type=8)
    router.include_router(route_points_router)  # Точки маршрута (FK_Type=4)
    router.include_router(users_router)  # Пользователи
    router.include_router(vehicles_router)  # Список транспорта (FK_Type=10)

    # Детали списков
    router.include_router(chat_details_router)  # Детали чата - переписка (FK_Type=3)
    router.include_router(carrier_orders_router)  # Заказы перевозчиков (FK_Type=11)
    router.include_router(contact_details_router)  # Детали контакта (FK_Type=7)

    # Контекстное меню
    router.include_router(chat_message_menu_router)  # Для сообщения (/msg, /find, ответы на сообщения)

    return router


__all__ = [
    # Роутеры
    "commands_router",
    "admin_router",
    "actions_router",
    "broadcast_router",
    "users_router",
    "auth_router",
    "automation_router",
    "chat_message_menu_router",
    "orders_router",
    "chats_router",
    "vehicles_router",
    "carrier_orders_router",
    "route_points_router",
    "chat_details_router",
    "contacts_router",
    "contact_details_router",
    "sync_router",
    # Функции настройки
    "setup_aiogram_handlers",
]
