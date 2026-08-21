"""
Централизованный модуль для всех декораторов приложения.

Содержит:
1. Контекстные переменные для управления логами
2. Декораторы для управления логами (suppress_debug_logs, suppress_all_logs)
3. Декораторы для обработки ошибок (log_exceptions, handle_exception)
4. Декораторы для повторных попыток (retry_on_failure)
5. Декораторы для кеширования (cached_result)
6. Комбинированные декораторы (silent_operation, with_retry_and_log, silent_retry, robust_operation)
"""

import asyncio
import contextvars
import functools
import logging
import time
from collections.abc import Callable
from typing import Any, Protocol

# ============================================================
# 1. ПРОТОКОЛ ДЛЯ ЛОГГЕРА
# ============================================================


class LoggerProtocol(Protocol):
    """
    Протокол для объектов, поддерживающих методы логирования.

    Используется для того, чтобы декораторы могли принимать как
    стандартный logging.Logger, так и ExtendedLogger из проекта.
    """

    def debug(self, msg: str, *args: Any, **kwargs: Any) -> None: ...
    def info(self, msg: str, *args: Any, **kwargs: Any) -> None: ...
    def warning(self, msg: str, *args: Any, **kwargs: Any) -> None: ...
    def error(self, msg: str, *args: Any, **kwargs: Any) -> None: ...
    def critical(self, msg: str, *args: Any, **kwargs: Any) -> None: ...
    def log(self, level: int, msg: str, *args: Any, **kwargs: Any) -> None: ...
    def exception(self, msg: str, *args: Any, **kwargs: Any) -> None: ...


# ============================================================
# 2. КОНТЕКСТНЫЕ ПЕРЕМЕННЫЕ ДЛЯ УПРАВЛЕНИЯ ЛОГАМИ
# ============================================================

# Контекстная переменная для подавления debug-логов
_suppress_debug = contextvars.ContextVar("suppress_debug", default=False)

# Контекстная переменная для подавления ВСЕХ логов (кроме critical)
_suppress_all_logs = contextvars.ContextVar("suppress_all_logs", default=False)

# Контекстная переменная для измерения времени выполнения
_timer_start = contextvars.ContextVar("timer_start", default=None)


def is_debug_suppressed() -> bool:
    """
    Проверка, подавлены ли debug-логи в текущем контексте.

    Returns:
        bool: True если debug-логи подавлены
    """
    return _suppress_debug.get()


def is_all_logs_suppressed() -> bool:
    """
    Проверка, подавлены ли все логи в текущем контексте.

    Returns:
        bool: True если все логи подавлены
    """
    return _suppress_all_logs.get()


# ============================================================
# 3. ДЕКОРАТОРЫ ДЛЯ УПРАВЛЕНИЯ ЛОГАМИ
# ============================================================


def suppress_debug_logs(func: Callable) -> Callable:
    """
    Декоратор, который отключает debug-логи в текущем контексте выполнения.
    Другие параллельные задачи не затрагиваются.

    Использование:
        @suppress_debug_logs
        async def sync_avanpost():
            db_logger.debug("Это не выведется")  # ← подавлено
            await some_internal()  # ← здесь тоже подавлено

    Вложенные вызовы:
        @suppress_debug_logs
        async def outer():
            db_logger.debug("Не выведется")  # ← подавлено
            await inner()  # ← здесь тоже подавлено

        async def inner():
            db_logger.debug("Тоже не выведется")  # ← подавлено (контекст сохраняется)

    Args:
        func: Декорируемая функция

    Returns:
        Callable: Обернутая функция
    """

    @functools.wraps(func)
    async def async_wrapper(*args: Any, **kwargs: Any) -> Any:
        token = _suppress_debug.set(True)
        try:
            return await func(*args, **kwargs)
        finally:
            _suppress_debug.reset(token)

    @functools.wraps(func)
    def sync_wrapper(*args: Any, **kwargs: Any) -> Any:
        token = _suppress_debug.set(True)
        try:
            return func(*args, **kwargs)
        finally:
            _suppress_debug.reset(token)

    return async_wrapper if asyncio.iscoroutinefunction(func) else sync_wrapper


def suppress_all_logs(func: Callable) -> Callable:
    """
    Декоратор, который отключает ВСЕ логи (кроме critical) в текущем контексте.

    Использование:
        @suppress_all_logs
        async def heavy_operation():
            db_logger.info("Не выведется")  # ← подавлено
            app_logger.warning("Тоже не выведется")  # ← подавлено

    Args:
        func: Декорируемая функция

    Returns:
        Callable: Обернутая функция
    """

    @functools.wraps(func)
    async def async_wrapper(*args: Any, **kwargs: Any) -> Any:
        token = _suppress_all_logs.set(True)
        try:
            return await func(*args, **kwargs)
        finally:
            _suppress_all_logs.reset(token)

    @functools.wraps(func)
    def sync_wrapper(*args: Any, **kwargs: Any) -> Any:
        token = _suppress_all_logs.set(True)
        try:
            return func(*args, **kwargs)
        finally:
            _suppress_all_logs.reset(token)

    return async_wrapper if asyncio.iscoroutinefunction(func) else sync_wrapper


def log_execution_time(
    logger: logging.Logger | LoggerProtocol | Any | None = None,
    level: int = logging.DEBUG,
    message: str = "Executed {func_name} in {duration:.2f}ms",
) -> Callable:
    """
    Декоратор для замера времени выполнения функции.

    Args:
        logger: Логгер для вывода (принимает logging.Logger, ExtendedLogger или любой объект с методами логирования)
        level: Уровень логирования
        message: Шаблон сообщения (доступны: func_name, duration, args, kwargs)

    Использование:
        @log_execution_time()
        async def my_function():
            await asyncio.sleep(1)
        # → "Executed my_function in 1002.34ms"

    Returns:
        Callable: Декоратор
    """
    from app.logger import app_logger

    # Определение целевого логгера
    target_logger = app_logger if logger is None else logger

    def decorator(func: Callable) -> Callable:
        @functools.wraps(func)
        async def async_wrapper(*args: Any, **kwargs: Any) -> Any:
            start = time.perf_counter()
            try:
                return await func(*args, **kwargs)
            finally:
                duration = (time.perf_counter() - start) * 1000
                formatted = message.format(
                    func_name=func.__name__,
                    duration=duration,
                    args=args,
                    kwargs=kwargs,
                )
                # Безопасное логирование
                if hasattr(target_logger, "log"):
                    target_logger.log(level, formatted)
                else:
                    # Fallback для объектов без метода log
                    if hasattr(target_logger, "debug"):
                        target_logger.debug(formatted)

        @functools.wraps(func)
        def sync_wrapper(*args: Any, **kwargs: Any) -> Any:
            start = time.perf_counter()
            try:
                return func(*args, **kwargs)
            finally:
                duration = (time.perf_counter() - start) * 1000
                formatted = message.format(
                    func_name=func.__name__,
                    duration=duration,
                    args=args,
                    kwargs=kwargs,
                )
                if hasattr(target_logger, "log"):
                    target_logger.log(level, formatted)
                else:
                    if hasattr(target_logger, "debug"):
                        target_logger.debug(formatted)

        return async_wrapper if asyncio.iscoroutinefunction(func) else sync_wrapper

    return decorator


# ============================================================
# 4. ДЕКОРАТОРЫ ДЛЯ ОБРАБОТКИ ОШИБОК
# ============================================================


def log_exceptions(
    logger: logging.Logger | LoggerProtocol | Any | None = None,
    log_level: str = "error",
    reraise: bool = True,
) -> Callable:
    """
    Декоратор для логирования исключений в асинхронных/синхронных функциях.

    Поддерживает:
    - Стандартный logging.Logger
    - ExtendedLogger из проекта
    - Любой объект с методами логирования (debug, info, warning, error, critical)

    Args:
        logger: Логгер для вывода (по умолчанию app_logger)
        log_level: Уровень логирования (debug, info, warning, error, critical)
        reraise: Пробрасывать исключение дальше после логирования (по умолчанию True)

    Использование:
        @log_exceptions()
        async def my_function():
            raise ValueError("Something went wrong")
        # → Логирует ошибку и пробрасывает её дальше

        @log_exceptions(reraise=False)
        async def safe_function():
            raise ValueError("Something went wrong")
        # → Логирует ошибку, но не пробрасывает (возвращает None)

        @log_exceptions(api_logger)  # ExtendedLogger
        async def api_handler():
            ...

        @log_exceptions(logging.getLogger("custom"))  # logging.Logger
        async def custom_handler():
            ...

    Особенности:
        - asyncio.CancelledError логируется на уровне DEBUG и пробрасывается
        - Все остальные исключения логируются на указанном уровне
        - В лог добавляется имя функции и traceback

    Returns:
        Callable: Декоратор
    """
    from app.logger import app_logger

    # Определение целевого логгера
    target_logger = app_logger if logger is None else logger

    def decorator(func: Callable) -> Callable:
        @functools.wraps(func)
        async def async_wrapper(*args: Any, **kwargs: Any) -> Any:
            try:
                return await func(*args, **kwargs)
            except asyncio.CancelledError:
                # CancelledError логируем на уровне DEBUG
                if hasattr(target_logger, "debug"):
                    target_logger.debug(f"Task {func.__name__} was cancelled")
                raise
            except Exception as e:
                # Получаем метод логирования
                log_method = _get_log_method(target_logger, log_level)

                # Логируем ошибку с traceback
                log_method(f"Exception in {func.__name__}: {e}", exc_info=True)

                if reraise:
                    raise
                return None

        @functools.wraps(func)
        def sync_wrapper(*args: Any, **kwargs: Any) -> Any:
            try:
                return func(*args, **kwargs)
            except Exception as e:
                log_method = _get_log_method(target_logger, log_level)
                log_method(f"Exception in {func.__name__}: {e}", exc_info=True)

                if reraise:
                    raise
                return None

        return async_wrapper if asyncio.iscoroutinefunction(func) else sync_wrapper

    return decorator


def _get_log_method(logger: Any, log_level: str) -> Callable[..., None]:
    """
    Безопасное получение метода логирования из объекта.
    """
    # Пробуем получить метод с указанным уровнем
    if hasattr(logger, log_level):
        method = getattr(logger, log_level)
        if callable(method):
            return method  # type: ignore[no-any-return]

    # Если нет - пробуем error
    if hasattr(logger, "error"):
        method = logger.error
        if callable(method):
            return method  # type: ignore[no-any-return]

    # Если ничего нет - используем стандартный логгер
    return logging.getLogger().error


async def handle_exception(
    exception: Exception,
    logger: logging.Logger | LoggerProtocol | Any | None = None,
    component: str = "app",
) -> None:
    """
    Глобальный обработчик исключений с категоризацией.

    Args:
        exception: Исключение для обработки
        logger: Логгер для вывода (по умолчанию app_logger)
        component: Компонент, в котором произошла ошибка (для контекста)

    Использование:
        try:
            await risky_operation()
        except Exception as e:
            await handle_exception(e, component="api")
    """
    from app.exceptions import DatabaseError, TelegramError, ValidationError
    from app.logger import app_logger

    target_logger = app_logger if logger is None else logger

    if isinstance(exception, DatabaseError):
        if hasattr(target_logger, "error"):
            target_logger.error(f"Database error in {component}: {exception}")
    elif isinstance(exception, TelegramError):
        if hasattr(target_logger, "error"):
            target_logger.error(f"Telegram error in {component}: {exception}")
    elif isinstance(exception, ValidationError):
        if hasattr(target_logger, "warning"):
            target_logger.warning(f"Validation error in {component}: {exception}")
    else:
        if hasattr(target_logger, "critical"):
            target_logger.critical(f"Unexpected error in {component}: {exception}", exc_info=True)


# ============================================================
# 5. ДЕКОРАТОРЫ ДЛЯ ПОВТОРНЫХ ПОПЫТОК
# ============================================================


def retry_on_failure(
    attempts: int = 3,
    delay: float = 1.0,
    backoff: float = 2.0,
    exceptions: tuple = (Exception,),
    logger: logging.Logger | LoggerProtocol | Any | None = None,
) -> Callable:
    """
    Декоратор для повторных попыток при ошибках.

    Args:
        attempts: Количество попыток
        delay: Начальная задержка между попытками (сек)
        backoff: Множитель для задержки (экспоненциальная задержка)
        exceptions: Кортеж исключений, при которых нужно повторять
        logger: Логгер для вывода (по умолчанию app_logger)

    Использование:
        @retry_on_failure(attempts=3, delay=1.0)
        async def unstable_operation():
            ...

    Returns:
        Callable: Декоратор
    """
    from app.logger import app_logger

    target_logger = app_logger if logger is None else logger

    def decorator(func: Callable) -> Callable:
        @functools.wraps(func)
        async def async_wrapper(*args: Any, **kwargs: Any) -> Any:
            last_exception = None
            current_delay = delay

            for attempt in range(1, attempts + 1):
                try:
                    return await func(*args, **kwargs)
                except exceptions as e:
                    last_exception = e
                    if attempt == attempts:
                        log_method = _get_log_method(target_logger, "error")
                        log_method(f"All {attempts} attempts failed for {func.__name__}: {e}")
                        raise

                    log_method = _get_log_method(target_logger, "warning")
                    log_method(
                        f"Attempt {attempt}/{attempts} failed for {func.__name__}: {e}. "
                        f"Retrying in {current_delay:.2f}s..."
                    )
                    await asyncio.sleep(current_delay)
                    current_delay *= backoff

            raise last_exception  # type: ignore[misc]

        @functools.wraps(func)
        def sync_wrapper(*args: Any, **kwargs: Any) -> Any:
            last_exception = None
            current_delay = delay

            for attempt in range(1, attempts + 1):
                try:
                    return func(*args, **kwargs)
                except exceptions as e:
                    last_exception = e
                    if attempt == attempts:
                        log_method = _get_log_method(target_logger, "error")
                        log_method(f"All {attempts} attempts failed for {func.__name__}: {e}")
                        raise

                    log_method = _get_log_method(target_logger, "warning")
                    log_method(
                        f"Attempt {attempt}/{attempts} failed for {func.__name__}: {e}. "
                        f"Retrying in {current_delay:.2f}s..."
                    )
                    time.sleep(current_delay)
                    current_delay *= backoff

            raise last_exception  # type: ignore[misc]

        return async_wrapper if asyncio.iscoroutinefunction(func) else sync_wrapper

    return decorator


# ============================================================
# 6. ДЕКОРАТОРЫ ДЛЯ КЕШИРОВАНИЯ
# ============================================================


def cached_result(ttl: int | None = None) -> Callable:
    """
    Простой декоратор для кеширования результата функции.

    Args:
        ttl: Время жизни кеша в секундах (None = бесконечно)

    Использование:
        @cached_result(ttl=60)
        async def get_expensive_data():
            ...

    Returns:
        Callable: Декоратор
    """
    cache: dict = {}

    def decorator(func: Callable) -> Callable:
        @functools.wraps(func)
        async def async_wrapper(*args: Any, **kwargs: Any) -> Any:
            key = (args, tuple(kwargs.items()))

            if key in cache:
                result, timestamp = cache[key]
                if ttl is None or (time.time() - timestamp) < ttl:
                    return result

            result = await func(*args, **kwargs)
            cache[key] = (result, time.time())
            return result

        @functools.wraps(func)
        def sync_wrapper(*args: Any, **kwargs: Any) -> Any:
            key = (args, tuple(kwargs.items()))

            if key in cache:
                result, timestamp = cache[key]
                if ttl is None or (time.time() - timestamp) < ttl:
                    return result

            result = func(*args, **kwargs)
            cache[key] = (result, time.time())
            return result

        return async_wrapper if asyncio.iscoroutinefunction(func) else sync_wrapper

    return decorator


# ============================================================
# 7. КОМБИНИРОВАННЫЕ ДЕКОРАТОРЫ
# ============================================================


def silent_operation(log_level: str = "debug") -> Callable:
    """
    Комбинированный декоратор для "тихих" операций:
    - Подавляет debug-логи
    - Измеряет время выполнения

    Args:
        log_level: Уровень логирования для результата (debug, info, warning)

    Использование:
        @silent_operation()
        async def sync_data():
            # Все debug-логи внутри подавлены
            # Время выполнения будет записано в лог
            ...

    Returns:
        Callable: Декоратор
    """
    level_map = {
        "debug": logging.DEBUG,
        "info": logging.INFO,
        "warning": logging.WARNING,
        "error": logging.ERROR,
    }
    log_level_int = level_map.get(log_level, logging.DEBUG)

    def decorator(func: Callable) -> Callable:
        # Применение декораторрв в правильном порядке
        decorated = suppress_debug_logs(func)
        decorated = log_execution_time(level=log_level_int)(decorated)
        return decorated

    return decorator


def with_retry_and_log(
    attempts: int = 3,
    delay: float = 1.0,
    backoff: float = 2.0,
    exceptions: tuple = (Exception,),
    logger: logging.Logger | LoggerProtocol | Any | None = None,
    log_level: str = "error",
) -> Callable:
    """
    Комбинированный декоратор: повторяет попытки и логирует финальную ошибку.

    Порядок: retry (внутри) → log_exceptions (снаружи)

    Использование:
        @with_retry_and_log(attempts=3, log_level="error")
        async def fetch_from_api():
            return await http_client.get("https://api.example.com/data")

    Особенности:
        - Делает до attempts попыток при ошибках
        - Логирует только финальную ошибку (после всех неудачных попыток)
        - Поддерживает экспоненциальную задержку между попытками

    Returns:
        Callable: Декоратор
    """

    def decorator(func: Callable) -> Callable:
        # retry_on_failure ВНУТРИ, log_exceptions СНАРУЖИ
        decorated = retry_on_failure(attempts, delay, backoff, exceptions, logger)(func)
        decorated = log_exceptions(logger, log_level, reraise=True)(decorated)
        return decorated  # type: ignore[no-any-return]

    return decorator


def silent_retry(
    attempts: int = 3,
    delay: float = 1.0,
    backoff: float = 2.0,
    exceptions: tuple = (Exception,),
    log_level: str = "warning",
) -> Callable:
    """
    "Тихий" повтор: подавляет debug-логи, логирует только финальную ошибку.

    Комбинация: suppress_debug_logs + with_retry_and_log

    Использование:
        @silent_retry(attempts=3)
        async def sync_data():
            # Все debug-логи внутри подавлены
            # При ошибках делаются повторные попытки
            # Финальная ошибка логируется на уровне WARNING
            ...

    Returns:
        Callable: Декоратор
    """

    def decorator(func: Callable) -> Callable:
        decorated = with_retry_and_log(attempts, delay, backoff, exceptions, log_level=log_level)(func)
        decorated = suppress_debug_logs(decorated)
        return decorated  # type: ignore[no-any-return]

    return decorator


def robust_operation(
    attempts: int = 3,
    delay: float = 1.0,
    backoff: float = 2.0,
    exceptions: tuple = (Exception,),
    log_level: str = "error",
    measure_time: bool = True,
) -> Callable:
    """
    Полный комбинированный декоратор для надежных операций.

    Комбинация:
        - retry_on_failure: повторные попытки при ошибках
        - log_exceptions: логирование финальной ошибки
        - log_execution_time: измерение времени выполнения
        - suppress_debug_logs: подавление debug-логов

    Использование:
        @robust_operation(attempts=5, log_level="error")
        async def critical_sync():
            # До 5 попыток при ошибках
            # Логируется только финальная ошибка
            # Измеряется время выполнения
            # Debug-логи подавлены
            ...

    Returns:
        Callable: Декоратор
    """

    def decorator(func: Callable) -> Callable:
        decorated = with_retry_and_log(attempts, delay, backoff, exceptions, log_level=log_level)(func)

        if measure_time:
            level_map = {
                "debug": logging.DEBUG,
                "info": logging.INFO,
                "warning": logging.WARNING,
                "error": logging.ERROR,
            }
            decorated = log_execution_time(level=level_map.get(log_level, logging.INFO))(decorated)

        decorated = suppress_debug_logs(decorated)
        return decorated  # type: ignore[no-any-return]

    return decorator


# ============================================================
# 8. ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ ДЛЯ ТЕСТИРОВАНИЯ
# ============================================================


def reset_all_contexts() -> None:
    """
    Сброс всех контекстных переменных (для тестов).
    """
    _suppress_debug.set(False)
    _suppress_all_logs.set(False)
    _timer_start.set(None)


__all__ = [
    # Контекстные переменные
    "is_debug_suppressed",
    "is_all_logs_suppressed",
    # Декораторы для логов
    "suppress_debug_logs",
    "suppress_all_logs",
    "log_execution_time",
    "silent_operation",
    # Декораторы для обработки
    "log_exceptions",
    "handle_exception",
    "retry_on_failure",
    # Комбинированные декораторы
    "with_retry_and_log",
    "silent_retry",
    "robust_operation",
    # Декораторы для кеширования
    "cached_result",
    # Вспомогательные
    "reset_all_contexts",
]
