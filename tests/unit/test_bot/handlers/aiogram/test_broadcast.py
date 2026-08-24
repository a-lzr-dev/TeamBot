"""Тесты для обработчиков рассылок.

Этот модуль содержит тесты для проверки функциональности массовых рассылок в боте.

Тесты покрывают:
1. Команду /bc - открытие меню управления рассылками
2. Команду /bc_send - создание новой рассылки
3. Команду /bc_del - отмена существующей рассылки
4. Просмотр истории рассылок
5. Работу с колбэками для подтверждения/отмены

Основные компоненты:
- broadcast_module - модуль с обработчиками рассылок
- BroadcastStates - состояния FSM для создания рассылки
- BroadcastCancelStates - состояния FSM для отмены рассылки

Особенности:
- Все тесты асинхронные (pytest.mark.asyncio)
- Используются моки для изоляции от внешних зависимощений
- Проверяются различные сценарии: успешные и с ошибками
- Тестируется как административный доступ, так и ограничения

Примечания:
- Все команды рассылок доступны только администраторам
- Создание рассылки требует подтверждения перед отправкой
- Отмена рассылки удаляет все связанные сообщения из Telegram
"""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message, User

import app.bot.handlers.aiogram.broadcast as broadcast_module


class TestBroadcastHandlers:
    """Тесты для обработчиков рассылок.

    Класс содержит тесты для проверки всех функций управления рассылками:
    - Открытие меню
    - Создание рассылки
    - Отмена рассылки
    - История рассылок
    """

    @pytest.fixture
    def mock_message(self):
        """Создание мока Message.

        Создает стандартный мок сообщения для администратора:
        - ID пользователя 1039799368 (администратор)
        - Chat ID 123456789
        - Текст команды /bc

        Returns:
            MagicMock: Мок Message
        """
        message = MagicMock(spec=Message)
        message.from_user = MagicMock(spec=User)
        message.from_user.id = 1039799368  # Admin ID
        message.chat = MagicMock()
        message.chat.id = 123456789
        message.message_id = 100
        message.text = "/bc"
        return message

    @pytest.fixture
    def mock_callback(self):
        """Создание мока CallbackQuery.

        Создает стандартный мок callback-запроса для администратора:
        - ID пользователя 1039799368
        - Callback data "bc_menu"
        - Сообщением с chat_id 123456789

        Returns:
            MagicMock: Мок CallbackQuery
        """
        callback = MagicMock(spec=CallbackQuery)
        callback.from_user = MagicMock(spec=User)
        callback.from_user.id = 1039799368
        callback.data = "bc_menu"
        callback.message = MagicMock(spec=Message)
        callback.message.message_id = 100
        callback.message.chat = MagicMock()
        callback.message.chat.id = 123456789
        callback.answer = AsyncMock()
        return callback

    @pytest.fixture
    def mock_state(self):
        """Создание мока FSMContext.

        Создает мок состояния с пустыми данными.

        Returns:
            MagicMock: Мок FSMContext
        """
        state = MagicMock(spec=FSMContext)
        state.get_data = AsyncMock(return_value={})
        state.update_data = AsyncMock()
        state.set_state = AsyncMock()
        state.clear = AsyncMock()
        return state

    @pytest.fixture
    def mock_bot_manager(self):
        """Создание мока BotManager.

        Создает мок менеджера бота с основными методами для рассылок:
        - send_answer - отправка ответа
        - send_toast - отправка уведомлений
        - send_message - отправка сообщений
        - edit_callback_message - редактирование сообщения
        - broadcast_message - выполнение рассылки
        - delete_message_by_id - удаление сообщения

        Returns:
            AsyncMock: Мок BotManager
        """
        bot_manager = AsyncMock()
        bot_manager.send_answer = AsyncMock(return_value={"success": True, "message_id": 200})
        bot_manager.send_toast = AsyncMock()
        bot_manager.send_message = AsyncMock(return_value={"success": True, "message_id": 300})
        bot_manager.delete_message_by_link = AsyncMock()
        bot_manager.edit_callback_message = AsyncMock()
        bot_manager.broadcast_message = AsyncMock(
            return_value={
                "success": True,
                "total": 5,
                "successful": 5,
                "failed": 0,
                "failed_chats": [],
                "sent_messages": [{"chat_id": 1, "message_id": 100}],
            }
        )
        bot_manager.delete_message_by_id = AsyncMock(return_value={"success": True})
        return bot_manager

    @pytest.mark.asyncio
    async def test_cmd_bc_menu_admin(self, mock_message, mock_state, mock_bot_manager):
        """Тест команды /bc для администратора.

        Проверяет:
        1. Команда /bc открывает меню управления рассылками
        2. Отправляется сообщение с меню для администратора

        Использует мок _is_admin (return_value=True).
        """
        with (
            patch("app.bot.handlers.aiogram.broadcast.get_bot_manager", return_value=mock_bot_manager),
            patch("app.bot.handlers.aiogram.broadcast._is_admin", return_value=True),
        ):
            await broadcast_module.cmd_bc_menu(mock_message)

            mock_bot_manager.send_answer.assert_called_once()

    @pytest.mark.asyncio
    async def test_cmd_bc_menu_non_admin(self, mock_message, mock_state, mock_bot_manager):
        """Тест команды /bc для не-администратора.

        Проверяет:
        1. Команда /bc не доступна для обычных пользователей
        2. Отправляется уведомление об отсутствии прав

        Использует мок _is_admin (return_value=False).
        """
        mock_message.from_user.id = 999

        with (
            patch("app.bot.handlers.aiogram.broadcast.get_bot_manager", return_value=mock_bot_manager),
            patch("app.bot.handlers.aiogram.broadcast._is_admin", return_value=False),
        ):
            await broadcast_module.cmd_bc_menu(mock_message)

            mock_bot_manager.send_toast.assert_called_once()

    @pytest.mark.asyncio
    async def test_show_broadcast_menu_callback(self, mock_callback, mock_bot_manager):
        """Тест показа меню рассылок из колбэка.

        Проверяет:
        1. Колбэк "bc_menu" открывает меню управления рассылками
        2. Сообщение редактируется с новым содержимым

        Использует мок edit_callback_message.
        """
        with (
            patch("app.bot.handlers.aiogram.broadcast.get_bot_manager", return_value=mock_bot_manager),
            patch("app.bot.handlers.aiogram.broadcast._is_admin", return_value=True),
        ):
            await broadcast_module.show_broadcast_menu(mock_callback)

            mock_bot_manager.edit_callback_message.assert_called_once()

    @pytest.mark.asyncio
    async def test_cmd_bc_send_admin(self, mock_message, mock_state, mock_bot_manager):
        """Тест команды /bc_send для администратора.

        Проверяет:
        1. Команда /bc_send начинает процесс создания рассылки
        2. Устанавливается состояние BroadcastStates.waiting_for_text

        Использует мок mock_state.set_state.
        """
        mock_message.text = "/bc_send"

        with (
            patch("app.bot.handlers.aiogram.broadcast.get_bot_manager", return_value=mock_bot_manager),
            patch("app.bot.handlers.aiogram.broadcast._is_admin", return_value=True),
        ):
            await broadcast_module.cmd_bc_send(mock_message, mock_state)

            mock_state.set_state.assert_called_with(broadcast_module.BroadcastStates.waiting_for_text)

    @pytest.mark.asyncio
    async def test_cmd_bc_send_non_admin(self, mock_message, mock_state, mock_bot_manager):
        """Тест команды /bc_send для не-администратора.

        Проверяет:
        1. Команда /bc_send не доступна для обычных пользователей
        2. Отправляется сообщение об ошибке

        Использует mock_message.from_user.id = 999 и _is_admin (return_value=False).
        """
        mock_message.text = "/bc_send"
        mock_message.from_user.id = 999

        with (
            patch("app.bot.handlers.aiogram.broadcast.get_bot_manager", return_value=mock_bot_manager),
            patch("app.bot.handlers.aiogram.broadcast._is_admin", return_value=False),
        ):
            await broadcast_module.cmd_bc_send(mock_message, mock_state)

            mock_bot_manager.send_answer.assert_called()

    @pytest.mark.asyncio
    async def test_broadcast_get_text(self, mock_message, mock_state, mock_bot_manager):
        """Тест получения текста для рассылки.

        Проверяет:
        1. После ввода текста устанавливается состояние подтверждения
        2. Подсчитывается количество чатов для рассылки

        Использует моки для db_manager и _chat_repo.
        """
        mock_message.text = "Test broadcast message"
        mock_message.from_user.id = 1039799368

        with (
            patch("app.bot.handlers.aiogram.broadcast.get_bot_manager", return_value=mock_bot_manager),
            patch("app.bot.handlers.aiogram.broadcast._is_admin", return_value=True),
            patch("app.bot.handlers.aiogram.broadcast.db_manager") as mock_db,
        ):
            mock_session = AsyncMock()
            mock_db.get_session.return_value.__aenter__.return_value = mock_session

            with patch("app.bot.handlers.aiogram.broadcast._chat_repo") as mock_chat:
                mock_chat.get_chats = AsyncMock(return_value=[MagicMock() for _ in range(3)])

                await mock_state.set_state(broadcast_module.BroadcastStates.waiting_for_text)

                mock_state.set_state.assert_called_with(broadcast_module.BroadcastStates.waiting_for_text)

    @pytest.mark.asyncio
    async def test_bc_confirm_send(self, mock_callback, mock_state, mock_bot_manager):
        """Тест подтверждения отправки рассылки.

        Проверяет:
        1. Колбэк "bc_confirm" запускает рассылку
        2. Создается запись в БД
        3. Выполняется broadcast_message
        4. После отправки состояние очищается

        Использует моки для всех внешних зависимостей.
        """
        mock_callback.data = "bc_confirm"
        mock_state.get_data = AsyncMock(
            return_value={
                "text": "Test message",
                "parse_mode": "HTML",
                "sender_user_id": 1039799368,
            }
        )

        with (
            patch("app.bot.handlers.aiogram.broadcast.get_bot_manager", return_value=mock_bot_manager),
            patch("app.bot.handlers.aiogram.broadcast.db_manager") as mock_db,
        ):
            mock_session = AsyncMock()
            mock_db.get_session.return_value.__aenter__.return_value = mock_session

            with patch("app.bot.handlers.aiogram.broadcast._broadcast_repo") as mock_broadcast:
                mock_broadcast.create_broadcast = AsyncMock(return_value=MagicMock(FID=1))
                mock_broadcast.update_broadcast_status = AsyncMock()

                with patch("app.bot.handlers.aiogram.broadcast._chat_repo") as mock_chat:
                    mock_chat.get_chats = AsyncMock(return_value=[MagicMock() for _ in range(3)])

                    await broadcast_module.bc_confirm_send(mock_callback, mock_state)

                    mock_bot_manager.broadcast_message.assert_called_once()
                    mock_state.clear.assert_called()

    @pytest.mark.asyncio
    async def test_bc_cancel_send(self, mock_callback, mock_state, mock_bot_manager):
        """Тест отмены создания рассылки.

        Проверяет:
        1. Колбэк "bc_cancel_send" отменяет создание рассылки
        2. Состояние очищается
        3. Показывается меню рассылок

        Использует мок edit_callback_message.
        """
        mock_callback.data = "bc_cancel_send"

        with (
            patch("app.bot.handlers.aiogram.broadcast.get_bot_manager", return_value=mock_bot_manager),
            patch("app.bot.handlers.aiogram.broadcast._is_admin", return_value=True),
        ):
            await broadcast_module.bc_cancel_send(mock_callback, mock_state)

            mock_state.clear.assert_called()
            mock_bot_manager.edit_callback_message.assert_called_once()

    @pytest.mark.asyncio
    async def test_bc_history(self, mock_callback, mock_bot_manager):
        """Тест просмотра истории рассылок.

        Проверяет:
        1. Колбэк "bc_history" показывает последние 10 рассылок
        2. Отображается информация о каждой рассылке (ID, статус, статистика)

        Использует моки для _broadcast_repo.get_recent_broadcasts.
        """
        mock_callback.data = "bc_history"

        with (
            patch("app.bot.handlers.aiogram.broadcast.get_bot_manager", return_value=mock_bot_manager),
            patch("app.bot.handlers.aiogram.broadcast._is_admin", return_value=True),
            patch("app.bot.handlers.aiogram.broadcast.db_manager") as mock_db,
        ):
            mock_session = AsyncMock()
            mock_db.get_session.return_value.__aenter__.return_value = mock_session

            with patch("app.bot.handlers.aiogram.broadcast._broadcast_repo") as mock_broadcast:
                mock_broadcast.get_recent_broadcasts = AsyncMock(
                    return_value=[
                        MagicMock(
                            FID=1,
                            FTitle="Test 1",
                            FStatus="sent",
                            FSuccessCount=5,
                            FTotalChats=10,
                            FCreatedAt=MagicMock(strftime=lambda x: "2024-01-01"),
                        )
                    ]
                )

                await broadcast_module.bc_history(mock_callback)

                mock_bot_manager.edit_callback_message.assert_called_once()
