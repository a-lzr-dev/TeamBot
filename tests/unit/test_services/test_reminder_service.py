"""
Модуль с тестами для сервиса управления напоминаниями (ReminderService).

Содержит набор асинхронных тестов, проверяющих бизнес-логику работы с напоминаниями:
- создание напоминаний с различными параметрами;
- получение списка напоминаний с фильтрацией;
- завершение напоминаний с указанием результата;
- поиск по кодовому слову;
- деактивация и удаление (в т.ч. мягкое) напоминаний;
- получение статистики по напоминаниям.
Все тесты используют моки для изоляции от реальной базы данных.
"""

from datetime import datetime, timedelta
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.services.reminder_service import ReminderService


class TestReminderService:
    """
    Набор тестов для проверки корректности работы ReminderService.

    Тестируются основные сценарии использования сервиса:
    - создание, чтение, обновление и удаление напоминаний;
    - фильтрация и поиск;
    - статистические выборки.
    """

    @pytest.fixture
    def service(self):
        """Создаёт экземпляр сервиса напоминаний для каждого теста."""
        return ReminderService()

    @pytest.fixture
    def sample_reminder_data(self):
        """
        Возвращает образец данных для создания напоминания.

        Содержит все необходимые поля с типовыми значениями:
        - идентификатор пользователя;
        - заголовок и описание;
        - категория;
        - временные параметры (время срабатывания, интервал, лимит);
        - кодовое слово;
        - настройки уведомлений.
        """
        return {
            "user_id": 123,
            "title": "Test Reminder",
            "description": "Test description",
            "category": "work",
            "remind_at": datetime.now() + timedelta(hours=1),
            "remind_until": None,
            "remind_interval": 30,
            "max_remind_count": 5,
            "code_word": "test123",
            "notification_type": "private",
            "chat_id": None,
            "shared_with": None,
            "encrypt": False,
        }

    @pytest.fixture
    def mock_repo(self):
        """
        Создаёт замоканный репозиторий с предопределёнными ответами.

        Возвращает кортеж (экземпляр мока репозитория, мок сессии).
        Все методы репозитория замоканы на AsyncMock с возвращаемыми значениями,
        соответствующими успешному выполнению операций.
        """
        mock_session = AsyncMock()
        mock_session.flush = AsyncMock()
        mock_session.commit = AsyncMock()
        mock_session.refresh = AsyncMock()

        mock_repo_instance = MagicMock()
        mock_repo_instance.create_reminder = AsyncMock(return_value=MagicMock(FID=1))
        mock_repo_instance.complete_reminder = AsyncMock(return_value=(True, "Completed"))
        mock_repo_instance.get_reminders = AsyncMock(return_value=[])
        mock_repo_instance.find_by_code_word = AsyncMock(return_value=[])
        mock_repo_instance.deactivate_reminder = AsyncMock(return_value=True)
        mock_repo_instance.delete_reminder = AsyncMock(return_value=True)
        mock_repo_instance.get_stats = AsyncMock(
            return_value={
                "total": 10,
                "completed": 5,
                "successful": 4,
                "unsuccessful": 1,
                "success_rate": 80.0,
                "daily": [],
            }
        )
        mock_repo_instance.format_reminder = MagicMock(return_value={})

        return mock_repo_instance, mock_session

    @pytest.mark.asyncio
    async def test_create_reminder(self, service, sample_reminder_data, mock_repo):
        """
        Проверяет успешное создание напоминания.

        Убеждается, что метод create_reminder вызывает соответствующий метод
        репозитория с правильными параметрами.
        """
        mock_repo_instance, mock_session = mock_repo
        service._repository = mock_repo_instance

        await service.create_reminder(
            user_id=sample_reminder_data["user_id"],
            title=sample_reminder_data["title"],
            remind_at=sample_reminder_data["remind_at"],
            session=mock_session,
            description=sample_reminder_data["description"],
            category=sample_reminder_data["category"],
            remind_interval=sample_reminder_data["remind_interval"],
            max_remind_count=sample_reminder_data["max_remind_count"],
            code_word=sample_reminder_data["code_word"],
            notification_type=sample_reminder_data["notification_type"],
        )

        mock_repo_instance.create_reminder.assert_called_once()
        call_args = mock_repo_instance.create_reminder.call_args[1]
        assert call_args["user_id"] == sample_reminder_data["user_id"]
        assert call_args["title"] == sample_reminder_data["title"]

    @pytest.mark.asyncio
    async def test_get_reminders(self, service, mock_repo):
        """
        Проверяет получение списка напоминаний без фильтров.

        Ожидается, что метод вернёт список (в том числе пустой)
        и вызовет соответствующий метод репозитория.
        """
        mock_repo_instance, mock_session = mock_repo
        service._repository = mock_repo_instance

        reminders = await service.get_reminders(
            user_id=123,
            session=mock_session,
        )

        assert isinstance(reminders, list)
        mock_repo_instance.get_reminders.assert_called_once()

    @pytest.mark.asyncio
    async def test_get_reminders_with_filters(self, service, mock_repo):
        """
        Проверяет получение напоминаний с применением фильтров.

        Убеждается, что переданный фильтр (категория) корректно
        передаётся в репозиторий.
        """
        mock_repo_instance, mock_session = mock_repo
        service._repository = mock_repo_instance

        reminders = await service.get_reminders(
            user_id=123,
            session=mock_session,
            category="work",
        )

        assert isinstance(reminders, list)
        mock_repo_instance.get_reminders.assert_called_once()
        call_args = mock_repo_instance.get_reminders.call_args[1]
        assert call_args["category"] == "work"

    @pytest.mark.asyncio
    async def test_complete_reminder(self, service, mock_repo):
        """
        Проверяет завершение напоминания с указанием результата.

        Ожидается, что метод вернёт (True, "Completed") и вызовет
        соответствующий метод репозитория.
        """
        mock_repo_instance, mock_session = mock_repo
        service._repository = mock_repo_instance

        success, msg = await service.complete_reminder(
            reminder_id=1,
            user_id=123,
            session=mock_session,
            successful=True,
        )

        assert success is True
        assert msg == "Completed"
        mock_repo_instance.complete_reminder.assert_called_once()

    @pytest.mark.asyncio
    async def test_find_by_code_word(self, service, mock_repo):
        """
        Проверяет поиск напоминаний по кодовому слову.

        Убеждается, что в репозиторий передаются все необходимые
        параметры: user_id, code_word, а также значения по умолчанию
        для chat_id и include_completed.
        """
        mock_repo_instance, mock_session = mock_repo
        service._repository = mock_repo_instance

        results = await service.find_by_code_word(
            user_id=123,
            code_word="secret123",
            session=mock_session,
        )

        assert isinstance(results, list)
        mock_repo_instance.find_by_code_word.assert_called_once_with(
            session=mock_session,
            user_id=123,
            code_word="secret123",
            chat_id=None,
            include_completed=False,
        )

    @pytest.mark.asyncio
    async def test_deactivate_reminder(self, service, mock_repo):
        """
        Проверяет деактивацию напоминания.

        Ожидается, что метод вернёт True и вызовет соответствующий
        метод репозитория.
        """
        mock_repo_instance, mock_session = mock_repo
        service._repository = mock_repo_instance

        success = await service.deactivate_reminder(
            reminder_id=1,
            session=mock_session,
        )

        assert success is True
        mock_repo_instance.deactivate_reminder.assert_called_once()

    @pytest.mark.asyncio
    async def test_delete_reminder_soft(self, service, mock_repo):
        """
        Проверяет мягкое удаление напоминания (soft delete).

        Убеждается, что флаг soft=True передаётся в репозиторий.
        """
        mock_repo_instance, mock_session = mock_repo
        service._repository = mock_repo_instance

        success = await service.delete_reminder(
            reminder_id=1,
            session=mock_session,
            soft=True,
        )

        assert success is True
        mock_repo_instance.delete_reminder.assert_called_once_with(
            session=mock_session,
            reminder_id=1,
            soft=True,
        )

    @pytest.mark.asyncio
    async def test_get_reminder_stats(self, service, mock_repo):
        """
        Проверяет получение статистики по напоминаниям.

        Ожидается, что метод вернёт словарь с корректными значениями
        (общее количество, завершённые, успешные, процент успеха)
        и вызовет репозиторий с переданным периодом.
        """
        mock_repo_instance, mock_session = mock_repo
        service._repository = mock_repo_instance

        stats = await service.get_reminder_stats(
            user_id=123,
            session=mock_session,
            period="day",
        )

        assert stats["total"] == 10
        assert stats["completed"] == 5
        assert stats["success_rate"] == 80.0
        mock_repo_instance.get_stats.assert_called_once_with(
            session=mock_session,
            user_id=123,
            period="day",
        )
