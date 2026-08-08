from collections.abc import Awaitable, Callable
from typing import Any

from fastapi import Request, Response
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.types import ASGIApp

from ...config import settings
from ...core import RateLimitConfig, RateLimitScope, rate_limit_manager
from ...logger import api_logger


class APIRateLimitMiddleware(BaseHTTPMiddleware):
    """Middleware для ограничения частоты запросов к API"""

    def __init__(
        self,
        app: ASGIApp,
        limit: int | None = None,
        period: int | None = None,
        exclude_paths: list[str] | None = None,
        component: str = "api",
    ) -> None:
        super().__init__(app)
        self.component = component

        # Получение значений из настроек с явным приведением типов
        settings_limit = getattr(settings, "API_RATE_LIMIT", 100)
        settings_period = getattr(settings, "API_RATE_PERIOD", 60)

        # Приведение к int с проверкой типа
        default_limit = self._ensure_int(settings_limit, 100)
        default_period = self._ensure_int(settings_period, 60)

        # Регистрируем API scope, если еще не зарегистрирован
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

    @staticmethod
    def _ensure_int(value: Any, default: int) -> int:
        """Безопасное приведение значения к int"""
        if value is None:
            return default
        try:
            return int(value)
        except (ValueError, TypeError):
            return default

    async def dispatch(self, request: Request, call_next: Callable[[Request], Awaitable[Response]]) -> Response:
        # Проверка, нужно ли пропустить
        if self._is_excluded(request.url.path):
            return await call_next(request)

        # Получение ключа (IP + метод + путь)
        client_ip = request.client.host if request.client else "unknown"
        key = f"{client_ip}:{request.method}:{request.url.path}"

        # Контекст для проверки исключений
        context = {"path": request.url.path, "method": request.method, "client_ip": client_ip}

        # Проверка лимита
        if not rate_limit_manager.is_allowed(RateLimitScope.API, key, context=context):
            api_logger.warning(
                f"Rate limit exceeded for {client_ip} on {request.url.path}",
                extra={"client_ip": client_ip, "path": request.url.path, "method": request.method},
            )

            remaining = rate_limit_manager.get_remaining(RateLimitScope.API, key)
            reset_time = rate_limit_manager.get_reset_time(RateLimitScope.API, key)

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

        # Добавление информации о лимите в ответ
        response = await call_next(request)
        response.headers["X-RateLimit-Limit"] = str(self._get_limit())
        response.headers["X-RateLimit-Remaining"] = str(rate_limit_manager.get_remaining(RateLimitScope.API, key))

        return response

    @staticmethod
    def _is_excluded(path: str) -> bool:
        """Проверка, исключен ли путь из rate limiting"""
        config = rate_limit_manager.get_config(RateLimitScope.API)
        if not config:
            return False
        return any(path.startswith(excluded) for excluded in config.exclude_paths)

    @staticmethod
    def _get_limit() -> int:
        """Получение текущего лимита"""
        config = rate_limit_manager.get_config(RateLimitScope.API)
        return config.limit if config else 100

    @staticmethod
    def _get_period() -> int:
        """Получение текущего периода"""
        config = rate_limit_manager.get_config(RateLimitScope.API)
        return config.period if config else 60

    @staticmethod
    def _get_timestamp() -> str:
        """Получение текущего timestamp"""
        from datetime import datetime

        return datetime.now().isoformat() + "Z"


__all__ = ["APIRateLimitMiddleware"]
