"""
Модуль с тестами для базовых моделей и миксинов.

Содержит набор тестов для проверки корректности работы всех базовых миксинов
и Enum-классов, используемых в моделях данных:
- UserMixin — базовые атрибуты пользователя;
- ChatMemberMixin — атрибуты участника чата;
- TimestampMixin — временные метки создания и обновления;
- SoftDeleteMixin — мягкое удаление (флаг, время, инициатор);
- ActiveMixin — флаг активности;
- ChatType и ChatMemberStatus — перечисления с методами преобразования.

Тесты проверяют:
- наличие и корректность атрибутов в классах-наследниках;
- работу методов преобразования строк в Enum-значения;
- соответствие значений Enum ожидаемым литералам.
"""

from app.models.base import (
    ActiveMixin,
    ChatMemberMixin,
    ChatMemberStatus,
    ChatType,
    SoftDeleteMixin,
    TimestampMixin,
    UserMixin,
    datetime_now,
)


class TestMixins:
    """Набор тестов для проверки корректности работы миксинов."""

    def test_user_mixin_attributes(self) -> None:
        """
        Проверяет, что UserMixin предоставляет все необходимые атрибуты пользователя.

        Тестируются поля: FID, FUserName, FFirstName, FLastName, FFlagBot.
        """

        class TestUser(UserMixin):
            pass

        user = TestUser()
        user.FID = 123
        user.FUserName = "test_user"
        user.FFirstName = "Test"
        user.FLastName = "User"
        user.FFlagBot = False

        assert user.FID == 123
        assert user.FUserName == "test_user"
        assert user.FFirstName == "Test"
        assert user.FLastName == "User"
        assert user.FFlagBot is False

    def test_chat_member_mixin_attributes(self) -> None:
        """
        Проверяет, что ChatMemberMixin предоставляет атрибуты статуса и активности.
        """

        class TestChatMember(ChatMemberMixin):
            pass

        member = TestChatMember()
        member.FStatus = ChatMemberStatus.ADMINISTRATOR
        member.FFlagActive = True

        assert member.FStatus == ChatMemberStatus.ADMINISTRATOR
        assert member.FFlagActive is True

    def test_timestamp_mixin_attributes(self) -> None:
        """
        Проверяет, что TimestampMixin предоставляет поля FCreatedAt и FUpdatedAt.
        """

        class TestTimestamp(TimestampMixin):
            pass

        obj = TestTimestamp()
        now = datetime_now()
        obj.FCreatedAt = now
        obj.FUpdatedAt = now

        assert obj.FCreatedAt == now
        assert obj.FUpdatedAt == now

    def test_soft_delete_mixin_attributes(self) -> None:
        """
        Проверяет, что SoftDeleteMixin предоставляет атрибуты мягкого удаления:
        FIsDeleted, FDeletedAt, FDeletedBy.
        """

        class TestSoftDelete(SoftDeleteMixin):
            pass

        obj = TestSoftDelete()
        obj.FIsDeleted = True
        obj.FDeletedAt = datetime_now()
        obj.FDeletedBy = 123

        assert obj.FIsDeleted is True
        assert obj.FDeletedAt is not None
        assert obj.FDeletedBy == 123

    def test_active_mixin_attributes(self) -> None:
        """
        Проверяет, что ActiveMixin предоставляет флаг активности FIsActive.
        """

        class TestActive(ActiveMixin):
            pass

        obj = TestActive()
        obj.FIsActive = False

        assert obj.FIsActive is False


class TestEnums:
    """Набор тестов для Enum-классов, используемых в моделях."""

    def test_chat_type_values(self) -> None:
        """
        Проверяет, что все значения ChatType соответствуют ожидаемым строковым литералам.
        Включая SENDER, который присутствует в некоторых контекстах.
        """
        assert ChatType.PRIVATE.value == "private"
        assert ChatType.GROUP.value == "group"
        assert ChatType.SUPERGROUP.value == "supergroup"
        assert ChatType.CHANNEL.value == "channel"
        assert ChatType.SENDER.value == "sender"

    def test_chat_member_status_values(self) -> None:
        """
        Проверяет, что все значения ChatMemberStatus соответствуют ожидаемым литералам.
        """
        assert ChatMemberStatus.CREATOR.value == "creator"
        assert ChatMemberStatus.ADMINISTRATOR.value == "administrator"
        assert ChatMemberStatus.MEMBER.value == "member"
        assert ChatMemberStatus.RESTRICTED.value == "restricted"
        assert ChatMemberStatus.LEFT.value == "left"
        assert ChatMemberStatus.KICKED.value == "kicked"

    def test_chat_type_from_string(self) -> None:
        """
        Проверяет регистронезависимое преобразование строки в ChatType.

        Корректные значения должны преобразовываться в соответствующие Enum,
        невалидные — возвращать None.
        """
        assert ChatType.from_string("private") == ChatType.PRIVATE
        assert ChatType.from_string("PRIVATE") == ChatType.PRIVATE
        assert ChatType.from_string("group") == ChatType.GROUP
        assert ChatType.from_string("supergroup") == ChatType.SUPERGROUP
        assert ChatType.from_string("channel") == ChatType.CHANNEL
        assert ChatType.from_string("invalid") is None

    def test_chat_member_status_from_string(self) -> None:
        """
        Проверяет регистронезависимое преобразование строки в ChatMemberStatus.

        Корректные значения должны преобразовываться в соответствующие Enum,
        невалидные — возвращать None.
        """
        assert ChatMemberStatus.from_string("creator") == ChatMemberStatus.CREATOR
        assert ChatMemberStatus.from_string("administrator") == ChatMemberStatus.ADMINISTRATOR
        assert ChatMemberStatus.from_string("member") == ChatMemberStatus.MEMBER
        assert ChatMemberStatus.from_string("invalid") is None
