"""Модели данных TeamBot.

Содержит все модели данных, используемые в приложении:
1. Базовые модели и Enum (base.py)
2. Модели Avanpost для синхронизации (avanpost.py)
3. Основные модели Telegram (main.py)
   - Пользователи, чаты, участники, сообщения
   - Ошибки и фильтры
   - Периодические задачи
   - Напоминания
   - Настройки уведомлений
   - Автоматизация
   - Рассылки
"""

from .avanpost import (
    AvanpostContactLangModel,
    AvanpostContactLinkModel,
    # Данные
    AvanpostContactModel,
    AvanpostContactMsgModel,
    AvanpostContactMsgProcessModel,
    AvanpostDirContactGroupModel,
    AvanpostDirContactLinkTypeModel,
    AvanpostDirContactMsgDirectionTypeModel,
    AvanpostDirContactMsgProcessTypeModel,
    AvanpostDirContactMsgTypeModel,
    AvanpostDirFileTypeModel,
    # Базовые справочники
    AvanpostDirLanguageModel,
    AvanpostDirOperatorModel,
    AvanpostDirOwnerModel,
    AvanpostDirOwnerMotorCadeModel,
    AvanpostDirScenarioActionLangModel,
    AvanpostDirScenarioActionModel,
    AvanpostDirScenarioActionTypeModel,
    AvanpostDirScenarioActionValueModel,
    AvanpostDirScenarioActionValueTypeModel,
    AvanpostDirScenarioCustomModel,
    AvanpostDirScenarioGroupItemLangModel,
    AvanpostDirScenarioGroupItemLinkScenarioGroupModel,
    AvanpostDirScenarioGroupItemLinkScenarioInstructionModel,
    AvanpostDirScenarioGroupItemLinkScenarioModel,
    AvanpostDirScenarioGroupItemModel,
    AvanpostDirScenarioGroupItemTypeModel,
    # Меню действий
    AvanpostDirScenarioGroupModel,
    AvanpostDirScenarioInstructionFileModel,
    AvanpostDirScenarioInstructionLangModel,
    AvanpostDirScenarioInstructionModel,
    # Сценарии действий
    AvanpostDirScenarioModel,
    AvanpostDirScenarioTypeModel,
    # Системные
    AvanpostDirSysDataTypeModel,
    AvanpostDirUserContactRoleTypeModel,
    AvanpostDirUserLinkContactMsgControlProcessTypeModel,
    AvanpostDirUserStatusTypeModel,
    # Отложенная синхронизация
    AvanpostFileModel,
    AvanpostLinkContactMsgFileModel,
    AvanpostLinkMsgFileModel,
    # Оперативная синхронизация
    AvanpostMsgModel,
    AvanpostSysUpdateModel,
    AvanpostSysUserUpdateModel,
    AvanpostUserChatLangModel,
    AvanpostUserChatModel,
    AvanpostUserLinkChatContactMsgModel,
    AvanpostUserLinkContactModel,
    AvanpostUserLinkContactMsgControlModel,
    AvanpostUserLinkModel,
    AvanpostUserMissionItemLangModel,
    AvanpostUserMissionItemModel,
    AvanpostUserMissionLangModel,
    AvanpostUserMissionModel,
    AvanpostUserModel,
    AvanpostUserOrderLangModel,
    AvanpostUserOrderLinkMissionModel,
    AvanpostUserOrderModel,
    AvanpostUserStatusModel,
    AvanpostUserVehicleModel,
)
from .base import (
    ActiveMixin,
    BaseModel,
    ChatMemberMixin,
    ChatMemberStatus,
    ChatType,
    ErrorCategory,
    ErrorSeverity,
    ErrorStatus,
    MessageActionType,
    MessageSource,
    MessageType,
    SoftDeleteMixin,
    TimestampMixin,
    UserMixin,
    UserRequestAutomationPriority,
    UserRequestAutomationStatus,
    datetime_now,
)
from .main import (
    # Модели рассылок
    BroadcastMessageLinkModel,
    BroadcastModel,
    # Основные модели Telegram
    ChatMemberModel,
    ChatMessageModel,
    ChatModel,
    # Модели настроек
    ChatNotificationSettingsModel,
    # Модели ошибок
    ErrorFilterModel,
    ErrorMessageLinkModel,
    ErrorModel,
    # Модели периодических задач
    PeriodicTaskModel,
    UserChatMemberModel,
    UserModel,
    # Модели напоминаний
    UserReminderModel,
    UserReminderShareModel,
    # Модели автоматизации
    UserRequestAutomationModel,
)

__all__ = [
    # Base
    "BaseModel",
    "datetime_now",
    "UserMixin",
    "ChatMemberMixin",
    "TimestampMixin",
    "SoftDeleteMixin",
    "ActiveMixin",
    # Enum
    "ChatType",
    "ChatMemberStatus",
    "MessageType",
    "MessageActionType",
    "MessageSource",
    "ErrorCategory",
    "ErrorSeverity",
    "ErrorStatus",
    "UserRequestAutomationStatus",
    "UserRequestAutomationPriority",
    # Avanpost - справочники
    "AvanpostDirLanguageModel",
    "AvanpostDirContactGroupModel",
    "AvanpostDirContactLinkTypeModel",
    "AvanpostDirOperatorModel",
    "AvanpostDirOwnerModel",
    "AvanpostDirOwnerMotorCadeModel",
    "AvanpostDirFileTypeModel",
    "AvanpostDirContactMsgDirectionTypeModel",
    "AvanpostDirContactMsgTypeModel",
    "AvanpostDirContactMsgProcessTypeModel",
    "AvanpostDirUserStatusTypeModel",
    "AvanpostDirUserContactRoleTypeModel",
    "AvanpostDirUserLinkContactMsgControlProcessTypeModel",
    "AvanpostDirScenarioGroupItemTypeModel",
    "AvanpostDirScenarioTypeModel",
    "AvanpostDirScenarioActionTypeModel",
    "AvanpostDirScenarioActionValueTypeModel",
    # Avanpost - сценарии
    "AvanpostDirScenarioModel",
    "AvanpostDirScenarioActionModel",
    "AvanpostDirScenarioActionLangModel",
    "AvanpostDirScenarioActionValueModel",
    "AvanpostDirScenarioInstructionModel",
    "AvanpostDirScenarioInstructionFileModel",
    "AvanpostDirScenarioInstructionLangModel",
    "AvanpostDirScenarioCustomModel",
    # Avanpost - меню действий
    "AvanpostDirScenarioGroupModel",
    "AvanpostDirScenarioGroupItemModel",
    "AvanpostDirScenarioGroupItemLangModel",
    "AvanpostDirScenarioGroupItemLinkScenarioModel",
    "AvanpostDirScenarioGroupItemLinkScenarioGroupModel",
    "AvanpostDirScenarioGroupItemLinkScenarioInstructionModel",
    # Avanpost - данные
    "AvanpostContactModel",
    "AvanpostContactLangModel",
    "AvanpostContactLinkModel",
    "AvanpostUserModel",
    "AvanpostUserLinkModel",
    "AvanpostUserChatModel",
    "AvanpostUserChatLangModel",
    # Avanpost - оперативная синхронизация
    "AvanpostMsgModel",
    "AvanpostContactMsgModel",
    "AvanpostContactMsgProcessModel",
    "AvanpostUserStatusModel",
    "AvanpostUserLinkContactModel",
    "AvanpostUserMissionModel",
    "AvanpostUserMissionLangModel",
    "AvanpostUserMissionItemModel",
    "AvanpostUserMissionItemLangModel",
    "AvanpostUserOrderModel",
    "AvanpostUserOrderLangModel",
    "AvanpostUserOrderLinkMissionModel",
    "AvanpostUserVehicleModel",
    "AvanpostUserLinkChatContactMsgModel",
    "AvanpostUserLinkContactMsgControlModel",
    # Avanpost - отложенная синхронизация
    "AvanpostFileModel",
    "AvanpostLinkMsgFileModel",
    "AvanpostLinkContactMsgFileModel",
    # Avanpost - системные
    "AvanpostDirSysDataTypeModel",
    "AvanpostSysUpdateModel",
    "AvanpostSysUserUpdateModel",
    # Telegram - основные
    "UserModel",
    "ChatModel",
    "UserChatMemberModel",
    "ChatMemberModel",
    "ChatMessageModel",
    # Telegram - ошибки
    "ErrorModel",
    "ErrorMessageLinkModel",
    "ErrorFilterModel",
    # Telegram - периодические задачи
    "PeriodicTaskModel",
    # Telegram - напоминания
    "UserReminderModel",
    "UserReminderShareModel",
    # Telegram - настройки
    "ChatNotificationSettingsModel",
    # Telegram - автоматизация
    "UserRequestAutomationModel",
    # Telegram - рассылки
    "BroadcastModel",
    "BroadcastMessageLinkModel",
]
