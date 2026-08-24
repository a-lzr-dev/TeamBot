"""Модуль маршрутов для управления массовыми рассылками (Broadcast).

Этот модуль предоставляет API эндпоинты для работы с рассылками в Telegram боте:
- Создание новой рассылки
- Отмена существующей рассылки с удалением всех сообщений
- Просмотр истории и статуса рассылок
- Получение статистики по рассылкам

Все эндпоинты используют общий префикс /broadcast и требуют прав администратора.
Модуль интегрируется с BotManager для выполнения рассылок и репозиториями
для работы с базой данных.

Роуты:
    POST / - Создание новой рассылки
    DELETE /{broadcast_id} - Отмена рассылки
    GET / - Получение списка рассылок
    GET /{broadcast_id} - Получение информации о рассылке
    GET /stats - Получение статистики по рассылкам
"""

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field, field_validator
from sqlalchemy.ext.asyncio import AsyncSession

from ...bot.dependencies import get_bot_manager
from ...bot.manager import BotManager
from ...config import settings
from ...db.dependencies import get_db_manager
from ...db.repositories import BroadcastRepository, ChatRepository
from ...logger import api_logger
from ...models import ChatType, datetime_now
from ...utils.decorators import log_exceptions
from ..dependencies import get_session

# Создание роутера с префиксом /broadcast и тегом для документации
router = APIRouter(prefix="/broadcast", tags=["Broadcast"])

# Репозитории (создаются один раз на уровне модуля для переиспользования)
_broadcast_repo = BroadcastRepository()
_chat_repo = ChatRepository()


# ============ МОДЕЛИ ============


class CreateBroadcastRequest(BaseModel):
    """Модель запроса для создания новой рассылки.

    Поддерживает все параметры отправки сообщений в Telegram, а также фильтрацию чатов по типам и исключение указанных
    чатов.
    """

    text: str = Field(..., description="Текст сообщения для рассылки", min_length=1, max_length=4096)
    parse_mode: str | None = Field("HTML", description="Режим парсинга: 'HTML', 'Markdown', 'MarkdownV2' или None")
    disable_web_page_preview: bool = Field(True, description="Отключить предпросмотр ссылок")
    disable_notification: bool = Field(False, description="Отключить уведомление у получателей")
    protect_content: bool = Field(False, description="Защитить содержимое от пересылки")
    chat_types: list[ChatType] | None = Field(None, description="Типы чатов для отправки (опционально)")
    exclude_chat_ids: list[int] | None = Field(None, description="ID чатов, которые нужно исключить (опционально)")
    only_active: bool = Field(True, description="Отправлять только в активные чаты")
    message_thread_id: int | None = Field(None, description="ID топика для отправки (опционально)")
    title: str | None = Field(None, description="Заголовок рассылки (для отображения в списке)", max_length=200)

    @field_validator("parse_mode")
    @classmethod
    def validate_parse_mode(cls, v: str | None) -> str | None:
        """Валидация режима парсинга.

        Args:
            v: Режим парсинга

        Returns:
            str | None: Валидный режим в верхнем регистре

        Raises:
            ValueError: Если режим не поддерживается
        """
        if v is not None:
            v_upper = v.upper()
            if v_upper not in ["HTML", "MARKDOWN", "MARKDOWN_V2"]:
                raise ValueError('parse_mode must be "HTML", "Markdown", "MarkdownV2" or None')
            return v_upper
        return None


class CreateBroadcastResponse(BaseModel):
    """Модель ответа при создании рассылки."""

    success: bool = Field(..., description="Успешность операции")
    broadcast_id: int | None = Field(None, description="ID созданной рассылки")
    total_chats: int = Field(0, description="Всего чатов для отправки")
    success_count: int = Field(0, description="Успешно отправлено")
    failed_count: int = Field(0, description="Не удалось отправить")
    failed_chats: list[dict] = Field(default_factory=list, description="Список чатов с ошибками")
    sent_messages: list[dict] = Field(default_factory=list, description="Отправленные сообщения")
    timestamp: str = Field(..., description="Время отправки")


class CancelBroadcastResponse(BaseModel):
    """Модель ответа при отмене рассылки."""

    success: bool = Field(..., description="Успешность операции")
    broadcast_id: int = Field(..., description="ID отмененной рассылки")
    deleted_count: int = Field(0, description="Количество удаленных сообщений")
    message: str = Field(..., description="Сообщение о результате")
    timestamp: str = Field(..., description="Время операции")


class BroadcastInfoResponse(BaseModel):
    """Модель ответа с информацией о рассылке."""

    success: bool = Field(..., description="Успешность операции")
    broadcast: dict | None = Field(None, description="Информация о рассылке")
    messages: list[dict] = Field(default_factory=list, description="Список сообщений рассылки")
    timestamp: str = Field(..., description="Время запроса")


class BroadcastListResponse(BaseModel):
    """Модель ответа со списком рассылок."""

    success: bool = Field(..., description="Успешность операции")
    broadcasts: list[dict] = Field(default_factory=list, description="Список рассылок")
    total: int = Field(0, description="Общее количество рассылок")
    timestamp: str = Field(..., description="Время запроса")


class BroadcastStatsResponse(BaseModel):
    """Модель ответа со статистикой по рассылкам."""

    success: bool = Field(..., description="Успешность операции")
    stats: dict = Field(..., description="Статистика по рассылкам")
    timestamp: str = Field(..., description="Время запроса")


class ErrorResponse(BaseModel):
    """Стандартная модель ответа при ошибке."""

    success: bool = Field(default=False, description="Успешность операции (всегда False)")
    error: str = Field(..., description="Сообщение об ошибке")
    timestamp: str = Field(..., description="Время ошибки")


# ============ ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ ============


async def _get_bot_manager() -> BotManager:
    """Получение экземпляра BotManager с проверкой статуса.

    Returns:
        BotManager: Экземпляр менеджера бота

    Raises:
        HTTPException: Если бот не запущен (HTTP 503)
    """
    bot_manager = get_bot_manager()
    status = await bot_manager.get_status()
    if not status.get("is_running", False):
        raise HTTPException(status_code=503, detail="Bot service not available")
    return bot_manager


def _is_admin(user_id: int) -> bool:
    """Проверка, является ли пользователь администратором."""
    return user_id in settings.ADMIN_IDS


async def _get_sender_info(user_id: int) -> dict:
    """Получение информации об отправителе.

    Args:
        user_id: ID пользователя

    Returns:
        dict: Информация об отправителе
    """
    try:
        async with get_db_manager().get_session() as session:
            from ...db.repositories import UserRepository

            user_repo = UserRepository()
            user = await user_repo.get_user_by_id(session, user_id, show_logs=False)
            if user:
                return {
                    "sender_user_id": user_id,
                    "sender_first_name": user.FFirstName,
                    "sender_username": user.FUserName,
                }
    except Exception as e:
        api_logger.warning(f"⚠️ Failed to get sender info: {e}")

    return {
        "sender_user_id": user_id,
        "sender_first_name": f"User_{user_id}",
        "sender_username": None,
    }


async def _broadcast_progress(current: int, total: int) -> None:
    """Callback для отслеживания прогресса рассылки."""
    if current % 10 == 0 or current == total:
        api_logger.debug(f"📊 Broadcast progress: {current}/{total}")


# ============ ЭНДПОИНТЫ ============


@router.post(
    "/",
    response_model=CreateBroadcastResponse | ErrorResponse,
    summary="Создать рассылку",
    description="Создает новую массовую рассылку и отправляет сообщение во все указанные чаты",
)
@log_exceptions(api_logger)
async def create_broadcast(
    request: CreateBroadcastRequest,
    user_id: int = Query(..., description="ID пользователя, создающего рассылку", gt=0),
    session: AsyncSession = Depends(get_session),
) -> JSONResponse:
    """Создание и выполнение массовой рассылки.

    Args:
        request: Данные для создания рассылки
        user_id: ID пользователя, создающего рассылку
        session: Асинхронная сессия SQLAlchemy

    Returns:
        JSONResponse: Результат создания и отправки рассылки
    """
    api_logger.info(f"📢 Creating broadcast by user {user_id}")

    # Проверка прав администратора
    if not _is_admin(user_id):
        api_logger.warning(f"⚠️ User {user_id} attempted to create broadcast without admin rights")
        return JSONResponse(
            status_code=403,
            content=ErrorResponse(
                error="You don't have admin rights to create broadcasts",
                timestamp=datetime_now().isoformat() + "Z",
            ).model_dump(),
        )

    # Получение менеджера бота
    try:
        bot_manager = await _get_bot_manager()
    except HTTPException as e:
        return JSONResponse(
            status_code=e.status_code,
            content=ErrorResponse(
                error=e.detail,
                timestamp=datetime_now().isoformat() + "Z",
            ).model_dump(),
        )

    # Получение информации об отправителе
    sender_info = await _get_sender_info(user_id)

    # Подготовка заголовка рассылки
    title = request.title or request.text[:100] + ("..." if len(request.text) > 100 else "")

    # Получение списка чатов для рассылки
    chats = await _chat_repo.get_chats(session, is_active=request.only_active)

    # Фильтр по типам чатов
    if request.chat_types:
        chat_type_values = [ct.value for ct in request.chat_types]
        chats = [c for c in chats if c.FType.value in chat_type_values]

    # Исключение указанных чатов
    if request.exclude_chat_ids:
        chats = [c for c in chats if c.FID not in request.exclude_chat_ids]

    total_chats = len(chats)

    if total_chats == 0:
        api_logger.warning("⚠️ No chats found for broadcast")
        return JSONResponse(
            status_code=400,
            content=ErrorResponse(
                error="No active chats found for broadcast",
                timestamp=datetime_now().isoformat() + "Z",
            ).model_dump(),
        )

    api_logger.info(f"📊 Broadcasting to {total_chats} chats")

    # 1. Создание записи о рассылке в БД
    broadcast = await _broadcast_repo.create_broadcast(
        session=session,
        user_id=user_id,
        title=title,
        text=request.text,
        parse_mode=request.parse_mode,
        total_chats=total_chats,
    )

    await session.commit()

    # 2. Выполнение рассылки через BotManager
    result = await bot_manager.broadcast_message(
        text=request.text,
        parse_mode=request.parse_mode,
        disable_web_page_preview=request.disable_web_page_preview,
        disable_notification=request.disable_notification,
        protect_content=request.protect_content,
        chat_types=[ct.value for ct in request.chat_types] if request.chat_types else None,
        exclude_chat_ids=request.exclude_chat_ids,
        only_active=request.only_active,
        sender_user_id=sender_info.get("sender_user_id"),
        sender_first_name=sender_info.get("sender_first_name"),
        sender_username=sender_info.get("sender_username"),
        progress_callback=_broadcast_progress,
        message_thread_id=request.message_thread_id,
        broadcast_id=broadcast.FID,
    )

    # 3. Обновление статуса рассылки в БД
    await _broadcast_repo.update_broadcast_status(
        session=session,
        broadcast_id=broadcast.FID,
        status="sent" if result.get("success") and result.get("failed", 0) == 0 else "failed",
        success_count=result.get("successful", 0),
        failed_count=result.get("failed", 0),
    )

    await session.commit()

    # 4. Формирование ответа
    response = CreateBroadcastResponse(
        success=result.get("success", False),
        broadcast_id=broadcast.FID,
        total_chats=total_chats,
        success_count=result.get("successful", 0),
        failed_count=result.get("failed", 0),
        failed_chats=result.get("failed_chats", [])[:10],
        sent_messages=result.get("sent_messages", []),
        timestamp=datetime_now().isoformat() + "Z",
    )

    status_code = 200 if response.success_count > 0 else 500

    return JSONResponse(status_code=status_code, content=response.model_dump())


@router.delete(
    "/{broadcast_id}",
    response_model=CancelBroadcastResponse | ErrorResponse,
    summary="Отменить рассылку",
    description="Отменяет активную рассылку и удаляет все связанные сообщения из Telegram и БД",
)
@log_exceptions(api_logger)
async def cancel_broadcast(
    broadcast_id: int,
    user_id: int = Query(..., description="ID пользователя, отменяющего рассылку", gt=0),
    session: AsyncSession = Depends(get_session),
) -> JSONResponse:
    """Отмена рассылки с удалением всех сообщений.

    Args:
        broadcast_id: ID рассылки для отмены
        user_id: ID пользователя, отменяющего рассылку
        session: Асинхронная сессия SQLAlchemy

    Returns:
        JSONResponse: Результат отмены рассылки
    """
    api_logger.info(f"🗑️ Cancelling broadcast {broadcast_id} by user {user_id}")

    # Проверка прав администратора
    if not _is_admin(user_id):
        api_logger.warning(f"⚠️ User {user_id} attempted to cancel broadcast without admin rights")
        return JSONResponse(
            status_code=403,
            content=ErrorResponse(
                error="You don't have admin rights to cancel broadcasts",
                timestamp=datetime_now().isoformat() + "Z",
            ).model_dump(),
        )

    # Получение информации о рассылке
    broadcast = await _broadcast_repo.get_broadcast_by_id(session, broadcast_id)

    if not broadcast:
        api_logger.warning(f"⚠️ Broadcast {broadcast_id} not found")
        return JSONResponse(
            status_code=404,
            content=ErrorResponse(
                error=f"Broadcast {broadcast_id} not found",
                timestamp=datetime_now().isoformat() + "Z",
            ).model_dump(),
        )

    # Проверка, можно ли отменить рассылку
    if broadcast.FStatus == "cancelled":
        return JSONResponse(
            status_code=400,
            content=ErrorResponse(
                error=f"Broadcast {broadcast_id} is already cancelled",
                timestamp=datetime_now().isoformat() + "Z",
            ).model_dump(),
        )

    # Получение менеджера бота
    try:
        bot_manager = await _get_bot_manager()
    except HTTPException as e:
        return JSONResponse(
            status_code=e.status_code,
            content=ErrorResponse(
                error=e.detail,
                timestamp=datetime_now().isoformat() + "Z",
            ).model_dump(),
        )

    # Получение всех связанных сообщений
    links = await _broadcast_repo.get_broadcast_messages(session, broadcast_id)

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
    await _broadcast_repo.force_cancel_broadcast(
        session=session,
        broadcast_id=broadcast_id,
        cancelled_by=user_id,
    )

    await session.commit()

    api_logger.info(f"✅ Broadcast {broadcast_id} cancelled, deleted {deleted_count} messages")

    return JSONResponse(
        status_code=200,
        content=CancelBroadcastResponse(
            success=True,
            broadcast_id=broadcast_id,
            deleted_count=deleted_count,
            message=f"Broadcast {broadcast_id} cancelled successfully",
            timestamp=datetime_now().isoformat() + "Z",
        ).model_dump(),
    )


@router.get(
    "/",
    response_model=BroadcastListResponse | ErrorResponse,
    summary="Получить список рассылок",
    description="Возвращает список рассылок с пагинацией и фильтрацией по статусу",
)
@log_exceptions(api_logger)
async def get_broadcasts(
    limit: int = Query(10, ge=1, le=100, description="Количество записей на странице"),
    offset: int = Query(0, ge=0, description="Смещение для пагинации"),
    status: str | None = Query(None, description="Фильтр по статусу: pending, sent, cancelled, failed"),
    session: AsyncSession = Depends(get_session),
) -> JSONResponse:
    """Получение списка рассылок с пагинацией и фильтрацией.

    Args:
        limit: Количество записей на странице
        offset: Смещение для пагинации
        status: Фильтр по статусу
        session: Асинхронная сессия SQLAlchemy

    Returns:
        JSONResponse: Список рассылок
    """
    api_logger.info(f"📋 Getting broadcasts list (limit={limit}, offset={offset}, status={status})")

    # Получение рассылок через репозиторий
    broadcasts = await _broadcast_repo.get_recent_broadcasts(
        session=session,
        limit=limit + offset,
        include_cancelled=True,
    )

    # Применение фильтра по статусу
    if status:
        broadcasts = [b for b in broadcasts if b.FStatus == status]

    # Пагинация
    total = len(broadcasts)
    paginated = broadcasts[offset : offset + limit]

    # Формирование списка
    broadcast_list = []
    for bc in paginated:
        broadcast_list.append(
            {
                "id": bc.FID,
                "user_id": bc.FK_User,
                "title": bc.FTitle,
                "text": bc.FText[:200] + ("..." if len(bc.FText) > 200 else ""),
                "parse_mode": bc.FParseMode,
                "total_chats": bc.FTotalChats,
                "success_count": bc.FSuccessCount,
                "failed_count": bc.FFailedCount,
                "status": bc.FStatus,
                "created_at": bc.FCreatedAt.isoformat() + "Z",
                "sent_at": bc.FSentAt.isoformat() + "Z" if bc.FSentAt else None,
                "cancelled_at": bc.FCancelledAt.isoformat() + "Z" if bc.FCancelledAt else None,
                "cancelled_by": bc.FK_CancelledBy,
            }
        )

    return JSONResponse(
        status_code=200,
        content=BroadcastListResponse(
            success=True,
            broadcasts=broadcast_list,
            total=total,
            timestamp=datetime_now().isoformat() + "Z",
        ).model_dump(),
    )


@router.get(
    "/{broadcast_id}",
    response_model=BroadcastInfoResponse | ErrorResponse,
    summary="Получить информацию о рассылке",
    description="Возвращает детальную информацию о рассылке и списке отправленных сообщений",
)
@log_exceptions(api_logger)
async def get_broadcast(
    broadcast_id: int,
    session: AsyncSession = Depends(get_session),
) -> JSONResponse:
    """Получение детальной информации о рассылке.

    Args:
        broadcast_id: ID рассылки
        session: Асинхронная сессия SQLAlchemy

    Returns:
        JSONResponse: Информация о рассылке
    """
    api_logger.info(f"📋 Getting broadcast info for {broadcast_id}")

    # Получение информации о рассылке
    broadcast = await _broadcast_repo.get_broadcast_by_id(session, broadcast_id)

    if not broadcast:
        api_logger.warning(f"⚠️ Broadcast {broadcast_id} not found")
        return JSONResponse(
            status_code=404,
            content=ErrorResponse(
                error=f"Broadcast {broadcast_id} not found",
                timestamp=datetime_now().isoformat() + "Z",
            ).model_dump(),
        )

    # Получение связанных сообщений
    links = await _broadcast_repo.get_broadcast_messages(session, broadcast_id)

    messages = []
    for link in links:
        messages.append(
            {
                "message_id": link.FK_Message,
                "chat_id": link.FK_Chat,
                "is_deleted": link.FIsDeleted,
                "deleted_at": link.FDeletedAt.isoformat() + "Z" if link.FDeletedAt else None,
            }
        )

    broadcast_info = {
        "id": broadcast.FID,
        "user_id": broadcast.FK_User,
        "title": broadcast.FTitle,
        "text": broadcast.FText,
        "parse_mode": broadcast.FParseMode,
        "total_chats": broadcast.FTotalChats,
        "success_count": broadcast.FSuccessCount,
        "failed_count": broadcast.FFailedCount,
        "status": broadcast.FStatus,
        "created_at": broadcast.FCreatedAt.isoformat() + "Z",
        "sent_at": broadcast.FSentAt.isoformat() + "Z" if broadcast.FSentAt else None,
        "cancelled_at": broadcast.FCancelledAt.isoformat() + "Z" if broadcast.FCancelledAt else None,
        "cancelled_by": broadcast.FK_CancelledBy,
    }

    return JSONResponse(
        status_code=200,
        content=BroadcastInfoResponse(
            success=True,
            broadcast=broadcast_info,
            messages=messages,
            timestamp=datetime_now().isoformat() + "Z",
        ).model_dump(),
    )


@router.get(
    "/stats",
    response_model=BroadcastStatsResponse | ErrorResponse,
    summary="Статистика по рассылкам",
    description="Возвращает статистику по рассылкам: количество по статусам, общее количество сообщений и т.д.",
)
@log_exceptions(api_logger)
async def get_broadcast_stats(
    session: AsyncSession = Depends(get_session),
) -> JSONResponse:
    """Получение статистики по рассылкам.

    Args:
        session: Асинхронная сессия SQLAlchemy

    Returns:
        JSONResponse: Статистика по рассылкам
    """
    api_logger.info("📊 Getting broadcast stats")

    # Получение всех рассылок
    broadcasts = await _broadcast_repo.get_recent_broadcasts(
        session=session,
        limit=10000,
        include_cancelled=True,
    )

    # Подсчет статистики
    status_counts = {
        "pending": 0,
        "sent": 0,
        "cancelled": 0,
        "failed": 0,
    }

    total_chats = 0
    total_success = 0
    total_failed = 0
    total_messages = 0

    for bc in broadcasts:
        status_counts[bc.FStatus] = status_counts.get(bc.FStatus, 0) + 1
        total_chats += bc.FTotalChats
        total_success += bc.FSuccessCount
        total_failed += bc.FFailedCount

        # Подсчет сообщений в рассылках
        links = await _broadcast_repo.get_broadcast_messages(session, bc.FID)
        total_messages += len(links)

    stats = {
        "total_broadcasts": len(broadcasts),
        "by_status": status_counts,
        "total_chats": total_chats,
        "total_success": total_success,
        "total_failed": total_failed,
        "total_messages": total_messages,
        "success_rate": (total_success / total_chats * 100) if total_chats > 0 else 0,
    }

    return JSONResponse(
        status_code=200,
        content=BroadcastStatsResponse(
            success=True,
            stats=stats,
            timestamp=datetime_now().isoformat() + "Z",
        ).model_dump(),
    )


__all__ = ["router"]
