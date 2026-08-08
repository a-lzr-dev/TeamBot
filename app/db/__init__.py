from .dependencies import get_db_manager
from .manager import (
    DBConfig,
    DBEngine,
    DBManager,
    DBType,
    db_manager,
)
from .repositories import (
    AutomationRequestRepository,
    AvanpostRepository,
    ChatRepository,
    ErrorRepository,
    MessageRepository,
    ReminderRepository,
    UserRepository,
)

__all__ = [
    # Менеджеры
    "DBManager",
    "db_manager",
    "DBType",
    "DBConfig",
    "DBEngine",
    # Репозитории
    "AvanpostRepository",
    "AutomationRequestRepository",
    "ChatRepository",
    "ErrorRepository",
    "MessageRepository",
    "ReminderRepository",
    "UserRepository",
    # Зависимости
    "get_db_manager",
]
