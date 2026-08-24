"""Тесты для декораторов."""

import asyncio
import logging
import time

import pytest

from app.logger import app_logger
from app.utils.decorators import (
    cached_result,
    log_exceptions,
    log_execution_time,
    retry_on_failure,
    robust_operation,  # Добавить
    silent_operation,
    silent_retry,  # Добавить
    suppress_debug_logs,
)


class TestSuppressDecorators:
    """Тесты для декораторов подавления логов."""

    def test_suppress_debug_logs_async(self, caplog):
        """Тест подавления DEBUG логов в асинхронной функции."""

        @suppress_debug_logs
        async def test_func():
            app_logger.debug("This is debug message")
            return "result"

        with caplog.at_level(logging.DEBUG):
            result = asyncio.run(test_func())
            assert result == "result"
            assert "This is debug message" not in caplog.text

    def test_suppress_debug_logs_sync(self, caplog):
        """Тест подавления DEBUG логов в синхронной функции."""

        @suppress_debug_logs
        def test_func():
            app_logger.debug("This is debug message")
            return "result"

        with caplog.at_level(logging.DEBUG):
            result = test_func()
            assert result == "result"
            assert "This is debug message" not in caplog.text

    def test_suppress_all_logs_async(self, caplog):
        """Тест подавления всех логов в асинхронной функции."""

        @suppress_debug_logs
        async def test_func():
            app_logger.info("This is info message")
            app_logger.warning("This is warning message")
            return "result"

        with caplog.at_level(logging.INFO):
            result = asyncio.run(test_func())
            assert result == "result"
            assert "This is info message" in caplog.text
            assert "This is warning message" in caplog.text

    def test_suppress_all_logs_sync(self, caplog):
        """Тест подавления всех логов в синхронной функции."""

        @suppress_debug_logs
        def test_func():
            app_logger.info("This is info message")
            return "result"

        with caplog.at_level(logging.INFO):
            result = test_func()
            assert result == "result"
            assert "This is info message" in caplog.text


class TestLogExecutionTime:
    """Тесты для декоратора логирования времени выполнения."""

    def test_log_execution_time_async(self, caplog):
        """Тест логирования времени выполнения асинхронной функции."""

        @log_execution_time()
        async def test_func():
            await asyncio.sleep(0.01)
            return "result"

        with caplog.at_level(logging.DEBUG):
            result = asyncio.run(test_func())
            assert result == "result"
            assert "Executed test_func in" in caplog.text
            assert "ms" in caplog.text

    def test_log_execution_time_sync(self, caplog):
        """Тест логирования времени выполнения синхронной функции."""

        @log_execution_time()
        def test_func():
            time.sleep(0.01)
            return "result"

        with caplog.at_level(logging.DEBUG):
            result = test_func()
            assert result == "result"
            assert "Executed test_func in" in caplog.text
            assert "ms" in caplog.text

    def test_custom_message(self, caplog):
        """Тест с пользовательским сообщением."""

        @log_execution_time(message="Custom message: {func_name} took {duration:.2f}ms")
        def test_func():
            time.sleep(0.01)
            return "result"

        with caplog.at_level(logging.DEBUG):
            result = test_func()
            assert result == "result"
            assert "Custom message" in caplog.text


class TestLogExceptions:
    """Тесты для декоратора логирования исключений."""

    def test_log_exceptions_async_with_reraise(self, caplog):
        """Тест логирования исключений в асинхронной функции с пробросом."""

        @log_exceptions(reraise=True)
        async def test_func():
            raise ValueError("Test error")

        with caplog.at_level(logging.ERROR):
            with pytest.raises(ValueError, match="Test error"):
                asyncio.run(test_func())
            assert "Exception in test_func" in caplog.text
            assert "ValueError" in caplog.text
            assert "Test error" in caplog.text

    def test_log_exceptions_async_without_reraise(self, caplog):
        """Тест логирования исключений в асинхронной функции без проброса."""

        @log_exceptions(reraise=False)
        async def test_func():
            raise ValueError("Test error")

        with caplog.at_level(logging.ERROR):
            result = asyncio.run(test_func())
            assert result is None

    def test_log_exceptions_sync(self, caplog):
        """Тест логирования исключений в синхронной функции."""

        @log_exceptions(reraise=False)
        def test_func():
            raise ValueError("Test error")

        with caplog.at_level(logging.ERROR):
            result = test_func()
            assert result is None

    def test_cancelled_error(self, caplog):
        """Тест обработки CancelledError."""

        @log_exceptions(reraise=True)
        async def test_func():
            raise asyncio.CancelledError()

        with caplog.at_level(logging.ERROR):
            with pytest.raises(asyncio.CancelledError):
                asyncio.run(test_func())
            assert "Exception in test_func" not in caplog.text


class TestRetryOnFailure:
    """Тесты для декоратора повторных попыток."""

    def test_retry_success_first_try(self):
        """Тест успешного выполнения с первой попытки."""
        call_count = 0

        @retry_on_failure(attempts=3, delay=0.01)
        def test_func():
            nonlocal call_count
            call_count += 1
            return "success"

        result = test_func()
        assert result == "success"
        assert call_count == 1

    def test_retry_success_after_failures(self):
        """Тест успешного выполнения после нескольких неудачных попыток."""
        call_count = 0

        @retry_on_failure(attempts=3, delay=0.01)
        def test_func():
            nonlocal call_count
            call_count += 1
            if call_count < 3:
                raise ValueError("Temporary error")
            return "success"

        result = test_func()
        assert result == "success"
        assert call_count == 3

    def test_retry_failure_all_attempts(self):
        """Тест неудачного выполнения после всех попыток."""
        call_count = 0

        @retry_on_failure(attempts=3, delay=0.01)
        def test_func():
            nonlocal call_count
            call_count += 1
            raise ValueError("Permanent error")

        with pytest.raises(ValueError, match="Permanent error"):
            test_func()
        assert call_count == 3

    def test_retry_with_backoff(self):
        """Тест с экспоненциальной задержкой."""
        call_count = 0

        @retry_on_failure(attempts=3, delay=0.01, backoff=2)
        def test_func():
            nonlocal call_count
            call_count += 1
            if call_count < 3:
                raise ValueError("Temporary error")
            return "success"

        result = test_func()
        assert result == "success"
        assert call_count == 3


class TestCombinedDecorators:
    """Тесты для комбинированных декораторов."""

    def test_silent_operation(self, caplog):
        """Тест тихой операции."""

        @silent_operation()
        def test_func():
            return "result"

        with caplog.at_level(logging.WARNING):
            result = test_func()
            assert result == "result"
            assert "Executed test_func" not in caplog.text

    def test_silent_retry(self, caplog):
        """Тест тихой операции с повторными попытками."""
        attempt = 0

        @silent_retry(attempts=3, delay=0.01)
        def test_func():
            nonlocal attempt
            attempt += 1
            if attempt < 3:
                raise ValueError("Temporary error")
            return "success"

        with caplog.at_level(logging.WARNING):
            result = test_func()
            assert result == "success"
            assert attempt == 3

    def test_robust_operation(self, caplog):
        """Тест надежной операции."""

        @robust_operation(attempts=2, delay=0.01, log_level="error")
        def test_func():
            raise ValueError("Permanent error")

        with caplog.at_level(logging.ERROR):
            result = test_func()
            assert result is None


class TestCachedResult:
    """Тесты для декоратора кэширования результатов."""

    def test_cached_result_async(self):
        """Тест кэширования результатов асинхронной функции."""
        call_count = 0

        @cached_result(ttl=60)
        async def test_func(x: int):
            nonlocal call_count
            call_count += 1
            return x * 2

        result1 = asyncio.run(test_func(5))
        result2 = asyncio.run(test_func(5))
        result3 = asyncio.run(test_func(10))

        assert result1 == 10
        assert result2 == 10
        assert result3 == 20
        assert call_count == 2

    def test_cached_result_sync(self):
        """Тест кэширования результатов синхронной функции."""
        call_count = 0

        @cached_result(ttl=60)
        def test_func(x: int):
            nonlocal call_count
            call_count += 1
            return x * 2

        result1 = test_func(5)
        result2 = test_func(5)
        result3 = test_func(10)

        assert result1 == 10
        assert result2 == 10
        assert result3 == 20
        assert call_count == 2

    def test_cached_result_ttl(self):
        """Тест истечения срока кэширования."""
        call_count = 0

        @cached_result(ttl=0.1)
        def test_func(x: int):
            nonlocal call_count
            call_count += 1
            return x * 2

        result1 = test_func(5)
        time.sleep(0.2)
        result2 = test_func(5)

        assert result1 == 10
        assert result2 == 10
        assert call_count == 2
