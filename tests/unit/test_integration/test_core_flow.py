"""
Модуль с интеграционным тестом основного потока работы приложения.

Содержит набор тестов для проверки ключевых сценариев работы приложения:
1. Инициализация и запуск приложения;
2. Запуск отдельных компонентов (DB, API, Bot);
3. Обработка ошибок при запуске компонентов;
4. Получение статуса и проверка здоровья;
5. Остановка приложения.

Тесты используют моки для всех внешних зависимостей (DBManager, APIManager, BotManager),
что позволяет тестировать логику ApplicationManager без реальных подключений.
"""

from unittest.mock import AsyncMock, MagicMock

import pytest

from app.api.manager import APIManager
from app.bot.manager import BotManager
from app.core.application import ApplicationManager, AppState
from app.db.manager import DBManager


class TestCoreFlow:
    """
    Набор интеграционных тестов для проверки основного потока работы приложения.

    Тестируются все ключевые методы ApplicationManager:
    - start() — запуск приложения и его компонентов;
    - stop() — корректная остановка;
    - get_status() — получение текущего состояния;
    - health_check() — проверка работоспособности;
    - uptime — вычисление времени работы.
    """

    @pytest.fixture
    def mock_db(self):
        """Создаёт мок менеджера базы данных (DBManager) с асинхронными методами."""
        db = MagicMock(spec=DBManager)
        db.initialize_all = AsyncMock()
        db.init_tables = AsyncMock()
        db.seed_tables = AsyncMock()
        db.get_session = AsyncMock()
        db.close_all = AsyncMock()
        return db

    @pytest.fixture
    def mock_api(self):
        """Создаёт мок менеджера API (APIManager) с асинхронными методами."""
        api = MagicMock(spec=APIManager)
        api.initialize = AsyncMock()
        api.start = AsyncMock()
        api.stop = AsyncMock()
        api.is_running = False
        api.get_status = AsyncMock(return_value={"is_running": False})
        return api

    @pytest.fixture
    def mock_bot(self):
        """Создаёт мок менеджера бота (BotManager) с асинхронными методами."""
        bot = MagicMock(spec=BotManager)
        bot.start = AsyncMock()
        bot.stop = AsyncMock()
        bot.initialize = AsyncMock()
        bot.is_running = False
        bot.get_status = AsyncMock(return_value={"is_running": False})
        bot.health_check = AsyncMock(return_value={"is_running": False})
        return bot

    @pytest.mark.asyncio
    async def test_full_application_flow(self, mock_db, mock_api, mock_bot):
        """
        Проверяет полный цикл работы приложения: запуск → проверка статуса → остановка.

        Шаги:
        1. Создаётся экземпляр ApplicationManager.
        2. Подменяются компоненты на моки.
        3. Выполняется запуск всех компонентов (db, api, bot).
        4. Проверяется, что состояние приложения изменилось на RUNNING.
        5. Проверяется получение статуса и здоровья.
        6. Выполняется остановка приложения.
        7. Проверяется, что состояние изменилось на STOPPED.
        """
        app = ApplicationManager()
        app.db = mock_db
        app.api = mock_api
        app.bot = mock_bot

        await app.start(["db", "api", "bot"])
        assert app.state == AppState.RUNNING
        assert app.is_running is True

        status = await app.get_status()
        assert status["app"]["state"] == "running"
        assert status["app"]["is_running"] is True

        health = await app.health_check()
        assert health["app"] is True

        await app.stop()
        assert app.state == AppState.STOPPED
        assert app.is_running is False

    @pytest.mark.asyncio
    async def test_application_start_components(self, mock_db, mock_api, mock_bot):
        """
        Проверяет запуск отдельных компонентов приложения.

        При запуске только компонента "db" должны быть вызваны методы
        initialize_all() и init_tables() менеджера БД.
        """
        app = ApplicationManager()
        app.db = mock_db
        app.api = mock_api
        app.bot = mock_bot

        await app.start(["db"])
        assert app.state == AppState.RUNNING
        mock_db.initialize_all.assert_called_once()
        mock_db.init_tables.assert_called_once()

        await app.stop(["db"])
        assert app.state == AppState.STOPPED

    @pytest.mark.asyncio
    async def test_application_error_handling(self, mock_db, mock_api, mock_bot):
        """
        Проверяет обработку ошибок при запуске компонентов.

        Симулируется ошибка при инициализации БД.
        Ожидается, что приложение не останется в состоянии RUNNING,
        а перейдёт в ERROR или STOPPED.
        """
        app = ApplicationManager()
        app.db = mock_db
        app.api = mock_api
        app.bot = mock_bot

        mock_db.initialize_all = AsyncMock(side_effect=Exception("DB connection failed"))

        with pytest.raises(Exception, match="DB connection failed"):
            await app.start(["db"])

        assert app.is_running is False
        assert app.state in (AppState.ERROR, AppState.STOPPED)

    @pytest.mark.asyncio
    async def test_application_uptime(self):
        """
        Проверяет вычисление времени работы (uptime) приложения.

        Устанавливается состояние RUNNING с фиктивным временем старта.
        Ожидается, что uptime возвращает неотрицательное число.
        После остановки uptime должен стать None.
        """
        app = ApplicationManager()
        app._state = AppState.RUNNING
        app._start_time = 100.0

        assert app.is_running is True
        assert app.uptime is not None
        assert app.uptime >= 0

        app._state = AppState.STOPPED
        app._start_time = None

        assert app.is_running is False
        assert app.uptime is None
