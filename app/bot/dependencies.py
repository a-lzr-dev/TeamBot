"""
Модуль зависимостей для получения экземпляра менеджера бота.

Назначение:
    Предоставляет функцию для получения глобального экземпляра BotManager
    через систему зависимостей FastAPI и Aiogram. Обеспечивает единую точку
    доступа к менеджеру бота во всем приложении.

Основные разделы:
    1.  get_bot_manager(): Основная функция для получения экземпляра BotManager
    2.  Проверка инициализации менеджера перед возвратом
    3.  Поддержка TYPE_CHECKING для избежания циклических импортов

Технические особенности:
    - Использует TYPE_CHECKING для предотвращения циклических импортов
    - Ленивый импорт bot_manager внутри функции
    - Поднимает RuntimeError если менеджер не инициализирован
    - Интегрируется с системой зависимостей FastAPI через Depends()

Архитектура:
    - Единая точка доступа к BotManager для всего приложения
    - Используется в API роутерах, обработчиках и сервисах
    - Поддерживает инъекцию зависимостей в FastAPI и Aiogram
"""

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    # Импорт только для проверки типов, чтобы избежать циклических зависимостей
    from .manager import BotManager


def get_bot_manager() -> "BotManager":
    """Зависимость для получения экземпляра менеджера Telegram бота.

    Возвращает глобальный экземпляр BotManager, реализованный как синглтон.
    Используется для управления жизненным циклом бота и выполнения операций
    с Telegram API.

    Returns:
        BotManager: Экземпляр менеджера бота

    Raises:
        RuntimeError: Если BotManager не инициализирован

    Пример использования в FastAPI:
        @router.get("/bot/status")
        async def get_bot_status(bot_manager: BotManager = Depends(get_bot_manager)):
            return await bot_manager.get_status()

    Пример использования в Aiogram обработчике:
        from app.bot.dependencies import get_bot_manager
        bot_manager = get_bot_manager()
        await bot_manager.send_message(chat_id=123, text="Hello")
    """
    from .manager import bot_manager

    if bot_manager is None:
        raise RuntimeError("TelegramManager is not initialized")
    return bot_manager


__all__ = ["get_bot_manager"]
