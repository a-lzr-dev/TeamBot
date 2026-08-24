"""
Модуль с тестами для репозитория чатов (ChatRepository).

Содержит набор асинхронных интеграционных тестов, проверяющих работу с чатами
и их участниками:
- создание и обновление чатов;
- получение чатов по ID и списком с фильтрацией;
- управление участниками чата (добавление, удаление, деактивация);
- обновление времени синхронизации участников;
- массовая деактивация отсутствующих участников.

Тесты используют реальную тестовую БД (in-memory SQLite) и создают
необходимые тестовые данные (чаты, пользователи) перед каждым тестом.
"""

import time

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.repositories import ChatRepository, UserRepository
from app.models import ChatMemberStatus, ChatType


class TestChatRepository:
    """
    Набор тестов для проверки корректности работы ChatRepository.

    Тестируются все основные операции с чатами и их участниками:
    - CRUD для чатов;
    - управление участниками;
    - фильтрация и поиск;
    - массовые операции (деактивация).
    """

    @pytest.mark.asyncio
    async def test_save_chat_create(self, db_session: AsyncSession) -> None:
        """
        Проверяет создание нового чата.

        После сохранения проверяются:
        - идентификатор чата;
        - тип чата (SUPERGROUP);
        - название;
        - флаг активности.
        """
        chat_id = -1001234567890
        chat = await ChatRepository.save_chat(
            session=db_session,
            chat_id=chat_id,
            chat_type="supergroup",
            title="Test Chat",
            is_active=True,
        )

        assert chat is not None
        assert chat.FID == chat_id
        assert chat.FType == ChatType.SUPERGROUP
        assert chat.FTitle == "Test Chat"
        assert chat.FFlagActive is True

    @pytest.mark.asyncio
    async def test_save_chat_update(self, db_session: AsyncSession) -> None:
        """
        Проверяет обновление существующего чата.

        Создаётся чат с начальными данными, затем обновляется.
        Проверяется, что все поля изменились корректно.
        """
        chat_id = -1001234567891

        await ChatRepository.save_chat(
            session=db_session,
            chat_id=chat_id,
            chat_type="group",
            title="Old Title",
            is_active=True,
        )

        chat = await ChatRepository.save_chat(
            session=db_session,
            chat_id=chat_id,
            chat_type="supergroup",
            title="New Title",
            is_active=False,
        )

        assert chat.FType == ChatType.SUPERGROUP
        assert chat.FTitle == "New Title"
        assert chat.FFlagActive is False

    @pytest.mark.asyncio
    async def test_get_chat_by_id(self, db_session: AsyncSession) -> None:
        """
        Проверяет получение чата по идентификатору.

        Создаётся чат, затем выполняется поиск по ID.
        Ожидается, что найденный чат будет соответствовать созданному.
        При поиске несуществующего ID должен возвращаться None.
        """
        chat_id = -1001234567892

        await ChatRepository.save_chat(
            session=db_session,
            chat_id=chat_id,
            chat_type="channel",
            title="Test Channel",
        )

        chat = await ChatRepository.get_chat_by_id(db_session, chat_id)
        assert chat is not None
        assert chat.FID == chat_id
        assert chat.FType == ChatType.CHANNEL

        chat = await ChatRepository.get_chat_by_id(db_session, 999999)
        assert chat is None

    @pytest.mark.asyncio
    async def test_get_chats(self, db_session: AsyncSession) -> None:
        """
        Проверяет получение списка чатов с фильтрацией по активности.

        Создаются несколько чатов с разными флагами активности,
        затем запрашивается список с фильтром is_active=True.
        Проверяется, что все возвращённые чаты имеют FFlagActive = True.
        """
        for i in range(3):
            await ChatRepository.save_chat(
                session=db_session,
                chat_id=-1001234567893 + i,
                chat_type="group" if i % 2 == 0 else "supergroup",
                title=f"Chat {i}",
                is_active=i % 2 == 0,
            )

        chats = await ChatRepository.get_chats(db_session)
        assert len(chats) >= 3

        active_chats = await ChatRepository.get_chats(db_session, is_active=True)
        for chat in active_chats:
            assert chat.FFlagActive is True

    @pytest.mark.asyncio
    async def test_get_user_chat_members(self, db_session: AsyncSession) -> None:
        """
        Проверяет получение списка участников чата.

        Создаются три пользователя, каждый добавляется в тестовый чат.
        Затем запрашивается список участников — ожидается не менее 3 записей.
        """
        chat_id = -1001234567894

        await ChatRepository.save_chat(
            session=db_session,
            chat_id=chat_id,
            chat_type="group",
            title="Members Test",
        )

        timestamp = int(time.time() * 1000) % 1000000
        for i, user_id in enumerate([1001, 1002, 1003]):
            await UserRepository.save_user(
                session=db_session,
                user_id=user_id,
                first_name=f"User{user_id}",
                username=f"test_user_{timestamp}_{i}",
            )
            await ChatRepository.save_chat_member(
                session=db_session,
                user_id=user_id,
                chat_id=chat_id,
                status="member",
                is_active=True,
            )

        members = await ChatRepository.get_user_chat_members(db_session, chat_id=chat_id)
        assert len(members) >= 3

    @pytest.mark.asyncio
    async def test_save_chat_member(self, db_session: AsyncSession) -> None:
        """
        Проверяет добавление участника в чат.

        Создаётся чат и пользователь, затем вызывается save_chat_member.
        Проверяется, что запись создана с корректными полями:
        FK_User, FK_Chat, статус ADMINISTRATOR, активность True.
        """
        chat_id = -1001234567895
        user_id = 12345
        timestamp = int(time.time() * 1000) % 1000000

        await ChatRepository.save_chat(
            session=db_session,
            chat_id=chat_id,
            chat_type="group",
            title="Member Test",
        )

        await UserRepository.save_user(
            session=db_session,
            user_id=user_id,
            first_name="Test",
            username=f"test_user_{timestamp}",
        )

        member = await ChatRepository.save_chat_member(
            session=db_session,
            user_id=user_id,
            chat_id=chat_id,
            status="administrator",
            is_active=True,
        )

        assert member is not None
        assert member.FK_User == user_id
        assert member.FK_Chat == chat_id
        assert member.FStatus == ChatMemberStatus.ADMINISTRATOR
        assert member.FFlagActive is True

    @pytest.mark.asyncio
    async def test_remove_chat_member(self, db_session: AsyncSession) -> None:
        """
        Проверяет удаление (деактивацию) участника чата.

        Участник добавляется в чат, затем удаляется через remove_chat_member.
        Проверяется, что запись остаётся в БД, но флаг FFlagActive становится False.
        """
        chat_id = -1001234567896
        user_id = 12346
        timestamp = int(time.time() * 1000) % 1000000

        await ChatRepository.save_chat(
            session=db_session,
            chat_id=chat_id,
            chat_type="group",
            title="Remove Test",
        )

        await UserRepository.save_user(
            session=db_session,
            user_id=user_id,
            first_name="Test",
            username=f"test_user_{timestamp}",
        )

        await ChatRepository.save_chat_member(
            session=db_session,
            user_id=user_id,
            chat_id=chat_id,
            status="member",
            is_active=True,
        )

        result = await ChatRepository.remove_chat_member(db_session, user_id, chat_id)
        assert result is True

        member = await ChatRepository.get_chat_member_by_keys(db_session, user_id=user_id, chat_id=chat_id)
        assert member is not None
        assert member.FFlagActive is False

    @pytest.mark.asyncio
    async def test_update_member_sync_time(self, db_session: AsyncSession) -> None:
        """
        Проверяет обновление времени синхронизации участника.

        После вызова update_member_sync_time поле FDateUpdated должно измениться.
        """
        chat_id = -1001234567897
        user_id = 12347
        timestamp = int(time.time() * 1000) % 1000000

        await ChatRepository.save_chat(
            session=db_session,
            chat_id=chat_id,
            chat_type="group",
            title="Sync Test",
        )

        await UserRepository.save_user(
            session=db_session,
            user_id=user_id,
            first_name="Test",
            username=f"test_user_{timestamp}",
        )

        await ChatRepository.save_chat_member(
            session=db_session,
            user_id=user_id,
            chat_id=chat_id,
            status="member",
            is_active=True,
        )

        await ChatRepository.update_member_sync_time(db_session, user_id, chat_id)

        member = await ChatRepository.get_chat_member_by_keys(db_session, user_id=user_id, chat_id=chat_id)
        assert member is not None
        assert member.FDateUpdated is not None

    @pytest.mark.asyncio
    async def test_deactivate_missing_members(self, db_session: AsyncSession) -> None:
        """
        Проверяет массовую деактивацию участников, отсутствующих в переданном списке.

        Создаются три участника, затем вызывается deactivate_missing_members
        с активным множеством {1001}. Ожидается, что участники 1002 и 1003
        будут деактивированы (количество deactivated == 2).
        """
        chat_id = -1001234567898
        timestamp = int(time.time() * 1000) % 1000000

        await ChatRepository.save_chat(
            session=db_session,
            chat_id=chat_id,
            chat_type="group",
            title="Deactivate Test",
        )

        for i, user_id in enumerate([1001, 1002, 1003]):
            await UserRepository.save_user(
                session=db_session,
                user_id=user_id,
                first_name=f"User{user_id}",
                username=f"test_user_{timestamp}_{i}",
            )
            await ChatRepository.save_chat_member(
                session=db_session,
                user_id=user_id,
                chat_id=chat_id,
                status="member",
                is_active=True,
            )

        deactivated = await ChatRepository.deactivate_missing_members(
            session=db_session,
            chat_id=chat_id,
            active_user_ids={1001},
        )

        assert deactivated == 2

        members = await ChatRepository.get_user_chat_members(db_session, chat_id=chat_id, is_active=True)
        assert len(members) == 1
        assert members[0].FID == 1001
