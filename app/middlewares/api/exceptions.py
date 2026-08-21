from collections.abc import Awaitable, Callable

from fastapi import Request, Response
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException
from starlette.middleware.base import BaseHTTPMiddleware

from ...exceptions import AppError
from ...logger import api_logger
from ...utils.decorators import handle_exception


class ExceptionHandlerMiddleware(BaseHTTPMiddleware):
    """Middleware для глобальной обработки исключений"""

    async def dispatch(self, request: Request, call_next: Callable[[Request], Awaitable[Response]]) -> Response:
        try:
            return await call_next(request)

        except AppError as e:
            # Обработка кастомных исключений приложения
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
            # Обработка HTTP исключений FastAPI
            api_logger.warning(f"HTTP exception: {e.status_code} - {e.detail}")
            return JSONResponse(
                status_code=e.status_code,
                content={"error": "HTTPException", "message": e.detail, "type": "http_error", "path": request.url.path},
            )

        except Exception as e:
            # Обработка неожиданных ошибок
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
