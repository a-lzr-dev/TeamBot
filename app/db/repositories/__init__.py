from .automation_requests import AutomationRequestRepository
from .avanpost import AvanpostRepository
from .avanpost_actions import AvanpostActionsRepository
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
from .users import UserRepository

__all__ = [
    # Новый репозиторий для действий
    "AvanpostActionsRepository",
    # Основные репозитории
    "AvanpostRepository",
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
    # Общие
    "GenericRepository",
]
