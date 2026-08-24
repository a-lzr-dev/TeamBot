import pytest

from app.utils.json import log_json_errors


class TestJsonUtils:
    """
    Тесты для декоратора log_json_errors.

    Проверяет:
    - Успешное выполнение декорированной функции
    - Логирование ошибок с JSON-данными
    - Логирование ошибок без JSON-данных
    - Обработку ошибок с не-JSON аргументами
    """

    # ============================================================
    # 1. УСПЕШНОЕ ВЫПОЛНЕНИЕ
    # ============================================================

    @pytest.mark.asyncio
    async def test_log_json_errors_success_async(self, caplog):
        """
        Тест успешного выполнения асинхронной декорированной функции.

        Проверяет:
        - Функция возвращает ожидаемый результат
        - Ошибки не логируются при успешном выполнении
        """

        @log_json_errors
        async def test_func():
            return "success"

        result = await test_func()
        assert result == "success"
        assert "Error in test_func" not in caplog.text

    # ============================================================
    # 2. ЛОГИРОВАНИЕ ОШИБОК С JSON-ДАННЫМИ
    # ============================================================

    @pytest.mark.asyncio
    async def test_log_json_errors_with_list(self, caplog):
        """
        Тест логирования ошибки с JSON-данными (список).

        Проверяет:
        - Исключение перехватывается и пробрасывается дальше
        - Сообщение об ошибке логируется
        - Проблемные записи логируются с указанием поля 'id'
        """

        @log_json_errors
        async def test_func(data):
            raise ValueError("Test error with list")

        with pytest.raises(ValueError, match="Test error with list"):
            await test_func([{"id": 1, "name": "test"}, {"id": 2, "name": "test2"}])

        assert "Error in test_func" in caplog.text
        assert "Test error with list" in caplog.text
        assert "Problematic records" in caplog.text
        assert "id" in caplog.text

    # ============================================================
    # 3. ЛОГИРОВАНИЕ ОШИБОК БЕЗ JSON-ДАННЫХ
    # ============================================================

    @pytest.mark.asyncio
    async def test_log_json_errors_no_json_data(self, caplog):
        """
        Тест логирования ошибки без JSON-данных.

        Проверяет:
        - Исключение перехватывается и пробрасывается дальше
        - Сообщение об ошибке логируется
        - Отсутствует сообщение о проблемных записях (нет данных для логирования)
        """

        @log_json_errors
        async def test_func():
            raise ValueError("Plain error without JSON")

        with pytest.raises(ValueError, match="Plain error without JSON"):
            await test_func()

        assert "Error in test_func" in caplog.text
        assert "Plain error without JSON" in caplog.text
        assert "Problematic records" not in caplog.text

    @pytest.mark.asyncio
    async def test_log_json_errors_with_non_json_args(self, caplog):
        """
        Тест логирования ошибки с не-JSON аргументами.

        Проверяет:
        - Исключение перехватывается и пробрасывается дальше
        - Сообщение об ошибке логируется
        - Отсутствует сообщение о проблемных записях (аргументы не являются JSON-данными)
        """

        @log_json_errors
        async def test_func(a, b, c):
            raise TypeError("Non-JSON args error")

        with pytest.raises(TypeError, match="Non-JSON args error"):
            await test_func(1, "string", None)

        assert "Error in test_func" in caplog.text
        assert "Non-JSON args error" in caplog.text
        assert "Problematic records" not in caplog.text
