"""
Модуль с расширенными тестами для сервиса обработки ошибок (ErrorService).

Содержит набор асинхронных интеграционных тестов, проверяющих полный жизненный цикл ошибок:
- логирование ошибок (как внутренних, так и внешних);
- обновление существующих ошибок (увеличение счётчика вхождений);
- проверка и решение ошибок;
- переоткрытие решённых ошибок;
- получение статистики по ошибкам;
- удаление сообщений, связанных с ошибками.

ВНИМАНИЕ: Тесты помечены как skipped (пропущены), так как требуют полной схемы базы данных
со всеми таблицами. Для запуска необходимо развернуть тестовую БД с полной миграцией.
"""

import pytest

from app.models import ErrorCategory, ErrorSeverity, ErrorStatus
from app.services.error_service import ErrorService


class TestErrorServiceExtended:
    """
    Расширенный набор тестов для проверки корректности работы ErrorService.

    Тестируются интеграционные сценарии, требующие полноценного доступа к БД:
    - создание новых ошибок и обновление существующих;
    - изменение статусов ошибок (решение, переоткрытие);
    - агрегация статистики;
    - каскадное удаление связанных сущностей.
    """

    @pytest.fixture
    def service(self):
        """Создаёт экземпляр сервиса ошибок для каждого теста."""
        return ErrorService()

    @pytest.mark.asyncio
    @pytest.mark.skip(reason="Requires full database schema with all tables")
    async def test_log_error_with_session(self, service, db_session):
        """
        Проверяет логирование ошибки с переданной сессией.

        Искусственно вызывается ValueError, который логируется через метод log_error.
        Ожидается, что в БД будет создана запись с кодом "ValueError" и сообщением "Test error",
        а также сохранены переданные контекстные данные (component, user_id, chat_id и т.д.).
        """
        try:
            raise ValueError("Test error")
        except ValueError as e:
            error_model, chat_message = await service.log_error(
                error=e,
                session=db_session,
                component="test",
                user_id=123,
                chat_id=456,
                message_id=789,
                category=ErrorCategory.SYSTEM,
                severity=ErrorSeverity.ERROR,
                context={"test": "context"},
            )

            assert error_model is not None
            assert error_model.FErrorCode == "ValueError"
            assert error_model.FErrorMessage == "Test error"

    @pytest.mark.asyncio
    @pytest.mark.skip(reason="Requires full database schema with all tables")
    async def test_log_external_error_new(self, service, db_session):
        """
        Проверяет логирование новой внешней ошибки.

        Создаётся новая ошибка с кодом "EXT_001" и источником "test_system".
        Ожидается, что запись будет создана со статусом NEW и корректными полями.
        """
        error = await service.log_external_error(
            error_code="EXT_001",
            error_message="External error",
            source_system="test_system",
            session=db_session,
            user_id=123,
            user_login="test_user",
            category=ErrorCategory.EXTERNAL,
            severity=ErrorSeverity.ERROR,
            details="Test details",
            source_module="test_module",
            chat_ids=[123],
            send_to_telegram=False,
        )

        assert error is not None
        assert error.FErrorCode == "EXT_001"
        assert error.FSourceSystem == "test_system"
        assert error.FCategory == ErrorCategory.EXTERNAL
        assert error.FStatus == ErrorStatus.NEW

    @pytest.mark.asyncio
    @pytest.mark.skip(reason="Requires full database schema with all tables")
    async def test_log_external_error_existing(self, service, db_session):
        """
        Проверяет обновление существующей внешней ошибки.

        Сначала создаётся ошибка с кодом "EXT_002", затем она логируется повторно.
        Ожидается, что будет найдена существующая запись, а счётчик вхождений (FCountOccurrences)
        увеличится на 1.
        """
        error1 = await service.log_external_error(
            error_code="EXT_002",
            error_message="Existing error",
            source_system="test_system",
            session=db_session,
            send_to_telegram=False,
        )

        error2 = await service.log_external_error(
            error_code="EXT_002",
            error_message="Existing error",
            source_system="test_system",
            session=db_session,
            send_to_telegram=False,
        )

        assert error2 is not None
        assert error2.FID == error1.FID
        assert error2.FCountOccurrences == error1.FCountOccurrences + 1

    @pytest.mark.asyncio
    @pytest.mark.skip(reason="Requires full database schema with all tables")
    async def test_check_and_resolve_error(self, service, db_session):
        """
        Проверяет решение ошибки.

        Создаётся ошибка, затем вызывается метод check_and_resolve_error.
        Ожидается, что статус ошибки изменится на RESOLVED, а метод вернёт успешный результат.
        """
        error = await service.log_external_error(
            error_code="EXT_003",
            error_message="Resolvable error",
            source_system="test_system",
            session=db_session,
            send_to_telegram=False,
        )

        success, message = await service.check_and_resolve_error(
            error_id=error.FID,
            resolved_by=123,
            session=db_session,
        )

        assert success is True
        assert message == "Error resolved successfully"

        from app.db.repositories import ErrorRepository

        resolved = await ErrorRepository.get_error_by_id(db_session, error.FID)
        assert resolved is not None
        assert resolved.FStatus == ErrorStatus.RESOLVED

    @pytest.mark.asyncio
    @pytest.mark.skip(reason="Requires full database schema with all tables")
    async def test_reopen_error(self, service, db_session):
        """
        Проверяет переоткрытие решённой ошибки.

        Создаётся ошибка, решается, затем переоткрывается через метод reopen_error.
        Ожидается, что статус изменится на REOPENED, а метод вернёт успешный результат.
        """
        error = await service.log_external_error(
            error_code="EXT_004",
            error_message="Reopen test",
            source_system="test_system",
            session=db_session,
            send_to_telegram=False,
        )

        await service.check_and_resolve_error(
            error_id=error.FID,
            resolved_by=123,
            session=db_session,
        )

        success, message = await service.reopen_error(
            error_id=error.FID,
            session=db_session,
        )

        assert success is True
        assert message == "Error reopened"

        from app.db.repositories import ErrorRepository

        reopened = await ErrorRepository.get_error_by_id(db_session, error.FID)
        assert reopened is not None
        assert reopened.FStatus == ErrorStatus.REOPENED

    @pytest.mark.asyncio
    @pytest.mark.skip(reason="Requires full database schema with all tables")
    async def test_get_error_stats(self, service, db_session):
        """
        Проверяет получение статистики по ошибкам.

        Создаются несколько ошибок с кодом "EXT_xxx" в категории EXTERNAL.
        Затем запрашивается статистика по этой категории.
        Ожидается, что общее количество ошибок будет не меньше созданного.
        """
        for i in range(3):
            await service.log_external_error(
                error_code=f"EXT_{i:03d}",
                error_message=f"Test error {i}",
                source_system="test_system",
                session=db_session,
                category=ErrorCategory.EXTERNAL,
                send_to_telegram=False,
            )

        stats = await service.get_error_stats(
            session=db_session,
            category=ErrorCategory.EXTERNAL,
        )

        assert stats["total"] >= 3

    @pytest.mark.asyncio
    @pytest.mark.skip(reason="Requires full database schema with all tables")
    async def test_delete_error_messages(self, service, db_session):
        """
        Проверяет удаление сообщений, связанных с ошибкой.

        Создаётся ошибка с привязанным chat_id, затем вызывается метод delete_error_messages.
        Ожидается, что операция пройдёт успешно, а в результате будет указан идентификатор ошибки.
        """
        error = await service.log_external_error(
            error_code="EXT_005",
            error_message="Delete test",
            source_system="test_system",
            session=db_session,
            chat_ids=[123],
            send_to_telegram=False,
        )

        result = await service.delete_error_messages(
            error_id=error.FID,
            session=db_session,
            delete_from_telegram=False,
        )

        assert result["success"] is True
        assert result["error_id"] == error.FID
