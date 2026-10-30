from .automation_requests import AutomationRequestRepository
from .avanpost import AvanpostRepository
from .avanpost_actions import AvanpostActionRepository
from .avanpost_users import AvanpostUserRepository
from .broadcast import BroadcastRepository
from .chats import ChatRepository
from .dirs import DirContactGroupRepository, DirLanguageRepository
from .errors import ErrorRepository
from .errors_filters import ErrorFilterRepository
from .generic import GenericRepository
from .messages import MessageRepository
from .notifications_settings import NotificationSettingsRepository
from .reminders import ReminderRepository
from .stats import StatsRepository
from .system import SystemRepository
from .teamdroid import TeamdroidProcedureRepository
from .users import UserRepository

__all__ = [
    # Репозиторий для работы с меню действий
    "AvanpostActionRepository",
    # Основные репозитории
    "AvanpostRepository",
    "AvanpostUserRepository",
    "BroadcastRepository",
    "ChatRepository",
    "UserRepository",
    "MessageRepository",
    # Справочники
    "DirLanguageRepository",
    "DirContactGroupRepository",
    # Системные
    "SystemRepository",
    "StatsRepository",
    # Ошибки
    "ErrorRepository",
    "ErrorFilterRepository",
    # Уведомления
    "NotificationSettingsRepository",
    # Напоминания
    "ReminderRepository",
    # Автоматизация
    "AutomationRequestRepository",
    # Teamdroid SQL Server (ext.PA_mbl_*)
    "TeamdroidProcedureRepository",
    # Общие
    "GenericRepository",
]
