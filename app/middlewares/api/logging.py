"""
Middleware для логирования HTTP запросов и ответов.

Назначение:
    Автоматическое логирование всех входящих HTTP запросов и исходящих ответов
    с информацией о времени выполнения, статусе и клиенте.

Основные функции:
    1. Логирование всех HTTP запросов с методом, путём и параметрами
    2. Замер времени выполнения запроса
    3. Логирование статуса ответа и длительности
    4. Добавление заголовка X-Process-Time с временем выполнения
    5. Логирование ошибок при обработке запросов

Технические особенности:
    - Интеграция с FastAPI/Starlette через BaseHTTPMiddleware
    - Использует ExtendedLogger с методом log_request
    - Замер времени через time.perf_counter() для высокой точности
    - Безопасная обработка отсутствия клиентского IP

Архитектура:
    - Реализует интерфейс BaseHTTPMiddleware от Starlette
    - Поддерживает настраиваемый компонент для логирования
    - Интегрируется с API логгером
"""

import time
from collections.abc import Awaitable, Callable

from fastapi import Request, Response
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.types import ASGIApp

from ...logger import api_logger

# ============================================================
# 1. КЛАСС MIDDLEWARE ДЛЯ ЛОГИРОВАНИЯ ЗАПРОСОВ
# ============================================================


class APILoggingMiddleware(BaseHTTPMiddleware):
    """
    Middleware для логирования HTTP запросов и ответов.

    Автоматически логирует все входящие запросы с информацией о:
    - HTTP методе и пути
    - IP адресе клиента
    - Статусе ответа
    - Времени выполнения в миллисекундах

    Также добавляет заголовок X-Process-Time к ответу.

    Пример использования в FastAPI:
        app.add_middleware(APILoggingMiddleware, component="api")

    Attributes:
        component (str): Имя компонента для логирования
    """

    def __init__(self, app: ASGIApp, component: str = "api") -> None:
        """
        Инициализация middleware логирования.

        Args:
            app: ASGI приложение
            component: Имя компонента для логирования (по умолчанию "api")
        """
        super().__init__(app)
        self.component = component

    # ============================================================
    # 1.1. ОСНОВНОЙ МЕТОД ОБРАБОТКИ ЗАПРОСА
    # ============================================================

    async def dispatch(self, request: Request, call_next: Callable[[Request], Awaitable[Response]]) -> Response:
        """
        Основной метод обработки запроса с логированием.

        Args:
            request: Объект запроса FastAPI/Starlette
            call_next: Функция для передачи запроса дальше по цепочке

        Returns:
            Response: Ответ от приложения с добавленным заголовком

        Flow:
            1. Сбор информации о запросе (метод, путь, IP)
            2. Замер времени начала выполнения
            3. Выполнение запроса
            4. Замер времени окончания и вычисление длительности
            5. Логирование запроса через api_logger
            6. Добавление заголовка X-Process-Time
            7. Возврат ответа
        """
        # 1. Информация о запросе
        client_ip = request.client.host if request.client else "unknown"
        method = request.method
        path = request.url.path
        query_params = str(request.query_params) if request.query_params else ""

        # 2. Замер времени выполнения
        start_time = time.perf_counter()

        try:
            # 3. Обработка запроса
            response = await call_next(request)

            # 4. Вычисление времени выполнения
            process_time = (time.perf_counter() - start_time) * 1000

            # 5. Логирование через ExtendedLogger
            api_logger.log_request(
                method=method,
                path=path + ("?" + query_params if query_params else ""),
                status_code=response.status_code,
                duration_ms=process_time,
                client_ip=client_ip,
            )

            # 6. Добавление заголовка с временем выполнения
            response.headers["X-Process-Time"] = f"{process_time:.2f}ms"

            # 7. Возврат ответа
            return response

        except Exception as e:
            # Логирование ошибки при обработке запроса
            api_logger.log_error(error=e, message=f"Request failed: {method} {path}", extra={"client_ip": client_ip})
            raise


__all__ = ["APILoggingMiddleware"]
