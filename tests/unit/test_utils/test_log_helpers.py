"""Тесты для LogHelper."""

import logging

from app.utils.log_helpers import LogHelper


class TestLogHelper:
    """Тесты для LogHelper."""

    def test_truncate_short_text(self):
        """Тест обрезания короткого текста."""
        text = "Short text"
        result = LogHelper.truncate(text, max_length=100)
        assert result == text

    def test_truncate_long_text(self):
        """Тест обрезания длинного текста."""
        text = "A" * 1000
        result = LogHelper.truncate(text, max_length=100)
        assert len(result) <= 100
        assert "[TRUNCATED]" in result

    def test_truncate_empty_text(self):
        """Тест обрезания пустого текста."""
        result = LogHelper.truncate("")
        assert result == ""

    def test_truncate_error(self, caplog):
        """Тест обрезания ошибки."""
        error = ValueError("This is a test error message")
        result = LogHelper.truncate_error(error, max_length=50)
        assert len(result) <= 50

    def test_truncate_json(self):
        """Тест обрезания JSON."""
        data = {"key": "value", "nested": {"a": 1, "b": 2}}
        result = LogHelper.truncate_json(data, max_length=100)
        assert isinstance(result, str)
        assert "key" in result

    def test_log_batch_error_fast(self, caplog):
        """Тест логирования ошибки пакета."""
        logger = logging.getLogger("test")
        logger.setLevel(logging.WARNING)

        error = ValueError("Test error")
        LogHelper.log_batch_error_fast(
            logger=logger,
            operation="INSERT",
            table="test_table",
            error=error,
            batch_size=10,
        )

        assert "⚠️ INSERT failed" in caplog.text
        assert "test_table" in caplog.text

    def test_log_json_preview_debug(self, caplog):
        """Тест логирования JSON на уровне DEBUG."""
        logger = logging.getLogger("test")
        logger.setLevel(logging.DEBUG)

        data = {"test": "data"}
        LogHelper.log_json_preview(
            logger=logger,
            message="Test message",
            data=data,
            level="debug",
        )

        assert "Test message" in caplog.text
        assert "test" in caplog.text

    def test_log_json_preview_not_debug(self, caplog):
        """Тест логирования JSON когда DEBUG не включен."""
        logger = logging.getLogger("test")
        logger.setLevel(logging.INFO)

        data = {"test": "data"}
        LogHelper.log_json_preview(
            logger=logger,
            message="Test message",
            data=data,
        )

        assert "Test message" not in caplog.text

    def test_log_error(self, caplog):
        """Тест логирования ошибки."""
        logger = logging.getLogger("test")
        logger.setLevel(logging.ERROR)

        error = ValueError("Test error")
        LogHelper.log_error(
            logger=logger,
            message="Error occurred",
            error=error,
            level="error",
        )

        assert "Error occurred" in caplog.text
        assert "Test error" in caplog.text

    def test_log_warning(self, caplog):
        """Тест логирования предупреждения."""
        logger = logging.getLogger("test")
        logger.setLevel(logging.WARNING)

        LogHelper.log_warning(
            logger=logger,
            message="Warning message",
        )

        assert "Warning message" in caplog.text

    def test_log_info(self, caplog):
        """Тест логирования информационного сообщения."""
        logger = logging.getLogger("test")
        logger.setLevel(logging.INFO)

        LogHelper.log_info(
            logger=logger,
            message="Info message",
        )

        assert "Info message" in caplog.text

    def test_log_sql_error(self, caplog):
        """Тест логирования SQL ошибки."""
        logger = logging.getLogger("test")
        logger.setLevel(logging.ERROR)

        error = ValueError("SQL error")
        LogHelper.log_sql_error(
            logger=logger,
            operation="SELECT",
            table="test_table",
            sql="SELECT * FROM test",
            error=error,
        )

        assert "SELECT failed" in caplog.text
        assert "SQL: SELECT * FROM test" in caplog.text
