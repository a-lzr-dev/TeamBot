"""
Middleware для сбора метрик HTTP запросов.

Назначение:
    Автоматический сбор и агрегация метрик по всем входящим HTTP запросам
    для мониторинга производительности и анализа нагрузки.

Основные функции:
    1. Подсчёт количества запросов по эндпоинтам
    2. Подсчёт количества ошибок (статус >= 400)
    3. Сбор времени выполнения запросов
    4. Агрегация метрик (min, max, avg)
    5. Ограничение хранения (последние 1000 записей)
    6. Сброс метрик по запросу

Технические особенности:
    - Интеграция с FastAPI/Starlette через BaseHTTPMiddleware
    - Использование defaultdict для автоматической инициализации
    - Ограничение размера хранимых данных (1000 записей на эндпоинт)
    - Агрегация времени выполнения (min, max, avg, count)

Архитектура:
    - Реализует интерфейс BaseHTTPMiddleware от Starlette
    - Хранит метрики в памяти (внутреннее состояние)
    - Предоставляет API для получения и сброса метрик
"""

import time
from collections import defaultdict
from collections.abc import Awaitable, Callable
from typing import Any

from fastapi import Request, Response
from starlette.middleware.base import BaseHTTPMiddleware

# ============================================================
# 1. КЛАСС MIDDLEWARE ДЛЯ СБОРА МЕТРИК
# ============================================================


class MetricsMiddleware(BaseHTTPMiddleware):
    """
    Middleware для сбора метрик HTTP запросов.

    Собирает и агрегирует метрики по всем эндпоинтам:
    - Количество запросов
    - Количество ошибок (HTTP статус >= 400)
    - Время выполнения (min, max, avg)

    Метрики хранятся в памяти и доступны через метод get_metrics().

    Пример использования в FastAPI:
        app.add_middleware(MetricsMiddleware)

    Attributes:
        request_count (dict[str, int]): Счётчик запросов по эндпоинтам
        error_count (dict[str, int]): Счётчик ошибок по эндпоинтам
        response_times (dict[str, list[float]]): Время выполнения по эндпоинтам
    """

    def __init__(self, app: Any):
        """
        Инициализация middleware сбора метрик.

        Args:
            app: ASGI приложение
        """
        super().__init__(app)
        self.request_count: dict[str, int] = defaultdict(int)
        self.error_count: dict[str, int] = defaultdict(int)
        self.response_times: dict[str, list[float]] = defaultdict(list)

    # ============================================================
    # 1.1. ОСНОВНОЙ МЕТОД ОБРАБОТКИ ЗАПРОСА
    # ============================================================

    async def dispatch(self, request: Request, call_next: Callable[[Request], Awaitable[Response]]) -> Response:
        """
        Основной метод обработки запроса со сбором метрик.

        Args:
            request: Объект запроса FastAPI/Starlette
            call_next: Функция для передачи запроса дальше по цепочке

        Returns:
            Response: Ответ от приложения

        Flow:
            1. Замер времени начала выполнения
            2. Выполнение запроса
            3. Обновление счётчика запросов
            4. Обновление счётчика ошибок (если статус >= 400)
            5. Расчёт времени выполнения и сохранение
            6. Ограничение размера хранимых данных
            7. Возврат ответа
        """
        start_time = time.perf_counter()
        path = request.url.path
        method = request.method
        key = f"{method} {path}"

        try:
            response = await call_next(request)

            # 1. Обновление счётчика запросов
            self.request_count[key] += 1

            # 2. Обновление счётчика ошибок (статус >= 400)
            if response.status_code >= 400:
                self.error_count[key] += 1

            # 3. Расчёт и сохранение времени выполнения
            process_time = (time.perf_counter() - start_time) * 1000
            self.response_times[key].append(process_time)

            # 4. Ограничение хранения метрик (последние 1000 записей)
            if len(self.response_times[key]) > 1000:
                self.response_times[key] = self.response_times[key][-1000:]

            return response

        except Exception:
            # При исключении тоже считаем ошибку
            self.error_count[key] += 1
            raise

    # ============================================================
    # 1.2. ПОЛУЧЕНИЕ И СБРОС МЕТРИК
    # ============================================================

    def get_metrics(self) -> dict[str, dict[str, int] | dict[str, dict[str, float | int]]]:
        """
        Получение собранных метрик.

        Returns:
            dict[str, dict[str, int] | dict[str, dict[str, float | int]]]: Метрики в формате:
                {
                    "requests": {"/api/users": 100, ...},
                    "errors": {"/api/users": 5, ...},
                    "response_times": {
                        "/api/users": {
                            "min": 10.5,
                            "max": 250.3,
                            "avg": 45.2,
                            "count": 100
                        },
                        ...
                    }
                }
        """
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
        """Сброс всех собранных метрик."""
        self.request_count.clear()
        self.error_count.clear()
        self.response_times.clear()


__all__ = [
    "MetricsMiddleware",
]
