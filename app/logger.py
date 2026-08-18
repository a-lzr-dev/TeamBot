import logging
import sys
from logging.handlers import RotatingFileHandler
from pathlib import Path
from typing import Any, Protocol, runtime_checkable

from .config import settings

# ==================== ПРОТОКОЛ ДЛЯ ЛОГГЕРА ====================


@runtime_checkable
class LoggerProtocol(Protocol):
    """
    Протокол для логгера, поддерживающего основные методы логирования.
    Совместим как с logging.Logger, так и с ExtendedLogger.
    """

    def debug(self, msg: str, *args: Any, **kwargs: Any) -> None: ...

    def info(self, msg: str, *args: Any, **kwargs: Any) -> None: ...

    def warning(self, msg: str, *args: Any, **kwargs: Any) -> None: ...

    def error(self, msg: str, *args: Any, **kwargs: Any) -> None: ...

    def critical(self, msg: str, *args: Any, **kwargs: Any) -> None: ...

    def log(self, level: int, msg: str, *args: Any, **kwargs: Any) -> None: ...

    def exception(self, msg: str, *args: Any, **kwargs: Any) -> None: ...


# ==================== ФОРМАТТЕРЫ ====================


class ConsoleFormatter(logging.Formatter):
    """Форматтер для консольного вывода логов"""

    # ANSI цветовые коды
    COLORS = {
        "DEBUG": "\033[36m",  # Голубой (Cyan)
        "INFO": "\033[32m",  # Зеленый (Green)
        "WARNING": "\033[33m",  # Желтый (Yellow)
        "ERROR": "\033[31m",  # Красный (Red)
        "CRITICAL": "\033[35m",  # Фиолетовый (Magenta)
        "RESET": "\033[0m",  # Сброс цвета
    }

    def format(self, record: logging.LogRecord) -> str:
        """Форматирование записи лога с добавлением цветов и выравниванием"""
        original_levelname = record.levelname
        padded_levelname = original_levelname.ljust(8)
        if original_levelname in self.COLORS:
            record.levelname = f"{self.COLORS[original_levelname]}{padded_levelname}{self.COLORS['RESET']}"
        else:
            record.levelname = padded_levelname
        result = super().format(record)
        record.levelname = original_levelname
        return result


# ==================== НАСТРОЙКА ЛОГГЕРОВ ====================


class LoggerSetup:
    """Настройка логирования для всего приложения"""

    _instance: "LoggerSetup | None" = None
    _loggers: dict[str, logging.Logger] = {}

    def __new__(cls) -> "LoggerSetup":
        """Создание единственного экземпляра класса"""
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    def __init__(self) -> None:
        """Инициализация настроек логирования"""
        if not hasattr(self, "initialized"):
            self.log_dir = Path(getattr(settings, "LOG_DIR", "logs"))
            self.log_dir.mkdir(parents=True, exist_ok=True)
            self.initialized = True

    def get_logger(self, name: str, level: str | None = None) -> logging.Logger:
        """Получение логера с указанными именем"""
        if name in self._loggers:
            return self._loggers[name]

        logger = logging.getLogger(name)

        if level is None:
            level = getattr(settings, "LOG_LEVEL", "INFO")
        log_level = getattr(logging, level.upper(), logging.INFO)
        logger.setLevel(log_level)

        if not logger.handlers:
            self._add_handlers(logger, name)

        self._loggers[name] = logger
        return logger

    def _add_handlers(self, logger: logging.Logger, name: str) -> None:
        """Добавление обработчиков в логер с указанным именем"""

        file_formatter = logging.Formatter(
            "%(asctime)s | %(levelname)-7s | %(name)-5s | %(message)s", datefmt="%Y-%m-%d %H:%M:%S"
        )

        console_formatter = ConsoleFormatter(
            "%(asctime)s | %(levelname)s | %(name)-5s | %(message)s", datefmt="%Y-%m-%d %H:%M:%S"
        )

        # Файловый обработчик
        file_handler = RotatingFileHandler(
            self.log_dir / f"{name.strip()}.log",
            maxBytes=getattr(settings, "LOG_MAX_BYTES", 10_000_000),
            backupCount=getattr(settings, "LOG_BACKUP_COUNT", 5),
            encoding="utf-8",
        )
        file_handler.setFormatter(file_formatter)
        logger.addHandler(file_handler)

        # Консольный обработчик
        console_handler = logging.StreamHandler(sys.stdout)
        console_handler.setFormatter(console_formatter)
        logger.addHandler(console_handler)

        logger.propagate = False


# ==================== РАСШИРЕННЫЙ ЛОГГЕР ====================


class ExtendedLogger:
    """
    Расширенный логгер с дополнительными методами для структурированного логирования.
    Реализует LoggerProtocol.
    """

    def __init__(self, logger: logging.Logger, component: str = "app"):
        self._logger = logger
        self._component = component

    # ============ БАЗОВЫЕ МЕТОДЫ ЛОГИРОВАНИЯ ============

    def debug(self, msg: str, *args: Any, **kwargs: Any) -> None:
        """Логирование на уровне DEBUG"""
        self._logger.debug(msg, *args, **kwargs)

    def info(self, msg: str, *args: Any, **kwargs: Any) -> None:
        """Логирование на уровне INFO"""
        self._logger.info(msg, *args, **kwargs)

    def warning(self, msg: str, *args: Any, **kwargs: Any) -> None:
        """Логирование на уровне WARNING"""
        self._logger.warning(msg, *args, **kwargs)

    def error(self, msg: str, *args: Any, **kwargs: Any) -> None:
        """Логирование на уровне ERROR"""
        self._logger.error(msg, *args, **kwargs)

    def critical(self, msg: str, *args: Any, **kwargs: Any) -> None:
        """Логирование на уровне CRITICAL"""
        self._logger.critical(msg, *args, **kwargs)

    def log(self, level: int, msg: str, *args: Any, **kwargs: Any) -> None:
        """Общий метод логирования"""
        self._logger.log(level, msg, *args, **kwargs)

    def exception(self, msg: str, *args: Any, **kwargs: Any) -> None:
        """Логирование исключения"""
        self._logger.exception(msg, *args, **kwargs)

    # ============ ДОПОЛНИТЕЛЬНЫЕ МЕТОДЫ ============

    def log_request(
        self,
        method: str,
        path: str,
        status_code: int | None = None,
        duration_ms: float | None = None,
        client_ip: str | None = None,
        **kwargs: Any,
    ) -> None:
        """Логирование HTTP-запроса"""
        message = f"{method} {path}"
        if status_code is not None:
            message = f"{message} -> {status_code}"
        if duration_ms is not None:
            message = f"{message} ({duration_ms:.2f}ms)"
        if client_ip:
            message = f"{message} from {client_ip}"

        self._logger.info(message, extra=kwargs)

    def log_telegram_event(
        self,
        event_type: str,
        user_id: int | None = None,
        chat_id: int | None = None,
        **kwargs: Any,
    ) -> None:
        """Логирование Telegram-события"""
        message = f"Telegram event: {event_type}"
        if user_id is not None:
            message += f" user={user_id}"
        if chat_id is not None:
            message += f" chat={chat_id}"

        self._logger.debug(message, extra=kwargs)

    def log_error(self, error: Exception, message: str = "Error occurred", **kwargs: Any) -> None:
        """Логирование ошибки с контекстом"""
        extra = kwargs.get("extra", {})
        if isinstance(extra, dict):
            extra["error_type"] = type(error).__name__
            extra["error_message"] = str(error)

        self._logger.error(f"{message}: {error}", exc_info=True, extra=extra)


# ==================== СОЗДАНИЕ ЭКЗЕМПЛЯРОВ ====================

logger_setup = LoggerSetup()

# Базовые логгеры
_app_logger = logger_setup.get_logger("app")
_api_logger = logger_setup.get_logger("api")
_bot_logger = logger_setup.get_logger("bot")
_db_logger = logger_setup.get_logger("db")
_admin_logger = logger_setup.get_logger("admin")

# Расширенные логгеры с дополнительными методами
app_logger = ExtendedLogger(_app_logger, "app")
api_logger = ExtendedLogger(_api_logger, "api")
bot_logger = ExtendedLogger(_bot_logger, "bot")
db_logger = ExtendedLogger(_db_logger, "db")
admin_logger = ExtendedLogger(_admin_logger, "admin")

# ==================== ЭКСПОРТ ====================

__all__ = [
    # Протокол
    "LoggerProtocol",
    # Настройка
    "logger_setup",
    # Базовые логгеры
    "_app_logger",
    "_api_logger",
    "_bot_logger",
    "_db_logger",
    "_admin_logger",
    # Расширенные логгеры
    "app_logger",
    "api_logger",
    "bot_logger",
    "db_logger",
    "admin_logger",
]
