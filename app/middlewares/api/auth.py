"""
Middleware для аутентификации запросов к API.

Назначение:
    Обеспечивает аутентификацию входящих HTTP запросов через API ключи.
    Защищает эндпоинты API от несанкционированного доступа.

Основные функции:
    1. Проверка наличия API ключа в заголовке X-API-Key
    2. Валидация API ключа по списку из настроек
    3. Пропуск публичных путей (health, docs, relay-ingest, WS)
    4. Пропуск запросов с доверенных хостов (TRUSTED_HOSTS)
    5. Пропуск CORS preflight (OPTIONS) и WebSocket upgrade запросов
    6. Добавление информации о пользователе в request.state

Технические особенности:
    - Интеграция с FastAPI/Starlette через BaseHTTPMiddleware
    - Динамический список публичных путей: учитывает WS_NOTIFY_PATH
      и WS_RELAY_INGEST_PATH из настроек
    - Поддержка CIDR-нотации (например, 192.168.12.0/24)
    - Поддержка X-Forwarded-For / X-Real-IP для работы за прокси
    - Constant-time сравнение API-ключа (hmac.compare_digest)
    - В production тело ошибки не содержит client_ip

Безопасность:
    - В production необходимо настроить API_KEYS в конфигурации
    - /internal/push защищён отдельным Bearer-токеном (WS_RELAY_AUTH_TOKEN)
      внутри relay_handler, а не API-ключом
    - /ws/notify проверяет токен в query при accept в ws_notify_handler
    - Логирование предупреждений при неавторизованных попытках

Архитектура:
    - Реализует интерфейс BaseHTTPMiddleware от Starlette
    - Поддерживает асинхронную обработку запросов
    - Интегрируется с настройками приложения через settings
"""

import hmac
import ipaddress
from collections.abc import Awaitable, Callable

from fastapi import Request, Response
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware

from ...config import settings
from ...logger import api_logger


def _is_dev_env() -> bool:
    """Проверка, что мы в development-окружении."""
    return (getattr(settings, "APP_ENV", "") or "").lower() in ("development", "dev")


# ============================================================
# 1. КЛАСС MIDDLEWARE ДЛЯ АУТЕНТИФИКАЦИИ
# ============================================================


class AuthMiddleware(BaseHTTPMiddleware):
    """
    Middleware для аутентификации запросов к API.

    Проверяет наличие и валидность API ключа в заголовке X-API-Key.
    Публичные пути, доверенные хосты, CORS preflight и WebSocket upgrade
    пропускаются без проверки.

    Attributes:
        PUBLIC_PATHS (list[str]): Базовый список путей, не требующих аутентификации

    Пример использования в FastAPI:
        app.add_middleware(AuthMiddleware)
    """

    # Базовые пути, которые не требуют аутентификации.
    # Пути relay-ingest и WS добавляются динамически из настроек
    # (см. _get_public_paths), чтобы учитывать WS_NOTIFY_PATH
    # и WS_RELAY_INGEST_PATH из .env.
    PUBLIC_PATHS = [
        "/api/v1/health",
        "/api/v1/ping",
        "/api/v1/ready",
        "/api/docs",
        "/api/redoc",
        "/api/openapi.json",
        "/health",
        "/version",
    ]

    # Доверенные IP-адреса и подсети (CIDR), которым не нужен API-ключ.
    # Значения по умолчанию можно переопределить через settings.API_TRUSTED_HOSTS.
    DEFAULT_TRUSTED_HOSTS = [
        "127.0.0.1",  # localhost (IPv4)
        "::1",  # localhost (IPv6)
        "172.17.0.1",  # Docker bridge (по умолчанию)
        "192.168.12.1",  # ваш доверенный хост
    ]

    # ============================================================
    # 1.1. ОСНОВНОЙ МЕТОД ОБРАБОТКИ ЗАПРОСА
    # ============================================================

    async def dispatch(
        self,
        request: Request,
        call_next: Callable[[Request], Awaitable[Response]],
    ) -> Response:
        """
        Основной метод обработки запроса.

        Args:
            request: Объект запроса FastAPI/Starlette
            call_next: Функция для передачи запроса дальше по цепочке

        Returns:
            Response: Ответ от приложения или ошибка аутентификации
        """
        # Пропускаем WebSocket — его аутентификация в ws_notify_handler
        if request.scope["type"] == "websocket":
            return await call_next(request)

        path = request.url.path
        method = request.method

        # 0. WebSocket upgrade: пропускаем всегда.
        #    Аутентификация WS-клиента выполняется в ws_notify_handler
        #    через query-параметр token.
        if self._is_websocket_upgrade(request):
            api_logger.debug(f"🔓 WebSocket upgrade: {path}")
            return await call_next(request)

        # 0.1. CORS preflight (OPTIONS): пропускаем, чтобы браузер
        #      получил корректные CORS-заголовки от CORSMiddleware.
        if method == "OPTIONS":
            api_logger.debug(f"🔓 CORS preflight: {path}")
            return await call_next(request)

        # 1. Проверка, является ли путь публичным
        if self._is_public_path(path):
            api_logger.debug(f"🔓 Public path: {path}")
            return await call_next(request)

        # 2. Проверка, является ли хост доверенным
        client_ip = self._get_client_ip(request)
        if self._is_trusted_host(client_ip):
            api_logger.info(f"🔓 Trusted host {client_ip} -> {path} (no API key required)")
            request.state.user = {
                "api_key": None,
                "role": "trusted_host",
                "client_ip": client_ip,
            }
            return await call_next(request)

        # 3. Проверка API ключа
        api_key = request.headers.get("X-API-Key")

        if not api_key:
            api_logger.warning(f"⚠️ Missing API key for {path} (client={client_ip})")
            return self._unauthorized_response(
                path=path,
                client_ip=client_ip,
                status_code=401,
                error="Unauthorized",
                message="Missing API key. Please provide X-API-Key header.",
            )

        # 4. Проверка валидности API ключа
        if not self._is_valid_api_key(api_key):
            api_logger.warning(f"⚠️ Invalid API key for {path} (client={client_ip})")
            return self._unauthorized_response(
                path=path,
                client_ip=client_ip,
                status_code=403,
                error="Forbidden",
                message="Invalid API key.",
            )

        # 5. Добавление информации о пользователе в request
        request.state.user = {
            "api_key": api_key,
            "role": "admin",
            "client_ip": client_ip,
        }

        # 6. Передача запроса дальше
        return await call_next(request)

    # ============================================================
    # 1.2. ВСПОМОГАТЕЛЬНЫЕ МЕТОДЫ
    # ============================================================

    @staticmethod
    def _is_websocket_upgrade(request: Request) -> bool:
        """Проверка, что запрос — WebSocket upgrade."""
        upgrade = request.headers.get("upgrade", "").lower()
        connection = request.headers.get("connection", "").lower()
        return upgrade == "websocket" and "upgrade" in connection

    @classmethod
    def _get_public_paths(cls) -> list[str]:
        """
        Возвращает список публичных путей, включая динамические:
        relay-ingest и WS-эндпоинт (если WS_NOTIFY_ENABLED=true).

        Returns:
            list[str]: Полный список публичных путей
        """
        paths = list(cls.PUBLIC_PATHS)

        if getattr(settings, "WS_NOTIFY_ENABLED", False):
            # Relay ingest: путь из настроек, по умолчанию /internal/push
            ingest_path = getattr(settings, "WS_RELAY_INGEST_PATH", None) or "/internal/push"
            paths.append(ingest_path)

            # WebSocket endpoint: путь из настроек, по умолчанию /ws/notify
            ws_path = getattr(settings, "WS_NOTIFY_PATH", None) or "/ws/notify"
            paths.append(ws_path)

        return paths

    @classmethod
    def _is_public_path(cls, path: str) -> bool:
        """
        Проверка, является ли путь публичным.

        Использует точное совпадение или префикс с "/":
        - "/api/docs" совпадёт с "/api/docs" и "/api/docs/..."
        - "/api/v1/health" НЕ совпадёт с "/api/v1/health-check"
        - "/internal/push" — точное совпадение (не префикс)

        Args:
            path: Путь запроса

        Returns:
            bool: True если путь публичный (не требует аутентификации)
        """
        # Точное совпадение для корня
        if path == "/":
            return False

        for public_path in cls._get_public_paths():
            # Точное совпадение
            if path == public_path:
                return True
            # Префикс с "/" (для подресурсов вроде /api/docs/swagger-ui.css)
            if path.startswith(public_path + "/"):
                return True

        return False

    def _is_trusted_host(self, client_ip: str) -> bool:
        """
        Проверка, является ли IP-адрес доверенным.

        Поддерживает:
        - Точные IPv4/IPv6 адреса: "192.168.12.1", "::1"
        - CIDR-подсети: "192.168.12.0/24", "10.0.0.0/8"

        Args:
            client_ip: IP-адрес клиента

        Returns:
            bool: True если хост доверенный
        """
        if not client_ip or client_ip == "unknown":
            return False

        try:
            ip = ipaddress.ip_address(client_ip)
        except ValueError:
            api_logger.warning(f"⚠️ Invalid client IP: {client_ip!r}")
            return False

        for trusted in self._get_trusted_hosts():
            try:
                if "/" in trusted:
                    network = ipaddress.ip_network(trusted, strict=False)
                    if ip in network:
                        return True
                else:
                    if ip == ipaddress.ip_address(trusted):
                        return True
            except ValueError:
                api_logger.warning(f"⚠️ Invalid trusted host entry: {trusted!r}")
                continue

        return False

    @staticmethod
    def _get_client_ip(request: Request) -> str:
        """
        Получение IP-адреса клиента с учётом X-Forwarded-For / X-Real-IP.

        Args:
            request: Объект запроса

        Returns:
            str: IP-адрес клиента или "unknown"
        """
        forwarded_for = request.headers.get("X-Forwarded-For")
        if forwarded_for:
            client_ip = forwarded_for.split(",")[0].strip()
            if client_ip:
                return client_ip

        real_ip = request.headers.get("X-Real-IP")
        if real_ip:
            return real_ip.strip()

        client = request.client
        if client is not None and client.host is not None:
            return client.host

        return "unknown"

    @classmethod
    def _get_trusted_hosts(cls) -> list[str]:
        """
        Получение списка доверенных хостов.

        Приоритет:
        1. settings.API_TRUSTED_HOSTS (если задан и не пустой)
        2. cls.DEFAULT_TRUSTED_HOSTS (значения по умолчанию)

        Returns:
            list[str]: Список доверенных IP/подсетей
        """
        from_settings = getattr(settings, "API_TRUSTED_HOSTS", None)
        if from_settings:
            if isinstance(from_settings, list):
                return [str(h) for h in from_settings]
            if isinstance(from_settings, str):
                return [h.strip() for h in from_settings.split(",") if h.strip()]
        return cls.DEFAULT_TRUSTED_HOSTS

    @staticmethod
    def _is_valid_api_key(api_key: str) -> bool:
        """
        Проверка валидности API ключа.

        Использует hmac.compare_digest для защиты от timing-атак.

        Args:
            api_key: API ключ из заголовка запроса

        Returns:
            bool: True если ключ валидный
        """
        valid_keys = getattr(settings, "API_KEYS", []) or []
        if not valid_keys:
            api_logger.critical("🚨 API_KEYS is not configured! API is not protected.")
            return False

        provided: bytes = api_key.encode("utf-8")
        result = False
        for valid in valid_keys:
            candidate: bytes = valid.encode("utf-8") if isinstance(valid, str) else bytes(valid)
            # Сравниваем всегда, чтобы время не зависело от позиции совпадения
            if hmac.compare_digest(provided, candidate):
                result = True
        return result

    @staticmethod
    def _unauthorized_response(
        path: str,
        client_ip: str,
        status_code: int,
        error: str,
        message: str,
    ) -> JSONResponse:
        """
        Формирует JSON-ответ об ошибке аутентификации.

        В production не раскрывает client_ip в теле ответа.
        """
        content: dict[str, object] = {
            "error": error,
            "message": message,
            "path": path,
        }
        if _is_dev_env():
            content["client_ip"] = client_ip
        return JSONResponse(status_code=status_code, content=content)


__all__ = [
    "AuthMiddleware",
]
