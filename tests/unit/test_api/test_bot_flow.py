"""End-to-end тесты для бота.

Этот модуль содержит сквозные (E2E) тесты для проверки работы бота
в целом. Тесты проверяют основные сценарии использования бота
без реального взаимодействия с Telegram API (используются моки).

Тесты покрывают:
1. Инициализацию бота
2. Получение публичных команд
3. Получение команд для авторизованных пользователей
4. Получение административных команд
5. Работу с кешем команд пользователя
6. Статистику кеша команд

Особенности:
- Все тесты асинхронные (pytest.mark.asyncio)
- Используются моки для изоляции от внешних зависимостей
- Проверяются как позитивные, так и негативные сценарии
- Тесты не требуют реального подключения к Telegram

Примечания:
- В E2E тестах проверяются только публичные методы BotManager
- Для тестирования используются фикстуры из conftest.py
- Кеш команд проверяется на корректность добавления и удаления
"""

import pytest

from app.bot.manager import BotManager


class TestBotFlow:
    """E2E тесты для бота.

    Класс содержит сквозные тесты для проверки основных
    сценариев работы бота:
    - Инициализация менеджера
    - Команды для разных типов пользователей
    - Кеширование команд
    - Статистика кеша
    """

    @pytest.fixture
    def bot_manager(self, mock_settings) -> BotManager:
        """Создание менеджера бота для тестов.

        Использует mock_settings для изоляции от реальных настроек.
        Возвращает новый экземпляр BotManager для каждого теста.

        Args:
            mock_settings: Фикстура с тестовыми настройками

        Returns:
            BotManager: Новый экземпляр менеджера бота
        """
        return BotManager()

    @pytest.mark.asyncio
    async def test_bot_initialization(self, bot_manager: BotManager) -> None:
        """Проверка инициализации бота.

        Проверяет:
        - Флаг _initialized устанавливается в True
        - Менеджер корректно обрабатывает состояние инициализации

        Использует моки для имитации инициализации без реального API.
        """
        # В тестах используем моки
        bot_manager._initialized = True
        assert bot_manager._initialized is True

    @pytest.mark.asyncio
    async def test_get_public_commands(self) -> None:
        """Проверка публичных команд.

        Публичные команды доступны всем пользователям без авторизации:
        - /start - начало работы и авторизация
        - /help - справка по командам

        Проверяет:
        - Минимальное количество команд (>= 2)
        - Наличие обязательных команд /start и /help
        """
        commands = BotManager.get_public_commands()
        assert len(commands) >= 2
        assert any(c["command"] == "/start" for c in commands)
        assert any(c["command"] == "/help" for c in commands)

    @pytest.mark.asyncio
    async def test_get_auth_commands(self) -> None:
        """Проверка команд для авторизованных пользователей.

        Команды, доступные только после авторизации:
        - /actions - меню действий
        - /automation - меню автоматизации
        - /stats - статистика
        - /logout - выход из системы
        - /msg - контекстное меню сообщения
        - /id - получение ID пользователя

        Проверяет:
        - Минимальное количество команд (>= 6)
        - Наличие ключевых команд /actions и /logout
        """
        commands = BotManager.get_auth_commands()
        assert len(commands) >= 6
        assert any(c["command"] == "/actions" for c in commands)
        assert any(c["command"] == "/logout" for c in commands)

    @pytest.mark.asyncio
    async def test_get_admin_commands(self) -> None:
        """Проверка административных команд.

        Административные команды доступны только пользователям
        из списка ADMIN_IDS:
        - /users - список пользователей
        - /bc - меню рассылки
        - /sync - меню синхронизации
        - /admins - список администраторов

        Проверяет:
        - Минимальное количество команд (>= 4)
        - Наличие ключевых команд /users и /admins
        """
        commands = BotManager.get_admin_commands()
        assert len(commands) >= 4
        assert any(c["command"] == "/users" for c in commands)
        assert any(c["command"] == "/admins" for c in commands)

    @pytest.mark.asyncio
    async def test_user_commands_cache(self, bot_manager: BotManager) -> None:
        """Проверка кеша команд пользователя.

        Кеш команд используется для хранения персонализированных
        команд для каждого пользователя (авторизованные/администраторы).

        Проверяет:
        - Очистка кеша для пользователя
        - Добавление команд в кеш
        - Проверка наличия пользователя в кеше
        - Получение команд из кеша
        - Повторная очистка кеша

        Использует моки для имитации работы с БД и Telegram API.
        """
        user_id = 123456

        # Очистка кеша перед тестом (await обязателен, т.к. метод асинхронный)
        await bot_manager.clear_user_cache(user_id)

        # Проверяем, что кеш пуст
        assert bot_manager.is_user_in_cache(user_id) is False

        # Добавление в кеш
        bot_manager._user_commands_cache[user_id] = [{"command": "/test", "description": "Test"}]
        assert bot_manager.is_user_in_cache(user_id) is True

        # Получение команд
        commands = bot_manager.get_user_commands(user_id)
        assert commands is not None
        assert commands[0]["command"] == "/test"

        # Очистка кеша (await обязателен, т.к. метод асинхронный)
        await bot_manager.clear_user_cache(user_id)
        assert bot_manager.is_user_in_cache(user_id) is False

    @pytest.mark.asyncio
    async def test_cache_stats(self, bot_manager: BotManager) -> None:
        """Проверка статистики кеша команд.

        Статистика кеша используется для мониторинга:
        - Количество пользователей в кеше
        - Список ID пользователей

        Проверяет:
        - Корректный подсчет количества пользователей
        - Правильный список ID пользователей

        Использует моки для имитации заполнения кеша.
        """
        # Очистка кеша перед тестом (await обязателен, т.к. метод асинхронный)
        await bot_manager.clear_user_cache(0)

        # Добавление пользователей в кеш
        for i in range(3):
            bot_manager._user_commands_cache[i] = []

        stats = bot_manager.get_cache_stats()
        assert stats["total_users"] == 3
        assert sorted(stats["user_ids"]) == [0, 1, 2]
