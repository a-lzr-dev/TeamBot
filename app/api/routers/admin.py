from typing import Any

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from ...db import db_manager
from ...exceptions import DatabaseError, log_exceptions
from ...logger import api_logger
from ...utils.datetime import get_timestamp

router = APIRouter(tags=["Admin"])


class HealthResponse(BaseModel):
    """Модель ответа для health check"""

    status: str = Field(..., description="Статус API")
    timestamp: str = Field(..., description="Время проверки")


class DatabaseHealthResponse(BaseModel):
    """Модель ответа для проверки БД"""

    status: str = Field(..., description="Статус сервиса (ready/not ready)")
    database: str = Field(..., description="Статус подключения к БД (connected/disconnected)")
    timestamp: str = Field(..., description="Время проверки")


class ServiceStatusResponse(BaseModel):
    """Модель статуса сервиса"""

    service: str = Field(..., description="Название сервиса")
    status: str = Field(..., description="Статус сервиса (ok/error/unavailable)")
    details: dict[str, Any] | None = Field(None, description="Дополнительная информация")


class FullHealthResponse(BaseModel):
    """Модель полной проверки здоровья"""

    api: ServiceStatusResponse
    database: ServiceStatusResponse
    telegram: ServiceStatusResponse
    timestamp: str = Field(..., description="Время проверки")
    overall_status: str = Field(..., description="Общий статус (healthy/degraded/unhealthy)")


class StatsResponse(BaseModel):
    """Модель статистики"""

    database: dict[str, Any] = Field(..., description="Статистика БД")
    telegram: dict[str, Any] = Field(..., description="Статистика Telegram")
    timestamp: str = Field(..., description="Время получения статистики")


# ============ Вспомогательные функции ============
def create_service_status(service: str, status: str, details: dict[str, Any] | None = None) -> dict[str, Any]:
    """Создание объекта статуса сервиса"""
    return {"service": service, "status": status, "details": details or {}}


# ============ Эндпоинты ============
@router.get(
    "/health",
    response_model=HealthResponse,
    summary="Проверка здоровья API",
    description="Простая проверка, что API работает",
    tags=["Health"],
)
@log_exceptions(api_logger)
async def health_check() -> dict[str, Any]:
    """Health check эндпоинт"""
    api_logger.debug("✅ Health check requested")
    return {"status": "ok", "timestamp": get_timestamp()}


@router.get("/ping", summary="Ping эндпоинт", description="Простой пинг для проверки доступности", tags=["Health"])
@log_exceptions(api_logger)
async def ping() -> dict[str, str]:
    """Простой пинг для проверки доступности"""
    return {"pong": "ok", "timestamp": get_timestamp()}


@router.get(
    "/ready",
    summary="Проверка готовности",
    description="Проверка готовности для Kubernetes/оркестрации",
    tags=["Health"],
)
@log_exceptions(api_logger)
async def readiness() -> JSONResponse:
    """Проверка готовности всех сервисов"""
    api_logger.debug("🔍 Readiness check requested")

    errors = []

    # Проверка БД
    try:
        is_connected = await db_manager.check_connection()
        if not is_connected:
            errors.append("database unavailable")
            api_logger.warning("⚠️ Database unavailable")
    except Exception as e:
        api_logger.error(f"❌ Database check failed: {e}")
        errors.append(f"database error: {str(e)}")

    # Проверка Telegram
    try:
        from ...tg import tg_manager

        status = await tg_manager.get_status()
        if not status.get("is_running", False):
            errors.append("telegram bot not running")
            api_logger.warning("⚠️ Telegram bot not running")
    except Exception as e:
        api_logger.error(f"❌ Telegram check failed: {e}")
        errors.append(f"telegram error: {str(e)}")

    if errors:
        return JSONResponse(
            status_code=503, content={"status": "not ready", "reason": errors, "timestamp": get_timestamp()}
        )

    api_logger.info("✅ All services ready")
    return JSONResponse(status_code=200, content={"status": "ready", "timestamp": get_timestamp()})


@router.get(
    "/health/db",
    response_model=DatabaseHealthResponse,
    summary="Проверка подключения к БД",
    description="Проверяет доступность базы данных",
    tags=["Health", "Database"],
)
@log_exceptions(api_logger)
async def database_health_check() -> JSONResponse:
    """Проверка подключения к базе данных"""
    api_logger.debug("🔍 Database health check requested")

    try:
        is_connected = await db_manager.check_connection()

        if is_connected:
            api_logger.debug("✅ Database connection OK")
            return JSONResponse(
                status_code=200, content={"status": "ready", "database": "connected", "timestamp": get_timestamp()}
            )
        else:
            api_logger.warning("⚠️ Database connection failed")
            return JSONResponse(
                status_code=503,
                content={"status": "not ready", "database": "disconnected", "timestamp": get_timestamp()},
            )

    except Exception as e:
        api_logger.error(f"❌ Database health check error: {e}", exc_info=True)
        raise DatabaseError(f"Database health check failed: {e}") from e


@router.get(
    "/health/full",
    response_model=FullHealthResponse,
    summary="Полная проверка всех сервисов",
    description="Проверяет состояние API, БД и Telegram",
    tags=["Health"],
)
@log_exceptions(api_logger)
async def full_health_check() -> dict[str, Any]:
    """Комплексная проверка всех сервисов"""
    api_logger.info("🔍 Full health check requested")

    # Статус API
    api_status = create_service_status("api", "ok", {"version": "1.0.0"})

    # Статус БД
    db_details = {}
    db_status = "ok"
    try:
        is_connected = await db_manager.check_connection()
        if is_connected:
            try:
                stats = await db_manager.get_stats()
                db_details.update(stats)
            except Exception as e:
                api_logger.warning(f"Could not get DB stats: {e}")
                db_details["stats_error"] = str(e)
        else:
            db_status = "error"
            db_details["error"] = "Database connection failed"
    except Exception as e:
        db_status = "error"
        db_details["error"] = str(e)
        api_logger.error(f"DB health check failed: {e}")

    database_status = create_service_status("database", db_status, db_details)

    # Статус Telegram
    tg_details = {}
    tg_status = "ok"
    try:
        from ...tg import tg_manager

        status_info = await tg_manager.get_status()
        tg_details = {
            "is_running": status_info.get("is_running", False),
            "is_initialized": status_info.get("is_initialized", False),
            "tasks_count": status_info.get("tasks_count", 0),
        }
        if not status_info.get("is_running", False):
            tg_status = "error"
            tg_details["error"] = "Telegram bot is not running"
    except Exception as e:
        tg_status = "error"
        tg_details["error"] = str(e)
        api_logger.error(f"Telegram health check failed: {e}")

    telegram_status = create_service_status("telegram", tg_status, tg_details)

    # Определение общего статуса
    statuses = [api_status["status"], database_status["status"], telegram_status["status"]]
    if all(s == "ok" for s in statuses):
        overall = "healthy"
    elif any(s == "error" for s in statuses):
        overall = "unhealthy"
    else:
        overall = "degraded"

    response = {
        "api": api_status,
        "database": database_status,
        "telegram": telegram_status,
        "timestamp": get_timestamp(),
        "overall_status": overall,
    }

    if overall == "healthy":
        api_logger.info("✅ All services healthy")
    elif overall == "degraded":
        api_logger.warning("⚠️ Some services degraded")
    else:
        api_logger.error("❌ Services unhealthy")

    return response


@router.get(
    "/stats",
    response_model=StatsResponse,
    summary="Получение статистики",
    description="Получение статистики по БД и Telegram",
    tags=["Stats"],
)
@log_exceptions(api_logger)
async def get_stats() -> dict[str, Any]:
    """Получение статистики всех сервисов"""
    api_logger.info("📊 Stats requested")

    stats = {"database": {}, "telegram": {}, "timestamp": get_timestamp()}

    # Статистика БД
    try:
        db_stats = await db_manager.get_stats()
        stats["database"] = db_stats
        api_logger.debug("✅ Database stats collected")
    except Exception as e:
        api_logger.error(f"❌ Failed to get database stats: {e}")
        stats["database"] = {"error": str(e)}

    # Статистика Telegram
    try:
        from ...tg import tg_manager

        tg_stats = await tg_manager.get_status()
        stats["telegram"] = tg_stats
        api_logger.debug("✅ Telegram stats collected")
    except Exception as e:
        api_logger.error(f"❌ Failed to get telegram stats: {e}")
        stats["telegram"] = {"error": str(e)}

    return stats


@router.get("/metrics", summary="Метрики API", description="Получение метрик API (только для админов)", tags=["Stats"])
@log_exceptions(api_logger)
async def get_metrics(request: Request) -> dict[str, Any]:
    """Получение метрик API"""
    api_logger.info("📊 Metrics requested")

    metrics = {}

    if hasattr(request.app.state, "metrics_middleware"):
        try:
            metrics = request.app.state.metrics_middleware.get_metrics()
            api_logger.debug("✅ Metrics collected from middleware")
        except Exception as e:
            api_logger.error(f"❌ Failed to get metrics from middleware: {e}")
            metrics["error"] = str(e)
    else:
        metrics["message"] = "Metrics middleware not configured"

    return {"metrics": metrics, "timestamp": get_timestamp()}


@router.post(
    "/metrics/reset", summary="Сброс метрик", description="Сброс метрик API (только для админов)", tags=["Stats"]
)
@log_exceptions(api_logger)
async def reset_metrics(request: Request) -> dict[str, str]:
    """Сброс метрик API"""
    api_logger.info("🔄 Metrics reset requested")

    if hasattr(request.app.state, "metrics_middleware"):
        try:
            request.app.state.metrics_middleware.reset_metrics()
            api_logger.info("✅ Metrics reset successfully")
            return {"status": "success", "message": "Metrics reset successfully", "timestamp": get_timestamp()}
        except Exception as e:
            api_logger.error(f"❌ Failed to reset metrics: {e}")
            raise HTTPException(status_code=500, detail=f"Failed to reset metrics: {e}") from e
    else:
        raise HTTPException(status_code=404, detail="Metrics middleware not configured")


__all__ = ["router"]
