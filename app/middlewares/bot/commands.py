"""
Middleware для динамического обновления команд бота при авторизации.

Назначение:
    Автоматическое обновление доступных команд для пользователя в зависимости
    от его статуса авторизации и прав администратора.

Основные функции:
    1. Проверка статуса авторизации пользователя при каждом сообщении
    2. Обновление команд для авторизованных пользователей и администраторов
    3. Очистка кеша для неавторизованных пользователей
    4. Поддержка динамического изменения доступных команд

Технические особенности:
    - Интеграция с Aiogram через BaseMiddleware
    - Проверка авторизации через bot_manager.is_user_authorized()
    - Кеширование через bot_manager.is_user_in_cache()
    - Поддержка администраторов (ADMIN_IDS из настроек)

Архитектура:
    - Реализует интерфейс BaseMiddleware от Aiogram
    - Интегрируется с BotManager для управления командами
    - Использует настройки ADMIN_IDS для определения прав
"""

from collections.abc import Awaitable, Callable
from typing import Any

from aiogram import BaseMiddleware
from aiogram.types import Message, TelegramObject

from ...bot.dependencies import get_bot_manager
from ...config import settings
from ...logger import bot_logger

# ============================================================
# 1. КЛАСС MIDDLEWARE ДЛЯ ДИНАМИЧЕСКИХ КОМАНД
# ============================================================


class DynamicCommandsMiddleware(BaseMiddleware):
    """
    Middleware для динамического обновления команд при авторизации.

    Автоматически обновляет доступные команды для пользователя при каждом
    сообщении в зависимости от его статуса авторизации.

    Пример использования в Aiogram:
        dp.update.outer_middleware(DynamicCommandsMiddleware())

    Логика работы:
        1. Если пользователь авторизован или админ → обновить команды
        2. Если пользователь не авторизован → очистить кеш команд
    """

    def __init__(self) -> None:
        """Инициализация middleware динамических команд."""
        super().__init__()

    # ============================================================
    # 1.1. ОСНОВНОЙ МЕТОД ОБРАБОТКИ СОБЫТИЯ
    # ============================================================

    async def __call__(
        self,
        handler: Callable[[TelegramObject, dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: dict[str, Any],
    ) -> Any:
        """
        Основной метод обработки события с обновлением команд.

        Args:
            handler: Функция-обработчик события
            event: Объект события (Message, CallbackQuery и т.д.)
            data: Данные контекста для передачи обработчику

        Returns:
            Any: Результат выполнения обработчика

        Flow:
            1. Проверка, является ли событие Message
            2. Получение ID пользователя
            3. Проверка, является ли пользователь администратором
            4. Проверка статуса авторизации пользователя
            5. Обновление команд если авторизован и нет в кеше
            6. Очистка кеша если не авторизован
            7. Вызов обработчика
        """
        # 1. Проверка, что событие — сообщение от пользователя
        if isinstance(event, Message) and event.from_user:
            user_id = event.from_user.id
            bot_manager = get_bot_manager()

            # 2. Проверка прав администратора
            is_admin = user_id in getattr(settings, "ADMIN_IDS", [])

            # 3. Проверка статуса авторизации
            is_authorized = await bot_manager.is_user_authorized(user_id)

            # 4. Если пользователь авторизован или админ, но нет в кеше — обновляем команды
            if (is_authorized or is_admin) and not bot_manager.is_user_in_cache(user_id):
                await bot_manager.update_user_commands(user_id, is_admin)
                bot_logger.debug(f"✅ Commands updated for user {user_id} via middleware")

            # 5. Если пользователь не авторизован и есть в кеше — очищаем
            elif not is_authorized and bot_manager.is_user_in_cache(user_id):
                await bot_manager.clear_user_cache(user_id)
                bot_logger.debug(f"🧹 Cache cleared for unauthorized user {user_id}")

        # 6. Вызов обработчика
        return await handler(event, data)


__all__ = ["DynamicCommandsMiddleware"]
