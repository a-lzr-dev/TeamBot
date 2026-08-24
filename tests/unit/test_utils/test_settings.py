"""Тесты для модуля настроек."""

import os
from unittest.mock import patch

from app.utils.settings import env_bool, env_int


class TestSettings:
    """Тесты для функций настроек."""

    def test_env_bool_true(self):
        """Тест env_bool с True."""
        with patch.dict(os.environ, {"TEST_BOOL": "true"}):
            assert env_bool("TEST_BOOL", False) is True

        with patch.dict(os.environ, {"TEST_BOOL": "1"}):
            assert env_bool("TEST_BOOL", False) is True

        with patch.dict(os.environ, {"TEST_BOOL": "yes"}):
            assert env_bool("TEST_BOOL", False) is True

    def test_env_bool_false(self):
        """Тест env_bool с False."""
        with patch.dict(os.environ, {"TEST_BOOL": "false"}):
            assert env_bool("TEST_BOOL", True) is False

        with patch.dict(os.environ, {"TEST_BOOL": "0"}):
            assert env_bool("TEST_BOOL", True) is False

        with patch.dict(os.environ, {"TEST_BOOL": "no"}):
            assert env_bool("TEST_BOOL", True) is False

    def test_env_bool_default(self):
        """Тест env_bool с значением по умолчанию."""
        # Переменная не установлена
        assert env_bool("NONEXISTENT_BOOL", True) is True
        assert env_bool("NONEXISTENT_BOOL", False) is False

    def test_env_int(self):
        """Тест env_int."""
        with patch.dict(os.environ, {"TEST_INT": "42"}):
            assert env_int("TEST_INT", 0) == 42

    def test_env_int_default(self):
        """Тест env_int с значением по умолчанию."""
        # Переменная не установлена
        assert env_int("NONEXISTENT_INT", 100) == 100

    def test_env_int_invalid(self):
        """Тест env_int с невалидным значением."""
        with patch.dict(os.environ, {"TEST_INT": "not_a_number"}):
            # Должен вернуть значение по умолчанию
            assert env_int("TEST_INT", 42) == 42
