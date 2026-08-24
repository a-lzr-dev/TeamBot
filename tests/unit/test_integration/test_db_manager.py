"""
Модуль с интеграционными тестами для менеджера базы данных (DBManager).

Содержит набор тестов для проверки корректности работы DBManager:
- синглтон-паттерн (единственный экземпляр менеджера);
- регистрация баз данных с конфигурацией;
- получение движка (engine) по имени;
- обработка ошибки при запросе несуществующей БД;
- инициализация всех зарегистрированных БД;
- получение сессии для работы с БД;
- сбор статистики по подключениям;
- корректное закрытие всех соединений.

Тесты используют моки для изоляции от реальных подключений к БД
и асинхронные фикстуры для проверки работы контекстных менеджеров.
"""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.db.manager import DBConfig, DBEngine, DBManager


class TestDBManager:
    """
    Набор интеграционных тестов для проверки корректности работы DBManager.

    Тестируются все основные операции менеджера БД:
    - управление экземплярами (синглтон);
    - регистрация и получение конфигураций;
    - жизненный цикл соединений (инициализация, сессии, закрытие);
    - мониторинг и статистика.
    """

    @pytest.fixture
    def db_manager(self):
        """Создаёт экземпляр менеджера БД для каждого теста."""
        return DBManager()

    def test_singleton(self, db_manager):
        """
        Проверяет, что DBManager реализует паттерн синглтон.

        Два вызова конструктора должны возвращать один и тот же объект.
        """
        manager2 = DBManager()
        assert db_manager is manager2

    def test_register_database(self, db_manager):
        """
        Проверяет регистрацию новой базы данных.

        После регистрации движок должен появиться в словаре _engines,
        а первая зарегистрированная БД становится первичной.
        """
        config = DBConfig(
            url="sqlite+aiosqlite:///:memory:",
            echo=False,
            is_primary=True,
        )
        db_manager.register_database("test", config)

        assert "test" in db_manager._engines
        assert db_manager._primary_name == "test"

    def test_get_engine(self, db_manager):
        """
        Проверяет получение движка (DBEngine) по имени зарегистрированной БД.

        Возвращаемый объект должен быть экземпляром DBEngine.
        """
        config = DBConfig(
            url="sqlite+aiosqlite:///:memory:",
            echo=False,
            is_primary=True,
        )
        db_manager.register_database("test", config)

        engine = db_manager.get_engine("test")
        assert engine is not None
        assert isinstance(engine, DBEngine)

    def test_get_engine_not_found(self, db_manager):
        """
        Проверяет, что при запросе несуществующей БД выбрасывается KeyError.
        """
        with pytest.raises(KeyError):
            db_manager.get_engine("nonexistent")

    @pytest.mark.asyncio
    async def test_initialize_all(self, db_manager):
        """
        Проверяет инициализацию всех зарегистрированных БД.

        Мокается метод initialize() движка. После вызова флаг is_initialized
        должен стать True.
        """
        config = DBConfig(
            url="sqlite+aiosqlite:///:memory:",
            echo=False,
            is_primary=True,
        )
        db_manager.register_database("test", config)

        with patch.object(db_manager._engines["test"], "initialize", AsyncMock()):
            await db_manager.initialize_all()
            assert db_manager.is_initialized is True

    @pytest.mark.asyncio
    async def test_get_session(self, db_manager):
        """
        Проверяет получение асинхронной сессии через контекстный менеджер.

        Создаётся мок-сессия с необходимыми асинхронными методами,
        которая должна быть возвращена при входе в контекстный менеджер.
        """
        config = DBConfig(
            url="sqlite+aiosqlite:///:memory:",
            echo=False,
            is_primary=True,
        )
        db_manager.register_database("test", config)

        mock_session = MagicMock()
        mock_session.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session.__aexit__ = AsyncMock(return_value=None)
        mock_session.commit = AsyncMock()
        mock_session.rollback = AsyncMock()
        mock_session.close = AsyncMock()
        mock_session.execute = AsyncMock()

        mock_session_factory = MagicMock(return_value=mock_session)

        engine = db_manager._engines["test"]
        engine._session_factory = mock_session_factory
        engine._initialized = True

        with patch.object(engine, "initialize", AsyncMock()):
            async with db_manager.get_session("test") as session:
                assert session == mock_session

        mock_session_factory.assert_called_once()

    @pytest.mark.asyncio
    async def test_get_stats(self, db_manager):
        """
        Проверяет получение статистики по БД.

        Возвращаемый словарь должен содержать информацию о базах данных,
        первичной БД, счётчике сессий и общем количестве БД.
        """
        config = DBConfig(
            url="sqlite+aiosqlite:///:memory:",
            echo=False,
            is_primary=True,
        )
        db_manager.register_database("test", config)

        stats = await db_manager.get_stats()
        assert "databases" in stats
        assert "primary" in stats
        assert "session_counter" in stats
        assert "total_databases" in stats

    @pytest.mark.asyncio
    async def test_close_all(self, db_manager):
        """
        Проверяет корректное закрытие всех соединений с БД.

        После вызова close_all() все движки должны быть освобождены,
        а флаг is_initialized установлен в False.
        """
        config = DBConfig(
            url="sqlite+aiosqlite:///:memory:",
            echo=False,
            is_primary=True,
        )
        db_manager.register_database("test", config)

        with patch.object(db_manager._engines["test"], "dispose", AsyncMock()):
            await db_manager.close_all()
            assert db_manager.is_initialized is False
