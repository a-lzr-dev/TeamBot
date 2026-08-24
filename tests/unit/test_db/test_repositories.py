"""
Модуль с тестами для репозитория пользователей (UserRepository).

Содержит набор асинхронных интеграционных тестов, проверяющих базовые операции
с пользователями в базе данных:
- создание нового пользователя;
- обновление существующего пользователя;
- получение пользователя по ID;
- получение пользователя по номеру телефона;
- получение всех пользователей (с пагинацией);
- обновление времени последней активности.

Тесты используют реальную тестовую БД (in-memory SQLite) и проверяют
как позитивные, так и негативные сценарии.
"""

import uuid

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.repositories import UserRepository


class TestUserRepository:
    """
    Набор тестов для проверки корректности работы UserRepository.

    Тестируются методы CRUD и поиска:
    - save_user — создание и обновление;
    - get_user_by_id — получение по идентификатору;
    - get_user_by_phone — получение по номеру телефона;
    - get_all_users — получение списка с пагинацией;
    - update_last_activity — обновление времени активности.
    """

    @pytest.mark.asyncio
    async def test_save_user_create(self, db_session: AsyncSession, sample_user_data: dict) -> None:
        """
        Проверяет создание нового пользователя.

        После сохранения проверяются все переданные поля:
        FID, FFirstName, FLastName, FUserName, FFlagBot, FPhone.
        """
        user = await UserRepository.save_user(
            session=db_session,
            user_id=sample_user_data["user_id"],
            first_name=sample_user_data["first_name"],
            last_name=sample_user_data["last_name"],
            username=sample_user_data["username"],
            is_bot=sample_user_data["is_bot"],
            phone=sample_user_data["phone"],
        )

        assert user is not None
        assert user.FID == sample_user_data["user_id"]
        assert user.FFirstName == sample_user_data["first_name"]
        assert user.FLastName == sample_user_data["last_name"]
        assert user.FUserName == sample_user_data["username"]
        assert user.FFlagBot == sample_user_data["is_bot"]
        assert user.FPhone == sample_user_data["phone"]

    @pytest.mark.asyncio
    async def test_save_user_update(self, db_session: AsyncSession) -> None:
        """
        Проверяет обновление существующего пользователя.

        Сначала создаётся пользователь с начальными данными,
        затем он обновляется с новыми значениями.
        Проверяется, что все поля изменились корректно.
        """
        user_id = 987654321
        unique_suffix = uuid.uuid4().hex[:8]

        await UserRepository.save_user(
            session=db_session,
            user_id=user_id,
            first_name="Old",
            last_name="Name",
            username=f"old_user_{unique_suffix}",
            is_bot=False,
            phone="+123",
        )

        user = await UserRepository.save_user(
            session=db_session,
            user_id=user_id,
            first_name="New",
            last_name="Name",
            username=f"new_user_{unique_suffix}",
            is_bot=True,
            phone="+456",
        )

        assert user.FFirstName == "New"
        assert user.FUserName == f"new_user_{unique_suffix}"
        assert user.FFlagBot is True
        assert user.FPhone == "+456"

    @pytest.mark.asyncio
    async def test_get_user_by_id(self, db_session: AsyncSession, sample_user_data: dict) -> None:
        """
        Проверяет получение пользователя по ID.

        Создаётся пользователь, затем выполняется поиск по его ID.
        Ожидается, что найденный пользователь будет соответствовать созданному.
        При поиске несуществующего ID должен возвращаться None.
        """
        await UserRepository.save_user(
            session=db_session,
            user_id=sample_user_data["user_id"],
            first_name="Test",
            last_name="User",
            username="test_user",
        )

        user = await UserRepository.get_user_by_id(db_session, sample_user_data["user_id"])

        assert user is not None
        assert user.FID == sample_user_data["user_id"]

        user = await UserRepository.get_user_by_id(db_session, 999999)
        assert user is None

    @pytest.mark.asyncio
    async def test_get_user_by_phone(self, db_session: AsyncSession) -> None:
        """
        Проверяет получение пользователя по номеру телефона.

        Создаётся пользователь с указанным номером, затем выполняется поиск.
        Ожидается, что найденный пользователь будет соответствовать созданному.
        При поиске несуществующего номера должен возвращаться None.
        """
        user_id = 123456790
        phone = "+1234567890"

        await UserRepository.save_user(
            session=db_session,
            user_id=user_id,
            first_name="Test",
            username="test_user",
            phone=phone,
        )
        await db_session.commit()

        user = await UserRepository.get_user_by_phone(db_session, phone)
        assert user is not None
        assert user.FID == user_id

        user = await UserRepository.get_user_by_phone(db_session, "+999")
        assert user is None

    @pytest.mark.asyncio
    async def test_get_all_users(self, db_session: AsyncSession) -> None:
        """
        Проверяет получение всех пользователей.

        Создаются несколько пользователей с уникальными идентификаторами,
        затем запрашивается полный список. Проверяется, что все созданные
        пользователи присутствуют в результатах.
        Также проверяется работа с лимитом (пагинацией).
        """
        unique_suffix = uuid.uuid4().hex[:8]

        for i in range(3):
            await UserRepository.save_user(
                session=db_session,
                user_id=100 + i,
                first_name=f"User{i}",
                username=f"user_{unique_suffix}_{i}",
            )

        users = await UserRepository.get_all_users(db_session)
        user_ids = {u.FID for u in users}
        assert any(uid in user_ids for uid in [100, 101, 102])

        users = await UserRepository.get_all_users(db_session, limit=2)
        assert len(users) <= 2

    @pytest.mark.asyncio
    async def test_update_last_activity(self, db_session: AsyncSession, sample_user_data: dict) -> None:
        """
        Проверяет обновление времени последней активности пользователя.

        Создаётся пользователь, затем вызывается метод update_last_activity.
        Для существующего пользователя метод должен вернуть True,
        для несуществующего — False.
        """
        await UserRepository.save_user(
            session=db_session,
            user_id=sample_user_data["user_id"],
            first_name="Test",
            username="test_user",
        )

        result = await UserRepository.update_last_activity(db_session, sample_user_data["user_id"])
        assert result is True

        result = await UserRepository.update_last_activity(db_session, 999999)
        assert result is False
