"""
Модуль настройки Aiogram обработчиков.

Этот модуль объединяет все обработчики сообщений и колбэков
в единый роутер для регистрации в основном приложении.

Основные компоненты:
    - setup_aiogram_handlers(): Функция настройки всех обработчиков

Экспортируемые роутеры:
    - auth_router: Авторизация пользователей
    - chat_router: Управление чатами
    - commands_router: Обработка команд
    - admin_router: Административные функции
    - actions_router: Обработка действий
    - users_router: Управление пользователями
    - automation_router: Автоматизация и конвертация
    - chat_message_menu_router: Контекстное меню сообщений
    - orders_router: Заказы
    - chats_router: Списки чатов
    - vehicles_router: Транспортные средства
    - carrier_orders_router: Заказы перевозчиков
    - chat_details_router: Детали чатов
    - contacts_router: Список контактов (FK_Type=6)
    - contact_details_router: Контактная информация (FK_Type=7)

Вспомогательные функции:
    - show_menu: Отображение меню
    - back_to_users: Возврат к списку пользователей
    - show_users_list: Отображение списка пользователей
"""

from aiogram import Router

# Основные обработчики
from .actions import router as actions_router
from .admin import router as admin_router
from .auth import router as auth_router
from .automation import router as automation_router
from .commands import router as commands_router

# Уникальные
from .custom import (
    chat_details_router,
    chat_message_menu_router,
)

# Детали
from .details import (
    contact_details_router,
)

# Списки
from .lists import (
    carrier_orders_router,
    chats_router,
    contacts_router,
    orders_router,
    users_router,
    vehicles_router,
)


def setup_aiogram_handlers() -> Router:
    """
    Настройка всех Aiogram обработчиков.

    Создает корневой роутер и регистрирует в нем все дочерние роутеры
    для обработки сообщений, колбэков и команд.

    Returns:
        Router: Корневой роутер со всеми зарегистрированными обработчиками

    Пример использования:
        # В основном файле приложения
        from app.bot.handlers.aiogram import setup_aiogram_handlers

        router = setup_aiogram_handlers()
        dispatcher.include_router(router)
    """
    router = Router()

    # Регистрация всех роутеров
    router.include_router(auth_router)  # Авторизация
    router.include_router(commands_router)  # Команды (/help, /id, /msg, /find и др.)
    router.include_router(admin_router)  # Администрирование
    router.include_router(actions_router)  # Действия
    router.include_router(automation_router)  # Автоматизация

    # Списки
    router.include_router(chats_router)  # Список чатов (FK_Type=9)
    router.include_router(contacts_router)  # Список контактов (FK_Type=6)
    router.include_router(orders_router)  # Список заказов заказчиков (FK_Type=8)
    router.include_router(users_router)  # Пользователи
    router.include_router(vehicles_router)  # Список транспорта (FK_Type=10)

    # Детали списков
    router.include_router(chat_details_router)  # Детали чата - список сообщений
    router.include_router(carrier_orders_router)  # Детали заказа заказчика - список заказов перевозчиков (FK_Type=11)
    router.include_router(contact_details_router)  # Детали контакта - список контактной ифнормации (FK_Type=7)

    # Контекстное меню
    router.include_router(chat_message_menu_router)  # Для сообщения (/msg, /find, ответы на сообщения)

    return router


__all__ = [
    # Роутеры
    "commands_router",
    "admin_router",
    "actions_router",
    "users_router",
    "auth_router",
    "automation_router",
    "chat_message_menu_router",
    "orders_router",
    "chats_router",
    "vehicles_router",
    "carrier_orders_router",
    "chat_details_router",
    "contacts_router",
    "contact_details_router",
    # Функции настройки
    "setup_aiogram_handlers",
]
