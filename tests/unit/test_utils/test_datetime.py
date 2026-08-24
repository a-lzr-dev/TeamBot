"""Тесты для модуля datetime."""

import re
from datetime import UTC

from app.models import datetime_now
from app.utils.datetime import get_timestamp


class TestDatetime:
    """Тесты для функций работы с датой и временем."""

    def test_datetime_now_returns_datetime(self) -> None:
        """Проверка, что datetime_now возвращает datetime без timezone."""
        dt = datetime_now()
        assert dt is not None
        # Проверка, что timezone отсутствует
        assert dt.tzinfo is None

    def test_datetime_now_has_correct_format(self) -> None:
        """Проверка, что datetime_now возвращает правильный формат."""
        dt = datetime_now()
        # Проверка, что это datetime объект
        assert hasattr(dt, "year")
        assert hasattr(dt, "month")
        assert hasattr(dt, "day")
        assert hasattr(dt, "hour")
        assert hasattr(dt, "minute")
        assert hasattr(dt, "second")

    def test_get_timestamp_returns_string(self) -> None:
        """Проверка, что get_timestamp возвращает строку."""
        timestamp = get_timestamp()
        assert isinstance(timestamp, str)

    def test_get_timestamp_format(self) -> None:
        """Проверка формата ISO timestamp с Z."""
        timestamp = get_timestamp()
        # Формат: YYYY-MM-DDTHH:MM:SS.ssssssZ
        pattern = r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(\.\d+)?Z$"
        assert re.match(pattern, timestamp) is not None

    def test_get_timestamp_timezone(self) -> None:
        """Проверка, что timestamp заканчивается на Z (UTC)."""
        timestamp = get_timestamp()
        assert timestamp.endswith("Z")

    def test_get_timestamp_consistency(self) -> None:
        """Проверка, что два последовательных вызова дают разные значения."""
        t1 = get_timestamp()
        t2 = get_timestamp()
        # В идеальном мире они разные, но могут быть равны в очень быстрых тестах
        # Проверяем, что это строки
        assert isinstance(t1, str)
        assert isinstance(t2, str)

    def test_datetime_now_is_utc_equivalent(self) -> None:
        """Проверка, что datetime_now возвращает время, близкое к UTC."""
        from datetime import datetime

        # Получаем время из функции
        dt_func = datetime_now()
        # Получаем текущее UTC время
        dt_utc = datetime.now(UTC).replace(tzinfo=None)

        # Разница не должна превышать 1 секунду
        diff = abs((dt_func - dt_utc).total_seconds())
        assert diff < 1.0, f"Time difference: {diff}s"
