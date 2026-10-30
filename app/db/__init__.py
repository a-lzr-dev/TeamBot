from .dependencies import get_db_manager
from .manager import (
    DBConfig,
    DBEngine,
    DBManager,
    DBType,
    build_teamdroid_sql_conn_str,
    close_teamdroid_sql,
    db_manager,
    get_teamdroid_sql_conn,
    teamdroid_sql_cursor,
)
from .repositories import (
    AutomationRequestRepository,
    AvanpostRepository,
    ChatRepository,
    ErrorRepository,
    MessageRepository,
    ReminderRepository,
    SystemRepository,
    TeamdroidProcedureRepository,
    UserRepository,
)

__all__ = [
    # Менеджеры
    "DBManager",
    "db_manager",
    "DBType",
    "DBConfig",
    "DBEngine",
    # Teamdroid SQL singleton
    "build_teamdroid_sql_conn_str",
    "get_teamdroid_sql_conn",
    "close_teamdroid_sql",
    "teamdroid_sql_cursor",
    # Репозитории
    "AvanpostRepository",
    "AutomationRequestRepository",
    "ChatRepository",
    "ErrorRepository",
    "MessageRepository",
    "ReminderRepository",
    "SystemRepository",
    "TeamdroidProcedureRepository",
    "UserRepository",
    # Зависимости
    "get_db_manager",
]
