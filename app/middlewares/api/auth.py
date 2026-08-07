from collections.abc import Awaitable, Callable

from fastapi import Request, Response
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware

from ...config import settings
from ...logger import api_logger


class AuthMiddleware(BaseHTTPMiddleware):
    """Middleware для аутентификации запросов"""

    # Пути, которые не требуют аутентификации
    PUBLIC_PATHS = [
        "/api/v1/health",
        "/api/v1/ping",
        "/api/v1/ready",
        "/api/docs",
        "/api/redoc",
        "/api/openapi.json",
        "/",
        "/health",
        "/version",
    ]

    async def dispatch(self, request: Request, call_next: Callable[[Request], Awaitable[Response]]) -> Response:
        # Проверка, нужна ли аутентификация
        if self._is_public_path(request.url.path):
            return await call_next(request)

        # Проверка API ключа
        api_key = request.headers.get("X-API-Key")

        if not api_key:
            api_logger.warning(f"⚠️ Missing API key for {request.url.path}")
            return JSONResponse(
                status_code=401,
                content={
                    "error": "Unauthorized",
                    "message": "Missing API key. Please provide X-API-Key header.",
                    "path": request.url.path,
                },
            )

        # Проверка валидности API ключа
        if not self._is_valid_api_key(api_key):
            api_logger.warning(f"⚠️ Invalid API key for {request.url.path}")
            return JSONResponse(
                status_code=403, content={"error": "Forbidden", "message": "Invalid API key.", "path": request.url.path}
            )

        # Добавление информации о пользователе в request
        request.state.user = {"api_key": api_key, "role": "admin"}

        return await call_next(request)

    def _is_public_path(self, path: str) -> bool:
        """Проверка, является ли путь публичным"""
        return any(path.startswith(public_path) for public_path in self.PUBLIC_PATHS)

    @staticmethod
    def _is_valid_api_key(api_key: str) -> bool:
        """Проверка валидности API ключа"""
        valid_keys = getattr(settings, "API_KEYS", [])
        if not valid_keys:
            # Если ключи не настроены, разрешаем все (только для разработки)
            return True
        return api_key in valid_keys


__all__ = [
    "AuthMiddleware",
]
