"""
Модуль с расширенными тестами для репозитория пользователей (UserRepository).

Содержит набор асинхронных интеграционных тестов, проверяющих работу с пользователями:
- сохранение пользователя со всеми полями;
- частичное обновление пользователя (сохранение существующих значений);
- получение всех пользователей с ограничением по количеству;
- поиск пользователей по имени и username;
- обновление времени последней активности;
- обработка несуществующего телефона;
- валидация некорректных идентификаторов.

Тесты используют реальную тестовую БД (in-memory SQLite) и проверяют
как позитивные, так и негативные сценарии.
"""

import uuid

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.repositories import UserRepository


class TestUserRepositoryExtended:
    """
    Расширенный набор тестов для проверки корректности работы UserRepository.

    Тестируются методы:
    - save_user — создание и обновление пользователей;
    - get_all_users — получение списка с пагинацией;
    - search_users — поиск по тексту;
    - update_last_activity — обновление времени активности;
    - get_user_by_phone — поиск по номеру телефона;
    - валидация входных данных.
    """

    @pytest.mark.asyncio
    async def test_save_user_with_all_fields(self, db_session: AsyncSession):
        """
        Проверяет сохранение пользователя со всеми доступными полями.

        После сохранения проверяются все переданные атрибуты:
        FID, FFirstName, FLastName, FUserName, FFlagBot, FPhone, FK_Chat.
        """
        user_id = 123456789
        user = await UserRepository.save_user(
            session=db_session,
            user_id=user_id,
            first_name="Test",
            last_name="User",
            username="test_user_full",
            is_bot=False,
            phone="+1234567890",
            chat_id=123456,
        )

        assert user.FID == user_id
        assert user.FFirstName == "Test"
        assert user.FLastName == "User"
        assert user.FUserName == "test_user_full"
        assert user.FFlagBot is False
        assert user.FPhone == "+1234567890"
        assert user.FK_Chat == 123456

    @pytest.mark.asyncio
    async def test_save_user_update_partial(self, db_session: AsyncSession):
        """
        Проверяет частичное обновление пользователя.

        При обновлении с частичными данными:
        - Переданные поля должны обновиться.
        - Непереданные поля должны остаться без изменений.

        Особенно важно: если username не передан, он не должен
        перезаписываться значением None.
        """
        user_id = 123456790
        original_username = "old_user"

        user = await UserRepository.save_user(
            session=db_session,
            user_id=user_id,
            first_name="Old",
            last_name="Name",
            username=original_username,
            is_bot=False,
            phone="+123",
        )
        assert user.FUserName == original_username

        updated_user = await UserRepository.save_user(
            session=db_session,
            user_id=user_id,
            first_name="New",
        )

        assert updated_user.FFirstName == "New"
        assert updated_user.FUserName == original_username
        assert updated_user.FLastName == "Name"
        assert updated_user.FFlagBot is False
        assert updated_user.FPhone == "+123"

    @pytest.mark.asyncio
    async def test_get_all_users_with_limit(self, db_session: AsyncSession):
        """
        Проверяет получение списка пользователей с ограничением по количеству.

        Создаются несколько пользователей с уникальными идентификаторами,
        затем запрашивается список с лимитом 2. Проверяется, что:
        - возвращено не более 2 записей;
        - хотя бы один из созданных пользователей присутствует в результатах.
        """
        unique_suffix = uuid.uuid4().hex[:8]

        user_ids = []
        for i in range(3):
            user_id = 123456800 + i
            user_ids.append(user_id)
            await UserRepository.save_user(
                session=db_session,
                user_id=user_id,
                first_name=f"User{i}",
                username=f"user_{unique_suffix}_{i}",
                is_bot=False,
            )

        users = await UserRepository.get_all_users(db_session, limit=2)

        assert len(users) <= 2

        user_ids_found = {u.FID for u in users}
        assert any(uid in user_ids_found for uid in user_ids)

    @pytest.mark.asyncio
    async def test_search_users(self, db_session: AsyncSession):
        """
        Проверяет поиск пользователей по тексту (имя, фамилия, username).

        Создаётся тестовый пользователь, затем выполняются поисковые запросы:
        - по имени — ожидается результат;
        - по уникальному суффиксу в username — ожидается результат;
        - по несуществующему запросу — ожидается пустой список.
        """
        unique_suffix = uuid.uuid4().hex[:8]

        await UserRepository.save_user(
            session=db_session,
            user_id=123456700,
            first_name="SearchTest",
            last_name="User",
            username=f"search_user_{unique_suffix}",
        )

        results = await UserRepository.search_users(db_session, "SearchTest")
        assert len(results) >= 1
        assert any(u.FFirstName == "SearchTest" for u in results)

        results = await UserRepository.search_users(db_session, unique_suffix)
        assert len(results) >= 1

        results = await UserRepository.search_users(db_session, "nonexistent_user_xyz")
        assert len(results) == 0

    @pytest.mark.asyncio
    async def test_update_last_activity(self, db_session: AsyncSession):
        """
        Проверяет обновление времени последней активности пользователя.

        Для существующего пользователя метод должен вернуть True,
        для несуществующего — False.
        """
        user_id = 123456600

        await UserRepository.save_user(
            session=db_session,
            user_id=user_id,
            first_name="Activity",
            username="activity_user",
        )

        result = await UserRepository.update_last_activity(db_session, user_id)
        assert result is True

        result = await UserRepository.update_last_activity(db_session, 999999)
        assert result is False

    @pytest.mark.asyncio
    async def test_get_user_by_phone_not_found(self, db_session: AsyncSession):
        """
        Проверяет, что при поиске пользователя по несуществующему номеру
        возвращается None.
        """
        user = await UserRepository.get_user_by_phone(db_session, "+9999999999")
        assert user is None

    @pytest.mark.asyncio
    async def test_save_user_invalid_id(self, db_session: AsyncSession):
        """
        Проверяет, что при попытке сохранить пользователя с невалидным ID
        выбрасывается ValueError с соответствующим сообщением.

        Тестируются ID = 0 и отрицательный ID.
        """
        with pytest.raises(ValueError, match="Invalid user_id"):
            await UserRepository.save_user(
                session=db_session,
                user_id=0,
                first_name="Invalid",
                username="invalid_user",
            )

        with pytest.raises(ValueError, match="Invalid user_id"):
            await UserRepository.save_user(
                session=db_session,
                user_id=-1,
                first_name="Invalid",
                username="invalid_user",
            )
