"""
Модуль административных маршрутов API.

Предоставляет API эндпоинты для административных функций:
- Управление администраторами
- Синхронизация с Avanpost
- Загрузка пользователей из транспортных средств
- Статистика системы

Все эндпоинты используют общий префикс /admin и требуют прав администратора.
"""

from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from ...config import settings
from ...db.repositories import BroadcastRepository, ChatRepository, UserRepository
from ...logger import api_logger
from ...services.avanpost_sync_service import AvanpostSyncService
from ...services.seed_service import AvanpostSeedService
from ...utils import get_timestamp
from ...utils.decorators import log_exceptions
from ..dependencies import get_session

# Создание роутера с префиксом /admin и тегом для документации
router = APIRouter(prefix="/admin", tags=["Admin"])

# Репозитории (создаются один раз на уровне модуля для переиспользования)
_broadcast_repo = BroadcastRepository()
_chat_repo = ChatRepository()
_user_repo = UserRepository()


# ============ МОДЕЛИ ============


class AddAdminRequest(BaseModel):
    """Модель запроса для добавления администратора."""

    user_id: int = Field(..., description="ID пользователя для добавления в админы", gt=0)


class RemoveAdminRequest(BaseModel):
    """Модель запроса для удаления администратора."""

    user_id: int = Field(..., description="ID пользователя для удаления из админов", gt=0)


class SyncRequest(BaseModel):
    """Модель запроса для синхронизации."""

    force: bool = Field(False, description="Принудительная синхронизация (игнорировать кеш)")


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


# ============================================================
# 1. УПРАВЛЕНИЕ АДМИНИСТРАТОРАМИ
# ============================================================


@router.get(
    "/admins",
    summary="Список администраторов",
    description="Возвращает список всех администраторов",
)
@log_exceptions(api_logger)
async def get_admins() -> JSONResponse:
    """
    Получение списка администраторов.

    Returns:
        JSONResponse: Список ID администраторов
    """
    api_logger.info("👑 Getting admins list")

    return JSONResponse(
        status_code=200,
        content={
            "success": True,
            "admins": settings.ADMIN_IDS,
            "count": len(settings.ADMIN_IDS),
            "timestamp": get_timestamp(),
        },
    )


@router.post(
    "/admins/add",
    summary="Добавить администратора",
    description="Добавляет пользователя в список администраторов",
)
@log_exceptions(api_logger)
async def add_admin(
    request: AddAdminRequest,
) -> JSONResponse:
    """
    Добавление администратора.

    Args:
        request: Запрос с ID пользователя

    Returns:
        JSONResponse: Результат добавления
    """
    api_logger.info(f"➕ Adding admin: {request.user_id}")

    if request.user_id in settings.ADMIN_IDS:
        return JSONResponse(
            status_code=400,
            content={
                "success": False,
                "error": f"User {request.user_id} is already an admin",
                "timestamp": get_timestamp(),
            },
        )

    settings.ADMIN_IDS.append(request.user_id)

    api_logger.info(f"✅ Admin {request.user_id} added")

    return JSONResponse(
        status_code=200,
        content={
            "success": True,
            "message": f"User {request.user_id} added to admins",
            "admins": settings.ADMIN_IDS,
            "timestamp": get_timestamp(),
        },
    )


@router.post(
    "/admins/remove",
    summary="Удалить администратора",
    description="Удаляет пользователя из списка администраторов",
)
@log_exceptions(api_logger)
async def remove_admin(
    request: RemoveAdminRequest,
) -> JSONResponse:
    """
    Удаление администратора.

    Args:
        request: Запрос с ID пользователя

    Returns:
        JSONResponse: Результат удаления
    """
    api_logger.info(f"➖ Removing admin: {request.user_id}")

    if len(settings.ADMIN_IDS) <= 1:
        return JSONResponse(
            status_code=400,
            content={
                "success": False,
                "error": "Cannot remove the last admin",
                "timestamp": get_timestamp(),
            },
        )

    if request.user_id not in settings.ADMIN_IDS:
        return JSONResponse(
            status_code=404,
            content={
                "success": False,
                "error": f"User {request.user_id} is not an admin",
                "timestamp": get_timestamp(),
            },
        )

    settings.ADMIN_IDS.remove(request.user_id)

    api_logger.info(f"✅ Admin {request.user_id} removed")

    return JSONResponse(
        status_code=200,
        content={
            "success": True,
            "message": f"User {request.user_id} removed from admins",
            "admins": settings.ADMIN_IDS,
            "timestamp": get_timestamp(),
        },
    )


# ============================================================
# 2. СИНХРОНИЗАЦИЯ AVANPOST
# ============================================================


@router.post(
    "/sync/base",
    response_model=SyncResponse,
    summary="Синхронизировать базовые данные",
    description="Синхронизирует справочные данные из Avanpost (модели до 205)",
)
@log_exceptions(api_logger)
async def sync_base_data(
    request: SyncRequest = Depends(),
) -> JSONResponse:
    """
    Синхронизация базовых справочных данных Avanpost.

    Args:
        request: Параметры синхронизации

    Returns:
        JSONResponse: Результат синхронизации
    """
    api_logger.info(f"🔄 Syncing base data (force={request.force})")

    try:
        sync_service = AvanpostSyncService()
        await sync_service.initialize()

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


@router.post(
    "/sync/users",
    response_model=SyncResponse,
    summary="Синхронизировать пользователей",
    description="Синхронизирует пользовательские данные из Avanpost",
)
@log_exceptions(api_logger)
async def sync_users(
    request: SyncRequest = Depends(),
    mode: int = 1,
    user_ids: list[int] | None = None,
) -> JSONResponse:
    """
    Синхронизация пользовательских данных Avanpost.

    Args:
        request: Параметры синхронизации
        mode: Тип синхронизации (1 - base, 2 - details)
        user_ids: Список ID пользователей для синхронизации

    Returns:
        JSONResponse: Результат синхронизации
    """
    api_logger.info(f"👤 Syncing users (force={request.force}, mode={mode})")

    try:
        sync_service = AvanpostSyncService()
        await sync_service.initialize()

        result = await sync_service.sync_all_users(
            force=request.force,
            mode=mode,
            user_ids=user_ids,
        )

        return JSONResponse(
            status_code=200,
            content={
                "success": True,
                "message": f"User sync completed ({result.get('successful', 0)}/{result.get('total_users', 0)} users)",
                "stats": result,
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


@router.post(
    "/sync/seed_all_users",
    response_model=SyncResponse,
    summary="Загрузить всех пользователей из Avanpost",
    description="Загружает всех пользователей из Avanpost",
)
@log_exceptions(api_logger)
async def seed_all_users(
    session: AsyncSession = Depends(get_session),
) -> JSONResponse:
    """
    Загрузка всех пользователей из Avanpost.

    Args:
        session: Асинхронная сессия SQLAlchemy

    Returns:
        JSONResponse: Результат загрузки
    """
    api_logger.info("🚀 Starting Loading users from Avanpost...")

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


@router.get(
    "/sync/status",
    summary="Статус синхронизации",
    description="Получает статус последней синхронизации Avanpost",
)
@log_exceptions(api_logger)
async def get_sync_status() -> JSONResponse:
    """
    Получение статуса синхронизации Avanpost.

    Returns:
        JSONResponse: Статус синхронизации
    """
    api_logger.info("📊 Getting sync status")

    try:
        sync_service = AvanpostSyncService()
        await sync_service.initialize()

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
# 3. СТАТИСТИКА
# ============================================================


@router.get(
    "/stats",
    summary="Административная статистика",
    description="Получает общую административную статистику системы",
)
@log_exceptions(api_logger)
async def get_admin_stats(
    session: AsyncSession = Depends(get_session),
) -> JSONResponse:
    """
    Получение административной статистики.

    Args:
        session: Асинхронная сессия SQLAlchemy

    Returns:
        JSONResponse: Статистика системы
    """
    api_logger.info("📊 Getting admin stats")

    try:
        # Количество чатов
        chats = await _chat_repo.get_chats(session)
        active_chats = [c for c in chats if c.FFlagActive]

        # Количество пользователей
        users = await _user_repo.get_all_users(session)
        authorized_users = await _user_repo.get_authorized_users_count(session)

        # Количество рассылок (краткая статистика)
        broadcasts = await _broadcast_repo.get_recent_broadcasts(
            session=session,
            limit=1000,
            include_cancelled=True,
        )

        stats = {
            "chats": {
                "total": len(chats),
                "active": len(active_chats),
            },
            "users": {
                "total": len(users),
                "authorized": authorized_users,
            },
            "broadcasts": {
                "total": len(broadcasts),
                "sent": len([b for b in broadcasts if b.FStatus == "sent"]),
                "cancelled": len([b for b in broadcasts if b.FStatus == "cancelled"]),
                "pending": len([b for b in broadcasts if b.FStatus == "pending"]),
                "failed": len([b for b in broadcasts if b.FStatus == "failed"]),
            },
        }

        return JSONResponse(
            status_code=200,
            content={
                "success": True,
                "stats": stats,
                "timestamp": get_timestamp(),
            },
        )

    except Exception as e:
        api_logger.error(f"❌ Failed to get admin stats: {e}", exc_info=True)
        return JSONResponse(
            status_code=500,
            content={
                "success": False,
                "error": f"Failed to get admin stats: {str(e)}",
                "timestamp": get_timestamp(),
            },
        )


__all__ = ["router"]
