import time
from collections.abc import Awaitable, Callable

from fastapi import Request, Response
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.types import ASGIApp

from ...logger import api_logger


class APILoggingMiddleware(BaseHTTPMiddleware):
    """Middleware для логирования HTTP запросов и ответов"""

    def __init__(self, app: ASGIApp, component: str = "api") -> None:
        super().__init__(app)
        self.component = component

    async def dispatch(self, request: Request, call_next: Callable[[Request], Awaitable[Response]]) -> Response:
        # Информация о запросе
        client_ip = request.client.host if request.client else "unknown"
        method = request.method
        path = request.url.path
        query_params = str(request.query_params) if request.query_params else ""

        # Замер времени выполнения
        start_time = time.perf_counter()

        try:
            # Обработка запроса
            response = await call_next(request)

            # Вычисление времени выполнения
            process_time = (time.perf_counter() - start_time) * 1000

            # Логирование через ExtendedLogger
            api_logger.log_request(
                method=method,
                path=path + ("?" + query_params if query_params else ""),
                status_code=response.status_code,
                duration_ms=process_time,
                client_ip=client_ip,
            )

            # Добавление заголовка с временем выполнения
            response.headers["X-Process-Time"] = f"{process_time:.2f}ms"

            return response

        except Exception as e:
            api_logger.log_error(error=e, message=f"Request failed: {method} {path}", extra={"client_ip": client_ip})
            raise


__all__ = ["APILoggingMiddleware"]
