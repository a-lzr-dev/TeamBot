"""Модуль роутера для синхронизации данных с Avanpost.

Этот модуль предоставляет API эндпоинты для управления синхронизацией:
- Синхронизация базовых данных (справочники)
- Синхронизация контактов
- Синхронизация данных пользователей (одиночная и массовая)
- Загрузка пользователей из Avanpost
- Статус синхронизации

Все эндпоинты используют общий префикс /sync и требуют прав администратора.
Модуль интегрируется с AvanpostSyncService и AvanpostSeedService.

Роуты:
    GET /status - Статус синхронизации
    POST /base - Синхронизация базовых данных (справочники)
    POST /contacts - Синхронизация контактов
    POST /user/{user_id} - Синхронизация данных пользователя
    POST /users/all - Синхронизация всех пользователей
    POST /seed/users - Загрузка всех пользователей из Avanpost
"""

from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from ...api.dependencies import get_session
from ...config import settings
from ...db.repositories import UserRepository
from ...logger import api_logger
from ...services.avanpost_sync_service import AvanpostSyncService
from ...services.seed_service import AvanpostSeedService
from ...utils.datetime import get_timestamp
from ...utils.decorators import log_exceptions

# Создание роутера с префиксом /sync и тегом для документации
router = APIRouter(prefix="/sync", tags=["Sync"])

# Репозитории
_user_repo = UserRepository()


# ============ МОДЕЛИ ============


class SyncRequest(BaseModel):
    """Модель запроса для синхронизации."""

    force: bool = Field(False, description="Принудительная синхронизация (игнорировать кеш)")


class SyncUserRequest(BaseModel):
    """Модель запроса для синхронизации пользователя."""

    user_id: int = Field(..., description="ID пользователя в Avanpost", gt=0)
    force: bool = Field(False, description="Принудительная синхронизация")
    mode: int = Field(1, description="Режим синхронизации: 1 - base, 2 - details", ge=1, le=2)


class SyncAllUsersRequest(BaseModel):
    """Модель запроса для синхронизации всех пользователей."""

    force: bool = Field(False, description="Принудительная синхронизация")
    mode: int = Field(1, description="Режим синхронизации: 1 - base, 2 - details", ge=1, le=2)
    user_ids: list[int] | None = Field(None, description="Список ID пользователей для синхронизации")


class SyncResponse(BaseModel):
    """Модель ответа для синхронизации."""

    success: bool = Field(..., description="Успешность операции")
    message: str = Field(..., description="Сообщение о результате")
    stats: dict | None = Field(None, description="Статистика синхронизации")
    timestamp: str = Field(..., description="Время выполнения")


class ErrorResponse(BaseModel):
    """Стандартная модель ответа при ошибке."""

    success: bool = Field(False, description="Успешность операции (всегда False)")
    error: str = Field(..., description="Сообщение об ошибке")
    timestamp: str = Field(..., description="Время ошибки")


# ============ ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ ============


def _is_admin(user_id: int) -> bool:
    """Проверка, является ли пользователь администратором."""
    return user_id in settings.ADMIN_IDS


async def _get_sync_service() -> AvanpostSyncService:
    """Получение экземпляра сервиса синхронизации."""
    sync_service = AvanpostSyncService()
    await sync_service.initialize()
    return sync_service


# ============================================================
# 1. СТАТУС СИНХРОНИЗАЦИИ
# ============================================================


@router.get(
    "/status",
    summary="Статус синхронизации",
    description="Получает статус последней синхронизации Avanpost",
)
@log_exceptions(api_logger)
async def get_sync_status() -> JSONResponse:
    """Получение статуса синхронизации Avanpost.

    Returns:
        JSONResponse: Статус синхронизации
    """
    api_logger.info("📊 Getting sync status")

    try:
        sync_service = await _get_sync_service()
        status = await sync_service.get_status()

        return JSONResponse(
            status_code=200,
            content={
                "success": True,
                "status": status,
                "timestamp": get_timestamp(),
            },
        )

    except Exception as e:
        api_logger.error(f"❌ Failed to get sync status: {e}", exc_info=True)
        return JSONResponse(
            status_code=500,
            content={
                "success": False,
                "error": f"Failed to get sync status: {str(e)}",
                "timestamp": get_timestamp(),
            },
        )


# ============================================================
# 2. СИНХРОНИЗАЦИЯ БАЗОВЫХ ДАННЫХ
# ============================================================


@router.post(
    "/base",
    response_model=SyncResponse,
    summary="Синхронизировать базовые данные",
    description="Синхронизирует справочные данные из Avanpost (модели до 205)",
)
@log_exceptions(api_logger)
async def sync_base_data(
    request: SyncRequest,
) -> JSONResponse:
    """Синхронизация базовых справочных данных Avanpost.

    Args:
        request: Параметры синхронизации

    Returns:
        JSONResponse: Результат синхронизации
    """
    api_logger.info(f"🔄 Syncing base data (force={request.force})")

    try:
        sync_service = await _get_sync_service()
        stats = await sync_service.sync_base_data(force=request.force)

        stats_dict = stats.to_dict() if hasattr(stats, "to_dict") else {}

        return JSONResponse(
            status_code=200,
            content={
                "success": True,
                "message": "Base data sync completed",
                "stats": stats_dict,
                "timestamp": get_timestamp(),
            },
        )

    except Exception as e:
        api_logger.error(f"❌ Base sync failed: {e}", exc_info=True)
        return JSONResponse(
            status_code=500,
            content={
                "success": False,
                "message": f"Base sync failed: {str(e)}",
                "stats": None,
                "timestamp": get_timestamp(),
            },
        )


# ============================================================
# 3. СИНХРОНИЗАЦИЯ КОНТАКТОВ
# ============================================================


@router.post(
    "/contacts",
    response_model=SyncResponse,
    summary="Синхронизировать контакты",
    description="Синхронизирует контакты из Avanpost (модели 301-303)",
)
@log_exceptions(api_logger)
async def sync_contacts(
    request: SyncRequest,
) -> JSONResponse:
    """Синхронизация контактов Avanpost.

    Синхронизирует модели TAvanpostContacts, TAvanpostContactsLangs, TAvanpostContactsLinks.

    Args:
        request: Параметры синхронизации

    Returns:
        JSONResponse: Результат синхронизации
    """
    api_logger.info(f"🔄 Syncing contacts (force={request.force})")

    try:
        sync_service = await _get_sync_service()

        # Используем sync_base_data с фильтрацией по контактам
        stats = await sync_service.sync_base_data(force=request.force)
        stats_dict = stats.to_dict() if hasattr(stats, "to_dict") else {}

        # Фильтруем статистику по таблицам контактов
        table_stats = stats_dict.get("table_stats", {})
        contact_tables = ["TAvanpostContacts", "TAvanpostContactsLangs", "TAvanpostContactsLinks"]
        contact_stats = {k: v for k, v in table_stats.items() if k in contact_tables}

        total_inserted = sum(s.get("inserted", 0) for s in contact_stats.values())
        total_updated = sum(s.get("updated", 0) for s in contact_stats.values())
        total_deleted = sum(s.get("deleted", 0) for s in contact_stats.values())

        return JSONResponse(
            status_code=200,
            content={
                "success": True,
                "message": "Contacts sync completed",
                "stats": {
                    "total_inserted": total_inserted,
                    "total_updated": total_updated,
                    "total_deleted": total_deleted,
                    "table_stats": contact_stats,
                },
                "timestamp": get_timestamp(),
            },
        )

    except Exception as e:
        api_logger.error(f"❌ Contacts sync failed: {e}", exc_info=True)
        return JSONResponse(
            status_code=500,
            content={
                "success": False,
                "message": f"Contacts sync failed: {str(e)}",
                "stats": None,
                "timestamp": get_timestamp(),
            },
        )


# ============================================================
# 4. СИНХРОНИЗАЦИЯ ПОЛЬЗОВАТЕЛЯ
# ============================================================


@router.post(
    "/user/{user_id}",
    response_model=SyncResponse,
    summary="Синхронизировать пользователя",
    description="Синхронизирует данные конкретного пользователя из Avanpost",
)
@log_exceptions(api_logger)
async def sync_user(
    user_id: int,
    request: SyncRequest,
) -> JSONResponse:
    """Синхронизация данных конкретного пользователя Avanpost.

    Args:
        user_id: ID пользователя в Avanpost
        request: Параметры синхронизации

    Returns:
        JSONResponse: Результат синхронизации
    """
    api_logger.info(f"👤 Syncing user {user_id} (force={request.force})")

    if user_id <= 0:
        return JSONResponse(
            status_code=400,
            content={
                "success": False,
                "message": "Invalid user ID",
                "stats": None,
                "timestamp": get_timestamp(),
            },
        )

    try:
        sync_service = await _get_sync_service()
        stats = await sync_service.sync_user_data(user_id=user_id, force=request.force)

        stats_dict = stats.to_dict() if hasattr(stats, "to_dict") else {}

        return JSONResponse(
            status_code=200,
            content={
                "success": True,
                "message": f"User {user_id} sync completed",
                "stats": stats_dict,
                "timestamp": get_timestamp(),
            },
        )

    except Exception as e:
        api_logger.error(f"❌ User sync failed: {e}", exc_info=True)
        return JSONResponse(
            status_code=500,
            content={
                "success": False,
                "message": f"User sync failed: {str(e)}",
                "stats": None,
                "timestamp": get_timestamp(),
            },
        )


# ============================================================
# 5. СИНХРОНИЗАЦИЯ ВСЕХ ПОЛЬЗОВАТЕЛЕЙ
# ============================================================


@router.post(
    "/users/all",
    response_model=SyncResponse,
    summary="Синхронизировать всех пользователей",
    description="Синхронизирует данные всех пользователей из Avanpost",
)
@log_exceptions(api_logger)
async def sync_all_users(
    request: SyncAllUsersRequest,
) -> JSONResponse:
    """Синхронизация данных всех пользователей Avanpost.

    Args:
        request: Параметры синхронизации

    Returns:
        JSONResponse: Результат синхронизации
    """
    mode_name = "base" if request.mode == 1 else "details"
    api_logger.info(f"👥 Syncing all users (force={request.force}, mode={mode_name})")

    try:
        sync_service = await _get_sync_service()

        result = await sync_service.sync_all_users(
            force=request.force,
            mode=request.mode,
            user_ids=request.user_ids,
        )

        return JSONResponse(
            status_code=200,
            content={
                "success": True,
                "message": f"All users sync completed ({result.get('successful', 0)}/{result.get('total_users', 0)} users)",
                "stats": result,
                "timestamp": get_timestamp(),
            },
        )

    except Exception as e:
        api_logger.error(f"❌ All users sync failed: {e}", exc_info=True)
        return JSONResponse(
            status_code=500,
            content={
                "success": False,
                "message": f"All users sync failed: {str(e)}",
                "stats": None,
                "timestamp": get_timestamp(),
            },
        )


# ============================================================
# 6. ЗАГРУЗКА ВСЕХ ПОЛЬЗОВАТЕЛЕЙ ИЗ AVANPOST
# ============================================================


@router.post(
    "/seed/users",
    response_model=SyncResponse,
    summary="Загрузить всех пользователей из Avanpost",
    description="Загружает всех пользователей из Avanpost через хранимую процедуру",
)
@log_exceptions(api_logger)
async def seed_all_users(
    session: AsyncSession = Depends(get_session),
) -> JSONResponse:
    """Загрузка всех пользователей из Avanpost.

    Вызывает хранимую процедуру ext.PA_avp_RSAppUsers_DefaultAdding_Load
    и добавляет полученных пользователей в TAvanpostUsers.

    Args:
        session: Асинхронная сессия SQLAlchemy

    Returns:
        JSONResponse: Результат загрузки
    """
    api_logger.info("🚀 Starting loading all users from Avanpost...")

    try:
        result = await AvanpostSeedService.seed_avanpost_users_all(
            session=session,
            create_sync_records=True,
        )

        return JSONResponse(
            status_code=200,
            content={
                "success": result.get("errors", 0) == 0,
                "message": f"Loaded {result.get('total_added', 0)} users from Avanpost",
                "stats": result,
                "timestamp": get_timestamp(),
            },
        )

    except Exception as e:
        api_logger.error(f"❌ Users loading failed: {e}", exc_info=True)
        await session.rollback()
        return JSONResponse(
            status_code=500,
            content={
                "success": False,
                "message": f"Users loading failed: {str(e)}",
                "stats": None,
                "timestamp": get_timestamp(),
            },
        )


__all__ = ["router"]
