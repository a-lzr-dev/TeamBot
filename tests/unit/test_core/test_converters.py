"""
Модуль с тестами для модуля конвертеров (converters).

Содержит набор тестов для проверки всех функций преобразования данных:
- конвертеры типов чатов (ChatType) из различных источников;
- конвертеры статусов участников (ChatMemberStatus);
- извлечение информации о пользователях из Aiogram и Telethon;
- извлечение информации о сообщениях (текст, тип контента, медиа);
- парсинг команд и их аргументов;
- валидаторы идентификаторов (чат, пользователь, сообщение).

Тесты используют мок-объекты для имитации структур Aiogram и Telethon.
"""

from datetime import UTC

from app.core.converters import (
    chat_type_from_aiogram,
    chat_type_from_dialog,
    chat_type_from_string,
    chat_type_from_telethon,
    chat_type_to_str,
    extract_command,
    extract_command_args,
    get_content_type,
    get_media_info,
    get_message_text,
    member_status_from_aiogram,
    member_status_from_string,
    member_status_from_telethon,
    member_status_to_str,
    safe_datetime_convert,
    user_info_from_aiogram,
    user_info_from_telethon,
    validate_chat_id,
    validate_message_id,
    validate_user_id,
)
from app.models import ChatMemberStatus, ChatType


class TestChatTypeConverters:
    """Набор тестов для конвертеров типов чатов (ChatType)."""

    def test_chat_type_from_string(self) -> None:
        """Проверяет преобразование строки в ChatType с учётом регистра и fallback."""
        assert chat_type_from_string("private") == ChatType.PRIVATE
        assert chat_type_from_string("group") == ChatType.GROUP
        assert chat_type_from_string("supergroup") == ChatType.SUPERGROUP
        assert chat_type_from_string("channel") == ChatType.CHANNEL
        assert chat_type_from_string("") == ChatType.PRIVATE
        assert chat_type_from_string("invalid") == ChatType.PRIVATE

    def test_chat_type_to_str(self) -> None:
        """Проверяет преобразование ChatType в строковое представление."""
        assert chat_type_to_str(ChatType.PRIVATE) == "private"
        assert chat_type_to_str(ChatType.GROUP) == "group"
        assert chat_type_to_str(ChatType.SUPERGROUP) == "supergroup"
        assert chat_type_to_str(ChatType.CHANNEL) == "channel"
        assert chat_type_to_str(ChatType.SENDER) == "sender"

    def test_chat_type_from_aiogram(self) -> None:
        """Проверяет извлечение типа чата из объекта Aiogram."""

        class MockAiogramChat:
            type = "private"

        assert chat_type_from_aiogram(MockAiogramChat()) == ChatType.PRIVATE
        assert chat_type_from_aiogram(None) == ChatType.PRIVATE

        class MockChatNoType:
            pass

        assert chat_type_from_aiogram(MockChatNoType()) == ChatType.PRIVATE

    def test_chat_type_from_telethon(self) -> None:
        """Проверяет определение типа чата из объекта Telethon."""

        class MockEntity:
            pass

        entity = MockEntity()
        entity.megagroup = True
        assert chat_type_from_telethon(entity) == ChatType.SUPERGROUP

        entity = MockEntity()
        entity.channel = True
        assert chat_type_from_telethon(entity) == ChatType.CHANNEL

        entity = MockEntity()
        entity.group = True
        assert chat_type_from_telethon(entity) == ChatType.GROUP

        entity = MockEntity()
        entity.is_user = True
        assert chat_type_from_telethon(entity) == ChatType.PRIVATE

        assert chat_type_from_telethon(None) == ChatType.PRIVATE

    def test_chat_type_from_dialog(self) -> None:
        """Проверяет определение типа чата из диалога Telethon."""

        class MockDialog:
            pass

        dialog = MockDialog()
        dialog.is_group = True
        dialog.entity = None
        assert chat_type_from_dialog(dialog) == ChatType.GROUP

        dialog = MockDialog()
        dialog.is_channel = True
        dialog.entity = None
        assert chat_type_from_dialog(dialog) == ChatType.CHANNEL

        dialog = MockDialog()
        dialog.is_user = True
        dialog.entity = None
        assert chat_type_from_dialog(dialog) == ChatType.PRIVATE

        class MockEntity:
            pass

        entity = MockEntity()
        entity.group = True
        dialog = MockDialog()
        dialog.entity = entity
        assert chat_type_from_dialog(dialog) == ChatType.GROUP

        assert chat_type_from_dialog(None) == ChatType.PRIVATE


class TestMemberStatusConverters:
    """Набор тестов для конвертеров статусов участников (ChatMemberStatus)."""

    def test_member_status_from_string(self) -> None:
        """Проверяет преобразование строки в ChatMemberStatus с учётом регистра и fallback."""
        assert member_status_from_string("creator") == ChatMemberStatus.CREATOR
        assert member_status_from_string("administrator") == ChatMemberStatus.ADMINISTRATOR
        assert member_status_from_string("member") == ChatMemberStatus.MEMBER
        assert member_status_from_string("left") == ChatMemberStatus.LEFT
        assert member_status_from_string("") == ChatMemberStatus.MEMBER
        assert member_status_from_string("invalid") == ChatMemberStatus.MEMBER

    def test_member_status_to_str(self) -> None:
        """Проверяет преобразование ChatMemberStatus в строковое представление."""
        assert member_status_to_str(ChatMemberStatus.CREATOR) == "creator"
        assert member_status_to_str(ChatMemberStatus.ADMINISTRATOR) == "administrator"
        assert member_status_to_str(ChatMemberStatus.MEMBER) == "member"

    def test_member_status_from_aiogram(self) -> None:
        """Проверяет извлечение статуса участника из объекта Aiogram."""
        assert member_status_from_aiogram("creator") == ChatMemberStatus.CREATOR
        assert member_status_from_aiogram(None) == ChatMemberStatus.MEMBER

    def test_member_status_from_telethon(self) -> None:
        """Проверяет извлечение статуса участника из объекта Telethon."""

        class MockParticipant:
            pass

        participant = MockParticipant()
        participant.is_creator = True
        assert member_status_from_telethon(participant) == ChatMemberStatus.CREATOR

        participant = MockParticipant()
        participant.is_admin = True
        assert member_status_from_telethon(participant) == ChatMemberStatus.ADMINISTRATOR

        participant = MockParticipant()
        participant.is_member = False
        assert member_status_from_telethon(participant) == ChatMemberStatus.LEFT

        assert member_status_from_telethon(None) == ChatMemberStatus.MEMBER


class TestUserInfoExtractors:
    """Набор тестов для извлечения информации о пользователях."""

    def test_user_info_from_aiogram(self) -> None:
        """Проверяет извлечение данных пользователя из объекта Aiogram."""

        class MockAiogramUser:
            id = 123
            username = "test_user"
            first_name = "Test"
            last_name = "User"
            is_bot = False

        info = user_info_from_aiogram(MockAiogramUser())
        assert info["user_id"] == 123
        assert info["username"] == "test_user"
        assert info["first_name"] == "Test"
        assert info["last_name"] == "User"
        assert info["is_bot"] is False

        info = user_info_from_aiogram(None)
        assert info["user_id"] == 0
        assert info["username"] is None

    def test_user_info_from_telethon(self) -> None:
        """Проверяет извлечение данных пользователя из объекта Telethon."""

        class MockTelethonUser:
            id = 456
            username = "telethon_user"
            first_name = "Telethon"
            last_name = "User"
            bot = True
            phone = "+1234567890"

        info = user_info_from_telethon(MockTelethonUser())
        assert info["user_id"] == 456
        assert info["username"] == "telethon_user"
        assert info["first_name"] == "Telethon"
        assert info["last_name"] == "User"
        assert info["is_bot"] is True
        assert info["phone"] == "+1234567890"

        info = user_info_from_telethon(None)
        assert info["user_id"] == 0


class TestMessageInfoExtractors:
    """Набор тестов для извлечения информации о сообщениях."""

    def test_safe_datetime_convert(self) -> None:
        """Проверяет безопасное преобразование datetime в часовой пояс UTC."""
        from datetime import datetime

        dt = datetime.now(UTC)
        result = safe_datetime_convert(dt)
        assert result is not None
        assert result.tzinfo is None

        assert safe_datetime_convert(None) is None

    def test_get_message_text(self) -> None:
        """Проверяет извлечение текста из сообщения (текст или подпись)."""

        class MockMessage:
            text = "Hello world"

        assert get_message_text(MockMessage()) == "Hello world"

        class MockMessageWithCaption:
            caption = "Image caption"

        assert get_message_text(MockMessageWithCaption()) == "Image caption"

        assert get_message_text(None) is None

    def test_get_content_type(self) -> None:
        """Проверяет определение типа контента сообщения."""

        class MockMessage:
            content_type = "text"

        assert get_content_type(MockMessage()) == "text"

        assert get_content_type(None) == "text"

    def test_get_media_info(self) -> None:
        """Проверяет извлечение информации о медиафайле из сообщения."""

        class MockPhoto:
            file_id = "photo_id"
            file_unique_id = "unique_id"
            file_size = 1024

        class MockMessageWithPhoto:
            photo = [MockPhoto()]

        info = get_media_info(MockMessageWithPhoto())
        assert info["file_id"] == "photo_id"

        assert get_media_info(None) == {}


class TestCommandExtractors:
    """Набор тестов для извлечения команд и их аргументов."""

    def test_extract_command(self) -> None:
        """Проверяет извлечение команды из текста сообщения."""

        class MockMessage:
            text = "/start"

        assert extract_command(MockMessage()) == "/start"

        class MockMessageWithArgs:
            text = "/start arg1 arg2"

        assert extract_command(MockMessageWithArgs()) == "/start"

        class MockMessageNoCommand:
            text = "Hello"

        assert extract_command(MockMessageNoCommand()) is None

        assert extract_command(None) is None

    def test_extract_command_args(self) -> None:
        """Проверяет извлечение аргументов команды из текста сообщения."""

        class MockMessage:
            text = "/start arg1 arg2"

        assert extract_command_args(MockMessage()) == "arg1 arg2"

        class MockMessageNoArgs:
            text = "/start"

        assert extract_command_args(MockMessageNoArgs()) is None

        class MockMessageNoCommand:
            text = "Hello"

        assert extract_command_args(MockMessageNoCommand()) is None

        assert extract_command_args(None) is None


class TestValidationHelpers:
    """Набор тестов для валидаторов идентификаторов."""

    def test_validate_chat_id(self) -> None:
        """Проверяет валидацию идентификатора чата."""
        assert validate_chat_id(-100123) is True
        assert validate_chat_id(123) is True
        assert validate_chat_id(0) is False
        assert validate_chat_id(None) is False

    def test_validate_user_id(self) -> None:
        """Проверяет валидацию идентификатора пользователя."""
        assert validate_user_id(123) is True
        assert validate_user_id(0) is False
        assert validate_user_id(-1) is False
        assert validate_user_id(None) is False

    def test_validate_message_id(self) -> None:
        """Проверяет валидацию идентификатора сообщения."""
        assert validate_message_id(123) is True
        assert validate_message_id(0) is False
        assert validate_message_id(-1) is False
        assert validate_message_id(None) is False
