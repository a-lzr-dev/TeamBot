"""
Модуль с тестами для репозитория сообщений (MessageRepository).

Содержит набор асинхронных интеграционных тестов, проверяющих работу с сообщениями:
- создание сообщений с уникальными идентификаторами;
- обновление существующих сообщений;
- UPSERT-операция (создание или обновление);
- получение сообщений по ID и по чату;
- установка времени жизни сообщения;
- отметка сообщений как удалённых;
- получение истекших сообщений;
- подсчёт количества сообщений в чате.

Тесты используют реальную тестовую БД (in-memory SQLite) и создают
тестовые данные (чат, пользователь) перед каждым тестом.
"""

import time

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.repositories import ChatRepository, MessageRepository, UserRepository
from app.models import MessageSource, MessageType, datetime_now


class TestMessageRepository:
    """
    Набор тестов для проверки корректности работы MessageRepository.

    Тестируются все основные операции с сообщениями:
    - CRUD (создание, чтение, обновление, удаление);
    - управление временем жизни;
    - поиск и фильтрация;
    - агрегация (подсчёт количества).
    """

    @pytest.fixture(autouse=True)
    async def setup_chat_and_user(self, db_session: AsyncSession) -> None:
        """
        Создаёт тестовый чат и пользователя перед каждым тестом.

        Используется фикстура autouse=True, чтобы гарантировать наличие
        базовых сущностей для всех тестов MessageRepository.
        """
        self.chat_id = -1001234567899
        self.user_id = 12348
        self.timestamp = int(time.time() * 1000) % 1000000

        await ChatRepository.save_chat(
            session=db_session,
            chat_id=self.chat_id,
            chat_type="supergroup",
            title="Message Test Chat",
        )

        await UserRepository.save_user(
            session=db_session,
            user_id=self.user_id,
            first_name="Test",
            username=f"test_user_{self.timestamp}",
        )

        await db_session.commit()

    @pytest.mark.asyncio
    async def test_create_message(self, db_session: AsyncSession) -> None:
        """
        Проверяет создание сообщения со всеми полями.

        После создания проверяются:
        - идентификатор сообщения;
        - связь с чатом и пользователем;
        - тип сообщения;
        - текст;
        - время жизни и дата истечения.
        """
        message_id = int(time.time() * 1000) % 1000000000 + 123456

        message = await MessageRepository.create_message(
            session=db_session,
            message_id=message_id,
            chat_id=self.chat_id,
            user_id=self.user_id,
            message_type=MessageType.BOT_RESPONSE,
            text="Test message",
            source=MessageSource.BOT,
            lifetime_seconds=300,
        )

        assert message is not None
        assert message.FID == message_id
        assert message.FK_Chat == self.chat_id
        assert message.FK_User == self.user_id
        assert message.FK_MessageType == MessageType.BOT_RESPONSE
        assert message.FText == "Test message"
        assert message.FLifetimeSeconds == 300
        assert message.FExpiresAt is not None

    @pytest.mark.asyncio
    async def test_update_message(self, db_session: AsyncSession) -> None:
        """
        Проверяет обновление существующего сообщения.

        Создаётся сообщение с исходным текстом, затем обновляется
        через метод update_message. Проверяется, что текст изменился.
        """
        message_id = int(time.time() * 1000) % 1000000000 + 123457

        await MessageRepository.create_message(
            session=db_session,
            message_id=message_id,
            chat_id=self.chat_id,
            message_type=MessageType.BOT_RESPONSE,
            text="Original text",
            source=MessageSource.BOT,
        )

        updated = await MessageRepository.update_message(
            session=db_session,
            message_id=message_id,
            text="Updated text",
        )

        assert updated is not None
        assert updated.FText == "Updated text"

    @pytest.mark.asyncio
    async def test_create_or_update_message(self, db_session: AsyncSession) -> None:
        """
        Проверяет UPSERT-операцию: создание или обновление сообщения.

        При первом вызове должно создаваться новое сообщение (created=True),
        при втором — обновляться существующее (created=False).
        """
        message_id = int(time.time() * 1000) % 1000000000 + 123458

        message, created = await MessageRepository.create_or_update_message(
            session=db_session,
            message_id=message_id,
            chat_id=self.chat_id,
            message_type=MessageType.BOT_RESPONSE,
            text="Test message",
            source=MessageSource.BOT,
        )

        assert created is True
        assert message.FText == "Test message"

        message, created = await MessageRepository.create_or_update_message(
            session=db_session,
            message_id=message_id,
            chat_id=self.chat_id,
            message_type=MessageType.BOT_RESPONSE,
            text="Updated message",
            source=MessageSource.BOT,
        )

        assert created is False
        assert message.FText == "Updated message"

    @pytest.mark.asyncio
    async def test_get_message_by_id(self, db_session: AsyncSession) -> None:
        """
        Проверяет получение сообщения по идентификатору.

        Создаётся сообщение, затем выполняется поиск по его ID.
        Ожидается, что найденное сообщение будет соответствовать созданному.
        При поиске несуществующего ID должен возвращаться None.
        """
        message_id = int(time.time() * 1000) % 1000000000 + 123459

        await MessageRepository.create_message(
            session=db_session,
            message_id=message_id,
            chat_id=self.chat_id,
            message_type=MessageType.BOT_RESPONSE,
            text="Get me",
            source=MessageSource.BOT,
        )

        message = await MessageRepository.get_message_by_id(db_session, message_id)
        assert message is not None
        assert message.FText == "Get me"

        message = await MessageRepository.get_message_by_id(db_session, 999999)
        assert message is None

    @pytest.mark.asyncio
    async def test_get_messages_by_chat(self, db_session: AsyncSession) -> None:
        """
        Проверяет получение списка сообщений по чату.

        Создаются несколько сообщений в тестовом чате,
        затем запрашивается список. Проверяется количество полученных сообщений
        и работа с параметром limit.
        """
        base_id = int(time.time() * 1000) % 1000000000 + 123460

        for i in range(3):
            await MessageRepository.create_message(
                session=db_session,
                message_id=base_id + i,
                chat_id=self.chat_id,
                message_type=MessageType.BOT_RESPONSE,
                text=f"Message {i}",
                source=MessageSource.BOT,
            )

        messages = await MessageRepository.get_messages_by_chat(db_session, self.chat_id, limit=10)
        assert len(messages) >= 3

        messages = await MessageRepository.get_messages_by_chat(db_session, self.chat_id, limit=3)
        assert len(messages) <= 3

    @pytest.mark.asyncio
    async def test_set_message_lifetime(self, db_session: AsyncSession) -> None:
        """
        Проверяет установку времени жизни сообщения.

        Создаётся сообщение без времени жизни, затем через метод
        set_message_lifetime устанавливается срок жизни 600 секунд.
        Проверяется, что поля FLifetimeSeconds и FExpiresAt заполнены.
        """
        message_id = int(time.time() * 1000) % 1000000000 + 123465

        await MessageRepository.create_message(
            session=db_session,
            message_id=message_id,
            chat_id=self.chat_id,
            message_type=MessageType.BOT_RESPONSE,
            text="Lifetime test",
            source=MessageSource.BOT,
        )

        result = await MessageRepository.set_message_lifetime(db_session, message_id, 600)
        assert result is True

        message = await MessageRepository.get_message_by_id(db_session, message_id)
        assert message is not None
        assert message.FLifetimeSeconds == 600
        assert message.FExpiresAt is not None

    @pytest.mark.asyncio
    async def test_mark_messages_as_deleted(self, db_session: AsyncSession) -> None:
        """
        Проверяет отметку сообщений как удалённых.

        Создаются три сообщения, два из них помечаются как удалённые.
        Проверяется, что у помеченных сообщений FFlagDeleted = True,
        а у третьего — False.
        """
        base_id = int(time.time() * 1000) % 1000000000 + 123470

        for i in range(3):
            await MessageRepository.create_message(
                session=db_session,
                message_id=base_id + i,
                chat_id=self.chat_id,
                message_type=MessageType.BOT_RESPONSE,
                text=f"Delete {i}",
                source=MessageSource.BOT,
            )

        deleted = await MessageRepository.mark_messages_as_deleted(
            session=db_session,
            message_ids=[base_id, base_id + 1],
            deleted_by_type="test",
        )

        assert deleted == 2

        msg1 = await MessageRepository.get_message_by_id(db_session, base_id)
        assert msg1 is not None
        assert msg1.FFlagDeleted is True

        msg3 = await MessageRepository.get_message_by_id(db_session, base_id + 2)
        assert msg3 is not None
        assert msg3.FFlagDeleted is False

    @pytest.mark.asyncio
    async def test_get_expired_messages(self, db_session: AsyncSession) -> None:
        """
        Проверяет получение сообщений с истекшим временем жизни.

        Создаются сообщения с временем жизни 1 секунда,
        затем их дата истечения принудительно устанавливается в прошлое.
        Метод get_expired_messages должен вернуть все такие сообщения.
        """
        now = datetime_now()
        base_id = int(time.time() * 1000) % 1000000000 + 123480

        for i in range(3):
            msg = await MessageRepository.create_message(
                session=db_session,
                message_id=base_id + i,
                chat_id=self.chat_id,
                message_type=MessageType.BOT_RESPONSE,
                text=f"Expired {i}",
                source=MessageSource.BOT,
                lifetime_seconds=1,
            )
            msg.FExpiresAt = now
            await db_session.commit()

        expired = await MessageRepository.get_expired_messages(db_session, limit=10)
        assert len(expired) >= 3

    @pytest.mark.asyncio
    async def test_get_message_count_by_chat(self, db_session: AsyncSession) -> None:
        """
        Проверяет подсчёт количества сообщений в чате.

        Создаются три сообщения в тестовом чате,
        затем запрашивается их количество. Ожидается, что count >= 3.
        """
        base_id = int(time.time() * 1000) % 1000000000 + 123490

        for i in range(3):
            await MessageRepository.create_message(
                session=db_session,
                message_id=base_id + i,
                chat_id=self.chat_id,
                message_type=MessageType.BOT_RESPONSE,
                text=f"Count {i}",
                source=MessageSource.BOT,
            )

        count = await MessageRepository.get_message_count_by_chat(db_session, self.chat_id)
        assert count >= 3
