import time
from collections import defaultdict
from collections.abc import Awaitable, Callable
from typing import Any

from fastapi import Request, Response
from starlette.middleware.base import BaseHTTPMiddleware


class MetricsMiddleware(BaseHTTPMiddleware):
    """Middleware для сбора метрик запросов"""

    def __init__(self, app: Any):
        super().__init__(app)
        self.request_count: dict[str, int] = defaultdict(int)
        self.error_count: dict[str, int] = defaultdict(int)
        self.response_times: dict[str, list[float]] = defaultdict(list)

    async def dispatch(self, request: Request, call_next: Callable[[Request], Awaitable[Response]]) -> Response:
        start_time = time.perf_counter()

        try:
            response = await call_next(request)

            # Сбор метрик
            path = request.url.path
            method = request.method
            key = f"{method} {path}"

            self.request_count[key] += 1

            if response.status_code >= 400:
                self.error_count[key] += 1

            process_time = (time.perf_counter() - start_time) * 1000
            self.response_times[key].append(process_time)

            # Ограничение хранения метрик
            if len(self.response_times[key]) > 1000:
                self.response_times[key] = self.response_times[key][-1000:]

            return response

        except Exception:
            path = request.url.path
            method = request.method
            key = f"{method} {path}"
            self.error_count[key] += 1
            raise

    def get_metrics(self) -> dict[str, dict[str, int] | dict[str, dict[str, float | int]]]:
        """Получение собранных метрик"""
        metrics: dict[str, dict[str, int] | dict[str, dict[str, float | int]]] = {
            "requests": dict(self.request_count),
            "errors": dict(self.error_count),
            "response_times": {},
        }

        for path, times in self.response_times.items():
            if times:
                metrics["response_times"][path] = {  # type: ignore
                    "min": min(times),
                    "max": max(times),
                    "avg": sum(times) / len(times),
                    "count": len(times),
                }

        return metrics

    def reset_metrics(self) -> None:
        """Сброс метрик"""
        self.request_count.clear()
        self.error_count.clear()
        self.response_times.clear()


__all__ = [
    "MetricsMiddleware",
]
