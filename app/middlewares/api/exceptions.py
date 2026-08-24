"""
Middleware для глобальной обработки исключений в API.

Назначение:
    Перехватывает все исключения, возникающие при обработке запросов,
    и возвращает структурированные JSON ответы с информацией об ошибке.

Основные функции:
    1. Обработка кастомных исключений приложения (AppError)
    2. Обработка HTTP исключений FastAPI/Starlette
    3. Обработка неожиданных ошибок (Internal Server Error)
    4. Логирование всех ошибок с контекстом
    5. Возврат структурированных JSON ответов с информацией об ошибке

Технические особенности:
    - Интеграция с FastAPI/Starlette через BaseHTTPMiddleware
    - Поддержка кастомных исключений через AppError
    - Безопасное логирование через handle_exception
    - Единый формат JSON ответов для всех ошибок

Архитектура:
    - Реализует интерфейс BaseHTTPMiddleware от Starlette
    - Использует handle_exception для централизованного логирования
    - Возвращает JSONResponse с деталями ошибки
"""

from collections.abc import Awaitable, Callable

from fastapi import Request, Response
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException
from starlette.middleware.base import BaseHTTPMiddleware

from ...exceptions import AppError
from ...logger import api_logger
from ...utils.decorators import handle_exception

# ============================================================
# 1. КЛАСС MIDDLEWARE ДЛЯ ОБРАБОТКИ ИСКЛЮЧЕНИЙ
# ============================================================


class ExceptionHandlerMiddleware(BaseHTTPMiddleware):
    """
    Middleware для глобальной обработки исключений в API.

    Перехватывает все исключения и возвращает структурированные
    JSON ответы с информацией об ошибке.

    Пример использования в FastAPI:
        app.add_middleware(ExceptionHandlerMiddleware)

    Обрабатываемые типы ошибок:
        1. AppError — кастомные ошибки приложения (400/500)
        2. StarletteHTTPException — HTTP ошибки FastAPI
        3. Exception — все остальные неожиданные ошибки (500)
    """

    # ============================================================
    # 1.1. ОСНОВНОЙ МЕТОД ОБРАБОТКИ ЗАПРОСА
    # ============================================================

    async def dispatch(self, request: Request, call_next: Callable[[Request], Awaitable[Response]]) -> Response:
        """
        Основной метод обработки запроса с перехватом исключений.

        Args:
            request: Объект запроса FastAPI/Starlette
            call_next: Функция для передачи запроса дальше по цепочке

        Returns:
            Response: Ответ от приложения или JSON с ошибкой

        Flow:
            1. Попытка выполнения запроса
            2. Перехват и обработка AppError
            3. Перехват и обработка HTTPException
            4. Перехват и обработка неожиданных ошибок
            5. Возврат структурированного JSONResponse
        """
        try:
            return await call_next(request)

        except AppError as e:
            # 1. Обработка кастомных исключений приложения
            await handle_exception(e)
            return JSONResponse(
                status_code=400 if hasattr(e, "status_code") else 500,
                content={
                    "error": e.__class__.__name__,
                    "message": str(e),
                    "type": "app_error",
                    "path": request.url.path,
                },
            )

        except StarletteHTTPException as e:
            # 2. Обработка HTTP исключений FastAPI
            api_logger.warning(f"HTTP exception: {e.status_code} - {e.detail}")
            return JSONResponse(
                status_code=e.status_code,
                content={
                    "error": "HTTPException",
                    "message": e.detail,
                    "type": "http_error",
                    "path": request.url.path,
                },
            )

        except Exception as e:
            # 3. Обработка неожиданных ошибок
            await handle_exception(e)
            return JSONResponse(
                status_code=500,
                content={
                    "error": "InternalServerError",
                    "message": "An unexpected error occurred",
                    "type": "internal_error",
                    "path": request.url.path,
                },
            )


__all__ = [
    "ExceptionHandlerMiddleware",
]
