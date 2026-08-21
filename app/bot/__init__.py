# --- Импорт get_timestamp из общего utils ---
from ..utils.datetime import get_timestamp

# --- Callbacks ---
from .callbacks import (
    ActionCallbackHandler,
    AdminCallbackHandler,
    AuthCallbackHandler,
    BaseCallbackHandler,
    CallbackHandler,
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

# --- Clients ---
from .clients import (
    AiogramClient,
    BaseBotClient,
    TelethonClient,
)

# --- Handlers (Aiogram) ---
from .handlers.aiogram import (
    admin_router,
    chat_router,
    commands_router,
    setup_aiogram_handlers,
    users_router,
)

# --- Общие функции ---
from .handlers.aiogram.common import back_to_users, show_menu, show_users_list  # <-- добавлено

# --- Handlers (Telethon) ---
from .handlers.telethon import (
    setup_telethon_handlers,
)

# --- Keyboards ---
from .keyboards import (
    BUTTONS_PER_ROW_ACTIONS,
    # Generic
    DEFAULT_BUTTONS_PER_ROW,
    # Actions
    ActionKeyboard,
    # Admin
    AdminKeyboard,
    # Auth
    AuthKeyboard,
    # Automation
    AutomationKeyboard,
    BaseKeyboard,
    ListKeyboardBuilder,
    # Groups
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

# --- Manager ---
from .manager import (
    BotManager,
    bot_manager,
)

# --- Services ---
from .services import (
    AiogramBotService,
    ChatSyncEngine,
    SyncService,
    TelethonChatService,
    TelethonUserService,
)

# --- Types ---
from .types import (
    ChatInfo,
    ClientStatus,
    MessageConverterProtocol,
    MessageMediaInfo,
    ServiceStatus,
    SyncResult,
    TelegramAccountType,
    TelegramClientProtocol,
    UserInfo,
    safe_datetime_convert,
)

# --- Utils (объединенные) ---
from .utils import (
    CommandValidator,
    DataValidator,
    RateLimitValidator,
    TextValidator,
    UserConverter,
    Validator,
    # Дополнительные утилиты, если нужны
    chat_type_from_aiogram,
    chat_type_from_telethon,
    user_info_from_aiogram,
    user_info_from_telethon,
)

__all__ = [
    # Типы
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
    # Менеджер
    "BotManager",
    "bot_manager",
    # Клиенты
    "BaseBotClient",
    "AiogramClient",
    "TelethonClient",
    # Сервисы
    "AiogramBotService",
    "TelethonChatService",
    "TelethonUserService",
    "SyncService",
    "ChatSyncEngine",
    # Утилиты
    "UserConverter",
    "Validator",
    "TextValidator",
    "CommandValidator",
    "DataValidator",
    "RateLimitValidator",
    # Дополнительные утилиты из объединенного модуля
    "chat_type_from_aiogram",
    "chat_type_from_telethon",
    "user_info_from_aiogram",
    "user_info_from_telethon",
    # Обработчики
    "setup_aiogram_handlers",
    "chat_router",
    "commands_router",
    "admin_router",
    "setup_telethon_handlers",
    "users_router",
    # Клавиатуры - Base
    "BaseKeyboard",
    "get_inline_keyboard",
    "get_reply_keyboard",
    # Клавиатуры - Auth
    "AuthKeyboard",
    "get_auth_request_keyboard",
    "get_auth_needed_keyboard",
    "get_logout_keyboard",
    # Клавиатуры - Admin
    "AdminKeyboard",
    "get_broadcast_confirm_keyboard",
    "get_delete_confirm_keyboard",
    # Клавиатуры - Actions
    "ActionKeyboard",
    "get_action_menu_keyboard",
    "BUTTONS_PER_ROW_ACTIONS",
    # Клавиатуры - Users
    "UserKeyboard",
    "get_users_keyboard",
    "get_close_keyboard",
    # Клавиатуры - Generic
    "DEFAULT_BUTTONS_PER_ROW",
    "ListKeyboardBuilder",
    "get_confirm_keyboard",
    "get_back_keyboard",
    "get_navigation_keyboard",
    "get_search_keyboard",
    "get_search_cancel_keyboard",
    "get_priority_keyboard",
    "get_back_to_menu_keyboard",
    # Клавиатуры - Automation
    "AutomationKeyboard",
    # Колбэки
    "BaseCallbackHandler",
    "CallbackHandler",
    "callback_handler",
    "ActionCallbackHandler",
    "action_callback_handler",
    "AuthCallbackHandler",
    "auth_callback_handler",
    "AdminCallbackHandler",
    "admin_callback_handler",
    # Generic Callbacks
    "GenericListCallbackHandler",
    "GenericSearchHandler",
    "ListHandlerProtocol",
    "ListItemData",
    "ListStateProtocol",
    # Общие функции
    "show_menu",
    "back_to_users",
    "show_users_list",
]
