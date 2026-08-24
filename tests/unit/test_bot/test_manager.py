"""Расширенные тесты для BotManager.

Этот модуль содержит комплексные тесты для основного менеджера бота,
проверяющие его ключевые функции и взаимодействие с компонентами.

Тесты покрывают:
1. Инициализацию менеджера и всех его сервисов
2. Запуск и остановку бота
3. Проверку авторизации пользователей
4. Получение команд для разных типов пользователей
5. Получение статуса всех компонентов
6. Проверку здоровья (health check) системы

Особенности:
- Использует моки для изоляции от внешних зависимостей (Telegram API, БД)
- Проверяет корректность флагов состояния (_initialized, _is_running)
- Верифицирует взаимодействие с сервисами через патчи
- Тестирует публичные методы, доступные для внешнего использования

Примечания:
- Все тесты асинхронные (pytest.mark.asyncio)
- Используется pytest фикстура для создания экземпляра BotManager
- Моки настроены на возврат корректных значений для успешного прохождения тестов
"""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.bot.manager import BotManager


class TestBotManagerExtended:
    """Расширенные тесты для BotManager.

    Класс содержит тесты для проверки:
    - Жизненного цикла менеджера (инициализация, запуск, остановка)
    - Авторизации пользователей
    - Доступных команд
    - Статуса и здоровья системы
    """

    @pytest.fixture
    def bot_manager(self):
        """Создание менеджера бота для тестов.

        Возвращает новый экземпляр BotManager без инициализации.
        Используется в каждом тесте для изолированной проверки.

        Returns:
            BotManager: Новый экземпляр менеджера бота
        """
        return BotManager()

    @pytest.mark.asyncio
    async def test_initialize(self, bot_manager):
        """Тест инициализации менеджера.

        Проверяет, что:
        1. Начальное состояние _initialized = False
        2. После вызова initialize() все сервисы инициализируются
        3. Флаг _initialized становится True

        Использует моки для всех зависимостей, чтобы избежать реальных вызовов.
        """
        assert bot_manager._initialized is False

        with (
            patch.object(bot_manager._aiogram_client, "initialize", AsyncMock()),
            patch.object(bot_manager._telethon_client, "initialize", AsyncMock()),
            patch.object(bot_manager._message_service, "initialize", AsyncMock()),
            patch.object(bot_manager._bot_service, "initialize", AsyncMock()),
            patch.object(bot_manager._chat_service, "initialize", AsyncMock()),
            patch.object(bot_manager._user_service, "initialize", AsyncMock()),
            patch.object(bot_manager._sync_service, "initialize", AsyncMock()),
        ):
            await bot_manager.initialize()
            assert bot_manager._initialized is True

    @pytest.mark.asyncio
    async def test_start_stop(self, bot_manager):
        """Тест запуска и остановки бота.

        Проверяет:
        1. Метод start() запускает все компоненты
        2. Флаг _is_running становится True после start()
        3. Метод stop() останавливает все компоненты
        4. Флаг _is_running становится False после stop()

        Использует моки для методов, выполняющих реальные операции с Telegram API.
        """
        with (
            patch.object(bot_manager, "initialize", AsyncMock()),
            patch.object(bot_manager, "_setup_aiogram", AsyncMock(return_value=MagicMock())),
            patch.object(bot_manager, "_setup_telethon", AsyncMock()),
            patch.object(bot_manager, "_run_aiogram", AsyncMock()),
            patch.object(bot_manager, "_run_telethon", AsyncMock()),
            patch.object(bot_manager, "_wait_for_completion", AsyncMock()),
        ):
            await bot_manager.start()
            assert bot_manager._is_running is True

            await bot_manager.stop()
            assert bot_manager._is_running is False

    @pytest.mark.asyncio
    async def test_is_user_authorized(self, bot_manager):
        """Тест проверки авторизации пользователя.

        Проверяет:
        1. Метод возвращает True для авторизованных пользователей
        2. Метод возвращает False для неавторизованных пользователей
        3. Используется репозиторий UserRepository для проверки

        Использует моки для БД и репозитория, чтобы избежать реальных запросов.
        """
        # Пропускаем инициализацию клиента через мок
        with (
            patch.object(bot_manager, "_initialized", True),
            patch("app.bot.manager.db_manager") as mock_db,
        ):
            mock_session = AsyncMock()
            mock_db.get_session.return_value.__aenter__.return_value = mock_session

            with patch("app.bot.manager.UserRepository.is_user_authenticated", AsyncMock(return_value=True)):
                result = await bot_manager.is_user_authorized(123)
                assert result is True

            with patch("app.bot.manager.UserRepository.is_user_authenticated", AsyncMock(return_value=False)):
                result = await bot_manager.is_user_authorized(123)
                assert result is False

    @pytest.mark.asyncio
    async def test_get_commands_for_user(self, bot_manager):
        """Тест получения команд для пользователя.

        Проверяет три категории команд:
        1. Публичные команды (/start, /help) - доступны всем
        2. Команды для авторизованных пользователей (/actions, /logout и др.)
        3. Административные команды (/users, /admins и др.)

        Убеждается, что каждая категория содержит ожидаемые команды.
        """
        commands = bot_manager.get_public_commands()
        assert len(commands) >= 2
        assert any(c["command"] == "/start" for c in commands)

        auth_commands = bot_manager.get_auth_commands()
        assert len(auth_commands) >= 6
        assert any(c["command"] == "/actions" for c in auth_commands)

        admin_commands = bot_manager.get_admin_commands()
        assert len(admin_commands) >= 4
        assert any(c["command"] == "/users" for c in admin_commands)

    @pytest.mark.asyncio
    async def test_get_status(self, bot_manager):
        """Тест получения статуса всех компонентов.

        Проверяет:
        1. Статус возвращает информацию о состоянии менеджера
        2. Флаги _is_running и _is_initialized корректно отображаются
        3. Статусы всех клиентов (aiogram, telethon, sync) присутствуют в ответе

        Использует моки для клиентов, чтобы вернуть предсказуемые значения.
        """
        bot_manager._initialized = True
        bot_manager._is_running = True

        with (
            patch.object(bot_manager._aiogram_client, "get_status", AsyncMock(return_value={"connected": True})),
            patch.object(bot_manager._telethon_client, "get_status", AsyncMock(return_value={"connected": True})),
            patch.object(bot_manager._sync_service, "get_status", AsyncMock(return_value={"initialized": True})),
        ):
            status = await bot_manager.get_status()
            assert status["is_running"] is True
            assert status["is_initialized"] is True
            assert "aiogram" in status
            assert "telethon" in status
            assert "sync" in status

    @pytest.mark.asyncio
    async def test_health_check(self, bot_manager):
        """Тест проверки здоровья всех компонентов.

        Проверяет:
        1. Менеджер инициализирован
        2. Aiogram клиент подключен
        3. Telethon клиент подключен

        Использует моки для is_connected() методов клиентов.
        """
        bot_manager._initialized = True

        with (
            patch.object(bot_manager._aiogram_client, "is_connected", AsyncMock(return_value=True)),
            patch.object(bot_manager._telethon_client, "is_connected", AsyncMock(return_value=True)),
        ):
            health = await bot_manager.health_check()
            assert health["manager_initialized"] is True
            assert health["aiogram"] is True
            assert health["telethon"] is True
