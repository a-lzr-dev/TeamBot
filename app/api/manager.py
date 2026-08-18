import asyncio
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager, suppress
from typing import Any, Optional

import uvicorn
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from starlette.middleware.cors import CORSMiddleware

from ..config import settings
from ..exceptions import AppError, DatabaseError, handle_exception, log_exceptions
from ..logger import api_logger
from ..middlewares.api import (
    APILoggingMiddleware,
    APIRateLimitMiddleware,
    AuthMiddleware,
    ExceptionHandlerMiddleware,
    MetricsMiddleware,
)
from ..models import datetime_now
from ..services import error_service
from .routers import (
    admin_router,
    automation_router,
    avanpost_router,
    bot_msgs_router,
    bot_sync_router,
    errors_router,
    reminders_router,
)


class APIManager:
    """Менеджер для управления FastAPI приложением"""

    _instance: Optional["APIManager"] = None

    def __new__(cls) -> Any:
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    def __init__(self) -> None:
        if hasattr(self, "_initialized"):
            return

        self._app: FastAPI | None = None
        self._server: uvicorn.Server | None = None
        self._is_running = False
        self._initialized = False
        self._tasks: list[asyncio.Task] = []
        self._stop_event = asyncio.Event()

        # Публичные свойства для информации о сервере
        self.host: str = settings.API_HOST
        self.port: int = settings.API_PORT

        api_logger.debug("✅ API Manager instance created")
        self._initialized = True

    @staticmethod
    @asynccontextmanager
    async def _lifespan(_app: FastAPI) -> AsyncGenerator[None]:
        """Управление жизненным циклом API"""
        # Startup
        api_logger.info("🚀 API starting up...")
        yield  # Приложение работает здесь

        # Shutdown
        api_logger.info("⛔ API shutting down...")
        try:
            from ..bot.dependencies import get_bot_manager

            bot_manager = get_bot_manager()
            status = await bot_manager.get_status()
            if status.get("is_running", False):
                await bot_manager.stop()
            else:
                api_logger.info("ℹ️ Telegram manager was not running")
        except Exception as e:
            api_logger.error(f"❌ Telegram manager stopping failed: {e}", exc_info=True)
            await error_service.log_error(
                error=e,
                component="api",
                context={"phase": "lifespan_stop"},
            )

    @log_exceptions(api_logger)
    async def initialize(self) -> None:
        """Инициализация API приложения"""
        if self._initialized and self._app:
            api_logger.warning("⚠️ API Manager already initialized")
            return

        api_logger.debug("🚀 API Manager initializing...")

        # Создание FastAPI приложения
        self._app = FastAPI(
            title="TeamBot API",
            version="1.0.0",
            description="API для управления Telegram ботом TeamBot",
            docs_url="/api/docs",
            redoc_url="/api/redoc",
            openapi_url="/api/openapi.json",
            lifespan=APIManager._lifespan,
        )

        # Настройка middleware
        self._setup_middleware()

        # Подключение роутеров
        self._setup_routers()

        # Настройка обработчиков ошибок
        self._setup_exception_handlers()

        # Настройка эндпоинтов
        self._setup_endpoints()

        self._initialized = True
        api_logger.info("✅ API Manager initialized")

    def _setup_middleware(self) -> None:
        """Настройка middleware"""
        if not self._app:
            raise RuntimeError("App not initialized")

        # CORS
        self._app.add_middleware(
            CORSMiddleware,
            allow_origins=["*"],
            allow_credentials=True,
            allow_methods=["*"],
            allow_headers=["*"],
        )

        # Rate Limit Middleware
        self._app.add_middleware(
            APIRateLimitMiddleware,
            limit=getattr(settings, "API_RATE_LIMIT", 100),
            period=getattr(settings, "API_RATE_PERIOD", 60),
        )

        # Auth Middleware
        self._app.add_middleware(AuthMiddleware)

        # Exception Handler Middleware
        self._app.add_middleware(ExceptionHandlerMiddleware)

        # Logging Middleware
        self._app.add_middleware(
            APILoggingMiddleware,
            component="api",
        )

        # Metrics Middleware
        self._app.add_middleware(MetricsMiddleware)

    def _setup_routers(self) -> None:
        """Подключение роутеров"""
        if not self._app:
            raise RuntimeError("App not initialized")

        self._app.include_router(admin_router, prefix="/api/v1")
        self._app.include_router(bot_msgs_router, prefix="/api/v1")
        self._app.include_router(bot_sync_router, prefix="/api/v1")
        self._app.include_router(avanpost_router, prefix="/api/v1")
        self._app.include_router(errors_router, prefix="/api/v1")
        self._app.include_router(reminders_router, prefix="/api/v1")
        self._app.include_router(automation_router, prefix="/api/v1")

    def _setup_exception_handlers(self) -> None:
        """Настройка обработчиков исключений"""
        if not self._app:
            raise RuntimeError("App not initialized")

        @self._app.exception_handler(DatabaseError)
        async def database_error_handler(request: Request, exc: DatabaseError) -> JSONResponse:
            api_logger.error(f"❌ Database error: {exc}")

            await error_service.log_error(
                error=exc,
                component="database",
                context={
                    "path": request.url.path,
                    "method": request.method,
                    "client": request.client.host if request.client else "unknown",
                },
            )

            return JSONResponse(
                status_code=503,
                content={
                    "error": "DatabaseError",
                    "message": str(exc),
                    "path": request.url.path,
                    "timestamp": datetime_now().isoformat() + "Z",
                },
            )

        @self._app.exception_handler(AppError)
        async def app_error_handler(request: Request, exc: AppError) -> JSONResponse:
            await handle_exception(exc)

            await error_service.log_error(
                error=exc,
                component="api",
                context={
                    "path": request.url.path,
                    "method": request.method,
                    "client": request.client.host if request.client else "unknown",
                },
            )

            status_code = 400 if hasattr(exc, "status_code") else 500
            return JSONResponse(
                status_code=status_code,
                content={
                    "error": exc.__class__.__name__,
                    "message": str(exc),
                    "type": "app_error",
                    "path": request.url.path,
                    "timestamp": datetime_now().isoformat() + "Z",
                },
            )

        @self._app.exception_handler(Exception)
        async def global_exception_handler(request: Request, exc: Exception) -> JSONResponse:
            await handle_exception(exc)

            await error_service.log_error(
                error=exc,
                component="api",
                context={
                    "path": request.url.path,
                    "method": request.method,
                    "client": request.client.host if request.client else "unknown",
                },
            )

            return JSONResponse(
                status_code=500,
                content={
                    "error": "InternalServerError",
                    "message": "An unexpected error occurred",
                    "type": "internal_error",
                    "path": request.url.path,
                    "timestamp": datetime_now().isoformat() + "Z",
                },
            )

    def _setup_endpoints(self) -> None:
        """Настройка дополнительных эндпоинтов"""
        if not self._app:
            raise RuntimeError("App not initialized")

        @self._app.get("/")
        @log_exceptions(api_logger)
        async def root() -> dict[str, Any]:
            return {
                "name": "TeamBot API",
                "version": "1.0.0",
                "status": "running",
                "docs": "/api/docs",
                "redoc": "/api/redoc",
                "health": "/api/v1/health",
                "ping": "/api/v1/ping",
            }

        @self._app.get("/health")
        @log_exceptions(api_logger)
        async def health_simple() -> dict[str, Any]:
            return {"status": "ok", "timestamp": datetime_now().isoformat() + "Z"}

        @self._app.get("/version")
        @log_exceptions(api_logger)
        async def version() -> dict[str, Any]:
            return {
                "version": "1.0.0",
                "environment": getattr(settings, "APP_ENV", "production"),
                "debug": getattr(settings, "APP_DEBUG", False),
                "timestamp": datetime_now().isoformat() + "Z",
            }

        @self._app.get("/debug/middleware")
        @log_exceptions(api_logger)
        async def debug_middleware(request: Request) -> dict[str, Any]:
            return {
                "middleware_loaded": True,
                "metrics_middleware_available": hasattr(request.app.state, "metrics_middleware"),
                "auth_configured": True,
                "cors_configured": True,
                "rate_limit_configured": True,
            }

        @self._app.get("/debug/headers")
        @log_exceptions(api_logger)
        async def debug_headers(request: Request) -> dict[str, Any]:
            headers = dict(request.headers)
            if "authorization" in headers:
                headers["authorization"] = "***"
            if "x-api-key" in headers:
                headers["x-api-key"] = "***"
            return {
                "headers": headers,
                "client": request.client.host if request.client else "unknown",
                "method": request.method,
                "url": str(request.url),
            }

        @self._app.get("/debug/bot-status")
        @log_exceptions(api_logger)
        async def debug_bot_status() -> dict[str, Any]:
            try:
                from ..bot.dependencies import get_bot_manager

                bot_manager = get_bot_manager()
                status = await bot_manager.get_status()
                return {"bot": status, "timestamp": datetime_now().isoformat() + "Z"}
            except Exception as e:
                await error_service.log_error(
                    error=e,
                    component="api",
                    context={"endpoint": "bot_telegram_status"},
                )
                return {"error": str(e), "timestamp": datetime_now().isoformat() + "Z"}

        @self._app.get("/debug/routes")
        @log_exceptions(api_logger)
        async def debug_routes() -> dict[str, Any]:
            routes = []

            if self._app is None:
                return {"error": "App not initialized", "timestamp": datetime_now().isoformat() + "Z"}

            for route in self._app.routes:
                route_info: dict[str, Any] = {}

                if hasattr(route, "path"):
                    route_info["path"] = route.path
                elif hasattr(route, "path_regex"):
                    route_info["path"] = str(route.path_regex)
                else:
                    route_info["path"] = str(route)

                if hasattr(route, "name"):
                    route_info["name"] = route.name
                else:
                    route_info["name"] = None

                if hasattr(route, "methods"):
                    route_info["methods"] = list(route.methods) if route.methods else []
                elif hasattr(route, "method"):
                    route_info["methods"] = [route.method] if route.method else []
                else:
                    route_info["methods"] = []

                routes.append(route_info)

            return {"total_routes": len(routes), "routes": routes, "timestamp": datetime_now().isoformat() + "Z"}

    # ============ Публичные свойства ============

    @property
    def app(self) -> FastAPI:
        if not self._app:
            raise RuntimeError("API Manager not initialized. Call initialize() first.")
        return self._app

    @property
    def is_running(self) -> bool:
        return self._is_running

    @property
    def is_initialized(self) -> bool:
        return self._initialized

    @property
    def server_info(self) -> dict[str, Any]:
        return {
            "host": self.host,
            "port": self.port,
            "is_running": self._is_running,
            "is_initialized": self._initialized,
            "has_app": self._app is not None,
            "docs_url": "/api/docs" if self._app else None,
            "redoc_url": "/api/redoc" if self._app else None,
            "openapi_url": "/api/openapi.json" if self._app else None,
        }

    # ============ Публичные методы ============

    @log_exceptions(api_logger)
    async def start(self) -> None:
        if self._is_running:
            api_logger.warning("⚠️ API already running")
            return

        if not self._initialized:
            await self.initialize()

        api_logger.debug("🚀 API starting...")
        self._is_running = True
        self._stop_event.clear()

        self._tasks.append(asyncio.create_task(self._run_server(), name="api_server"))

        api_logger.info(f"✅ API started on {self.host}:{self.port}")

    async def _run_server(self) -> None:
        try:
            if self._app is None:
                api_logger.error("❌ App is not initialized")
                return

            config = uvicorn.Config(
                self._app,
                host=self.host,
                port=self.port,
                log_level=settings.LOG_LEVEL.lower(),
                access_log=False,
                loop="asyncio",
                timeout_keep_alive=getattr(settings, "HTTP_TIMEOUT_KEEP_ALIVE", 30),
                lifespan="on",
            )
            self._server = uvicorn.Server(config)
            await self._server.serve()
        except asyncio.CancelledError:
            api_logger.debug("ℹ️ API Server task cancelled")
            raise
        except Exception as e:
            api_logger.error(f"❌ API Server failed: {e}", exc_info=True)
            await error_service.log_error(
                error=e,
                component="api",
                context={"phase": "server_run"},
            )
            raise

    @log_exceptions(api_logger)
    async def stop(self) -> None:
        if not self._is_running:
            api_logger.warning("⚠️ API not running")
            return

        api_logger.debug("🚀 API Server stopped starting...")
        self._is_running = False
        self._stop_event.set()

        if self._server:
            try:
                self._server.should_exit = True
                api_logger.debug("⛔ API Server stopped")
            except Exception as e:
                api_logger.error(f"❌ API Server stopping failed: {e}", exc_info=True)
                await error_service.log_error(
                    error=e,
                    component="api",
                    context={"phase": "server_stop"},
                )

        for task in self._tasks:
            if not task.done():
                task.cancel()

        if self._tasks:
            with suppress(asyncio.CancelledError):
                await asyncio.gather(*self._tasks, return_exceptions=True)

        self._tasks.clear()
        api_logger.info("⛔ API stopped")

    @log_exceptions(api_logger)
    async def restart(self) -> None:
        api_logger.info("🔄 API restarting...")
        await self.stop()
        await asyncio.sleep(0.5)
        await self.start()
        api_logger.info("✅ API restarted")

    async def get_status(self) -> dict[str, Any]:
        return {
            "is_running": self._is_running,
            "is_initialized": self._initialized,
            "tasks_count": len(self._tasks),
            "host": self.host,
            "port": self.port,
            "has_app": self._app is not None,
            "docs_url": "/api/docs",
            "redoc_url": "/api/redoc",
            "openapi_url": "/api/openapi.json",
        }

    async def health_check(self) -> bool:
        try:
            if not self._is_running:
                return False
            return self._app is not None
        except Exception:
            return False


api_manager = APIManager()

__all__ = [
    "APIManager",
    "api_manager",
]
