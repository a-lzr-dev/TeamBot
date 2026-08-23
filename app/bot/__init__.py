"""
Пакет Telegram бота TeamBot.

Содержит все компоненты для работы с Telegram:
- Менеджер бота (BotManager) - главный координатор
- Клиенты (Aiogram, Telethon) - работа с Telegram API
- Сервисы - бизнес-логика
- Обработчики - обработка сообщений и колбэков
- Клавиатуры - создание интерфейсов
- Колбэки - обработка нажатий кнопок
- Типы и утилиты - общие определения
"""

# Импорт get_timestamp из общего utils
from ..utils.datetime import get_timestamp

# 2. КОЛБЭКИ (Обработчики нажатий кнопок)
from .callbacks import (
    # Специализированные
    ActionCallbackHandler,
    AdminCallbackHandler,
    AuthCallbackHandler,
    # Базовые
    BaseCallbackHandler,
    CallbackHandler,
    # Generic (универсальные списки)
    GenericListCallbackHandler,
    GenericSearchHandler,
    ListHandlerProtocol,
    ListItemData,
    ListStateProtocol,
    action_callback_handler,
    admin_callback_handler,
    auth_callback_handler,
    callback_handler,
)

# 1. КЛИЕНТЫ (Telegram API обертки)
from .clients import (
    AiogramClient,  # Aiogram клиент (Bot API)
    BaseBotClient,  # Базовый интерфейс клиента
    TelethonClient,  # Telethon клиент (User API)
)

# 3. ОБРАБОТЧИКИ (Handlers)
# 3.1 Aiogram обработчики (сообщения, команды, колбэки)
from .handlers.aiogram import (
    admin_router,  # Административные команды
    commands_router,  # Основные команды (/help, /id, /msg)
    setup_aiogram_handlers,  # Функция настройки всех Aiogram обработчиков
)

# 3.3 Список пользователей (экспортируется отдельно для удобства)
from .handlers.aiogram.lists import (
    users_router,  # Роутер для работы с пользователями (/users)
)

# 3.2 Telethon обработчики (события чатов, сообщений)
from .handlers.telethon import (
    setup_telethon_handlers,  # Функция настройки Telethon обработчиков
)

# 4. КЛАВИАТУРЫ (Keyboards)
from .keyboards import (
    # Константы
    BUTTONS_PER_ROW_ACTIONS,
    DEFAULT_BUTTONS_PER_ROW,
    # Действия (меню действий)
    ActionKeyboard,
    # Административные
    AdminKeyboard,
    # Аутентификация
    AuthKeyboard,
    # Автоматизация
    AutomationKeyboard,
    # Базовые
    BaseKeyboard,
    # Generic (универсальные)
    ListKeyboardBuilder,
    # Пользователи
    UserKeyboard,
    get_action_menu_keyboard,
    get_auth_needed_keyboard,
    get_auth_request_keyboard,
    get_back_keyboard,
    get_back_to_menu_keyboard,
    get_broadcast_confirm_keyboard,
    get_close_keyboard,
    get_confirm_keyboard,
    get_delete_confirm_keyboard,
    get_inline_keyboard,
    get_logout_keyboard,
    get_navigation_keyboard,
    get_priority_keyboard,
    get_reply_keyboard,
    get_search_cancel_keyboard,
    get_search_keyboard,
    get_users_keyboard,
)

# 5. МЕНЕДЖЕР (Главный координатор)
from .manager import (
    BotManager,  # Класс менеджера бота
    bot_manager,  # Глобальный экземпляр
)

# 6. СЕРВИСЫ (Бизнес-логика)
from .services import (
    # Aiogram сервисы
    AiogramBotService,  # Управление ботом (команды, информация)
    ChatSyncEngine,  # Ядро синхронизации (бизнес-логика)
    # Синхронизация
    SyncService,  # Основной сервис синхронизации
    # Telethon сервисы
    TelethonChatService,  # Работа с чатами
    TelethonUserService,  # Работа с пользователями
)

# 7. ТИПЫ (Type definitions)
from .types import (
    ChatInfo,  # Информация о чате
    ClientStatus,  # Статус клиента
    MessageConverterProtocol,  # Конвертер сообщений
    MessageMediaInfo,  # Информация о медиа
    # DTO
    ServiceStatus,  # Статус сервиса
    SyncResult,  # Результат синхронизации
    # Перечисления
    TelegramAccountType,  # Тип аккаунта (bot/user)
    # Протоколы
    TelegramClientProtocol,  # Интерфейс клиента
    UserInfo,  # Информация о пользователе
    # Утилиты
    safe_datetime_convert,  # Безопасное преобразование даты
)

# 8. УТИЛИТЫ (Utility functions)
from .utils import (
    CommandValidator,  # Валидация команд
    DataValidator,  # Валидация данных
    RateLimitValidator,  # Rate limiting
    TextValidator,  # Валидация текста
    # Конвертеры
    UserConverter,  # Работа с пользователями
    # Валидаторы
    Validator,  # Базовый валидатор
    chat_type_from_aiogram,  # Тип чата из Aiogram
    chat_type_from_telethon,  # Тип чата из Telethon
    user_info_from_aiogram,  # Информация о пользователе из Aiogram
    user_info_from_telethon,  # Информация о пользователе из Telethon
)

__all__ = [
    # ---------- ТИПЫ ----------
    "TelegramAccountType",
    "ClientStatus",
    "TelegramClientProtocol",
    "ServiceStatus",
    "MessageMediaInfo",
    "MessageConverterProtocol",
    "ChatInfo",
    "UserInfo",
    "SyncResult",
    "safe_datetime_convert",
    "get_timestamp",
    # ---------- МЕНЕДЖЕР ----------
    "BotManager",
    "bot_manager",
    # ---------- КЛИЕНТЫ ----------
    "BaseBotClient",
    "AiogramClient",
    "TelethonClient",
    # ---------- СЕРВИСЫ ----------
    "AiogramBotService",
    "TelethonChatService",
    "TelethonUserService",
    "SyncService",
    "ChatSyncEngine",
    # ---------- ОБРАБОТЧИКИ ----------
    "setup_aiogram_handlers",
    "setup_telethon_handlers",
    "commands_router",
    "admin_router",
    "users_router",
    # ---------- КЛАВИАТУРЫ (Base) ----------
    "BaseKeyboard",
    "get_inline_keyboard",
    "get_reply_keyboard",
    # ---------- КЛАВИАТУРЫ (Auth) ----------
    "AuthKeyboard",
    "get_auth_request_keyboard",
    "get_auth_needed_keyboard",
    "get_logout_keyboard",
    # ---------- КЛАВИАТУРЫ (Admin) ----------
    "AdminKeyboard",
    "get_broadcast_confirm_keyboard",
    "get_delete_confirm_keyboard",
    # ---------- КЛАВИАТУРЫ (Actions) ----------
    "ActionKeyboard",
    "get_action_menu_keyboard",
    "BUTTONS_PER_ROW_ACTIONS",
    # ---------- КЛАВИАТУРЫ (Users) ----------
    "UserKeyboard",
    "get_users_keyboard",
    "get_close_keyboard",
    # ---------- КЛАВИАТУРЫ (Generic) ----------
    "DEFAULT_BUTTONS_PER_ROW",
    "ListKeyboardBuilder",
    "get_confirm_keyboard",
    "get_back_keyboard",
    "get_navigation_keyboard",
    "get_search_keyboard",
    "get_search_cancel_keyboard",
    "get_priority_keyboard",
    "get_back_to_menu_keyboard",
    # ---------- КЛАВИАТУРЫ (Automation) ----------
    "AutomationKeyboard",
    # ---------- КОЛБЭКИ (Base) ----------
    "BaseCallbackHandler",
    "CallbackHandler",
    "callback_handler",
    # ---------- КОЛБЭКИ (Generic) ----------
    "GenericListCallbackHandler",
    "GenericSearchHandler",
    "ListHandlerProtocol",
    "ListItemData",
    "ListStateProtocol",
    # ---------- КОЛБЭКИ (Специализированные) ----------
    "ActionCallbackHandler",
    "action_callback_handler",
    "AuthCallbackHandler",
    "auth_callback_handler",
    "AdminCallbackHandler",
    "admin_callback_handler",
    # ---------- УТИЛИТЫ ----------
    "UserConverter",
    "Validator",
    "TextValidator",
    "CommandValidator",
    "DataValidator",
    "RateLimitValidator",
    # ---------- ДОПОЛНИТЕЛЬНЫЕ УТИЛИТЫ ----------
    "chat_type_from_aiogram",
    "chat_type_from_telethon",
    "user_info_from_aiogram",
    "user_info_from_telethon",
]
