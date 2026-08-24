"""
Модуль с тестами для Enum-классов моделей данных.

Содержит набор тестов для проверки корректности значений и методов преобразования
всех перечислений (Enum), используемых в моделях:
- ChatType — типы чатов (private, group, supergroup, channel);
- ChatMemberStatus — статусы участников чатов (creator, administrator, member, left, kicked);
- ErrorCategory — категории ошибок (arbitrary, periodic_task, task_execution, system, external);
- ErrorSeverity — уровни серьёзности ошибок (critical, error, warning, info);
- ErrorStatus — статусы обработки ошибок (new, in_progress, resolved, dismissed, reopened).

Тесты проверяют:
- соответствие значений полей Enum;
- преобразование из строковых представлений (регистронезависимо);
- преобразование из форматов Aiogram и Telethon (для ChatType и ChatMemberStatus).
"""

from app.models import ChatMemberStatus, ChatType, ErrorCategory, ErrorSeverity, ErrorStatus


class TestChatType:
    """Набор тестов для Enum ChatType (типы чатов)."""

    def test_values(self) -> None:
        """Проверяет, что значения полей соответствуют ожидаемым строковым литералам."""
        assert ChatType.PRIVATE.value == "private"
        assert ChatType.GROUP.value == "group"
        assert ChatType.SUPERGROUP.value == "supergroup"
        assert ChatType.CHANNEL.value == "channel"

    def test_from_aiogram(self) -> None:
        """Проверяет преобразование строковых значений из Aiogram в Enum."""
        # Корректные значения
        assert ChatType.from_aiogram("private") == ChatType.PRIVATE
        assert ChatType.from_aiogram("group") == ChatType.GROUP
        assert ChatType.from_aiogram("supergroup") == ChatType.SUPERGROUP
        assert ChatType.from_aiogram("channel") == ChatType.CHANNEL

        # Невалидное значение должно возвращать None
        assert ChatType.from_aiogram("invalid") is None

    def test_from_string(self) -> None:
        """Проверяет регистронезависимое преобразование из строки в Enum."""
        assert ChatType.from_string("private") == ChatType.PRIVATE
        assert ChatType.from_string("PRIVATE") == ChatType.PRIVATE
        assert ChatType.from_string("SuperGroup") == ChatType.SUPERGROUP
        assert ChatType.from_string("invalid") is None

    def test_from_telethon(self) -> None:
        """Проверяет определение типа чата из объекта Telethon."""

        class MockEntity:
            """Мок-объект, имитирующий сущность Telethon."""

            pass

        # Supergroup: megagroup = True
        entity = MockEntity()
        entity.megagroup = True
        assert ChatType.from_telethon(entity) == ChatType.SUPERGROUP

        # Channel: channel = True
        entity = MockEntity()
        entity.channel = True
        assert ChatType.from_telethon(entity) == ChatType.CHANNEL

        # Group: group = True
        entity = MockEntity()
        entity.group = True
        assert ChatType.from_telethon(entity) == ChatType.GROUP


class TestChatMemberStatus:
    """Набор тестов для Enum ChatMemberStatus (статусы участников чата)."""

    def test_values(self) -> None:
        """Проверяет, что значения полей соответствуют ожидаемым строковым литералам."""
        assert ChatMemberStatus.CREATOR.value == "creator"
        assert ChatMemberStatus.ADMINISTRATOR.value == "administrator"
        assert ChatMemberStatus.MEMBER.value == "member"
        assert ChatMemberStatus.LEFT.value == "left"
        assert ChatMemberStatus.KICKED.value == "kicked"

    def test_from_aiogram(self) -> None:
        """Проверяет преобразование строковых значений из Aiogram в Enum."""
        assert ChatMemberStatus.from_aiogram("creator") == ChatMemberStatus.CREATOR
        assert ChatMemberStatus.from_aiogram("administrator") == ChatMemberStatus.ADMINISTRATOR
        assert ChatMemberStatus.from_aiogram("member") == ChatMemberStatus.MEMBER
        assert ChatMemberStatus.from_aiogram("left") == ChatMemberStatus.LEFT
        assert ChatMemberStatus.from_aiogram("invalid") is None

    def test_from_string(self) -> None:
        """Проверяет регистронезависимое преобразование из строки в Enum."""
        assert ChatMemberStatus.from_string("creator") == ChatMemberStatus.CREATOR
        assert ChatMemberStatus.from_string("CREATOR") == ChatMemberStatus.CREATOR
        assert ChatMemberStatus.from_string("invalid") is None


class TestErrorEnums:
    """Набор тестов для Enum-классов, связанных с ошибками."""

    def test_error_category(self) -> None:
        """Проверяет значения категорий ошибок."""
        assert ErrorCategory.ARBITRARY.value == "arbitrary"
        assert ErrorCategory.PERIODIC_TASK.value == "periodic_task"
        assert ErrorCategory.TASK_EXECUTION.value == "task_execution"
        assert ErrorCategory.SYSTEM.value == "system"
        assert ErrorCategory.EXTERNAL.value == "external"

    def test_error_severity(self) -> None:
        """Проверяет значения уровней серьёзности ошибок."""
        assert ErrorSeverity.CRITICAL.value == "critical"
        assert ErrorSeverity.ERROR.value == "error"
        assert ErrorSeverity.WARNING.value == "warning"
        assert ErrorSeverity.INFO.value == "info"

    def test_error_status(self) -> None:
        """Проверяет значения статусов обработки ошибок."""
        assert ErrorStatus.NEW.value == "new"
        assert ErrorStatus.IN_PROGRESS.value == "in_progress"
        assert ErrorStatus.RESOLVED.value == "resolved"
        assert ErrorStatus.DISMISSED.value == "dismissed"
        assert ErrorStatus.REOPENED.value == "reopened"
