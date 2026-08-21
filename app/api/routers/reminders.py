"""
Модуль роутера для управления напоминаниями и делами.

Этот модуль предоставляет API эндпоинты для работы с напоминаниями:
- Создание напоминаний (личных и групповых)
- Завершение дел с отметкой успешности
- Получение списка дел пользователя с фильтрацией
- Управление кодовыми словами для доступа
- Статистика по делам
- Массовые операции (деактивация, удаление)

Все эндпоинты используют общий префикс /reminders и интегрируются
с reminder_service для бизнес-логики.

Роуты:
    POST / - Создание напоминания
    POST /{reminder_id}/complete - Завершение дела
    GET /user/{user_id} - Получение дел пользователя
    GET /{reminder_id} - Получение дела по ID
    DELETE /{reminder_id} - Удаление дела
    GET /stats/{user_id} - Статистика по делам
    POST /by-code-word - Поиск по кодовому слову
    POST /{reminder_id}/deactivate - Деактивация напоминания
    POST /bulk/deactivate - Массовая деактивация
    POST /bulk/delete - Массовое удаление
"""

from datetime import datetime
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from ...db.repositories import ReminderRepository
from ...logger import api_logger
from ...services.reminder_service import reminder_service
from ...utils.datetime import get_timestamp
from ...utils.decorators import log_exceptions
from ..dependencies import get_session

# Создание роутера с префиксом /reminders и тегом для документации
router = APIRouter(prefix="/reminders", tags=["Reminders"])

# Репозиторий для работы с напоминаниями (создается один раз на уровне модуля)
_reminder_repo = ReminderRepository()


class CreateReminderRequest(BaseModel):
    """
    Модель запроса для создания напоминания.

    Поддерживает создание как личных, так и групповых дел.
    """

    user_id: int = Field(..., description="ID пользователя-владельца")
    title: str = Field(..., description="Название дела", min_length=1, max_length=500)
    remind_at: datetime = Field(..., description="Время для первого напоминания")
    description: str | None = Field(None, description="Подробное описание дела")
    category: str | None = Field(None, description="Категория для группировки")
    remind_until: datetime | None = Field(None, description="Дата окончания оповещений")
    remind_interval: int | None = Field(None, description="Интервал между напоминаниями (минуты)")
    max_remind_count: int | None = Field(None, description="Максимальное количество оповещений")
    code_word: str | None = Field(None, description="Кодовое слово для доступа к делу")
    notification_type: str = Field("private", description="Тип уведомления: private, chat, group")
    chat_id: int | None = Field(None, description="ID чата для групповых уведомлений")
    shared_with: list[int] | None = Field(None, description="ID пользователей для общего дела")
    encrypt: bool = Field(False, description="Шифровать данные дела")


class CompleteReminderRequest(BaseModel):
    """
    Модель запроса для завершения дела.

    Используется для отметки дела как выполненного или невыполненного.
    """

    user_id: int = Field(..., description="ID пользователя, завершающего дело")
    successful: bool = Field(True, description="Успешно ли выполнено дело")


class ReminderResponse(BaseModel):
    """
    Модель ответа с информацией о напоминании.

    Содержит все поля дела в удобном для отображения формате.
    """

    id: int = Field(..., description="ID напоминания")
    title: str = Field(..., description="Название")
    description: str | None = Field(None, description="Описание")
    category: str | None = Field(None, description="Категория")
    remind_at: str = Field(..., description="Время напоминания (ISO формат)")
    remind_until: str | None = Field(None, description="Дата окончания оповещений")
    remind_interval: int | None = Field(None, description="Интервал в минутах")
    remind_count: int = Field(0, description="Количество отправленных уведомлений")
    max_remind_count: int | None = Field(None, description="Максимальное количество оповещений")
    is_completed: bool = Field(False, description="Завершено ли дело")
    is_successful: bool | None = Field(None, description="Успешно ли выполнено")
    completed_at: str | None = Field(None, description="Время завершения")
    is_group: bool = Field(False, description="Является ли общим делом")
    code_word: str | None = Field(None, description="Кодовое слово")
    is_encrypted: bool = Field(False, description="Зашифровано ли дело")
    notification_type: str = Field("private", description="Тип уведомления")
    created_at: str = Field(..., description="Время создания")
    updated_at: str = Field(..., description="Время последнего обновления")

    @classmethod
    def from_reminder_dict(cls, data: dict[str, Any]) -> "ReminderResponse":
        """
        Создание объекта ответа из словаря репозитория.

        Args:
            data: Словарь с данными напоминания

        Returns:
            ReminderResponse: Объект ответа
        """
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
    """Модель ответа со списком напоминаний."""

    success: bool = Field(..., description="Успешность операции")
    reminders: list[ReminderResponse] = Field(default_factory=list, description="Список напоминаний")
    count: int = Field(0, description="Количество напоминаний в списке")
    timestamp: str = Field(..., description="Время выполнения запроса")


class ReminderStatsResponse(BaseModel):
    """Модель ответа со статистикой по делам."""

    success: bool = Field(..., description="Успешность операции")
    stats: dict[str, Any] = Field(..., description="Статистические данные")
    timestamp: str = Field(..., description="Время выполнения запроса")


# ============ ЭНДПОИНТЫ ============


@router.post(
    "/",
    summary="Создать напоминание",
    description="Создает новое напоминание (личное или групповое)",
)
@log_exceptions(api_logger)
async def create_reminder(
    request: CreateReminderRequest,
    session: AsyncSession = Depends(get_session),
) -> JSONResponse:
    """
    Создание нового напоминания.

    Поддерживает:
    - Личные дела
    - Групповые дела с общим доступом
    - Шифрование содержимого
    - Кодовые слова для доступа

    Args:
        request: Данные для создания напоминания
        session: Асинхронная сессия SQLAlchemy

    Returns:
        JSONResponse: Созданное напоминание

    Raises:
        HTTPException: При ошибках создания
    """
    try:
        # Создание через сервис
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

        # Форматирование ответа
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


@router.post(
    "/{reminder_id}/complete",
    summary="Завершить дело",
    description="Отмечает дело как завершенное с указанием успешности",
)
@log_exceptions(api_logger)
async def complete_reminder(
    reminder_id: int,
    request: CompleteReminderRequest,
    session: AsyncSession = Depends(get_session),
) -> JSONResponse:
    """
    Завершение дела с указанием успешности выполнения.

    Args:
        reminder_id: ID дела для завершения
        request: Данные о пользователе и успешности
        session: Асинхронная сессия SQLAlchemy

    Returns:
        JSONResponse: Результат завершения
    """
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


@router.get(
    "/user/{user_id}",
    summary="Получить дела пользователя",
    description="Возвращает список дел пользователя с фильтрацией и пагинацией",
)
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
    """
    Получение списка дел пользователя.

    Поддерживает фильтрацию по:
    - Дате (дела на конкретную дату)
    - Категории
    - Статусу выполнения (включая завершенные)

    Args:
        user_id: ID пользователя
        session: Асинхронная сессия SQLAlchemy
        date: Дата для фильтрации (опционально)
        category: Категория для фильтрации (опционально)
        include_completed: Включать завершенные дела
        limit: Максимальное количество записей
        offset: Смещение для пагинации

    Returns:
        JSONResponse: Список дел пользователя
    """
    try:
        reminders_data = await reminder_service.get_reminders(
            user_id=user_id,
            date=date,
            category=category,
            include_completed=include_completed,
            limit=limit,
            offset=offset,
            session=session,
        )

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


@router.get(
    "/{reminder_id}",
    summary="Получить дело по ID",
    description="Возвращает детальную информацию о деле",
)
@log_exceptions(api_logger)
async def get_reminder_by_id(
    reminder_id: int,
    session: AsyncSession = Depends(get_session),
) -> JSONResponse:
    """
    Получение дела по его ID.

    Args:
        reminder_id: ID дела
        session: Асинхронная сессия SQLAlchemy

    Returns:
        JSONResponse: Информация о деле

    Raises:
        HTTPException: При ошибках получения
    """
    try:
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


@router.delete(
    "/{reminder_id}",
    summary="Удалить дело",
    description="Удаляет дело (мягкое или жесткое удаление)",
)
@log_exceptions(api_logger)
async def delete_reminder(
    reminder_id: int,
    session: AsyncSession = Depends(get_session),
    soft: bool = True,
) -> JSONResponse:
    """
    Удаление дела.

    Args:
        reminder_id: ID дела для удаления
        session: Асинхронная сессия SQLAlchemy
        soft: Мягкое удаление (только отметка) или жесткое (полное)

    Returns:
        JSONResponse: Результат удаления
    """
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


@router.get(
    "/stats/{user_id}",
    summary="Статистика дел",
    description="Получение статистики по делам пользователя за период",
)
@log_exceptions(api_logger)
async def get_reminder_stats(
    user_id: int,
    session: AsyncSession = Depends(get_session),
    period: str = Query("week", description="Период: day, week, month, year"),
) -> JSONResponse:
    """
    Получение статистики по делам пользователя.

    Возвращает:
    - Количество созданных дел
    - Количество завершенных
    - Процент успешных
    - Распределение по категориям
    - Динамику по дням

    Args:
        user_id: ID пользователя
        session: Асинхронная сессия SQLAlchemy
        period: Период для статистики

    Returns:
        JSONResponse: Статистика по делам
    """
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


@router.post(
    "/by-code-word",
    summary="Найти дела по кодовому слову",
    description="Поиск дел по кодовому слову для быстрого доступа",
)
@log_exceptions(api_logger)
async def find_reminders_by_code_word(
    user_id: int,
    code_word: str,
    session: AsyncSession = Depends(get_session),
    chat_id: int | None = None,
    include_completed: bool = False,
) -> JSONResponse:
    """
    Поиск дел по кодовому слову.

    Используется для быстрого доступа к делам без необходимости
    знать их ID или точное название.

    Args:
        user_id: ID пользователя
        code_word: Кодовое слово для поиска
        session: Асинхронная сессия SQLAlchemy
        chat_id: ID чата для фильтрации (опционально)
        include_completed: Включать завершенные дела

    Returns:
        JSONResponse: Найденные дела
    """
    try:
        reminders_data = await reminder_service.find_by_code_word(
            user_id=user_id,
            code_word=code_word,
            chat_id=chat_id,
            include_completed=include_completed,
            session=session,
        )

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


@router.post(
    "/{reminder_id}/deactivate",
    summary="Деактивировать напоминание",
    description="Деактивирует напоминание (отключает отправку уведомлений)",
)
@log_exceptions(api_logger)
async def deactivate_reminder(
    reminder_id: int,
    session: AsyncSession = Depends(get_session),
) -> JSONResponse:
    """
    Деактивация напоминания.

    Отключает отправку уведомлений по делу без его удаления.

    Args:
        reminder_id: ID дела для деактивации
        session: Асинхронная сессия SQLAlchemy

    Returns:
        JSONResponse: Результат деактивации
    """
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


@router.post(
    "/bulk/deactivate",
    summary="Массовая деактивация",
    description="Деактивирует несколько напоминаний за один запрос",
)
@log_exceptions(api_logger)
async def bulk_deactivate_reminders(
    reminder_ids: list[int],
    session: AsyncSession = Depends(get_session),
) -> JSONResponse:
    """
    Массовая деактивация напоминаний.

    Args:
        reminder_ids: Список ID дел для деактивации
        session: Асинхронная сессия SQLAlchemy

    Returns:
        JSONResponse: Количество деактивированных дел
    """
    try:
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


@router.post(
    "/bulk/delete",
    summary="Массовое удаление",
    description="Удаляет несколько напоминаний за один запрос",
)
@log_exceptions(api_logger)
async def bulk_delete_reminders(
    reminder_ids: list[int],
    session: AsyncSession = Depends(get_session),
    soft: bool = True,
) -> JSONResponse:
    """
    Массовое удаление напоминаний.

    Args:
        reminder_ids: Список ID дел для удаления
        session: Асинхронная сессия SQLAlchemy
        soft: Мягкое или жесткое удаление

    Returns:
        JSONResponse: Количество удаленных дел
    """
    try:
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
