"""
Модуль настройки AIogram обработчиков.

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

Вспомогательные функции:
    - show_menu: Отображение меню
    - back_to_users: Возврат к списку пользователей
    - show_users_list: Отображение списка пользователей
"""

from aiogram import Router

# Основные обработчики
from .actions import router as actions_router
from .admin import router as admin_router
from .auth import _auth_cache
from .auth import router as auth_router
from .automation import router as automation_router
from .chat import router as chat_router

# Контекстное меню для сообщений
from .chat_message_menu import router as chat_message_menu_router
from .commands import router as commands_router
from .common import back_to_users, show_menu, show_users_list

# Списки (заказы, чаты, транспорт, заказы перевозчиков, сообщения)
from .lists import (
    carrier_orders_router,
    chat_details_router,
    chats_router,
    orders_router,
    vehicles_router,
)
from .users import router as users_router


def setup_aiogram_handlers() -> Router:
    """
    Настройка всех AIogram обработчиков.

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
    router.include_router(chat_router)  # Чаты
    router.include_router(commands_router)  # Команды (/help, /id, /msg, /find и др.)
    router.include_router(admin_router)  # Администрирование
    router.include_router(actions_router)  # Действия
    router.include_router(users_router)  # Пользователи
    router.include_router(automation_router)  # Автоматизация

    # Списки (заказы, чаты, транспорт, заказы перевозчиков, сообщения)
    router.include_router(orders_router)  # Заказы
    router.include_router(chats_router)  # Чаты (список)
    router.include_router(vehicles_router)  # Транспорт
    router.include_router(carrier_orders_router)  # Заказы перевозчиков
    router.include_router(chat_details_router)  # Детали чатов

    # Контекстное меню для сообщений (/msg, /find, ответы на сообщения)
    router.include_router(chat_message_menu_router)

    return router


__all__ = [
    # Роутеры
    "chat_router",
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
    # Функции настройки
    "setup_aiogram_handlers",
    # Внутренние компоненты
    "_auth_cache",
    # Вспомогательные функции из common
    "show_menu",
    "back_to_users",
    "show_users_list",
]
