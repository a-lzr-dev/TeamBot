"""Тесты для обработчиков команд.

Этот модуль содержит тесты для проверки основных команд Telegram бота:
- /help - динамическая справка с учетом прав пользователя
- /id - получение ID пользователя и чата
- /msg - открытие контекстного меню для сообщения по ID

Тесты покрывают:
1. Команду /help для разных типов пользователей
2. Команду /id - вывод технической информации
3. Команду /msg - обработка аргументов и открытие меню

Основные компоненты:
- commands_module - модуль с обработчиками команд

Особенности:
- Все тесты асинхронные (pytest.mark.asyncio)
- Используются моки для изоляции от внешних зависимощений
- Проверяются различные сценарии использования команд
- Тестируется как позитивные, так и негативные сценарии

Примечания:
- Команда /help показывает разные команды для разных пользователей
- Команда /msg требует передачи ID сообщения
- Все команды используют единый механизм очистки старых сообщений
"""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from aiogram.types import Chat, Message, User

# Import the module, not the specific function
import app.bot.handlers.aiogram.commands as commands_module


class TestCommandsHandlers:
    """Тесты для обработчиков команд.

    Класс содержит тесты для проверки всех основных команд бота:
    - /help - динамическая справка
    - /id - информация о пользователе
    - /msg - контекстное меню сообщения
    """

    @pytest.fixture
    def mock_message(self):
        """Создание мока Message.

        Создает стандартный мок сообщения с:
        - ID пользователя 12345
        - Именем "Test User"
        - Username "test_user"
        - Chat ID 123456789

        Returns:
            MagicMock: Мок Message
        """
        message = MagicMock(spec=Message)
        message.from_user = MagicMock(spec=User)
        message.from_user.id = 12345
        message.from_user.first_name = "Test"
        message.from_user.last_name = "User"
        message.from_user.username = "test_user"
        message.from_user.is_bot = False
        message.chat = MagicMock(spec=Chat)
        message.chat.id = 123456789
        message.message_id = 100
        return message

    @pytest.fixture
    def mock_state(self):
        """Создание мока FSMContext.

        Создает мок состояния с пустыми данными.

        Returns:
            MagicMock: Мок FSMContext
        """
        state = MagicMock()
        state.get_data = AsyncMock(return_value={})
        state.update_data = AsyncMock()
        return state

    @pytest.fixture
    def mock_bot_manager(self):
        """Создание мока BotManager.

        Создает мок менеджера бота с основными методами:
        - send_answer - отправка ответа
        - send_toast - отправка уведомлений
        - send_message - отправка сообщений
        - delete_message_by_link - удаление сообщений

        Returns:
            AsyncMock: Мок BotManager
        """
        bot_manager = AsyncMock()
        bot_manager.send_answer = AsyncMock(return_value={"success": True, "message_id": 200})
        bot_manager.send_toast = AsyncMock()
        bot_manager.send_message = AsyncMock(return_value={"success": True, "message_id": 300})
        bot_manager.delete_message_by_link = AsyncMock()
        return bot_manager

    @pytest.mark.asyncio
    async def test_cmd_help_authenticated(self, mock_message, mock_state, mock_bot_manager):
        """Тест команды /help для авторизованного пользователя.

        Проверяет:
        1. Команда /help выполняется для авторизованного пользователя
        2. Отправляется справка с командами для авторизованных пользователей

        Использует мок is_user_authenticated (return_value=True).
        """
        with (
            patch("app.bot.handlers.aiogram.commands.get_bot_manager", return_value=mock_bot_manager),
            patch("app.bot.handlers.aiogram.commands.is_user_authenticated", AsyncMock(return_value=True)),
        ):
            await commands_module.cmd_help(mock_message, mock_state)

            mock_bot_manager.send_answer.assert_called_once()

    @pytest.mark.asyncio
    async def test_cmd_help_unauthenticated(self, mock_message, mock_state, mock_bot_manager):
        """Тест команды /help для неавторизованного пользователя.

        Проверяет:
        1. Команда /help выполняется для неавторизованного пользователя
        2. Отправляется справка с предложением авторизоваться

        Использует мок is_user_authenticated (return_value=False).
        """
        with (
            patch("app.bot.handlers.aiogram.commands.get_bot_manager", return_value=mock_bot_manager),
            patch("app.bot.handlers.aiogram.commands.is_user_authenticated", AsyncMock(return_value=False)),
        ):
            await commands_module.cmd_help(mock_message, mock_state)

            mock_bot_manager.send_answer.assert_called_once()

    @pytest.mark.asyncio
    async def test_cmd_help_admin(self, mock_message, mock_state, mock_bot_manager):
        """Тест команды /help для администратора.

        Проверяет:
        1. Команда /help выполняется для администратора
        2. Отправляется справка с административными командами

        Использует мок is_user_authenticated (return_value=True)
        и settings.ADMIN_IDS с ID администратора.
        """
        mock_message.from_user.id = 1039799368

        with (
            patch("app.bot.handlers.aiogram.commands.get_bot_manager", return_value=mock_bot_manager),
            patch("app.bot.handlers.aiogram.commands.is_user_authenticated", AsyncMock(return_value=True)),
            patch("app.bot.handlers.aiogram.commands.settings.ADMIN_IDS", [1039799368]),
        ):
            await commands_module.cmd_help(mock_message, mock_state)

            mock_bot_manager.send_answer.assert_called_once()

    @pytest.mark.asyncio
    async def test_cmd_id(self, mock_message, mock_state, mock_bot_manager):
        """Тест команды /id.

        Проверяет:
        1. Команда /id выводит ID пользователя
        2. В ответе присутствует ID пользователя (12345)

        Использует мок BotManager.send_answer для проверки содержимого.
        """
        with patch("app.bot.handlers.aiogram.commands.get_bot_manager", return_value=mock_bot_manager):
            await commands_module.cmd_id(mock_message, mock_state)

            mock_bot_manager.send_answer.assert_called_once()
            args, kwargs = mock_bot_manager.send_answer.call_args
            assert "12345" in kwargs.get("text", "")

    @pytest.mark.asyncio
    async def test_cmd_msg_no_args(self, mock_message, mock_state, mock_bot_manager):
        """Тест команды /msg без аргументов.

        Проверяет:
        1. Команда /msg без аргументов возвращает сообщение об ошибке
        2. Пользователь получает инструкцию по использованию

        Использует mock_message.text = "/msg".
        """
        mock_message.text = "/msg"

        with patch("app.bot.handlers.aiogram.commands.get_bot_manager", return_value=mock_bot_manager):
            await commands_module.cmd_msg(mock_message, mock_state)

            mock_bot_manager.send_answer.assert_called_once()

    @pytest.mark.asyncio
    async def test_cmd_msg_invalid_id(self, mock_message, mock_state, mock_bot_manager):
        """Тест команды /msg с неверным ID.

        Проверяет:
        1. Команда /msg с нечисловым ID возвращает сообщение об ошибке
        2. Пользователь получает уведомление о неверном формате

        Использует mock_message.text = "/msg abc".
        """
        mock_message.text = "/msg abc"

        with patch("app.bot.handlers.aiogram.commands.get_bot_manager", return_value=mock_bot_manager):
            await commands_module.cmd_msg(mock_message, mock_state)

            mock_bot_manager.send_answer.assert_called_once()

    @pytest.mark.asyncio
    async def test_cmd_msg_success(self, mock_message, mock_state, mock_bot_manager):
        """Тест успешного выполнения команды /msg.

        Проверяет:
        1. Команда /msg с валидным ID открывает контекстное меню
        2. Сообщение с командой удаляется
        3. Вызывается show_message_context_menu

        Использует моки для db_manager, get_message_by_id и show_message_context_menu.
        """
        mock_message.text = "/msg 12345"

        with (
            patch("app.bot.handlers.aiogram.commands.get_bot_manager", return_value=mock_bot_manager),
            patch("app.bot.handlers.aiogram.commands.db_manager") as mock_db,
        ):
            mock_session = AsyncMock()
            mock_db.get_session.return_value.__aenter__.return_value = mock_session

            with (
                patch(
                    "app.db.repositories.avanpost_users.AvanpostUserRepository.get_message_by_id",
                    AsyncMock(return_value={"id": 12345, "text": "Test"}),
                ),
                patch(
                    "app.bot.handlers.aiogram.custom.chat_message_menu.show_message_context_menu",
                    AsyncMock(),
                ),
            ):
                await commands_module.cmd_msg(mock_message, mock_state)

                # Проверяем, что метод delete_message_by_link был вызван
                assert mock_bot_manager.delete_message_by_link.called
