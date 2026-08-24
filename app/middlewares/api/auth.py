"""
Middleware для аутентификации запросов к API.

Назначение:
    Обеспечивает аутентификацию входящих HTTP запросов через API ключи.
    Защищает эндпоинты API от несанкционированного доступа.

Основные функции:
    1. Проверка наличия API ключа в заголовке X-API-Key
    2. Валидация API ключа по списку из настроек
    3. Пропуск публичных путей (health, docs и т.д.)
    4. Добавление информации о пользователе в request.state

Технические особенности:
    - Интеграция с FastAPI/Starlette через BaseHTTPMiddleware
    - Список публичных путей для исключения из аутентификации
    - Безопасный fallback для разработки (все ключи разрешены)
    - Логирование попыток доступа с неверными ключами

Безопасность:
    - В production необходимо настроить API_KEYS в конфигурации
    - Fallback только для разработки (если API_KEYS не настроены)
    - Заголовок X-API-Key обязателен для защищённых эндпоинтов
    - Логирование предупреждений при неавторизованных попытках

Архитектура:
    - Реализует интерфейс BaseHTTPMiddleware от Starlette
    - Поддерживает асинхронную обработку запросов
    - Интегрируется с настройками приложения через settings
"""

from collections.abc import Awaitable, Callable

from fastapi import Request, Response
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware

from ...config import settings
from ...logger import api_logger

# ============================================================
# 1. КЛАСС MIDDLEWARE ДЛЯ АУТЕНТИФИКАЦИИ
# ============================================================


class AuthMiddleware(BaseHTTPMiddleware):
    """
    Middleware для аутентификации запросов к API.

    Проверяет наличие и валидность API ключа в заголовке X-API-Key.
    Публичные пути (health, docs и т.д.) пропускаются без проверки.

    Attributes:
        PUBLIC_PATHS (list[str]): Список путей, не требующих аутентификации

    Пример использования в FastAPI:
        app.add_middleware(AuthMiddleware)
    """

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

    # ============================================================
    # 1.1. ОСНОВНОЙ МЕТОД ОБРАБОТКИ ЗАПРОСА
    # ============================================================

    async def dispatch(self, request: Request, call_next: Callable[[Request], Awaitable[Response]]) -> Response:
        """
        Основной метод обработки запроса.

        Выполняет проверку аутентификации для всех запросов,
        кроме публичных путей.

        Args:
            request: Объект запроса FastAPI/Starlette
            call_next: Функция для передачи запроса дальше по цепочке

        Returns:
            Response: Ответ от приложения или ошибка аутентификации

        Flow:
            1. Проверка, является ли путь публичным
            2. Проверка наличия API ключа в заголовке
            3. Проверка валидности API ключа
            4. Добавление данных пользователя в request.state
            5. Передача запроса дальше
        """
        # 1. Проверка, нужна ли аутентификация
        if self._is_public_path(request.url.path):
            return await call_next(request)

        # 2. Проверка API ключа
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

        # 3. Проверка валидности API ключа
        if not self._is_valid_api_key(api_key):
            api_logger.warning(f"⚠️ Invalid API key for {request.url.path}")
            return JSONResponse(
                status_code=403,
                content={
                    "error": "Forbidden",
                    "message": "Invalid API key.",
                    "path": request.url.path,
                },
            )

        # 4. Добавление информации о пользователе в request
        request.state.user = {"api_key": api_key, "role": "admin"}

        # 5. Передача запроса дальше
        return await call_next(request)

    # ============================================================
    # 1.2. ВСПОМОГАТЕЛЬНЫЕ МЕТОДЫ
    # ============================================================

    def _is_public_path(self, path: str) -> bool:
        """
        Проверка, является ли путь публичным.

        Args:
            path: Путь запроса

        Returns:
            bool: True если путь публичный (не требует аутентификации)
        """
        return any(path.startswith(public_path) for public_path in self.PUBLIC_PATHS)

    @staticmethod
    def _is_valid_api_key(api_key: str) -> bool:
        """
        Проверка валидности API ключа.

        Args:
            api_key: API ключ из заголовка запроса

        Returns:
            bool: True если ключ валидный

        Note:
            Если API_KEYS не настроены (пустой список), все ключи считаются
            валидными (только для разработки). В production необходимо
            настроить список валидных ключей.
        """
        valid_keys = getattr(settings, "API_KEYS", [])
        if not valid_keys:
            # Если ключи не настроены, разрешаем все (только для разработки)
            return True
        return api_key in valid_keys


__all__ = [
    "AuthMiddleware",
]
