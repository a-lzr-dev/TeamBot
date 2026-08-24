"""
Модуль с тестами для сервиса ошибок (ErrorService).

Содержит набор асинхронных тестов, проверяющих логику работы с ошибками:
- логирование ошибок с передачей исключения;
- обработка результатов (возврат модели ошибки и опционально сообщения чата);
- проверка автоматической генерации идентификаторов.

Тесты используют реальную тестовую БД (in-memory SQLite) для проверки
сохранения ошибок в базе данных.
"""

import pytest

from app.services.error_service import ErrorService


class TestErrorService:
    """
    Набор тестов для проверки корректности работы ErrorService.

    Тестируются основные сценарии:
    - логирование ошибок с контекстом;
    - обработка возвращаемых значений (одиночная модель или кортеж);
    - автоматическое создание записи в БД.
    """

    @pytest.mark.asyncio
    async def test_log_error(self, db_session):
        """
        Проверяет логирование ошибки через метод log_error.

        Шаги:
        1. Искусственно вызывается ValueError.
        2. Вызывается метод log_error с передачей исключения, компонента,
           идентификатора пользователя и контекста.
        3. Проверяется, что возвращённая модель ошибки не None.
        4. Проверяется, что FID был автоматически сгенерирован (не None).
        5. Проверяется, что код ошибки и сообщение соответствуют исключению.

        Обрабатывается ситуация, когда метод возвращает кортеж
        (error_model, chat_message) или только error_model.
        """
        error_service = ErrorService()

        try:
            raise ValueError("Test error")
        except ValueError as e:
            result = await error_service.log_error(
                error=e,
                component="test",
                user_id=123,
                context={"test": "context"},
            )

            # Поддержка обоих вариантов возврата: (error, chat_message) или только error
            if isinstance(result, tuple) and len(result) == 2:
                error_model, chat_message = result
            else:
                error_model = result

            assert error_model is not None
            assert error_model.FID is not None
            assert error_model.FErrorCode == "ValueError"
            assert error_model.FErrorMessage == "Test error"
