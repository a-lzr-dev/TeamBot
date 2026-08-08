from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from ...db import ReminderRepository
from ...exceptions import log_exceptions
from ...logger import api_logger
from ...services.reminder_service import reminder_service
from ...utils.datetime import get_timestamp
from ..dependencies import get_session

router = APIRouter(prefix="/reminders", tags=["Reminders"])


class CreateReminderRequest(BaseModel):
    user_id: int = Field(..., description="ID пользователя")
    title: str = Field(..., description="Название", min_length=1, max_length=500)
    remind_at: datetime = Field(..., description="Время напоминания")
    description: str | None = Field(None, description="Описание")
    category: str | None = Field(None, description="Категория")
    remind_until: datetime | None = Field(None, description="Дата окончания оповещений")
    remind_interval: int | None = Field(None, description="Интервал в минутах")
    max_remind_count: int | None = Field(None, description="Максимальное количество оповещений")
    code_word: str | None = Field(None, description="Кодовое слово")
    notification_type: str = Field("private", description="Тип уведомления")
    chat_id: int | None = Field(None, description="ID чата")
    shared_with: list[int] | None = Field(None, description="ID пользователей для общего дела")
    encrypt: bool = Field(False, description="Шифровать данные")


class CompleteReminderRequest(BaseModel):
    user_id: int = Field(..., description="ID пользователя")
    successful: bool = Field(True, description="Успешно ли выполнено")


# ============ Эндпоинты ============


@router.post("/", summary="Создать напоминание")
@log_exceptions(api_logger)
async def create_reminder(
    request: CreateReminderRequest,
    session: AsyncSession = Depends(get_session),
) -> JSONResponse:
    """Создание напоминания"""
    try:
        reminder = await reminder_service.create_reminder(
            user_id=request.user_id,
            title=request.title,
            remind_at=request.remind_at,
            description=request.description,
            category=request.category,
            remind_until=request.remind_until,
            remind_interval=request.remind_interval,
            max_remind_count=request.max_remind_count,
            code_word=request.code_word,
            notification_type=request.notification_type,
            chat_id=request.chat_id,
            shared_with=request.shared_with,
            encrypt=request.encrypt,
            session=session,
        )

        return JSONResponse(
            status_code=201,
            content={
                "success": True,
                "reminder": {
                    "id": reminder.FID,
                    "title": reminder.FTitle,
                    "remind_at": reminder.FRemindAt.isoformat(),
                },
                "timestamp": get_timestamp(),
            },
        )

    except Exception as e:
        api_logger.error(f"Failed to create reminder: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e)) from e


@router.post("/{reminder_id}/complete", summary="Завершить дело")
@log_exceptions(api_logger)
async def complete_reminder(
    reminder_id: int,
    request: CompleteReminderRequest,
    session: AsyncSession = Depends(get_session),
) -> JSONResponse:
    """Завершение дела"""
    try:
        success, message = await reminder_service.complete_reminder(
            reminder_id=reminder_id,
            user_id=request.user_id,
            successful=request.successful,
            session=session,
        )

        if success:
            return JSONResponse(
                status_code=200, content={"success": True, "message": message, "timestamp": get_timestamp()}
            )
        else:
            return JSONResponse(
                status_code=400, content={"success": False, "message": message, "timestamp": get_timestamp()}
            )

    except Exception as e:
        api_logger.error(f"Failed to complete reminder: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e)) from e


@router.get("/user/{user_id}", summary="Получить дела пользователя")
@log_exceptions(api_logger)
async def get_user_reminders(
    user_id: int,
    session: AsyncSession = Depends(get_session),
    date: datetime | None = None,
    category: str | None = None,
    include_completed: bool = False,
    limit: int = Query(100, ge=1, le=500),
    offset: int = Query(0, ge=0),
) -> JSONResponse:
    """Получение дел пользователя"""
    try:
        reminders = await reminder_service.get_reminders(
            user_id=user_id,
            date=date,
            category=category,
            include_completed=include_completed,
            limit=limit,
            offset=offset,
            session=session,
        )

        return JSONResponse(
            status_code=200,
            content={
                "success": True,
                "reminders": reminders,
                "count": len(reminders),
                "timestamp": get_timestamp(),
            },
        )

    except Exception as e:
        api_logger.error(f"Failed to get user reminders: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e)) from e


@router.get("/{reminder_id}", summary="Получить дело по ID")
@log_exceptions(api_logger)
async def get_reminder_by_id(
    reminder_id: int,
    session: AsyncSession = Depends(get_session),
) -> JSONResponse:
    """Получение дела по ID"""
    try:
        reminder = await reminder_service.get_reminder_by_id(
            reminder_id,
            session=session,
        )

        if not reminder:
            return JSONResponse(
                status_code=404,
                content={
                    "success": False,
                    "message": f"Reminder {reminder_id} not found",
                    "timestamp": get_timestamp(),
                },
            )

        return JSONResponse(
            status_code=200,
            content={
                "success": True,
                "reminder": reminder,
                "timestamp": get_timestamp(),
            },
        )

    except Exception as e:
        api_logger.error(f"Failed to get reminder: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e)) from e


@router.delete("/{reminder_id}", summary="Удалить дело")
@log_exceptions(api_logger)
async def delete_reminder(
    reminder_id: int,
    session: AsyncSession = Depends(get_session),
    soft: bool = True,
) -> JSONResponse:
    """Удаление дела"""
    try:
        success = await reminder_service.delete_reminder(
            reminder_id=reminder_id,
            soft=soft,
            session=session,
        )

        if success:
            return JSONResponse(
                status_code=200,
                content={
                    "success": True,
                    "message": f"Reminder {reminder_id} deleted successfully",
                    "timestamp": get_timestamp(),
                },
            )
        else:
            return JSONResponse(
                status_code=404,
                content={
                    "success": False,
                    "message": f"Reminder {reminder_id} not found",
                    "timestamp": get_timestamp(),
                },
            )

    except Exception as e:
        api_logger.error(f"Failed to delete reminder: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e)) from e


@router.get("/stats/{user_id}", summary="Статистика дел")
@log_exceptions(api_logger)
async def get_reminder_stats(
    user_id: int,
    session: AsyncSession = Depends(get_session),
    period: str = Query("week", description="Период: day, week, month, year"),
) -> JSONResponse:
    """Получение статистики по делам"""
    try:
        stats = await reminder_service.get_reminder_stats(
            user_id=user_id,
            period=period,
            session=session,
        )

        return JSONResponse(status_code=200, content={"success": True, "stats": stats, "timestamp": get_timestamp()})

    except Exception as e:
        api_logger.error(f"Failed to get reminder stats: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e)) from e


@router.post("/by-code-word", summary="Найти дела по кодовому слову")
@log_exceptions(api_logger)
async def find_reminders_by_code_word(
    user_id: int,
    code_word: str,
    session: AsyncSession = Depends(get_session),
    chat_id: int | None = None,
    include_completed: bool = False,
) -> JSONResponse:
    """Поиск дел по кодовому слову"""
    try:
        reminders = await reminder_service.find_by_code_word(
            user_id=user_id,
            code_word=code_word,
            chat_id=chat_id,
            include_completed=include_completed,
            session=session,
        )

        return JSONResponse(
            status_code=200,
            content={
                "success": True,
                "reminders": reminders,
                "count": len(reminders),
                "timestamp": get_timestamp(),
            },
        )

    except Exception as e:
        api_logger.error(f"Failed to find reminders by code word: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e)) from e


@router.post("/{reminder_id}/deactivate", summary="Деактивировать напоминание")
@log_exceptions(api_logger)
async def deactivate_reminder(
    reminder_id: int,
    session: AsyncSession = Depends(get_session),
) -> JSONResponse:
    """Деактивация напоминания"""
    try:
        success = await reminder_service.deactivate_reminder(
            reminder_id,
            session=session,
        )

        if success:
            return JSONResponse(
                status_code=200,
                content={
                    "success": True,
                    "message": f"Reminder {reminder_id} deactivated",
                    "timestamp": get_timestamp(),
                },
            )
        else:
            return JSONResponse(
                status_code=404,
                content={
                    "success": False,
                    "message": f"Reminder {reminder_id} not found",
                    "timestamp": get_timestamp(),
                },
            )

    except Exception as e:
        api_logger.error(f"Failed to deactivate reminder: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e)) from e


@router.post("/bulk/deactivate", summary="Массовая деактивация")
@log_exceptions(api_logger)
async def bulk_deactivate_reminders(
    reminder_ids: list[int],
    session: AsyncSession = Depends(get_session),
) -> JSONResponse:
    """Массовая деактивация напоминаний"""
    try:
        count = await ReminderRepository.bulk_deactivate(
            session=session,
            reminder_ids=reminder_ids,
        )

        return JSONResponse(
            status_code=200,
            content={
                "success": True,
                "deactivated": count,
                "timestamp": get_timestamp(),
            },
        )

    except Exception as e:
        api_logger.error(f"Failed to bulk deactivate reminders: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e)) from e


@router.post("/bulk/delete", summary="Массовое удаление")
@log_exceptions(api_logger)
async def bulk_delete_reminders(
    reminder_ids: list[int],
    session: AsyncSession = Depends(get_session),
    soft: bool = True,
) -> JSONResponse:
    """Массовое удаление напоминаний"""
    try:
        count = await ReminderRepository.bulk_delete(
            session=session,
            reminder_ids=reminder_ids,
            soft=soft,
        )

        return JSONResponse(
            status_code=200,
            content={
                "success": True,
                "deleted": count,
                "timestamp": get_timestamp(),
            },
        )

    except Exception as e:
        api_logger.error(f"Failed to bulk delete reminders: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e)) from e


__all__ = ["router"]
