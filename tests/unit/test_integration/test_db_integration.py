"""
Модуль с интеграционными тестами базы данных.

Содержит набор тестов для проверки корректности работы с базой данных:
- подключение к БД и выполнение простого запроса;
- существование основных таблиц;
- создание записей и откат транзакций.

Тесты используют реальные подключения к БД (in-memory SQLite или тестовую БД)
и проверяют интеграцию между DBManager, репозиториями и сессиями SQLAlchemy.
"""

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.manager import db_manager


class TestDBIntegration:
    """
    Набор интеграционных тестов для проверки работы с базой данных.

    Тестируются:
    - возможность установить соединение с БД;
    - наличие необходимых таблиц в схеме;
    - работа транзакций (создание + откат).
    """

    @pytest.mark.asyncio
    async def test_db_connection(self):
        """
        Проверяет возможность подключения к БД и выполнения простого запроса.

        Инициализируется менеджер БД, открывается сессия и выполняется
        запрос SELECT 1. Ожидается, что результат будет равен 1.
        """
        await db_manager.initialize_all()
        async with db_manager.get_session() as session:
            result = await session.execute(text("SELECT 1"))
            assert result.scalar() == 1

    @pytest.mark.asyncio
    async def test_tables_exist(self, session: AsyncSession):
        """
        Проверяет существование таблицы TUsers в схеме БД.

        Выполняется запрос к sqlite_master для проверки наличия таблицы.
        Ожидается, что таблица существует (результат не None).
        """
        result = await session.execute(text("SELECT name FROM sqlite_master WHERE type='table' AND name='TUsers'"))
        assert result.scalar() is not None

    @pytest.mark.asyncio
    async def test_create_and_rollback(self, db_session: AsyncSession):
        """
        Проверяет корректность работы транзакций: создание записи и откат.

        Шаги:
        1. Создаётся пользователь с ID 999999 через UserRepository.
        2. Выполняется flush для сохранения в БД.
        3. Проверяется, что пользователь существует.
        4. Выполняется откат транзакции (rollback).
        5. Проверяется, что пользователь был удалён из БД.

        Ожидается, что после отката запись больше не существует.
        """
        from app.db.repositories import UserRepository

        await UserRepository.save_user(
            session=db_session,
            user_id=999999,
            first_name="Rollback",
            username="rollback_test",
        )
        await db_session.flush()

        user = await UserRepository.get_user_by_id(db_session, 999999)
        assert user is not None

        await db_session.rollback()

        user = await UserRepository.get_user_by_id(db_session, 999999)
        assert user is None
