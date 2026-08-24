"""Модуль административных маршрутов API.

Предоставляет API эндпоинты для административных функций:
- Управление администраторами
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
    """Получение списка администраторов.

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
    """Добавление администратора.

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
    """Удаление администратора.

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
# 2. СТАТИСТИКА
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
    """Получение административной статистики.

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
