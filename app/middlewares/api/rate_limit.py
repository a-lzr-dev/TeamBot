"""
Middleware для ограничения частоты запросов к API.

Назначение:
    Защита API от чрезмерного количества запросов путём ограничения
    частоты запросов от одного клиента (IP адреса).

Основные функции:
    1. Ограничение количества запросов от одного IP адреса
    2. Настраиваемый лимит и период через конфигурацию
    3. Исключение публичных путей из ограничений
    4. Возврат заголовков с информацией о лимите (X-RateLimit-*)
    5. Логирование превышения лимита
    6. Поддержка настраиваемого компонента

Технические особенности:
    - Интеграция с FastAPI/Starlette через BaseHTTPMiddleware
    - Использование rate_limit_manager для управления лимитами
    - Ключ для ограничения: IP + метод + путь
    - Возврат HTTP 429 с информацией о лимите
    - Заголовки X-RateLimit-Limit, X-RateLimit-Remaining, X-RateLimit-Reset

Безопасность:
    - Защита от DDoS и брутфорс атак
    - Индивидуальные лимиты для каждого клиента
    - Исключение публичных эндпоинтов для доступности

Архитектура:
    - Реализует интерфейс BaseHTTPMiddleware от Starlette
    - Интегрируется с rate_limit_manager
    - Использует RateLimitConfig и RateLimitScope
"""

from collections.abc import Awaitable, Callable
from typing import Any

from fastapi import Request, Response
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.types import ASGIApp

from ...config import settings
from ...core import RateLimitConfig, RateLimitScope, rate_limit_manager
from ...logger import api_logger

# ============================================================
# 1. КЛАСС MIDDLEWARE ДЛЯ ОГРАНИЧЕНИЯ ЗАПРОСОВ
# ============================================================


class APIRateLimitMiddleware(BaseHTTPMiddleware):
    """
    Middleware для ограничения частоты запросов к API.

    Ограничивает количество запросов от одного IP адреса за определённый
    период времени. Возвращает HTTP 429 при превышении лимита.

    Пример использования в FastAPI:
        app.add_middleware(
            APIRateLimitMiddleware,
            limit=100,
            period=60,
            exclude_paths=["/api/v1/health"],
            component="api"
        )

    Attributes:
        component (str): Имя компонента для логирования
        _limiter (RateLimitManager): Менеджер ограничений
    """

    def __init__(
        self,
        app: ASGIApp,
        limit: int | None = None,
        period: int | None = None,
        exclude_paths: list[str] | None = None,
        component: str = "api",
    ) -> None:
        """
        Инициализация middleware ограничения запросов.

        Args:
            app: ASGI приложение
            limit: Максимальное количество запросов за период (по умолчанию из настроек)
            period: Период в секундах (по умолчанию из настроек)
            exclude_paths: Список путей, исключённых из ограничений
            component: Имя компонента для логирования
        """
        super().__init__(app)
        self.component = component

        # Получение значений из настроек с явным приведением типов
        settings_limit = getattr(settings, "API_RATE_LIMIT", 100)
        settings_period = getattr(settings, "API_RATE_PERIOD", 60)

        default_limit = self._ensure_int(settings_limit, 100)
        default_period = self._ensure_int(settings_period, 60)

        # Регистрируем API scope, если ещё не зарегистрирован
        config = RateLimitConfig(
            limit=limit if limit is not None else default_limit,
            period=period if period is not None else default_period,
            exclude_paths=exclude_paths
            or [
                "/api/v1/health",
                "/api/v1/ping",
                "/api/docs",
                "/api/redoc",
                "/api/openapi.json",
                "/",
                "/health",
                "/version",
            ],
        )

        rate_limit_manager.register_scope(RateLimitScope.API, config)

        # Сохраняем ссылку для быстрого доступа
        self._limiter = rate_limit_manager

    # ============================================================
    # 1.1. ВСПОМОГАТЕЛЬНЫЙ МЕТОД
    # ============================================================

    @staticmethod
    def _ensure_int(value: Any, default: int) -> int:
        """
        Безопасное приведение значения к int.

        Args:
            value: Значение для приведения
            default: Значение по умолчанию

        Returns:
            int: Приведённое значение или default
        """
        if value is None:
            return default
        try:
            return int(value)
        except (ValueError, TypeError):
            return default

    # ============================================================
    # 1.2. ОСНОВНОЙ МЕТОД ОБРАБОТКИ ЗАПРОСА
    # ============================================================

    async def dispatch(self, request: Request, call_next: Callable[[Request], Awaitable[Response]]) -> Response:
        """
        Основной метод обработки запроса с проверкой лимита.

        Args:
            request: Объект запроса FastAPI/Starlette
            call_next: Функция для передачи запроса дальше по цепочке

        Returns:
            Response: Ответ от приложения или ошибка 429

        Flow:
            1. Проверка исключённых путей
            2. Формирование ключа (IP + метод + путь)
            3. Проверка лимита через rate_limit_manager
            4. Если лимит превышен — возврат 429 с заголовками
            5. Иначе — передача запроса дальше с добавлением заголовков
        """
        # 1. Проверка, нужно ли пропустить
        if self._is_excluded(request.url.path):
            return await call_next(request)

        # 2. Получение ключа (IP + метод + путь)
        client_ip = request.client.host if request.client else "unknown"
        key = f"{client_ip}:{request.method}:{request.url.path}"

        # 3. Контекст для проверки исключений
        context = {"path": request.url.path, "method": request.method, "client_ip": client_ip}

        # 4. Проверка лимита
        if not rate_limit_manager.is_allowed(RateLimitScope.API, key, context=context):
            api_logger.warning(
                f"Rate limit exceeded for {client_ip} on {request.url.path}",
                extra={"client_ip": client_ip, "path": request.url.path, "method": request.method},
            )

            remaining = rate_limit_manager.get_remaining(RateLimitScope.API, key)
            reset_time = rate_limit_manager.get_reset_time(RateLimitScope.API, key)

            # 5. Возврат ошибки 429 с заголовками
            return JSONResponse(
                status_code=429,
                headers={
                    "X-RateLimit-Limit": str(self._get_limit()),
                    "X-RateLimit-Remaining": str(remaining),
                    "X-RateLimit-Reset": str(int(reset_time or 0)),
                    "Retry-After": str(self._get_period()),
                },
                content={
                    "error": "RateLimitExceeded",
                    "message": f"Too many requests. Limit: {self._get_limit()} per {self._get_period()} seconds.",
                    "retry_after": self._get_period(),
                    "remaining": remaining,
                    "timestamp": self._get_timestamp(),
                },
            )

        # 6. Добавление информации о лимите в ответ
        response = await call_next(request)
        response.headers["X-RateLimit-Limit"] = str(self._get_limit())
        response.headers["X-RateLimit-Remaining"] = str(rate_limit_manager.get_remaining(RateLimitScope.API, key))

        return response

    # ============================================================
    # 1.3. ВСПОМОГАТЕЛЬНЫЕ МЕТОДЫ ДЛЯ КОНФИГУРАЦИИ
    # ============================================================

    @staticmethod
    def _is_excluded(path: str) -> bool:
        """
        Проверка, исключён ли путь из rate limiting.

        Args:
            path: Путь запроса

        Returns:
            bool: True если путь исключён
        """
        config = rate_limit_manager.get_config(RateLimitScope.API)
        if not config:
            return False
        return any(path.startswith(excluded) for excluded in config.exclude_paths)

    @staticmethod
    def _get_limit() -> int:
        """
        Получение текущего лимита.

        Returns:
            int: Лимит запросов за период
        """
        config = rate_limit_manager.get_config(RateLimitScope.API)
        return config.limit if config else 100

    @staticmethod
    def _get_period() -> int:
        """
        Получение текущего периода.

        Returns:
            int: Период в секундах
        """
        config = rate_limit_manager.get_config(RateLimitScope.API)
        return config.period if config else 60

    @staticmethod
    def _get_timestamp() -> str:
        """
        Получение текущего timestamp.

        Returns:
            str: Текущее время в ISO формате
        """
        from datetime import datetime

        return datetime.now().isoformat() + "Z"


__all__ = ["APIRateLimitMiddleware"]
