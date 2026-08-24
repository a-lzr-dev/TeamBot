"""
Модуль с тестами для основных моделей данных приложения.

Содержит набор тестов для проверки корректности создания, свойств
и строковых представлений всех ключевых моделей:
- пользователи (UserModel);
- чаты (ChatModel);
- сообщения (ChatMessageModel);
- ошибки (ErrorModel);
- модели Avanpost (AvanpostUserModel, AvanpostContactModel, AvanpostDirScenarioGroupItemModel);
- рассылки (BroadcastModel);
- напоминания (UserReminderModel);
- заявки на автоматизацию (UserRequestAutomationModel).

Тесты проверяют:
- инициализацию моделей с корректными данными;
- работу вычисляемых свойств (fullname, display_name, display_text);
- строковые представления (__str__, __repr__);
- корректность маппинга моделей Avanpost.
"""

from datetime import timedelta

from app.models import (
    BroadcastModel,
    ChatMessageModel,
    ChatModel,
    ErrorModel,
    UserModel,
    UserReminderModel,
    UserRequestAutomationModel,
    datetime_now,
)
from app.models.avanpost import (
    AVANPOST_MODEL_MAPPING,
    AvanpostContactModel,
    AvanpostDirScenarioGroupItemModel,
    AvanpostUserModel,
)
from app.models.base import ChatType, ErrorCategory, ErrorSeverity, ErrorStatus, MessageType


class TestUserModel:
    """Набор тестов для модели пользователя UserModel."""

    def test_user_creation(self):
        """Проверяет создание пользователя со всеми основными полями."""
        user = UserModel(
            FID=12345,
            FUserName="test_user",
            FFirstName="Test",
            FLastName="User",
            FFlagBot=False,
            FPhone="+1234567890",
        )
        assert user.FID == 12345
        assert user.fullname == "Test User"
        assert user.display_name == "Test User (@test_user)"

    def test_user_properties(self):
        """Проверяет вычисляемые свойства пользователя."""
        user = UserModel(
            FID=12345,
            FUserName="test_user",
            FFirstName="Test",
            FLastName="User",
        )
        assert user.fullname == "Test User"
        assert user.is_authenticated is False
        assert user.avanpost_id is None

    def test_user_str_repr(self):
        """Проверяет строковые представления пользователя."""
        user = UserModel(
            FID=12345,
            FUserName="test_user",
            FFirstName="Test",
        )
        assert "Test" in str(user)
        assert "User" in repr(user)


class TestChatModel:
    """Набор тестов для модели чата ChatModel."""

    def test_chat_creation(self):
        """Проверяет создание чата с типом SUPERGROUP и флагом активности."""
        chat = ChatModel(
            FID=-1001234567890,
            FType=ChatType.SUPERGROUP,
            FTitle="Test Chat",
            FFlagActive=True,
        )
        assert chat.FID == -1001234567890
        assert chat.FType == ChatType.SUPERGROUP
        assert chat.FTitle == "Test Chat"
        assert chat.FFlagActive is True

    def test_chat_repr(self):
        """Проверяет строковое представление чата."""
        chat = ChatModel(
            FID=-1001234567890,
            FType=ChatType.SUPERGROUP,
            FTitle="Test Chat",
        )
        assert "Test Chat" in repr(chat)


class TestChatMessageModel:
    """Набор тестов для модели сообщения ChatMessageModel."""

    def test_message_creation(self):
        """Проверяет создание сообщения с текстом и временной меткой."""
        msg = ChatMessageModel(
            FID=12345,
            FK_Chat=-1001234567890,
            FK_User=12345,
            FK_MessageType=MessageType.USER_REQUEST,
            FText="Test message",
            FDateSent=datetime_now(),
        )
        assert msg.FID == 12345
        assert msg.FText == "Test message"
        assert msg.display_text == "Test message"

    def test_message_deleted_display(self):
        """Проверяет, что для удалённого сообщения возвращается специальная метка."""
        msg = ChatMessageModel(
            FID=12345,
            FK_Chat=-1001234567890,
            FK_MessageType=MessageType.USER_REQUEST,
            FFlagDeleted=True,
            FDeletedByType="admin",
        )
        assert msg.display_text == "[DELETED MESSAGE]"

    def test_message_repr(self):
        """Проверяет строковое представление сообщения."""
        msg = ChatMessageModel(
            FID=12345,
            FK_Chat=-1001234567890,
            FK_MessageType=MessageType.USER_REQUEST,
            FText="Test",
        )
        assert "active" in repr(msg)


class TestErrorModel:
    """Набор тестов для модели ошибки ErrorModel."""

    def test_error_creation(self):
        """Проверяет создание ошибки с кодом, сообщением и статусом."""
        error = ErrorModel(
            FErrorCode="TEST_001",
            FErrorMessage="Test error",
            FSourceSystem="test_system",
            FCategory=ErrorCategory.EXTERNAL,
            FSeverity=ErrorSeverity.ERROR,
            FStatus=ErrorStatus.NEW,
        )
        assert error.FErrorCode == "TEST_001"
        assert error.FStatus == ErrorStatus.NEW

    def test_error_with_occurrences(self):
        """Проверяет создание ошибки с количеством повторений."""
        error = ErrorModel(
            FErrorCode="TEST_002",
            FErrorMessage="Test error",
            FSourceSystem="test_system",
            FCountOccurrences=5,
        )
        assert error.FCountOccurrences == 5


class TestAvanpostModels:
    """Набор тестов для моделей, связанных с Avanpost."""

    def test_avanpost_user(self):
        """Проверяет создание пользователя Avanpost."""
        user = AvanpostUserModel(
            FID=100,
            FK_MenuGroup=5,
            FK_Language="RU",
            FName="Test User",
        )
        assert user.FID == 100
        assert user.FK_MenuGroup == 5

    def test_avanpost_contact(self):
        """Проверяет создание контакта Avanpost."""
        contact = AvanpostContactModel(
            FID=200,
            FK_Group=1,
        )
        assert contact.FID == 200

    def test_avanpost_menu_item(self):
        """Проверяет создание пункта меню Avanpost и его свойства."""
        item = AvanpostDirScenarioGroupItemModel(
            FID=300,
            FK_ScenarioGroup=5,
            FK_Type=1,
        )
        assert item.FID == 300
        assert item.has_subitems is False
        assert item.is_folder is False

    def test_avanpost_model_mapping(self):
        """Проверяет, что ключевые идентификаторы присутствуют в маппинге моделей."""
        assert 1 in AVANPOST_MODEL_MAPPING
        assert 101 in AVANPOST_MODEL_MAPPING
        assert 301 in AVANPOST_MODEL_MAPPING


class TestBroadcastModel:
    """Набор тестов для модели рассылки BroadcastModel."""

    def test_broadcast_creation(self):
        """Проверяет создание рассылки со статусом pending."""
        broadcast = BroadcastModel(
            FK_User=12345,
            FTitle="Test Broadcast",
            FText="Test message",
            FTotalChats=10,
            FStatus="pending",
        )
        assert broadcast.FK_User == 12345
        assert broadcast.FTitle == "Test Broadcast"
        assert broadcast.FStatus == "pending"

    def test_broadcast_repr(self):
        """Проверяет строковое представление рассылки."""
        broadcast = BroadcastModel(
            FK_User=12345,
            FTitle="Test",
            FStatus="sent",
            FTotalChats=5,
        )
        assert "Broadcast" in repr(broadcast)


class TestUserReminderModel:
    """Набор тестов для модели напоминания UserReminderModel."""

    def test_reminder_creation(self):
        """Проверяет создание активного напоминания с временем срабатывания."""
        reminder = UserReminderModel(
            FK_User=12345,
            FTitle="Test Reminder",
            FRemindAt=datetime_now() + timedelta(hours=1),
            FIsActive=True,
        )
        assert reminder.FK_User == 12345
        assert reminder.FTitle == "Test Reminder"
        assert reminder.FIsActive is True

    def test_reminder_encrypted(self):
        """Проверяет создание зашифрованного напоминания."""
        reminder = UserReminderModel(
            FK_User=12345,
            FTitle="🔒 Encrypted",
            FIsEncrypted=True,
            FEncryptedData="encrypted_data",
        )
        assert reminder.FIsEncrypted is True
        assert reminder.FEncryptedData == "encrypted_data"


class TestUserRequestAutomationModel:
    """Набор тестов для модели заявки на автоматизацию UserRequestAutomationModel."""

    def test_request_creation(self):
        """Проверяет создание заявки с приоритетом MEDIUM и статусом NEW."""
        from app.models.base import UserRequestAutomationPriority, UserRequestAutomationStatus

        request = UserRequestAutomationModel(
            FK_User=12345,
            FTitle="Test Request",
            FDescription="Test description",
            FPriority=UserRequestAutomationPriority.MEDIUM,
            FStatus=UserRequestAutomationStatus.NEW,
        )
        assert request.FK_User == 12345
        assert request.FPriority == UserRequestAutomationPriority.MEDIUM
        assert request.FStatus == UserRequestAutomationStatus.NEW

    def test_request_repr(self):
        """Проверяет строковое представление заявки."""
        from app.models.base import UserRequestAutomationPriority

        request = UserRequestAutomationModel(
            FK_User=12345,
            FTitle="Test",
            FPriority=UserRequestAutomationPriority.HIGH,
        )
        assert "UserRequestAutomation" in repr(request)
