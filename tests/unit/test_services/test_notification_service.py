"""
Модуль с тестами для сервиса уведомлений (NotificationService).

Содержит набор асинхронных и синхронных тестов, проверяющих логику работы с уведомлениями:
- проверка необходимости отправки уведомлений об ошибках с учётом настроек;
- форматирование сообщений об ошибках с возможностью включения деталей;
- генерация автоматических отчётов по ошибкам;
- работа с очередью уведомлений (добавление и обработка);
- вспомогательные методы: проверка времени в диапазоне, категорий и уровней серьёзности.
Все тесты используют моки для изоляции от внешних зависимостей (БД, бот, репозитории).
"""

from datetime import timedelta
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import ErrorCategory, ErrorSeverity, ErrorStatus
from app.services.notification_service import NotificationService


class TestNotificationService:
    """
    Набор тестов для проверки корректности работы NotificationService.

    Тестируются основные функции сервиса уведомлений:
    - принятие решений об отправке уведомлений;
    - формирование сообщений;
    - автоматическая генерация отчётов;
    - управление очередью уведомлений;
    - вспомогательные утилиты (время, категории, уровни).
    """

    @pytest.fixture
    def service(self):
        """Создаёт экземпляр сервиса уведомлений для каждого теста."""
        return NotificationService()

    @pytest.fixture
    def sample_error(self):
        """
        Возвращает образец модели ошибки для тестирования.

        Содержит минимальный набор полей: код, сообщение, источник,
        категория, серьёзность, статус, количество вхождений и временные метки.
        """
        from app.models import ErrorModel, datetime_now

        error = ErrorModel(
            FID=1,
            FErrorCode="TEST_001",
            FErrorMessage="Test error message",
            FSourceSystem="test_system",
            FCategory=ErrorCategory.EXTERNAL,
            FSeverity=ErrorSeverity.ERROR,
            FStatus=ErrorStatus.NEW,
            FCountOccurrences=1,
            FFirstOccurrence=datetime_now() - timedelta(hours=1),
            FLastOccurrence=datetime_now(),
        )
        return error

    @pytest.fixture
    def sample_settings(self):
        """
        Возвращает образец настроек уведомлений для чата.

        Включает параметры тишины, категории уведомлений, уровень серьёзности,
        настройки группировки и автоматических отчётов.
        """
        from app.models import ChatNotificationSettingsModel, ErrorSeverity

        settings = ChatNotificationSettingsModel(
            FK_Chat=123,
            FSilenceStart="23:00",
            FSilenceEnd="06:00",
            FSilenceEnabled=False,
            FNotifyErrors=True,
            FNotifyPeriodicTasks=True,
            FNotifyTaskExecution=True,
            FNotifySystem=True,
            FNotificationLevel=ErrorSeverity.ERROR,
            FGroupingEnabled=True,
            FGroupingWindowMinutes=60,
            FEnableAutoReports=True,
            FAutoReportInterval=60,
            FAutoReportHourStart=9,
            FAutoReportHourEnd=18,
        )
        return settings

    @pytest.fixture
    def mock_async_session(self):
        """Создаёт мок асинхронной сессии SQLAlchemy с базовыми методами."""
        session = MagicMock(spec=AsyncSession)
        session.execute = AsyncMock()
        session.commit = AsyncMock()
        session.rollback = AsyncMock()
        session.close = AsyncMock()
        return session

    @pytest.mark.asyncio
    async def test_should_notify_error_enabled(self, service, sample_error, mock_async_session):
        """
        Проверяет, что метод should_notify_error возвращает булево значение
        при включённых уведомлениях об ошибках.

        Мокается репозиторий настроек, возвращающий None (настройки по умолчанию).
        """
        with patch("app.services.notification_service.NotificationSettingsRepository") as mock_settings_repo:
            mock_settings_repo.get_by_chat_id = AsyncMock(return_value=None)

            assert hasattr(service, "should_notify_error")

            result = await service.should_notify_error(
                error=sample_error,
                chat_id=123,
                session=mock_async_session,
            )
            assert isinstance(result, bool)

    @pytest.mark.asyncio
    async def test_format_error_message(self, service, sample_error):
        """
        Проверяет форматирование сообщения об ошибке.

        Ожидается, что в результирующей строке будут присутствовать код ошибки
        и текст сообщения.
        """
        assert hasattr(service, "format_error_message")

        result = await service.format_error_message(sample_error)
        assert isinstance(result, str)
        assert "TEST_001" in result
        assert "Test error message" in result

    @pytest.mark.asyncio
    async def test_format_error_message_with_details(self, service, sample_error):
        """
        Проверяет форматирование сообщения с включением деталей.

        При установке флага include_details=True в выводе должно присутствовать
        поле FErrorDetails.
        """
        sample_error.FErrorDetails = "Detailed error information"
        result = await service.format_error_message(sample_error, include_details=True)
        assert "Detailed error information" in result

    @pytest.mark.asyncio
    async def test_generate_auto_report(self, service, mock_async_session):
        """
        Проверяет генерацию автоматического отчёта по ошибкам.

        Мокаются репозитории ошибок: возвращаются статистика и список лучших
        исполнителей. Ожидается, что метод вернёт строку с отчётом,
        содержащую ключевые слова (на русском или английском).
        """
        with patch("app.services.notification_service.ErrorRepository") as mock_error_repo:
            mock_error_repo.get_stats = AsyncMock(
                return_value={
                    "total": 10,
                    "new": 3,
                    "resolved": 5,
                    "in_progress": 2,
                    "total_occurrences": 15,
                    "resolution_rate": 50.0,
                    "period": {"start": "2024-01-01", "end": "2024-01-07"},
                }
            )

            with patch(
                "app.services.notification_service.ErrorRepository.get_top_resolvers",
                AsyncMock(
                    return_value=[{"first_name": "Admin", "last_name": "User", "username": "admin", "solved": 3}]
                ),
            ):
                assert hasattr(service, "generate_auto_report")

                result = await service.generate_auto_report(
                    chat_id=123,
                    session=mock_async_session,
                )
                assert isinstance(result, str)
                assert "Ежечасный отчет" in result or "hourly report" in result.lower()

    @pytest.mark.asyncio
    async def test_add_to_queue(self, service):
        """
        Проверяет добавление уведомления в очередь.

        После добавления длина очереди должна увеличиться, а запись должна
        содержать переданные chat_id и сообщение.
        """
        service.add_to_queue(123, "Test message")
        assert len(service._notification_queue) == 1
        assert service._notification_queue[0]["chat_id"] == 123
        assert service._notification_queue[0]["message"] == "Test message"

    @pytest.mark.asyncio
    async def test_process_notification_queue(self, service):
        """
        Проверяет обработку очереди уведомлений.

        Добавляются два уведомления, мокается бот-менеджер. Ожидается,
        что после обработки очередь очистится, а метод send_message будет
        вызван дважды.
        """
        service.add_to_queue(123, "Test message 1")
        service.add_to_queue(456, "Test message 2")

        with patch("app.services.notification_service.get_bot_manager") as mock_get_bot:
            mock_bot = AsyncMock()
            mock_bot.send_message = AsyncMock(return_value={"success": True, "message_id": 1})
            mock_get_bot.return_value = mock_bot

            await service.process_notification_queue()

            assert len(service._notification_queue) == 0
            assert mock_bot.send_message.call_count == 2

    def test_is_time_in_range(self, service):
        """
        Проверяет корректность определения попадания времени в диапазон.

        Тестируются обычный диапазон (09:00–18:00), диапазон с переходом
        через полночь (22:00–06:00) и ситуации вне диапазона.
        """
        assert hasattr(service, "_is_time_in_range")

        result = service._is_time_in_range("12:00", "09:00", "18:00")
        assert result is True

        result = service._is_time_in_range("20:00", "09:00", "18:00")
        assert result is False

        result = service._is_time_in_range("23:30", "22:00", "06:00")
        assert result is True

        result = service._is_time_in_range("12:00", "22:00", "06:00")
        assert result is False

    def test_is_category_enabled(self, service, sample_settings):
        """
        Проверяет, включена ли категория ошибок в настройках уведомлений.

        Тестируются категории EXTERNAL и PERIODIC_TASK при различных
        значениях флагов FNotifyErrors и FNotifyPeriodicTasks.
        """
        assert hasattr(service, "_is_category_enabled")

        result = service._is_category_enabled(ErrorCategory.EXTERNAL, sample_settings)
        assert result is True

        sample_settings.FNotifyErrors = False
        result = service._is_category_enabled(ErrorCategory.EXTERNAL, sample_settings)
        assert result is False

        sample_settings.FNotifyPeriodicTasks = True
        result = service._is_category_enabled(ErrorCategory.PERIODIC_TASK, sample_settings)
        assert result is True

        sample_settings.FNotifyPeriodicTasks = False
        result = service._is_category_enabled(ErrorCategory.PERIODIC_TASK, sample_settings)
        assert result is False

    def test_get_allowed_severities(self, service, sample_settings):
        """
        Проверяет получение списка разрешённых уровней серьёзности
        на основе настройки FNotificationLevel.

        Тестируются уровни ERROR, WARNING и CRITICAL, а также проверяется,
        что возвращаются только уровни не ниже заданного.
        """
        assert hasattr(service, "_get_allowed_severities")

        result = service._get_allowed_severities(sample_settings)
        assert "critical" in result
        assert "error" in result
        assert "warning" not in result

        sample_settings.FNotificationLevel = ErrorSeverity.WARNING
        result = service._get_allowed_severities(sample_settings)
        assert "critical" in result
        assert "error" in result
        assert "warning" in result

        sample_settings.FNotificationLevel = ErrorSeverity.CRITICAL
        result = service._get_allowed_severities(sample_settings)
        assert "critical" in result
        assert "error" not in result
