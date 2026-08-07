from datetime import datetime

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from ...db import db_manager
from ...exceptions import log_exceptions
from ...logger import api_logger
from ...models import ReminderShareModel
from ...services.reminder_service import reminder_service
from ...utils.datetime import get_timestamp

router = APIRouter(prefix="/reminders", tags=["Reminders"])


# ============ Pydantic модели ============


class CreateReminderRequest(BaseModel):
    """Модель запроса для создания напоминания"""

    user_id: int = Field(..., description="ID пользователя")  # ← ДОБАВИТЬ ЭТУ СТРОКУ
    title: str = Field(..., description="Название", min_length=1, max_length=500)
    remind_at: datetime = Field(..., description="Время напоминания")
    description: str | None = Field(None, description="Описание")
    category: str | None = Field(None, description="Категория")
    remind_until: datetime | None = Field(None, description="Дата окончания оповещений")
    remind_interval: int | None = Field(None, description="Интервал в минутах (0 - одноразово)")
    max_remind_count: int | None = Field(None, description="Максимальное количество оповещений")
    code_word: str | None = Field(None, description="Кодовое слово")
    notification_type: str = Field("private", description="Тип уведомления: private, group, both")
    chat_id: int | None = Field(None, description="ID чата (для групповых)")
    shared_with: list[int] | None = Field(None, description="ID пользователей для общего дела")
    encrypt: bool = Field(False, description="Шифровать данные")


class CompleteReminderRequest(BaseModel):
    """Модель запроса для завершения дела"""

    user_id: int = Field(..., description="ID пользователя")
    successful: bool = Field(True, description="Успешно ли выполнено")


class ReminderStatsRequest(BaseModel):
    """Модель запроса для статистики"""

    period: str = Field("week", description="Период: day, week, month, year")


# ============ Эндпоинты ============


@router.post("/", summary="Создать напоминание", description="Создание нового дела или напоминания")
@log_exceptions(api_logger)
async def create_reminder(request: CreateReminderRequest) -> JSONResponse:
    """Создание напоминания"""

    try:
        async with db_manager.get_session() as session:
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


@router.post("/{reminder_id}/complete", summary="Завершить дело", description="Отметить дело как выполненное")
@log_exceptions(api_logger)
async def complete_reminder(reminder_id: int, request: CompleteReminderRequest) -> JSONResponse:
    """Завершение дела"""

    try:
        async with db_manager.get_session() as session:
            success, message = await reminder_service.complete_reminder(
                reminder_id=reminder_id, user_id=request.user_id, successful=request.successful, session=session
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


@router.get("/user/{user_id}", summary="Получить дела пользователя", description="Получение списка дел пользователя")
@log_exceptions(api_logger)
async def get_user_reminders(
    user_id: int, date: datetime | None = None, category: str | None = None, include_completed: bool = False
) -> JSONResponse:
    """Получение дел пользователя"""

    try:
        async with db_manager.get_session() as session:
            reminders = await reminder_service.get_reminders(
                user_id=user_id, date=date, category=category, include_completed=include_completed, session=session
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


@router.get("/stats/{user_id}", summary="Статистика дел", description="Статистика выполнения дел пользователем")
@log_exceptions(api_logger)
async def get_reminder_stats(
    user_id: int, period: str = Query("week", description="Период: day, week, month, year")
) -> JSONResponse:
    """Получение статистики по делам"""

    try:
        async with db_manager.get_session() as session:
            stats = await reminder_service.get_reminder_stats(user_id=user_id, period=period, session=session)

            return JSONResponse(
                status_code=200, content={"success": True, "stats": stats, "timestamp": get_timestamp()}
            )

    except Exception as e:
        api_logger.error(f"Failed to get reminder stats: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e)) from e


@router.post("/by-code-word", summary="Найти дела по кодовому слову", description="Поиск дел по кодовому слову")
@log_exceptions(api_logger)
async def find_reminders_by_code_word(user_id: int, code_word: str, chat_id: int | None = None) -> JSONResponse:
    """Поиск дел по кодовому слову"""

    try:
        from sqlalchemy import or_, select

        from ...models import ReminderModel

        async with db_manager.get_session() as session:
            stmt = select(ReminderModel).where(
                or_(
                    ReminderModel.FK_User == user_id,
                    ReminderModel.FID.in_(
                        select(ReminderShareModel.FK_Reminder).where(ReminderShareModel.FK_User == user_id)
                    ),
                ),
                ReminderModel.FCodeWord == code_word,
                ReminderModel.FIsActive,
                not ReminderModel.FIsDeleted,
                not ReminderModel.FIsCompleted,
            )

            if chat_id:
                stmt = stmt.where(or_(ReminderModel.FK_Chat == chat_id, ReminderModel.FNotificationType == "private"))

            result = await session.execute(stmt)
            reminders = result.scalars().all()

            return JSONResponse(
                status_code=200,
                content={
                    "success": True,
                    "reminders": [
                        {
                            "id": r.FID,
                            "title": r.FTitle,
                            "description": r.FDescription,
                            "remind_at": r.FRemindAt.isoformat(),
                            "remind_count": r.FRemindCount,
                            "notification_type": r.FNotificationType,
                        }
                        for r in reminders
                    ],
                    "count": len(reminders),
                    "timestamp": get_timestamp(),
                },
            )

    except Exception as e:
        api_logger.error(f"Failed to find reminders by code word: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e)) from e
