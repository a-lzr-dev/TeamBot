"""Тесты для модуля исключений."""

import pytest

from app.exceptions import (
    AppError,
    AutomationError,
    ConfigurationError,
    ConversionError,
    DatabaseError,
    NotFoundError,
    PyWin32Error,
    TelegramError,
    ValidationError,
)


class TestExceptions:
    """Тесты для классов исключений."""

    def test_app_error(self) -> None:
        """Тест базового исключения."""
        error = AppError("Test error")
        assert str(error) == "Test error"
        assert isinstance(error, Exception)

    def test_database_error(self) -> None:
        """Тест ошибки базы данных."""
        error = DatabaseError("DB connection failed")
        assert str(error) == "DB connection failed"
        assert isinstance(error, AppError)

    def test_telegram_error(self) -> None:
        """Тест ошибки Telegram."""
        error = TelegramError("Telegram API error")
        assert str(error) == "Telegram API error"
        assert isinstance(error, AppError)

    def test_configuration_error(self) -> None:
        """Тест ошибки конфигурации."""
        error = ConfigurationError("Invalid config")
        assert str(error) == "Invalid config"
        assert isinstance(error, AppError)

    def test_validation_error(self) -> None:
        """Тест ошибки валидации."""
        error = ValidationError("Invalid data")
        assert str(error) == "Invalid data"
        assert isinstance(error, AppError)

    def test_not_found_error(self) -> None:
        """Тест ошибки 'объект не найден'."""
        error = NotFoundError("User not found")
        assert str(error) == "User not found"
        assert isinstance(error, AppError)

    def test_automation_error(self) -> None:
        """Тест ошибки автоматизации."""
        error = AutomationError("Automation failed")
        assert str(error) == "Automation failed"
        assert isinstance(error, AppError)

    def test_conversion_error(self) -> None:
        """Тест ошибки конвертации."""
        error = ConversionError("Conversion failed")
        assert str(error) == "Conversion failed"
        assert isinstance(error, AutomationError)

    def test_pywin32_error(self) -> None:
        """Тест ошибки pywin32."""
        error = PyWin32Error("Word COM error")
        assert str(error) == "Word COM error"
        assert isinstance(error, ConversionError)

    def test_exception_hierarchy(self) -> None:
        """Тест иерархии исключений."""
        # Проверка, что все исключения наследуются от AppError
        exception_classes = [
            DatabaseError,
            TelegramError,
            ConfigurationError,
            ValidationError,
            NotFoundError,
            AutomationError,
        ]

        for exc_class in exception_classes:
            assert issubclass(exc_class, AppError)
            assert issubclass(exc_class, Exception)

        # Проверка специализированных
        assert issubclass(ConversionError, AutomationError)
        assert issubclass(PyWin32Error, ConversionError)

    def test_exception_with_custom_message(self) -> None:
        """Тест исключений с пользовательским сообщением."""
        error = DatabaseError("Custom DB error: connection timeout")
        assert "Custom DB error" in str(error)
        assert "connection timeout" in str(error)

    def test_exception_raise_and_catch(self) -> None:
        """Тест поднятия и перехвата исключений."""
        with pytest.raises(ValidationError) as exc_info:
            raise ValidationError("Invalid email format")
        assert str(exc_info.value) == "Invalid email format"

        with pytest.raises(NotFoundError) as exc_info:
            raise NotFoundError("Chat not found")
        assert "Chat not found" in str(exc_info.value)
