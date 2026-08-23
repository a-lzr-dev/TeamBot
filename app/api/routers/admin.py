"""
Модуль административных маршрутов API.

Предоставляет API эндпоинты для административных функций:
- Управление рассылками (broadcast)
- Управление администраторами
- Синхронизация с Avanpost
- Загрузка пользователей из транспортных средств

Все эндпоинты используют общий префикс /admin и требуют прав администратора.
"""

from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from ...bot.dependencies import get_bot_manager
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


class BroadcastRequest(BaseModel):
    """Модель запроса для создания рассылки."""

    text: str = Field(..., description="Текст сообщения для рассылки", min_length=1)
    parse_mode: str = Field("HTML", description="Режим парсинга: HTML, Markdown, MarkdownV2")
    disable_web_page_preview: bool = Field(True, description="Отключить предпросмотр ссылок")
    chat_types: list[str] | None = Field(None, description="Типы чатов для отправки")
    exclude_chat_ids: list[int] | None = Field(None, description="ID чатов для исключения")
    only_active: bool = Field(True, description="Только активные чаты")
    message_thread_id: int | None = Field(None, description="ID топика для отправки")


class BroadcastResponse(BaseModel):
    """Модель ответа для рассылки."""

    success: bool = Field(..., description="Успешность операции")
    total: int = Field(0, description="Всего чатов")
    successful: int = Field(0, description="Успешно отправлено")
    failed: int = Field(0, description="Не удалось отправить")
    failed_chats: list[dict] = Field(default_factory=list, description="Чаты с ошибками")
    sent_messages: list[dict] = Field(default_factory=list, description="Отправленные сообщения")
    timestamp: str = Field(..., description="Время выполнения")


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


# ============ ЭНДПОИНТЫ ============

# ============================================================
# 1. УПРАВЛЕНИЕ РАССЫЛКАМИ
# ============================================================


@router.post(
    "/broadcast",
    response_model=BroadcastResponse,
    summary="Создать рассылку",
    description="Отправляет сообщение во все активные чаты, где присутствует бот",
)
@log_exceptions(api_logger)
async def create_broadcast(
    request: BroadcastRequest,
    session: AsyncSession = Depends(get_session),
) -> JSONResponse:
    """
    Создание массовой рассылки.

    Отправляет сообщение во все активные чаты с возможностью фильтрации
    по типам чатов и исключения отдельных чатов.

    Args:
        request: Данные для рассылки
        session: Асинхронная сессия SQLAlchemy

    Returns:
        JSONResponse: Результат рассылки со статистикой
    """
    api_logger.info(f"📢 Creating broadcast: {request.text[:50]}...")

    try:
        bot_manager = get_bot_manager()

        # Проверка статуса бота
        status = await bot_manager.get_status()
        if not status.get("is_running", False):
            return JSONResponse(
                status_code=503,
                content=ErrorResponse(
                    error="Bot service not available",
                    timestamp=get_timestamp(),
                ).model_dump(),
            )

        # Создание записи о рассылке в БД
        broadcast = await _broadcast_repo.create_broadcast(
            session=session,
            user_id=settings.ADMIN_IDS[0] if settings.ADMIN_IDS else 0,
            title=request.text[:100] + ("..." if len(request.text) > 100 else ""),
            text=request.text,
            parse_mode=request.parse_mode,
            total_chats=0,  # Будет обновлено после отправки
        )

        await session.commit()

        # Выполнение рассылки
        result = await bot_manager.broadcast_message(
            text=request.text,
            parse_mode=request.parse_mode,
            disable_web_page_preview=request.disable_web_page_preview,
            chat_types=request.chat_types,
            exclude_chat_ids=request.exclude_chat_ids,
            only_active=request.only_active,
            sender_user_id=settings.ADMIN_IDS[0] if settings.ADMIN_IDS else None,
            message_thread_id=request.message_thread_id,
            broadcast_id=broadcast.FID,
        )

        # Обновление статуса рассылки в БД
        await _broadcast_repo.update_broadcast_status(
            session=session,
            broadcast_id=broadcast.FID,
            status="sent" if result.get("success", False) else "failed",
            success_count=result.get("successful", 0),
            failed_count=result.get("failed", 0),
        )

        await session.commit()

        api_logger.info(f"✅ Broadcast completed: {result.get('successful', 0)}/{result.get('total', 0)} chats")

        return JSONResponse(
            status_code=200,
            content=BroadcastResponse(
                success=result.get("success", False),
                total=result.get("total", 0),
                successful=result.get("successful", 0),
                failed=result.get("failed", 0),
                failed_chats=result.get("failed_chats", [])[:10],
                sent_messages=result.get("sent_messages", []),
                timestamp=get_timestamp(),
            ).model_dump(),
        )

    except Exception as e:
        api_logger.error(f"❌ Broadcast failed: {e}", exc_info=True)
        await session.rollback()
        return JSONResponse(
            status_code=500,
            content=ErrorResponse(
                error=f"Broadcast failed: {str(e)}",
                timestamp=get_timestamp(),
            ).model_dump(),
        )


@router.post(
    "/broadcast/{broadcast_id}/cancel",
    summary="Отменить рассылку",
    description="Отменяет ранее созданную рассылку и удаляет все связанные сообщения",
)
@log_exceptions(api_logger)
async def cancel_broadcast(
    broadcast_id: int,
    session: AsyncSession = Depends(get_session),
) -> JSONResponse:
    """
    Отмена рассылки.

    Отменяет рассылку и удаляет все сообщения, отправленные в её рамках.

    Args:
        broadcast_id: ID рассылки для отмены
        session: Асинхронная сессия SQLAlchemy

    Returns:
        JSONResponse: Результат отмены
    """
    api_logger.info(f"🗑️ Cancelling broadcast #{broadcast_id}")

    try:
        # Получение рассылки
        broadcast = await _broadcast_repo.get_broadcast_by_id(session, broadcast_id)

        if not broadcast:
            return JSONResponse(
                status_code=404,
                content=ErrorResponse(
                    error=f"Broadcast #{broadcast_id} not found",
                    timestamp=get_timestamp(),
                ).model_dump(),
            )

        if broadcast.FStatus == "cancelled":
            return JSONResponse(
                status_code=400,
                content=ErrorResponse(
                    error=f"Broadcast #{broadcast_id} is already cancelled",
                    timestamp=get_timestamp(),
                ).model_dump(),
            )

        # Получение всех сообщений рассылки
        links = await _broadcast_repo.get_broadcast_messages(session, broadcast_id)

        bot_manager = get_bot_manager()

        # Удаление сообщений из Telegram
        deleted_count = 0
        for link in links:
            try:
                result = await bot_manager.delete_message_by_id(
                    chat_id=link.FK_Chat,
                    message_id=link.FK_Message,
                )
                if result.get("success"):
                    deleted_count += 1
            except Exception as e:
                api_logger.warning(f"⚠️ Failed to delete message {link.FK_Message}: {e}")

        # Отметка сообщений как удалённых в БД
        await _broadcast_repo.mark_messages_deleted(session, broadcast_id)

        # Отмена рассылки
        await _broadcast_repo.cancel_broadcast(
            session=session,
            broadcast_id=broadcast_id,
            cancelled_by=settings.ADMIN_IDS[0] if settings.ADMIN_IDS else 0,
        )

        await session.commit()

        api_logger.info(f"✅ Broadcast #{broadcast_id} cancelled, {deleted_count} messages deleted")

        return JSONResponse(
            status_code=200,
            content={
                "success": True,
                "message": f"Broadcast #{broadcast_id} cancelled",
                "deleted_messages": deleted_count,
                "timestamp": get_timestamp(),
            },
        )

    except Exception as e:
        api_logger.error(f"❌ Failed to cancel broadcast: {e}", exc_info=True)
        await session.rollback()
        return JSONResponse(
            status_code=500,
            content=ErrorResponse(
                error=f"Failed to cancel broadcast: {str(e)}",
                timestamp=get_timestamp(),
            ).model_dump(),
        )


@router.get(
    "/broadcast/history",
    summary="История рассылок",
    description="Возвращает список последних рассылок с их статусом",
)
@log_exceptions(api_logger)
async def get_broadcast_history(
    limit: int = 10,
    include_cancelled: bool = False,
    session: AsyncSession = Depends(get_session),
) -> JSONResponse:
    """
    Получение истории рассылок.

    Args:
        limit: Количество записей
        include_cancelled: Включать отмененные рассылки
        session: Асинхронная сессия SQLAlchemy

    Returns:
        JSONResponse: Список рассылок
    """
    api_logger.info(f"📋 Getting broadcast history (limit={limit})")

    try:
        broadcasts = await _broadcast_repo.get_recent_broadcasts(
            session=session,
            limit=limit,
            include_cancelled=include_cancelled,
        )

        result = []
        for bc in broadcasts:
            result.append(
                {
                    "id": bc.FID,
                    "title": bc.FTitle,
                    "status": bc.FStatus,
                    "total_chats": bc.FTotalChats,
                    "success_count": bc.FSuccessCount,
                    "failed_count": bc.FFailedCount,
                    "created_at": bc.FCreatedAt.isoformat() + "Z",
                    "sent_at": bc.FSentAt.isoformat() + "Z" if bc.FSentAt else None,
                    "cancelled_at": bc.FCancelledAt.isoformat() + "Z" if bc.FCancelledAt else None,
                }
            )

        return JSONResponse(
            status_code=200,
            content={
                "success": True,
                "total": len(result),
                "broadcasts": result,
                "timestamp": get_timestamp(),
            },
        )

    except Exception as e:
        api_logger.error(f"❌ Failed to get broadcast history: {e}", exc_info=True)
        return JSONResponse(
            status_code=500,
            content=ErrorResponse(
                error=f"Failed to get broadcast history: {str(e)}",
                timestamp=get_timestamp(),
            ).model_dump(),
        )


# ============================================================
# 2. УПРАВЛЕНИЕ АДМИНИСТРАТОРАМИ
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
            content=ErrorResponse(
                error=f"User {request.user_id} is already an admin",
                timestamp=get_timestamp(),
            ).model_dump(),
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
            content=ErrorResponse(
                error="Cannot remove the last admin",
                timestamp=get_timestamp(),
            ).model_dump(),
        )

    if request.user_id not in settings.ADMIN_IDS:
        return JSONResponse(
            status_code=404,
            content=ErrorResponse(
                error=f"User {request.user_id} is not an admin",
                timestamp=get_timestamp(),
            ).model_dump(),
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
# 3. СИНХРОНИЗАЦИЯ AVANPOST
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
            content=SyncResponse(
                success=True,
                message="Base data sync completed",
                stats=stats_dict,
                timestamp=get_timestamp(),
            ).model_dump(),
        )

    except Exception as e:
        api_logger.error(f"❌ Base sync failed: {e}", exc_info=True)
        return JSONResponse(
            status_code=500,
            content=SyncResponse(
                success=False,
                message=f"Base sync failed: {str(e)}",
                stats=None,
                timestamp=get_timestamp(),
            ).model_dump(),
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
            content=SyncResponse(
                success=True,
                message=f"User sync completed ({result.get('successful', 0)}/{result.get('total_users', 0)} users)",
                stats=result,
                timestamp=get_timestamp(),
            ).model_dump(),
        )

    except Exception as e:
        api_logger.error(f"❌ User sync failed: {e}", exc_info=True)
        return JSONResponse(
            status_code=500,
            content=SyncResponse(
                success=False,
                message=f"User sync failed: {str(e)}",
                stats=None,
                timestamp=get_timestamp(),
            ).model_dump(),
        )


@router.post(
    "/sync/vehicles",
    response_model=SyncResponse,
    summary="Загрузить пользователей из транспорта",
    description="Загружает пользователей из Avanpost Vehicles",
)
@log_exceptions(api_logger)
async def sync_vehicles(
    session: AsyncSession = Depends(get_session),
) -> JSONResponse:
    """
    Загрузка пользователей из Avanpost Vehicles.

    Args:
        session: Асинхронная сессия SQLAlchemy

    Returns:
        JSONResponse: Результат загрузки
    """
    api_logger.info("🚗 Loading users from Avanpost Vehicles")

    try:
        result = await AvanpostSeedService.seed_avanpost_users_all(
            session=session,
            create_sync_records=True,
        )

        return JSONResponse(
            status_code=200,
            content=SyncResponse(
                success=result.get("errors", 0) == 0,
                message=f"Loaded {result.get('total_added', 0)} users from vehicles",
                stats=result,
                timestamp=get_timestamp(),
            ).model_dump(),
        )

    except Exception as e:
        api_logger.error(f"❌ Vehicle sync failed: {e}", exc_info=True)
        await session.rollback()
        return JSONResponse(
            status_code=500,
            content=SyncResponse(
                success=False,
                message=f"Vehicle sync failed: {str(e)}",
                stats=None,
                timestamp=get_timestamp(),
            ).model_dump(),
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
            content=ErrorResponse(
                error=f"Failed to get sync status: {str(e)}",
                timestamp=get_timestamp(),
            ).model_dump(),
        )


# ============================================================
# 4. СТАТИСТИКА
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

        # Количество рассылок
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
            content=ErrorResponse(
                error=f"Failed to get admin stats: {str(e)}",
                timestamp=get_timestamp(),
            ).model_dump(),
        )


__all__ = ["router"]
