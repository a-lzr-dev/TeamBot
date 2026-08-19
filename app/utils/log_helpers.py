import json
import logging
from typing import Any


class LogHelper:
    """Помощник для безопасного логирования с минимальным оверхедом"""

    __slots__ = ()

    @staticmethod
    def truncate(text: str, max_length: int = 500) -> str:
        """
        Обрезание текста до указанной длины с сохранением начала и конца.

        Args:
            text: Текст для обрезания
            max_length: Максимальная длина (по умолчанию 500)

        Returns:
            str: Обрезанный текст
        """
        if not text:
            return ""
        if len(text) <= max_length:
            return text
        # Показываем начало и конец для длинных строк
        half = max_length // 2
        return f"{text[:half]}... [TRUNCATED] ...{text[-half:]}"

    @staticmethod
    def truncate_error(error: Exception, max_length: int = 200) -> str:
        """
        Обрезание сообщения об ошибке.

        Args:
            error: Ошибка
            max_length: Максимальная длина (по умолчанию 200)

        Returns:
            str: Обрезанное сообщение об ошибке
        """
        return LogHelper.truncate(str(error), max_length)

    @staticmethod
    def truncate_json(data: Any, max_length: int = 500, indent: int = 2) -> str:
        """
        Преобразование данных в JSON и обрезание до указанной длины.

        Args:
            data: Данные для сериализации
            max_length: Максимальная длина JSON (по умолчанию 500)
            indent: Отступ для форматирования (по умолчанию 2)

        Returns:
            str: Обрезанный JSON
        """
        try:
            json_str = json.dumps(data, ensure_ascii=False, default=str, indent=indent)
            return LogHelper.truncate(json_str, max_length)
        except Exception:
            return LogHelper.truncate(str(data), max_length)

    @staticmethod
    def log_batch_error_fast(
        logger: Any,
        operation: str,
        table: str,
        error: Exception,
        batch_size: int | None = None,
    ) -> None:
        """
        Быстрое логирование ошибки пакета (без JSON).

        Args:
            logger: Любой логгер (ExtendedLogger, logging.Logger)
            operation: Название операции (INSERT, UPDATE, DELETE)
            table: Имя таблицы
            error: Ошибка
            batch_size: Размер пакета (опционально)
        """
        error_msg = LogHelper.truncate_error(error, 1000)
        logger.warning(f"⚠️ {operation} failed for batch: {error_msg}")

        if hasattr(logger, "isEnabledFor") and logger.isEnabledFor(logging.DEBUG):
            logger.debug(f"   Table: {table}")
            if batch_size is not None:
                logger.debug(f"   Batch size: {batch_size}")

    @staticmethod
    def log_json_preview(
        logger: Any,
        message: str,
        data: Any,
        max_length: int = 500,
        level: str = "debug",
    ) -> None:
        """
        Логирование JSON с обрезанием.

        Args:
            logger: Любой логгер
            message: Сообщение перед JSON
            data: Данные для JSON
            max_length: Максимальная длина JSON (по умолчанию 500)
            level: Уровень логирования (debug, info, warning, error)
        """
        if not hasattr(logger, "isEnabledFor") or not logger.isEnabledFor(logging.DEBUG):
            return

        json_preview = LogHelper.truncate_json(data, max_length)
        log_method = getattr(logger, level.lower(), logger.debug)
        log_method(f"{message}: {json_preview}")

    @staticmethod
    def log_error(
        logger: Any,
        message: str,
        error: Exception,
        max_length: int = 200,
        level: str = "error",
    ) -> None:
        """
        Логирование ошибки с обрезанием сообщения и ошибки.

        Args:
            logger: Любой логгер
            message: Сообщение перед ошибкой (будет обрезано)
            error: Ошибка
            max_length: Максимальная длина (по умолчанию 200)
            level: Уровень логирования (debug, info, warning, error)
        """
        # Обрезаем и сообщение, и ошибку
        truncated_message = LogHelper.truncate(message, max_length)
        error_msg = LogHelper.truncate_error(error, max_length)
        log_method = getattr(logger, level.lower(), logger.error)
        log_method(f"{truncated_message}: {error_msg}")

    @staticmethod
    def log_warning(
        logger: Any,
        message: str,
        max_length: int = 200,
    ) -> None:
        """
        Логирование предупреждения с обрезанием.

        Args:
            logger: Любой логгер
            message: Сообщение
            max_length: Максимальная длина (по умолчанию 200)
        """
        truncated = LogHelper.truncate(message, max_length)
        logger.warning(truncated)

    @staticmethod
    def log_info(
        logger: Any,
        message: str,
        max_length: int = 500,
    ) -> None:
        """
        Логирование информационного сообщения с обрезанием.

        Args:
            logger: Любой логгер
            message: Сообщение
            max_length: Максимальная длина (по умолчанию 500)
        """
        truncated = LogHelper.truncate(message, max_length)
        logger.info(truncated)

    @staticmethod
    def log_sql_error(
        logger: Any,
        operation: str,
        table: str,
        sql: str,
        error: Exception,
        max_length: int = 1000,
    ) -> None:
        """
        Специализированный метод для логирования SQL ошибок с обрезанным SQL.

        Args:
            logger: Любой логгер
            operation: Название операции (INSERT, UPDATE, DELETE, SELECT)
            table: Имя таблицы
            sql: SQL запрос
            error: Ошибка
            max_length: Максимальная длина SQL (по умолчанию 1000)
        """
        truncated_sql = LogHelper.truncate(sql, max_length)
        error_msg = LogHelper.truncate_error(error, 200)
        logger.error(f"❌ {operation} failed for {table}: {error_msg}")
        logger.error(f"   SQL: {truncated_sql}")


__all__ = [
    "LogHelper",
]
