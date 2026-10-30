"""
Модуль управления FastAPI приложением для TeamBot.

Изменения относительно исходной версии:
    * подключается relay-роутер из app/ws/relay_handler.py;
    * WS-эндпоинт регистрируется тем же путём settings.WS_NOTIFY_PATH;
    * при старте проверяется, что WS_NOTIFY_TOKEN_VERIFY_MODE="trust" не
      используется в production (APP_ENV != "development");
    * push_service запускается только если WS_NOTIFY_ENABLED=true;
    * debug-эндпоинты регистрируются только при APP_DEBUG=true в development;
    * /api/v1/ws/stats отдаёт ошибку, если push-сервис выключен;
    * middleware регистрируются через фабрики `Callable[..., ASGIApp]`,
      чтобы удовлетворить типизацию Starlette `add_middleware` без
      подавления проверки аргументов на уровне определений фабрик.

Исправления Pyright:
    * `self._app` сужается до `FastAPI` после проверки `is None` (в
      `_setup_middleware`, `_setup_routers`, `_setup_exception_handlers`,
      `_setup_endpoints`, `_register_debug_endpoints`);
    * `request.client` проверяется на `None` перед `.host`;
    * `route.path` извлекается явным `getattr` с fallback-строкой вместо
      `str(route)` (repr `BaseRoute` не гарантирован);
    * `uvicorn.Server` сохраняется в локальную переменную перед `serve()`.

Исправления проверки AuthMiddleware (Вариант 1):
    Starlette хранит в `user_middleware` ту фабрику/класс, что передали
    в `add_middleware`. Мы передаём обёртки (`_auth_factory` и т.п.),
    поэтому `mw.cls.__name__` равен `"_auth_factory"`, а не
    `"AuthMiddleware"`. Guard обновлён:
      * фабрики обёрнуты `functools.wraps`, у них есть `__wrapped__`;
      * `_middleware_is_auth(mw)` распознаёт `AuthMiddleware` и напрямую,
        и через `__wrapped__`, и через известное имя фабрики;
      * поведение в рантайме не изменено — `_auth_factory` по-прежнему
        создаёт настоящий `AuthMiddleware(app)` на каждый запрос;
      * в production при реальном отсутствии AuthMiddleware guard
        продолжает падать (fail-closed).
"""

import asyncio
import functools
from collections.abc import AsyncGenerator, Callable
from contextlib import asynccontextmanager, suppress
from typing import Any, Optional

import uvicorn
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from starlette.middleware.cors import CORSMiddleware
from starlette.types import ASGIApp

from ..config import settings
from ..db.repositories import MessageRepository
from ..exceptions import AppError, DatabaseError
from ..logger import api_logger
from ..middlewares.api import (
    APILoggingMiddleware,
    APIRateLimitMiddleware,
    AuthMiddleware,
    ExceptionHandlerMiddleware,
    MetricsMiddleware,
)
from ..models import datetime_now
from ..utils.decorators import handle_exception, log_exceptions
from ..ws.relay_handler import router as ws_relay_router
from .routers import (
    admin_router,
    automation_router,
    avanpost_router,
    bot_msgs_router,
    bot_sync_router,
    errors_router,
    push_router,
    reminders_router,
    stats_router,
    sync_router,
    teamdroid_router,
    utils_router,
)


def _is_dev_env() -> bool:
    """Проверка, что мы в development-окружении."""
    return (getattr(settings, "APP_ENV", "") or "").lower() in ("development", "dev")


# ============================================================
# MIDDLEWARE FACTORIES
# ============================================================
#
# Starlette типизирует `add_middleware` как
#     def add_middleware(self, middleware_class: _MiddlewareFactory[**P], *args: P.args, **kwargs: P.kwargs)
# Классы middleware этому протоколу удовлетворяют по рантайму, но статический
# анализатор не выводит из класса `ParamSpec`. Фабрики ниже имеют явные
# сигнатуры (аргументы проверяются при их вызове внутри), а переменные-обёртки
# типизированы как `Callable[..., ASGIApp]` — это ровно то, что ожидает
# `add_middleware` в рантайме, без «пустого» `ParamSpec` и без ложных
# `Unexpected argument (from ParamSpec 'P')`.
#
# `functools.wraps(...)` добавляется для интроспекции: у фабрики появляется
# `__wrapped__`, указывающий на реальный класс middleware. Это используется
# guard-проверкой `AuthMiddleware` ниже: Starlette хранит в `user_middleware`
# именно фабрику (`mw.cls.__name__ == "_auth_factory"`), поэтому проверить
# наличие AuthMiddleware напрямую по имени класса нельзя.


@functools.wraps(CORSMiddleware)
def _cors_factory(
    app: ASGIApp,
    *,
    allow_origins: list[str],
    allow_credentials: bool,
    allow_methods: list[str],
    allow_headers: list[str],
) -> ASGIApp:
    return CORSMiddleware(
        app,
        allow_origins=allow_origins,
        allow_credentials=allow_credentials,
        allow_methods=allow_methods,
        allow_headers=allow_headers,
    )


@functools.wraps(APIRateLimitMiddleware)
def _rate_limit_factory(app: ASGIApp, *, limit: int, period: int) -> ASGIApp:
    return APIRateLimitMiddleware(app, limit=limit, period=period)


@functools.wraps(AuthMiddleware)
def _auth_factory(app: ASGIApp) -> ASGIApp:
    return AuthMiddleware(app)


@functools.wraps(ExceptionHandlerMiddleware)
def _exception_handler_factory(app: ASGIApp) -> ASGIApp:
    return ExceptionHandlerMiddleware(app)


@functools.wraps(APILoggingMiddleware)
def _logging_factory(app: ASGIApp, *, component: str) -> ASGIApp:
    return APILoggingMiddleware(app, component=component)


@functools.wraps(MetricsMiddleware)
def _metrics_factory(app: ASGIApp) -> ASGIApp:
    return MetricsMiddleware(app)


# Тип, совместимый с тем, что `add_middleware` принимает в рантайме.
_MiddlewareFactory = Callable[..., ASGIApp]

_CorsFactory: _MiddlewareFactory = _cors_factory
_RateLimitFactory: _MiddlewareFactory = _rate_limit_factory
_AuthFactory: _MiddlewareFactory = _auth_factory
_ExceptionHandlerFactory: _MiddlewareFactory = _exception_handler_factory
_LoggingFactory: _MiddlewareFactory = _logging_factory
_MetricsFactory: _MiddlewareFactory = _metrics_factory


class APIManager:
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
        self._tasks: list[asyncio.Task[Any]] = []
        self._stop_event = asyncio.Event()

        self.host: str = settings.API_HOST
        self.port: int = settings.API_PORT

        self._message_repo = MessageRepository()

        api_logger.debug("✅ API Manager instance created")
        self._initialized = True

    # ============================================================
    # LIFESPAN
    # ============================================================

    @staticmethod
    @asynccontextmanager
    async def _lifespan(_app: FastAPI) -> AsyncGenerator[None]:
        api_logger.info("🚀 API starting up...")

        push_started = False
        if settings.WS_NOTIFY_ENABLED:
            try:
                from ..ws import push_notification_service

                await push_notification_service.start()
                push_started = True
                api_logger.info("✅ Push notification service started")
            except Exception as e:  # noqa: BLE001
                api_logger.error(f"❌ Failed to start push service: {e}", exc_info=True)
                await _safe_log_error(e, component="api", context={"phase": "lifespan_start_push_service"})
        else:
            api_logger.info("ℹ️ WS_NOTIFY_ENABLED=false, push service not started")

        try:
            yield
        finally:
            api_logger.info("⛔ API shutting down...")

            if push_started:
                try:
                    from ..ws import push_notification_service

                    await push_notification_service.stop()
                    api_logger.info("✅ Push notification service stopped")
                except Exception as e:  # noqa: BLE001
                    api_logger.error(f"❌ Failed to stop push service: {e}", exc_info=True)

            # --- остановка Teamdroid-клиента ---
            try:
                from .routers.teamdroid import shutdown_teamdroid_client

                # shutdown_teamdroid_client синхронный, но может блокировать
                # при закрытии gRPC-канала. Вызываем в отдельном потоке.
                await asyncio.to_thread(shutdown_teamdroid_client)
                api_logger.info("✅ Teamdroid client stopped")
            except Exception as e:  # noqa: BLE001
                api_logger.error(f"❌ Failed to stop Teamdroid client: {e}", exc_info=True)
            # --- конец блока ---

            try:
                from ..bot.dependencies import get_bot_manager

                bot_manager = get_bot_manager()
                status = await bot_manager.get_status()
                if status.get("is_running", False):
                    await bot_manager.stop()
                else:
                    api_logger.info("ℹ️ Telegram manager was not running")
            except Exception as e:  # noqa: BLE001
                api_logger.error(f"❌ Telegram manager stopping failed: {e}", exc_info=True)

    # ============================================================
    # INITIALIZATION
    # ============================================================

    @log_exceptions(api_logger)
    async def initialize(self) -> None:
        if self._initialized and self._app is not None:
            api_logger.warning("⚠️ API Manager already initialized")
            return

        api_logger.debug("🚀 API Manager initializing...")

        # ── Safety check: refuse `trust` mode in production ──────────────
        env = (getattr(settings, "APP_ENV", "production") or "").lower()
        verify = settings.ws_notify_verify_mode
        if settings.WS_NOTIFY_ENABLED and verify == "trust" and env not in ("development", "dev"):
            raise RuntimeError(
                "WS_NOTIFY_TOKEN_VERIFY_MODE='trust' is only allowed when "
                f"APP_ENV=development, but APP_ENV='{env}'. "
                "Set WS_NOTIFY_TOKEN_VERIFY_MODE='grpc' or 'avanpost' "
                "or APP_ENV='development'."
            )

        # ── Safety check: relay auth token must be set in production ─────
        if (
            settings.WS_NOTIFY_ENABLED
            and not _is_dev_env()
            and not (getattr(settings, "WS_RELAY_AUTH_TOKEN", "") or "").strip()
        ):
            raise RuntimeError(
                "WS_RELAY_AUTH_TOKEN is empty in production. "
                "Set it in .env and mirror it into tinode.conf "
                "(push -> myrelay -> auth_token)."
            )

        api_keys = getattr(settings, "API_KEYS", []) or []
        api_logger.info("=" * 60)
        api_logger.info("🔧 Environment configuration:")
        api_logger.info(f"   APP_ENV          = {env}")
        api_logger.info(f"   APP_DEBUG        = {getattr(settings, 'APP_DEBUG', False)}")
        api_logger.info(f"   API_KEYS count   = {len(api_keys)}")
        api_logger.info(f"   API_HOST         = {self.host}")
        api_logger.info(f"   API_PORT         = {self.port}")
        api_logger.info(f"   WS_NOTIFY_ENABLED= {settings.WS_NOTIFY_ENABLED}")
        api_logger.info(f"   WS_VERIFY_MODE   = {verify}")
        api_logger.info(f"   WS_PATH          = {settings.WS_NOTIFY_PATH or '/ws/notify'}")
        api_logger.info("   RELAY_INGEST     = /internal/push")
        api_logger.info("=" * 60)

        self._app = FastAPI(
            title="TeamBot API",
            version="1.0.0",
            description="API для управления Telegram ботом TeamBot",
            docs_url="/api/docs",
            redoc_url="/api/redoc",
            openapi_url="/api/openapi.json",
            lifespan=APIManager._lifespan,
        )

        api_logger.info("🔧 [1/4] Setting up middleware...")
        self._setup_middleware()
        api_logger.info("🔧 [2/4] Setting up routers...")
        self._setup_routers()
        api_logger.info("🔧 [3/4] Setting up exception handlers...")
        self._setup_exception_handlers()
        api_logger.info("🔧 [4/4] Setting up endpoints...")
        self._setup_endpoints()

        # После setup `self._app` гарантированно не None (создан выше).
        app = self._app
        assert app is not None  # for type checkers

        api_logger.info("=" * 60)
        api_logger.info("📋 Registered middleware (order in `user_middleware`):")
        for idx, mw in enumerate(app.user_middleware):
            cls = mw.cls
            cls_name = getattr(cls, "__name__", type(cls).__name__)
            wrapped = getattr(cls, "__wrapped__", None)
            wrapped_name: str | None = None
            if wrapped is not None:
                name = getattr(wrapped, "__name__", None)
                if isinstance(name, str) and name:
                    wrapped_name = name

            if wrapped_name is not None:
                api_logger.info(f"   [{idx}] {cls_name} (wrapped: {wrapped_name})")
            else:
                api_logger.info(f"   [{idx}] {cls_name}")
        api_logger.info("=" * 60)

        # Проверка наличия AuthMiddleware. Starlette хранит в `user_middleware`
        # именно ту фабрику, что передана в `add_middleware`, поэтому `cls`
        # здесь — обёртка (`_auth_factory`), а не сам `AuthMiddleware`.
        # Распознаём обёртку по `__wrapped__` (благодаря functools.wraps) и по
        # известному имени фабрики; прямое совпадение оставляем для случая,
        # если когда-нибудь передадут класс напрямую.
        auth_present = any(_middleware_is_auth(mw) for mw in app.user_middleware)

        if not auth_present:
            msg = "🚨 CRITICAL: AuthMiddleware is NOT registered! API is running WITHOUT authentication!"
            api_logger.error(msg)
            if not _is_dev_env():
                raise RuntimeError(msg)
        else:
            api_logger.info("✅ AuthMiddleware is registered")

        self._initialized = True
        api_logger.info("✅ API Manager initialized")

    # ============================================================
    # MIDDLEWARE
    # ============================================================

    def _setup_middleware(self) -> None:
        if self._app is None:
            raise RuntimeError("App not initialized")

        # Сужаем тип: локальная переменная `app` гарантированно `FastAPI`.
        app: FastAPI = self._app

        # Pyright не умеет связывать ParamSpec 'P' в `add_middleware`
        # (Starlette: `def add_middleware(self, middleware_class: _MiddlewareFactory[P], *args: P.args, **kwargs: P.kwargs)`),
        # из-за чего ЛЮБОЙ именованный аргумент ловится как
        # `Unexpected argument (from ParamSpec 'P')`.
        # Обращаемся к методу через `Any`-инстанс, чтобы обойти разворачивание
        # сигнатуры; реальная проверка аргументов остаётся в фабриках.
        app_any: Any = app

        # Порядок: add_middleware кладёт в начало стека.
        # Итоговый порядок в `user_middleware` — обратный порядку вызовов.
        app_any.add_middleware(
            _CorsFactory,
            allow_origins=["*"],
            allow_credentials=True,
            allow_methods=["*"],
            allow_headers=["*"],
        )
        app_any.add_middleware(
            _RateLimitFactory,
            limit=getattr(settings, "API_RATE_LIMIT", 100),
            period=getattr(settings, "API_RATE_PERIOD", 60),
        )
        app_any.add_middleware(_AuthFactory)
        app_any.add_middleware(_ExceptionHandlerFactory)
        app_any.add_middleware(_LoggingFactory, component="api")
        app_any.add_middleware(_MetricsFactory)

    # ============================================================
    # ROUTERS
    # ============================================================

    def _setup_routers(self) -> None:
        if self._app is None:
            raise RuntimeError("App not initialized")

        app: FastAPI = self._app

        # Public business API.
        app.include_router(admin_router, prefix="/api/v1")
        app.include_router(bot_msgs_router, prefix="/api/v1")
        app.include_router(bot_sync_router, prefix="/api/v1")
        app.include_router(avanpost_router, prefix="/api/v1")
        app.include_router(errors_router, prefix="/api/v1")
        app.include_router(reminders_router, prefix="/api/v1")
        app.include_router(automation_router, prefix="/api/v1")
        app.include_router(push_router, prefix="/api/v1")
        app.include_router(stats_router, prefix="/api/v1")
        app.include_router(sync_router, prefix="/api/v1")
        app.include_router(teamdroid_router, prefix="/api/v1")
        app.include_router(utils_router, prefix="/api/v1")

        # Internal ingest from the Go myrelay adapter. Not prefixed with /api/v1
        # so it can be firewalled separately.
        if settings.WS_NOTIFY_ENABLED:
            app.include_router(ws_relay_router)

            # WebSocket endpoint for mobile clients.
            from ..ws.router import ws_notify_handler

            ws_path = settings.WS_NOTIFY_PATH or "/ws/notify"
            app.add_api_websocket_route(ws_path, ws_notify_handler)

            api_logger.info(f"✅ Routers registered; WS endpoint at {ws_path}; relay ingest at POST /internal/push")
        else:
            api_logger.info("ℹ️ WS_NOTIFY_ENABLED=false: relay ingest and WS endpoint are NOT registered")

    # ============================================================
    # EXCEPTION HANDLERS
    # ============================================================

    def _setup_exception_handlers(self) -> None:
        if self._app is None:
            raise RuntimeError("App not initialized")

        app: FastAPI = self._app

        @app.exception_handler(DatabaseError)
        async def database_error_handler(request: Request, exc: DatabaseError) -> JSONResponse:
            api_logger.error(f"❌ Database error: {exc}")
            await _safe_log_error(
                exc,
                component="database",
                context={"path": request.url.path, "method": request.method},
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

        @app.exception_handler(AppError)
        async def app_error_handler(request: Request, exc: AppError) -> JSONResponse:
            await handle_exception(exc)
            await _safe_log_error(
                exc,
                component="api",
                context={"path": request.url.path, "method": request.method},
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

        @app.exception_handler(Exception)
        async def global_exception_handler(request: Request, exc: Exception) -> JSONResponse:
            await handle_exception(exc)
            await _safe_log_error(
                exc,
                component="api",
                context={"path": request.url.path, "method": request.method},
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

    # ============================================================
    # ENDPOINTS
    # ============================================================

    def _setup_endpoints(self) -> None:
        if self._app is None:
            raise RuntimeError("App not initialized")

        app: FastAPI = self._app
        ws_path = settings.WS_NOTIFY_PATH or "/ws/notify"

        @app.get("/")
        @log_exceptions(api_logger)
        async def root() -> dict[str, Any]:
            return {
                "name": "TeamBot API",
                "version": "1.0.0",
                "status": "running",
                "docs": "/api/docs",
                "redoc": "/api/redoc",
                "health": "/health",
                "ws": ws_path if settings.WS_NOTIFY_ENABLED else None,
                "relay_ingest": "/internal/push" if settings.WS_NOTIFY_ENABLED else None,
            }

        @app.get("/health")
        @log_exceptions(api_logger)
        async def health_simple() -> dict[str, Any]:
            return {"status": "ok", "timestamp": datetime_now().isoformat() + "Z"}

        @app.get("/version")
        @log_exceptions(api_logger)
        async def version() -> dict[str, Any]:
            return {
                "version": "1.0.0",
                "environment": getattr(settings, "APP_ENV", "production"),
                "debug": getattr(settings, "APP_DEBUG", False),
                "timestamp": datetime_now().isoformat() + "Z",
            }

        # ── Push-service stats ──
        if settings.WS_NOTIFY_ENABLED:

            @app.get("/api/v1/ws/stats")
            @log_exceptions(api_logger)
            async def ws_stats() -> dict[str, Any]:
                try:
                    from ..ws import push_notification_service

                    status = await push_notification_service.get_status()
                    status["timestamp"] = datetime_now().isoformat() + "Z"
                    return status
                except Exception as e:  # noqa: BLE001
                    return {
                        "error": str(e),
                        "timestamp": datetime_now().isoformat() + "Z",
                    }

        # ── Debug endpoints (only when APP_DEBUG=true in development) ──
        if _is_dev_env() and getattr(settings, "APP_DEBUG", False):
            self._register_debug_endpoints()

    def _register_debug_endpoints(self) -> None:
        """Регистрирует /debug/* эндпоинты. Только для development+APP_DEBUG."""
        if self._app is None:
            raise RuntimeError("App not initialized")

        app: FastAPI = self._app
        api_logger.info("🔧 Debug endpoints enabled (APP_DEBUG=true, dev mode)")

        @app.get("/debug/middleware")
        @log_exceptions(api_logger)
        async def debug_middleware() -> dict[str, Any]:
            registered = {mw.cls.__name__ for mw in app.user_middleware}
            return {
                "middleware_loaded": len(registered) > 0,
                "registered_middleware": sorted(registered),
                "auth_configured": any(_middleware_is_auth(mw) for mw in app.user_middleware),
                "cors_configured": "CORSMiddleware" in registered or "_cors_factory" in registered,
                "rate_limit_configured": "APIRateLimitMiddleware" in registered or "_rate_limit_factory" in registered,
                "logging_configured": "APILoggingMiddleware" in registered or "_logging_factory" in registered,
                "metrics_configured": "MetricsMiddleware" in registered or "_metrics_factory" in registered,
                "exception_handler_configured": "ExceptionHandlerMiddleware" in registered
                or "_exception_handler_factory" in registered,
                "timestamp": datetime_now().isoformat() + "Z",
            }

        @app.get("/debug/middleware-info")
        @log_exceptions(api_logger)
        async def debug_middleware_info() -> dict[str, Any]:
            middleware_list = [
                {
                    "class": mw.cls.__name__,
                    "wrapped": getattr(getattr(mw.cls, "__wrapped__", None), "__name__", None),
                    "args": [str(a) for a in getattr(mw, "args", [])],
                    "kwargs": {k: str(v) for k, v in getattr(mw, "kwargs", {}).items()},
                }
                for mw in app.user_middleware
            ]
            return {
                "count": len(middleware_list),
                "middleware": middleware_list,
                "auth_present": any(_middleware_is_auth(mw) for mw in app.user_middleware),
                "timestamp": datetime_now().isoformat() + "Z",
            }

        @app.get("/debug/auth-config")
        @log_exceptions(api_logger)
        async def debug_auth_config() -> dict[str, Any]:
            keys = getattr(settings, "API_KEYS", []) or []
            return {
                "api_keys_count": len(keys),
                "api_keys_configured": len(keys) > 0,
                "api_keys_lengths": [len(str(k)) for k in keys],
                "public_paths_count": len(AuthMiddleware.PUBLIC_PATHS),
                "public_paths": AuthMiddleware.PUBLIC_PATHS,
                "app_env": getattr(settings, "APP_ENV", "unknown"),
                "app_debug": getattr(settings, "APP_DEBUG", False),
                "ws_verify_mode": settings.ws_notify_verify_mode,
                "timestamp": datetime_now().isoformat() + "Z",
            }

        @app.get("/debug/headers")
        @log_exceptions(api_logger)
        async def debug_headers(request: Request) -> dict[str, Any]:
            headers = dict(request.headers)
            for k in ("authorization", "x-api-key"):
                if k in headers:
                    headers[k] = "***"

            # Явное сужение типа: `request.client` имеет тип `Address | None`.
            client = request.client
            if client is not None:
                client_host = client.host
            else:
                client_host = "unknown"

            return {
                "headers": headers,
                "client": client_host,
                "method": request.method,
                "url": str(request.url),
            }

        @app.get("/debug/bot-status")
        @log_exceptions(api_logger)
        async def debug_bot_status() -> dict[str, Any]:
            try:
                from ..bot.dependencies import get_bot_manager

                bot_manager = get_bot_manager()
                status = await bot_manager.get_status()
                return {"bot": status, "timestamp": datetime_now().isoformat() + "Z"}
            except Exception as e:  # noqa: BLE001
                return {"error": str(e), "timestamp": datetime_now().isoformat() + "Z"}

        @app.get("/debug/routes")
        @log_exceptions(api_logger)
        async def debug_routes() -> dict[str, Any]:
            routes: list[dict[str, Any]] = []
            for route in app.routes:
                methods = getattr(route, "methods", None)
                # `BaseRoute` не гарантирует `__str__`/`__repr__`, поэтому
                # берём `path` явно и падаем в строковый литерал, а не в repr.
                raw_path = getattr(route, "path", None)
                path_repr = raw_path if isinstance(raw_path, str) else "<unknown>"
                info: dict[str, Any] = {
                    "path": path_repr,
                    "name": getattr(route, "name", None),
                    "methods": (
                        sorted(str(m) for m in methods) if isinstance(methods, (set, frozenset, list, tuple)) else []
                    ),
                }
                routes.append(info)
            return {
                "total_routes": len(routes),
                "routes": routes,
                "timestamp": datetime_now().isoformat() + "Z",
            }

    # ============================================================
    # PROPERTIES
    # ============================================================

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

    # ============================================================
    # LIFECYCLE (START / STOP / RESTART)
    # ============================================================

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
            # Сужаем `uvicorn.Server | None` до `uvicorn.Server` через локальную
            # переменную: Pyright не знает, что `self._server` не перезапишут
            # между присваиванием и вызовом `.serve()`.
            server = uvicorn.Server(config)
            self._server = server
            await server.serve()
        except asyncio.CancelledError:
            raise
        except Exception as e:  # noqa: BLE001
            api_logger.error(f"❌ API Server failed: {e}", exc_info=True)
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
            except Exception as e:  # noqa: BLE001
                api_logger.error(f"❌ API Server stopping failed: {e}", exc_info=True)
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
        await self.stop()
        await asyncio.sleep(0.5)
        await self.start()

    async def get_status(self) -> dict[str, Any]:
        return {
            "is_running": self._is_running,
            "is_initialized": self._initialized,
            "tasks_count": len(self._tasks),
            "host": self.host,
            "port": self.port,
            "has_app": self._app is not None,
            "ws_notify_enabled": settings.WS_NOTIFY_ENABLED,
        }

    async def health_check(self) -> bool:
        return self._is_running and self._app is not None


# ============================================================
# HELPERS
# ============================================================


def _middleware_is_auth(mw: Any) -> bool:
    """Проверяет, что запись `user_middleware` соответствует AuthMiddleware.

    Starlette хранит в `user_middleware` ту фабрику/класс, что передана в
    `add_middleware`. В этом проекте передаются обёртки-фабрики
    (`_auth_factory` и т.п.), поэтому `mw.cls.__name__` равен
    `"_auth_factory"`, а не `"AuthMiddleware"`. Распознаём тремя способами:

    1. Прямое совпадение `cls.__name__ == "AuthMiddleware"` — на случай,
       если когда-нибудь передадут класс напрямую (без фабрики).
    2. Совпадение по `cls.__wrapped__` — благодаря `functools.wraps` у
       фабрики есть `__wrapped__`, указывающий на исходный класс.
    3. Совпадение по известному имени фабрики `"_auth_factory"` — страховка,
       если `functools.wraps` по какой-то причине не сработал.
    """
    cls = getattr(mw, "cls", None)
    if cls is None:
        return False

    cls_name = getattr(cls, "__name__", "")
    if cls_name == "AuthMiddleware":
        return True

    wrapped = getattr(cls, "__wrapped__", None)
    if getattr(wrapped, "__name__", "") == "AuthMiddleware":
        return True

    if cls_name == "_auth_factory":
        return True

    return False


async def _safe_log_error(exc: Exception, component: str, context: dict[str, Any] | None = None) -> None:
    """Безопасно логирует ошибку через error_service.

    Не роняет приложение, если error_service недоступен.
    """
    try:
        from ..services import error_service

        await error_service.log_error(error=exc, component=component, context=context or {})
    except Exception as log_exc:  # noqa: BLE001
        api_logger.warning(f"⚠️ error_service.log_error failed: {log_exc}")


api_manager = APIManager()

__all__ = ["APIManager", "api_manager"]
