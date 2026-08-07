import re
from datetime import datetime, timedelta
from typing import Any

from ...logger import tg_logger


class Validator:
    """Базовый класс для валидаторов"""

    @staticmethod
    def validate_not_empty(value: Any, field_name: str) -> bool:
        """Проверка, что значение не пустое"""
        if value is None:
            tg_logger.warning(f"⚠️ {field_name} is None")
            return False

        if isinstance(value, str) and not value.strip():
            tg_logger.warning(f"⚠️ {field_name} is empty string")
            return False

        if isinstance(value, list | dict | set) and not value:
            tg_logger.warning(f"⚠️ {field_name} is empty collection")
            return False

        return True

    @staticmethod
    def validate_length(value: str, field_name: str, min_len: int = 1, max_len: int = 4096) -> bool:
        """Проверка длины строки"""
        if not Validator.validate_not_empty(value, field_name):
            return False

        if len(value) < min_len:
            tg_logger.warning(f"⚠️ {field_name} is too short: {len(value)} < {min_len}")
            return False

        if len(value) > max_len:
            tg_logger.warning(f"⚠️ {field_name} is too long: {len(value)} > {max_len}")
            return False

        return True

    @staticmethod
    def validate_positive_int(value: int, field_name: str) -> bool:
        """Проверка, что число положительное"""
        if not isinstance(value, int):
            tg_logger.warning(f"⚠️ {field_name} is not an integer: {type(value)}")
            return False

        if value <= 0:
            tg_logger.warning(f"⚠️ {field_name} must be positive: {value}")
            return False

        return True

    @staticmethod
    def validate_chat_id(chat_id: int) -> bool:
        """Валидация ID чата"""
        return Validator.validate_positive_int(abs(chat_id), "chat_id")

    @staticmethod
    def validate_user_id(user_id: int) -> bool:
        """Валидация ID пользователя"""
        return Validator.validate_positive_int(user_id, "user_id")

    @staticmethod
    def validate_message_id(message_id: int) -> bool:
        """Валидация ID сообщения"""
        return Validator.validate_positive_int(message_id, "message_id")


class TextValidator:
    """Валидатор текстовых данных"""

    @staticmethod
    def sanitize_text(text: str, max_length: int = 4096) -> str:
        """Санитайзинг текста (очистка от опасных символов)"""
        if not text:
            return ""

        # Обрезание длины
        if len(text) > max_length:
            text = text[:max_length]

        # Удаление лишних пробелов
        text = " ".join(text.split())

        # Экранирование опасных символов (для HTML)
        text = text.replace("&", "&amp;")
        text = text.replace("<", "&lt;")
        text = text.replace(">", "&gt;")
        text = text.replace('"', "&quot;")

        return text

    @staticmethod
    def validate_parse_mode(parse_mode: str | None) -> str | None:
        """Валидация режима парсинга"""
        if parse_mode is None:
            return None

        valid_modes = ["HTML", "MARKDOWN", "MARKDOWN_V2"]
        parse_mode_upper = parse_mode.upper()

        if parse_mode_upper not in valid_modes:
            tg_logger.warning(f"⚠️ Invalid parse_mode: {parse_mode}, using HTML")
            return "HTML"

        return parse_mode_upper

    @staticmethod
    def extract_mentions(text: str) -> list[str]:
        """Извлечение упоминаний из текста"""
        if not text:
            return []

        # Поиск @username
        pattern = r"@\w+"
        return re.findall(pattern, text)

    @staticmethod
    def extract_hashtags(text: str) -> list[str]:
        """Извлечение хэштегов из текста"""
        if not text:
            return []

        # Поиск #hashtag
        pattern = r"#\w+"
        return re.findall(pattern, text)

    @staticmethod
    def extract_links(text: str) -> list[str]:
        """Извлечение ссылок из текста"""
        if not text:
            return []

        # Поиск URL
        pattern = r"https?://[^\s]+"
        return re.findall(pattern, text)

    @staticmethod
    def truncate_text(text: str, max_length: int = 100, suffix: str = "...") -> str:
        """Обрезание текста до указанной длины"""
        if not text:
            return ""

        if len(text) <= max_length:
            return text

        return text[: max_length - len(suffix)] + suffix


class CommandValidator:
    """Валидатор команд"""

    @staticmethod
    def validate_command(command: str) -> bool:
        """Валидация команды"""
        if not command:
            return False

        if not command.startswith("/"):
            return False

        # Команда должна состоять из букв, цифр и подчеркивания
        command_name = command[1:]
        return bool(re.fullmatch(r"^[a-zA-Z0-9_]+$", command_name))

    @staticmethod
    def parse_command(text: str) -> dict[str, Any]:
        """Парсинг команды"""
        if not text or not text.startswith("/"):
            return {}

        parts = text.strip().split()

        if not parts:
            return {}

        command = parts[0]
        args = parts[1:] if len(parts) > 1 else []

        return {
            "command": command,
            "args": args,
            "args_text": " ".join(args) if args else "",
            "full_text": text,
        }

    @staticmethod
    def is_admin_command(command: str, admin_commands: list[str] | None = None) -> bool:
        """Проверка, является ли команда административной"""
        if admin_commands is None:
            admin_commands = ["/sync", "/stats", "/broadcast"]

        return command in admin_commands


class DataValidator:
    """Валидатор данных"""

    @staticmethod
    def validate_dict_keys(data: dict[str, Any], required_keys: list[str]) -> bool:
        """Проверка наличия обязательных ключей в словаре"""
        for key in required_keys:
            if key not in data:
                tg_logger.warning(f"⚠️ Missing required key: {key}")
                return False

        return True

    @staticmethod
    def validate_dict_types(data: dict[str, Any], type_map: dict[str, type]) -> bool:
        """Проверка типов значений в словаре"""
        for key, expected_type in type_map.items():
            if key in data and not isinstance(data[key], expected_type):
                tg_logger.warning(
                    f"⚠️ Invalid type for {key}: expected {expected_type.__name__}, got {type(data[key]).__name__}"
                )
                return False

        return True

    @staticmethod
    def validate_phone_number(phone: str) -> bool:
        """Валидация номера телефона"""
        if not phone:
            return False

        # Очистка от лишних символов
        cleaned = re.sub(r"[^\d+]", "", phone)

        # Проверка формата
        return bool(re.fullmatch(r"^\+?\d{10,15}$", cleaned))

    @staticmethod
    def validate_email(email: str) -> bool:
        """Валидация email"""
        if not email:
            return False

        pattern = r"^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$"
        return bool(re.fullmatch(pattern, email))

    @staticmethod
    def validate_username(username: str) -> bool:
        """Валидация username"""
        if not username:
            return False

        # Username может начинаться с @
        if username.startswith("@"):
            username = username[1:]

        # Проверка формата
        return bool(re.fullmatch(r"^[a-zA-Z0-9_]{5,32}$", username))


class RateLimitValidator:
    """Валидатор для rate limiting"""

    def __init__(self, limit: int = 10, period: int = 60) -> None:
        self.limit = limit
        self.period = period
        self._requests: dict[str, list[datetime]] = {}

    def is_allowed(self, key: str) -> bool:
        """Проверка, разрешен ли запрос"""
        now = datetime.now()

        # Очистка старых запросов
        if key in self._requests:
            self._requests[key] = [
                req_time for req_time in self._requests[key] if (now - req_time).total_seconds() < self.period
            ]
        else:
            self._requests[key] = []

        # Проверка лимита
        if len(self._requests[key]) >= self.limit:
            return False

        # Добавление запроса
        self._requests[key].append(now)
        return True

    def get_remaining(self, key: str) -> int:
        """Получение оставшегося количества запросов"""
        if key not in self._requests:
            return self.limit

        return max(0, self.limit - len(self._requests[key]))

    def get_reset_time(self, key: str) -> datetime | None:
        """Получение времени сброса"""
        if key not in self._requests or not self._requests[key]:
            return None

        oldest = min(self._requests[key])
        return oldest + timedelta(seconds=self.period)


__all__ = [
    "Validator",
    "TextValidator",
    "CommandValidator",
    "DataValidator",
    "RateLimitValidator",
]
