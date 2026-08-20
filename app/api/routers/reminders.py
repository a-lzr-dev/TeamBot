from datetime import datetime
from typing import Any

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

# Репозиторий (создаем один раз на уровне модуля)
_reminder_repo = ReminderRepository()


class CreateReminderRequest(BaseModel):
    """Модель запроса для создания напоминания"""

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
    """Модель запроса для завершения дела"""

    user_id: int = Field(..., description="ID пользователя")
    successful: bool = Field(True, description="Успешно ли выполнено")


class ReminderResponse(BaseModel):
    """Модель ответа для напоминания"""

    id: int = Field(..., description="ID напоминания")
    title: str = Field(..., description="Название")
    description: str | None = Field(None, description="Описание")
    category: str | None = Field(None, description="Категория")
    remind_at: str = Field(..., description="Время напоминания")
    remind_until: str | None = Field(None, description="Дата окончания оповещений")
    remind_interval: int | None = Field(None, description="Интервал в минутах")
    remind_count: int = Field(0, description="Количество отправленных уведомлений")
    max_remind_count: int | None = Field(None, description="Максимальное количество оповещений")
    is_completed: bool = Field(False, description="Завершено ли дело")
    is_successful: bool | None = Field(None, description="Успешно ли выполнено")
    completed_at: str | None = Field(None, description="Время завершения")
    is_group: bool = Field(False, description="Является ли общим делом")
    code_word: str | None = Field(None, description="Кодовое слово")
    is_encrypted: bool = Field(False, description="Зашифровано ли")
    notification_type: str = Field("private", description="Тип уведомления")
    created_at: str = Field(..., description="Время создания")
    updated_at: str = Field(..., description="Время обновления")

    @classmethod
    def from_reminder_dict(cls, data: dict[str, Any]) -> "ReminderResponse":
        """Создание из словаря, возвращаемого ReminderRepository.format_reminder()"""
        return cls(
            id=data.get("id", 0),
            title=data.get("title", ""),
            description=data.get("description"),
            category=data.get("category"),
            remind_at=data.get("remind_at", ""),
            remind_until=data.get("remind_until"),
            remind_interval=data.get("remind_interval"),
            remind_count=data.get("remind_count", 0),
            max_remind_count=data.get("max_remind_count"),
            is_completed=data.get("is_completed", False),
            is_successful=data.get("is_successful"),
            completed_at=data.get("completed_at"),
            is_group=data.get("is_group", False),
            code_word=data.get("code_word"),
            is_encrypted=data.get("is_encrypted", False),
            notification_type=data.get("notification_type", "private"),
            created_at=data.get("created_at", ""),
            updated_at=data.get("updated_at", ""),
        )


class ReminderListResponse(BaseModel):
    """Модель ответа со списком напоминаний"""

    success: bool = Field(..., description="Успешность операции")
    reminders: list[ReminderResponse] = Field(default_factory=list, description="Список напоминаний")
    count: int = Field(0, description="Количество напоминаний")
    timestamp: str = Field(..., description="Время запроса")


class ReminderStatsResponse(BaseModel):
    """Модель ответа со статистикой"""

    success: bool = Field(..., description="Успешность операции")
    stats: dict[str, Any] = Field(..., description="Статистика")
    timestamp: str = Field(..., description="Время запроса")


# ============ ЭНДПОИНТЫ ============


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

        # ИСПОЛЬЗУЕМ DTO ДЛЯ ФОРМАТИРОВАНИЯ ОТВЕТА
        reminder_data = _reminder_repo.format_reminder(reminder)
        response = ReminderResponse.from_reminder_dict(reminder_data)

        return JSONResponse(
            status_code=201,
            content={
                "success": True,
                "reminder": response.model_dump(),
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
        # ИСПОЛЬЗУЕМ reminder_service ДЛЯ ПОЛУЧЕНИЯ СПИСКА
        reminders_data = await reminder_service.get_reminders(
            user_id=user_id,
            date=date,
            category=category,
            include_completed=include_completed,
            limit=limit,
            offset=offset,
            session=session,
        )

        # ИСПОЛЬЗУЕМ DTO ДЛЯ ФОРМАТИРОВАНИЯ ОТВЕТА
        reminders = [ReminderResponse.from_reminder_dict(r) for r in reminders_data]

        return JSONResponse(
            status_code=200,
            content={
                "success": True,
                "reminders": [r.model_dump() for r in reminders],
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
        # ИСПОЛЬЗУЕМ reminder_service ДЛЯ ПОЛУЧЕНИЯ ДЕЛА
        reminder_data = await reminder_service.get_reminder_by_id(
            reminder_id,
            session=session,
        )

        if not reminder_data:
            return JSONResponse(
                status_code=404,
                content={
                    "success": False,
                    "message": f"Reminder {reminder_id} not found",
                    "timestamp": get_timestamp(),
                },
            )

        # ИСПОЛЬЗУЕМ DTO ДЛЯ ФОРМАТИРОВАНИЯ ОТВЕТА
        response = ReminderResponse.from_reminder_dict(reminder_data)

        return JSONResponse(
            status_code=200,
            content={
                "success": True,
                "reminder": response.model_dump(),
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
        # ИСПОЛЬЗУЕМ reminder_service ДЛЯ УДАЛЕНИЯ
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
        # ИСПОЛЬЗУЕМ reminder_service ДЛЯ ПОЛУЧЕНИЯ СТАТИСТИКИ
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
        # ИСПОЛЬЗУЕМ reminder_service ДЛЯ ПОИСКА
        reminders_data = await reminder_service.find_by_code_word(
            user_id=user_id,
            code_word=code_word,
            chat_id=chat_id,
            include_completed=include_completed,
            session=session,
        )

        # ИСПОЛЬЗУЕМ DTO ДЛЯ ФОРМАТИРОВАНИЯ ОТВЕТА
        reminders = [ReminderResponse.from_reminder_dict(r) for r in reminders_data]

        return JSONResponse(
            status_code=200,
            content={
                "success": True,
                "reminders": [r.model_dump() for r in reminders],
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
        # ИСПОЛЬЗУЕМ reminder_service ДЛЯ ДЕАКТИВАЦИИ
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
        # ИСПОЛЬЗУЕМ ReminderRepository ДЛЯ МАССОВОЙ ДЕАКТИВАЦИИ
        count = await _reminder_repo.bulk_deactivate(
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
        # ИСПОЛЬЗУЕМ ReminderRepository ДЛЯ МАССОВОГО УДАЛЕНИЯ
        count = await _reminder_repo.bulk_delete(
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
