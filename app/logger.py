"""
Модуль логирования TeamBot.

Предоставляет:
1. Настройку логгеров с ротацией файлов
2. Расширенный логгер с дополнительными методами
3. Поддержку подавления логов через contextvars
4. Цветной вывод в консоль
5. Структурированное логирование запросов и ошибок
"""

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
    """
    Форматтер для консольного вывода логов с цветами и выравниванием.

    Особенности:
    - Цветовая подсветка уровней логирования
    - Выравнивание уровня (8 символов)
    - Дополнительные поля (duration_ms) с эмодзи
    """

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
        """
        Форматирование записи лога с добавлением цветов и выравниванием.

        Args:
            record: Запись лога

        Returns:
            str: Отформатированное сообщение
        """
        original_levelname = record.levelname

        # Форматирование уровня с цветом и выравниванием
        padded_levelname = original_levelname.ljust(8)
        if original_levelname in self.COLORS:
            record.levelname = f"{self.COLORS[original_levelname]}{padded_levelname}{self.COLORS['RESET']}"
        else:
            record.levelname = padded_levelname

        # Форматирование основного сообщения
        result = super().format(record)

        # Добавление EXTRA полей
        extra_parts = self._format_extra_fields(record)

        # Добавление Extra к основному сообщению
        if extra_parts:
            extra_str = " │ ".join(extra_parts)
            result = f"{result} │ {extra_str}"

        # Восстановление оригинального значения уровня
        record.levelname = original_levelname

        return result

    @staticmethod
    def _format_extra_fields(record: logging.LogRecord) -> list[str]:
        """
        Форматирование дополнительных полей записи.

        Args:
            record: Запись лога

        Returns:
            list[str]: Список отформатированных полей
        """
        extra_parts = []

        # Поле duration_ms
        duration = getattr(record, "duration_ms", None)
        if duration is not None and duration != "N/A":
            formatted = f"{duration:.2f}ms" if isinstance(duration, int | float) else str(duration)[:50]
            extra_parts.append(f"⏱️ {formatted}")

        return extra_parts


# ==================== НАСТРОЙКА ЛОГГЕРОВ ====================


class LoggerSetup:
    """
    Настройка логирования для всего приложения.

    Реализует синглтон для централизованного управления логгерами.

    Особенности:
    - Автоматическое создание директории для логов
    - Ротация файлов логов
    - Поддержка нескольких логгеров (app, api, bot, db, admin)
    """

    _instance: "LoggerSetup | None" = None
    _loggers: dict[str, logging.Logger] = {}

    def __new__(cls) -> "LoggerSetup":
        """Создание единственного экземпляра класса."""
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    def __init__(self) -> None:
        """Инициализация настроек логирования."""
        if not hasattr(self, "initialized"):
            self.log_dir = Path(getattr(settings, "LOG_DIR", "logs"))
            self.log_dir.mkdir(parents=True, exist_ok=True)

            self._max_bytes = getattr(settings, "LOG_MAX_BYTES", 10_000_000)
            self._backup_count = getattr(settings, "LOG_BACKUP_COUNT", 5)
            self._default_level = getattr(settings, "LOG_LEVEL", "INFO")

            self.initialized = True

    # ==================== ПУБЛИЧНЫЕ МЕТОДЫ ====================

    def get_logger(self, name: str, level: str | None = None) -> logging.Logger:
        """
        Получение логгера с указанным именем.

        Args:
            name: Имя логгера (app, api, bot, db, admin)
            level: Уровень логирования (опционально)

        Returns:
            logging.Logger: Настроенный логгер
        """
        if name in self._loggers:
            return self._loggers[name]

        logger = self._create_logger(name, level)
        self._loggers[name] = logger
        return logger

    def get_all_loggers(self) -> dict[str, logging.Logger]:
        """
        Получение всех созданных логгеров.

        Returns:
            dict[str, logging.Logger]: Словарь {имя: логгер}
        """
        return self._loggers.copy()

    # ==================== ПРИВАТНЫЕ МЕТОДЫ ====================

    def _create_logger(self, name: str, level: str | None = None) -> logging.Logger:
        """
        Создание и настройка нового логгера.

        Args:
            name: Имя логгера
            level: Уровень логирования

        Returns:
            logging.Logger: Настроенный логгер
        """
        logger = logging.getLogger(name)

        # Установка уровня
        log_level = self._get_level(level)
        logger.setLevel(log_level)

        # Добавление обработчиков (только если их нет)
        if not logger.handlers:
            self._add_handlers(logger, name)

        logger.propagate = False
        return logger

    def _get_level(self, level: str | None = None) -> int:
        """
        Получение числового уровня логирования.

        Args:
            level: Строковое представление уровня

        Returns:
            int: Числовой уровень логирования
        """
        if level is None:
            level = self._default_level
        return getattr(logging, level.upper(), logging.INFO)

    def _add_handlers(self, logger: logging.Logger, name: str) -> None:
        """
        Добавление обработчиков в логгер.

        Args:
            logger: Логгер
            name: Имя логгера (используется для имени файла)
        """
        # Форматтеры
        file_formatter, console_formatter = self._create_formatters()

        # Файловый обработчик с ротацией
        file_handler = self._create_file_handler(name, file_formatter)
        logger.addHandler(file_handler)

        # Консольный обработчик
        console_handler = self._create_console_handler(console_formatter)
        logger.addHandler(console_handler)

    @staticmethod
    def _create_formatters() -> tuple[logging.Formatter, logging.Formatter]:
        """
        Создание форматеров для файлового и консольного вывода.

        Returns:
            tuple[logging.Formatter, logging.Formatter]: (file_formatter, console_formatter)
        """
        file_formatter = logging.Formatter(
            "%(asctime)s | %(levelname)-7s | %(name)-5s | %(message)s",
            datefmt="%Y-%m-%d %H:%M:%S",
        )

        console_formatter = ConsoleFormatter(
            "%(asctime)s | %(levelname)s | %(name)-5s | %(message)s",
            datefmt="%Y-%m-%d %H:%M:%S",
        )

        return file_formatter, console_formatter

    def _create_file_handler(self, name: str, formatter: logging.Formatter) -> RotatingFileHandler:
        """
        Создание файлового обработчика с ротацией.

        Args:
            name: Имя логгера (используется для имени файла)
            formatter: Форматтер

        Returns:
            RotatingFileHandler: Настроенный обработчик
        """
        log_file = self.log_dir / f"{name.strip()}.log"

        handler = RotatingFileHandler(
            filename=log_file,
            maxBytes=self._max_bytes,
            backupCount=self._backup_count,
            encoding="utf-8",
        )
        handler.setFormatter(formatter)
        return handler

    @staticmethod
    def _create_console_handler(formatter: logging.Formatter) -> logging.StreamHandler:
        """
        Создание консольного обработчика.

        Args:
            formatter: Форматтер

        Returns:
            logging.StreamHandler: Настроенный обработчик
        """
        handler = logging.StreamHandler(sys.stdout)
        handler.setFormatter(formatter)
        return handler


# ==================== РАСШИРЕННЫЙ ЛОГГЕР ====================


class ExtendedLogger:
    """
    Расширенный логгер с дополнительными методами для структурированного логирования.

    Реализует LoggerProtocol.

    Особенности:
    - Поддержка подавления логов через contextvars
    - Структурированное логирование HTTP-запросов
    - Логирование Telegram-событий
    - Детальное логирование ошибок с контекстом
    """

    def __init__(self, logger: logging.Logger, component: str = "app"):
        """
        Инициализация расширенного логгера.

        Args:
            logger: Базовый логгер
            component: Имя компонента (для контекста)
        """
        self._logger = logger
        self._component = component

    # ==================== БАЗОВЫЕ МЕТОДЫ ЛОГИРОВАНИЯ ====================

    def debug(self, msg: str, *args: Any, **kwargs: Any) -> None:
        """
        Логирование на уровне DEBUG с проверкой подавления.

        Args:
            msg: Сообщение
            *args: Аргументы для форматирования
            **kwargs: Дополнительные параметры
        """
        if self._is_debug_suppressed():
            return
        self._logger.debug(msg, *args, **kwargs)

    def info(self, msg: str, *args: Any, **kwargs: Any) -> None:
        """
        Логирование на уровне INFO с проверкой подавления.

        Args:
            msg: Сообщение
            *args: Аргументы для форматирования
            **kwargs: Дополнительные параметры
        """
        if self._is_all_logs_suppressed():
            return
        self._logger.info(msg, *args, **kwargs)

    def warning(self, msg: str, *args: Any, **kwargs: Any) -> None:
        """
        Логирование на уровне WARNING с проверкой подавления.

        Args:
            msg: Сообщение
            *args: Аргументы для форматирования
            **kwargs: Дополнительные параметры
        """
        if self._is_all_logs_suppressed():
            return
        self._logger.warning(msg, *args, **kwargs)

    def error(self, msg: str, *args: Any, **kwargs: Any) -> None:
        """
        Логирование на уровне ERROR (всегда выводится).

        Args:
            msg: Сообщение
            *args: Аргументы для форматирования
            **kwargs: Дополнительные параметры
        """
        self._logger.error(msg, *args, **kwargs)

    def critical(self, msg: str, *args: Any, **kwargs: Any) -> None:
        """
        Логирование на уровне CRITICAL (всегда выводится).

        Args:
            msg: Сообщение
            *args: Аргументы для форматирования
            **kwargs: Дополнительные параметры
        """
        self._logger.critical(msg, *args, **kwargs)

    def log(self, level: int, msg: str, *args: Any, **kwargs: Any) -> None:
        """
        Общий метод логирования с проверкой подавления.

        Args:
            level: Уровень логирования
            msg: Сообщение
            *args: Аргументы для форматирования
            **kwargs: Дополнительные параметры
        """
        if self._is_all_logs_suppressed() and level <= logging.WARNING:
            return
        self._logger.log(level, msg, *args, **kwargs)

    def exception(self, msg: str, *args: Any, **kwargs: Any) -> None:
        """
        Логирование исключения (всегда выводится с traceback).

        Args:
            msg: Сообщение
            *args: Аргументы для форматирования
            **kwargs: Дополнительные параметры
        """
        self._logger.exception(msg, *args, **kwargs)

    # ==================== СТРУКТУРИРОВАННОЕ ЛОГИРОВАНИЕ ====================

    def log_request(
        self,
        method: str,
        path: str,
        status_code: int | None = None,
        duration_ms: float | None = None,
        client_ip: str | None = None,
        **kwargs: Any,
    ) -> None:
        """
        Логирование HTTP-запроса.

        Args:
            method: HTTP метод (GET, POST, ...)
            path: Путь запроса
            status_code: Код ответа
            duration_ms: Время выполнения в миллисекундах
            client_ip: IP клиента
            **kwargs: Дополнительные параметры
        """
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
        """
        Логирование Telegram-события.

        Args:
            event_type: Тип события (command, message, callback, ...)
            user_id: ID пользователя
            chat_id: ID чата
            **kwargs: Дополнительные параметры
        """
        message = f"Telegram event: {event_type}"
        if user_id is not None:
            message += f" user={user_id}"
        if chat_id is not None:
            message += f" chat={chat_id}"

        self._logger.debug(message, extra=kwargs)

    def log_error(
        self,
        error: Exception,
        message: str = "Error occurred",
        **kwargs: Any,
    ) -> None:
        """
        Логирование ошибки с полным контекстом и стеком.

        Args:
            error: Исключение
            message: Сообщение перед ошибкой
            **kwargs: Дополнительные параметры (extra, ...)
        """
        import traceback

        # Получение полного стека
        tb_str = traceback.format_exc()

        extra = kwargs.get("extra", {})
        if isinstance(extra, dict):
            extra.update(self._extract_error_context(error, tb_str))

        self._logger.error(f"{message}: {error}", exc_info=True, extra=extra)

    def log_startup(self, message: str, **kwargs: Any) -> None:
        """
        Логирование события запуска.

        Args:
            message: Сообщение
            **kwargs: Дополнительные параметры
        """
        self._logger.info(f"🚀 {message}", extra=kwargs)

    def log_shutdown(self, message: str, **kwargs: Any) -> None:
        """
        Логирование события остановки.

        Args:
            message: Сообщение
            **kwargs: Дополнительные параметры
        """
        self._logger.info(f"⛔ {message}", extra=kwargs)

    def log_success(self, message: str, **kwargs: Any) -> None:
        """
        Логирование успешной операции.

        Args:
            message: Сообщение
            **kwargs: Дополнительные параметры
        """
        self._logger.info(f"✅ {message}", extra=kwargs)

    def log_warning(self, message: str, **kwargs: Any) -> None:
        """
        Логирование предупреждения с эмодзи.

        Args:
            message: Сообщение
            **kwargs: Дополнительные параметры
        """
        self._logger.warning(f"⚠️ {message}", extra=kwargs)

    def log_error_emoji(self, message: str, **kwargs: Any) -> None:
        """
        Логирование ошибки с эмодзи.

        Args:
            message: Сообщение
            **kwargs: Дополнительные параметры
        """
        self._logger.error(f"❌ {message}", extra=kwargs)

    # ==================== ВСПОМОГАТЕЛЬНЫЕ МЕТОДЫ ====================

    @staticmethod
    def _extract_error_context(error: Exception, tb_str: str) -> dict[str, Any]:
        """
        Извлечение контекста ошибки.

        Args:
            error: Исключение
            tb_str: Строка traceback

        Returns:
            dict[str, Any]: Словарь с контекстом ошибки
        """
        context = {
            "error_type": type(error).__name__,
            "error_message": str(error),
            "traceback": tb_str,
        }

        # Добавление информации о месте ошибки
        tb = error.__traceback__
        if tb:
            while tb.tb_next:
                tb = tb.tb_next
            context.update(
                {
                    "error_file": tb.tb_frame.f_code.co_filename,
                    "error_line": str(tb.tb_lineno),
                    "error_function": tb.tb_frame.f_code.co_name,
                }
            )

        return context

    @staticmethod
    def _is_debug_suppressed() -> bool:
        """
        Проверка, подавлены ли debug-логи в текущем контексте.

        Returns:
            bool: True если debug-логи подавлены
        """
        try:
            from app.utils.decorators import is_debug_suppressed

            return is_debug_suppressed()
        except ImportError:
            return False

    @staticmethod
    def _is_all_logs_suppressed() -> bool:
        """
        Проверка, подавлены ли все логи в текущем контексте.

        Returns:
            bool: True если все логи подавлены
        """
        try:
            from app.utils.decorators import is_all_logs_suppressed

            return is_all_logs_suppressed()
        except ImportError:
            return False

    # ==================== МЕТОДЫ ДЛЯ СОВМЕСТИМОСТИ ====================

    @property
    def component(self) -> str:
        """Имя компонента логгера."""
        return self._component

    @property
    def logger(self) -> logging.Logger:
        """Базовый логгер."""
        return self._logger


# ==================== СОЗДАНИЕ ЭКЗЕМПЛЯРОВ ====================

# Настройка логгеров
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
