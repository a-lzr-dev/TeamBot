from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from ...db.repositories import ErrorRepository, NotificationSettingsRepository
from ...exceptions import log_exceptions
from ...logger import api_logger
from ...models import ErrorCategory, ErrorSeverity
from ...services import error_service
from ...utils import get_timestamp
from ..dependencies import get_session

router = APIRouter(prefix="/errors", tags=["Errors"])

# Репозитории (создаем один раз на уровне модуля)
_error_repo = ErrorRepository()
_settings_repo = NotificationSettingsRepository()


class ErrorRequest(BaseModel):
    """Модель запроса для внешней ошибки"""

    error_code: str = Field(..., description="Код ошибки", min_length=1, max_length=100)
    error_message: str = Field(..., description="Сообщение об ошибке", min_length=1)
    source_system: str = Field(..., description="Система-источник", min_length=1, max_length=100)
    source_module: str | None = Field(None, description="Модуль-источник", max_length=100)
    user_id: int | None = Field(None, description="ID пользователя, у которого возникла ошибка")
    user_login: str | None = Field(None, description="Логин пользователя")
    category: ErrorCategory = Field(ErrorCategory.EXTERNAL, description="Категория ошибки")
    severity: ErrorSeverity = Field(ErrorSeverity.ERROR, description="Степень серьезности")
    details: str | None = Field(None, description="Детали ошибки")
    chat_ids: list[int] | None = Field(None, description="Список ID чатов для отправки сообщений")
    send_to_telegram: bool = Field(True, description="Отправить сообщение в Telegram")


class ErrorResolveRequest(BaseModel):
    """Модель запроса для решения ошибки"""

    resolved_by: int = Field(..., description="ID пользователя, который решает ошибку")
    check_procedure: str | None = Field(None, description="Хранимая процедура для проверки")


class ErrorFilterRequest(BaseModel):
    """Модель запроса для фильтра ошибок"""

    chat_id: int = Field(..., description="ID чата")
    pattern: str = Field(..., description="Шаблон для фильтрации")
    pattern_type: str = Field("contains", description="Тип шаблона: contains, exact, regex")
    category: ErrorCategory | None = Field(None, description="Категория ошибки")
    error_code: str | None = Field(None, description="Код ошибки")
    source_system: str | None = Field(None, description="Система-источник")
    is_regex: bool = Field(False, description="Использовать регулярное выражение")
    description: str | None = Field(None, description="Описание фильтра")


class ChatNotificationSettingsRequest(BaseModel):
    """Модель запроса для настроек уведомлений"""

    chat_id: int = Field(..., description="ID чата")
    silence_start: str | None = Field(None, description="Начало тишины (HH:MM)")
    silence_end: str | None = Field(None, description="Конец тишины (HH:MM)")
    silence_enabled: bool = Field(False, description="Включить тишину")
    notify_errors: bool = Field(True, description="Уведомлять об ошибках")
    notify_periodic_tasks: bool = Field(True, description="Уведомлять о периодических задачах")
    notify_task_execution: bool = Field(True, description="Уведомлять о выполнении задач")
    notify_system: bool = Field(True, description="Уведомлять о системных событиях")
    notification_level: ErrorSeverity = Field(ErrorSeverity.ERROR, description="Уровень уведомлений")
    grouping_enabled: bool = Field(True, description="Группировать ошибки")
    grouping_window_minutes: int = Field(60, description="Окно группировки в минутах")
    auto_reports_enabled: bool = Field(True, description="Включить автоматические отчеты")
    auto_report_interval: int = Field(60, description="Интервал отчетов в минутах")
    auto_report_hour_start: int = Field(9, description="Начало рабочего времени")
    auto_report_hour_end: int = Field(18, description="Конец рабочего времени")


# ============ Эндпоинты ============


@router.post(
    "/external", summary="Зарегистрировать внешнюю ошибку", description="Регистрация ошибки из внешней системы"
)
@log_exceptions(api_logger)
async def register_external_error(
    request: ErrorRequest,
    session: AsyncSession = Depends(get_session),
) -> JSONResponse:
    """
    Регистрация внешней ошибки.

    Отправка в Telegram происходит автоматически через LogHandlerService,
    который определяет топик на основе source_system.
    """
    api_logger.info(f"📝 Registering external error: {request.error_code} from {request.source_system}")

    try:
        chat_ids = request.chat_ids or []

        if chat_ids:
            api_logger.info(f"📨 Will send to {len(chat_ids)} specified chats: {chat_ids}")
        else:
            api_logger.debug("ℹ️ No chat_ids specified, error will be handled by LogHandlerService")

        # ИСПОЛЬЗУЕМ error_service ДЛЯ ЛОГИРОВАНИЯ ОШИБКИ
        error = await error_service.log_external_error(
            error_code=request.error_code,
            error_message=request.error_message,
            source_system=request.source_system,
            user_id=request.user_id,
            user_login=request.user_login,
            category=request.category,
            severity=request.severity,
            details=request.details,
            source_module=request.source_module,
            chat_ids=chat_ids,
            send_to_telegram=request.send_to_telegram,
            session=session,
        )

        # Используем репозиторий для получения количества связанных сообщений
        message_count = await _error_repo.get_linked_message_count(session, error.FID)

        api_logger.info(f"✅ Error saved with ID: {error.FID}, linked messages: {message_count}")

        return JSONResponse(
            status_code=201,
            content={
                "success": True,
                "error_id": error.FID,
                "linked_messages": message_count,
                "chats_sent": chat_ids if chat_ids else [],
                "message": "Error registered" + (" and message sent" if message_count > 0 else ""),
                "timestamp": get_timestamp(),
            },
        )

    except Exception as e:
        api_logger.error(f"❌ Failed to register external error: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e)) from e


@router.post("/{error_id}/resolve", summary="Решение ошибки", description="Проверка исчезновения ошибки и ее решение")
@log_exceptions(api_logger)
async def resolve_error(
    error_id: int,
    request: ErrorResolveRequest,
    session: AsyncSession = Depends(get_session),
) -> JSONResponse:
    """Решение ошибки"""

    api_logger.info(f"🔧 Resolving error {error_id} by user {request.resolved_by}")

    try:
        # ИСПОЛЬЗУЕМ error_service ДЛЯ РЕШЕНИЯ ОШИБКИ
        success, message = await error_service.check_and_resolve_error(
            error_id=error_id,
            resolved_by=request.resolved_by,
            check_procedure=request.check_procedure,
            session=session,
        )

        if success:
            api_logger.info(f"✅ Error {error_id} resolved successfully")
            return JSONResponse(
                status_code=200, content={"success": True, "message": message, "timestamp": get_timestamp()}
            )
        else:
            api_logger.warning(f"⚠️ Failed to resolve error {error_id}: {message}")
            return JSONResponse(
                status_code=400, content={"success": False, "message": message, "timestamp": get_timestamp()}
            )

    except Exception as e:
        api_logger.error(f"❌ Failed to resolve error: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e)) from e


@router.post("/{error_id}/reopen", summary="Переоткрыть ошибку", description="Переоткрытие ранее решенной ошибки")
@log_exceptions(api_logger)
async def reopen_error(
    error_id: int,
    session: AsyncSession = Depends(get_session),
) -> JSONResponse:
    """Переоткрытие ошибки"""

    api_logger.info(f"🔁 Reopening error {error_id}")

    try:
        # ИСПОЛЬЗУЕМ error_service ДЛЯ ПЕРЕОТКРЫТИЯ ОШИБКИ
        success, message = await error_service.reopen_error(
            error_id=error_id,
            session=session,
        )

        if success:
            api_logger.info(f"✅ Error {error_id} reopened successfully")
            return JSONResponse(
                status_code=200, content={"success": True, "message": message, "timestamp": get_timestamp()}
            )
        else:
            api_logger.warning(f"⚠️ Failed to reopen error {error_id}: {message}")
            return JSONResponse(
                status_code=400, content={"success": False, "message": message, "timestamp": get_timestamp()}
            )

    except Exception as e:
        api_logger.error(f"❌ Failed to reopen error: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e)) from e


@router.get("/stats", summary="Статистика ошибок", description="Получение статистики по ошибкам")
@log_exceptions(api_logger)
async def get_error_stats(
    start_date: datetime | None = None,
    end_date: datetime | None = None,
    category: ErrorCategory | None = None,
    session: AsyncSession = Depends(get_session),
) -> JSONResponse:
    """Получение статистики ошибок"""

    api_logger.info("📊 Getting error stats")

    try:
        # ИСПОЛЬЗУЕМ error_service ДЛЯ ПОЛУЧЕНИЯ СТАТИСТИКИ
        stats = await error_service.get_error_stats(
            start_date=start_date,
            end_date=end_date,
            category=category,
            session=session,
        )

        return JSONResponse(status_code=200, content={"success": True, "stats": stats, "timestamp": get_timestamp()})

    except Exception as e:
        api_logger.error(f"❌ Failed to get error stats: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e)) from e


@router.get(
    "/user/{user_id}/stats", summary="Статистика пользователя", description="Статистика пользователя по решению ошибок"
)
@log_exceptions(api_logger)
async def get_user_stats(
    user_id: int,
    session: AsyncSession = Depends(get_session),
) -> JSONResponse:
    """Получение статистики пользователя"""

    api_logger.info(f"📊 Getting user stats for user {user_id}")

    try:
        # ИСПОЛЬЗУЕМ error_service ДЛЯ ПОЛУЧЕНИЯ СТАТИСТИКИ ПОЛЬЗОВАТЕЛЯ
        stats = await error_service.get_user_stats(
            user_id=user_id,
            session=session,
        )

        return JSONResponse(status_code=200, content={"success": True, "stats": stats, "timestamp": get_timestamp()})

    except Exception as e:
        api_logger.error(f"❌ Failed to get user stats: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e)) from e


@router.put("/settings", summary="Настройки уведомлений", description="Обновление настроек уведомлений для чата")
@log_exceptions(api_logger)
async def update_notification_settings(
    request: ChatNotificationSettingsRequest,
    session: AsyncSession = Depends(get_session),
) -> JSONResponse:
    """Обновление настроек уведомлений"""

    api_logger.info(f"⚙️ Updating notification settings for chat {request.chat_id}")

    try:
        # ИСПОЛЬЗУЕМ репозиторий ДЛЯ ПОЛУЧЕНИЯ НАСТРОЕК
        settings_obj = await _settings_repo.get_by_chat_id(session=session, chat_id=request.chat_id)

        if settings_obj:
            # ИСПОЛЬЗУЕМ update() МЕТОД РЕПОЗИТОРИЯ ВМЕСТО ПРЯМОГО ИЗМЕНЕНИЯ
            updated_settings = await _settings_repo.update(
                session=session,
                chat_id=request.chat_id,
                silence_start=request.silence_start,
                silence_end=request.silence_end,
                silence_enabled=request.silence_enabled,
                notify_errors=request.notify_errors,
                notify_periodic_tasks=request.notify_periodic_tasks,
                notify_task_execution=request.notify_task_execution,
                notify_system=request.notify_system,
                notification_level=request.notification_level,
                grouping_enabled=request.grouping_enabled,
                grouping_window_minutes=request.grouping_window_minutes,
                auto_reports_enabled=request.auto_reports_enabled,
                auto_report_interval=request.auto_report_interval,
                auto_report_hour_start=request.auto_report_hour_start,
                auto_report_hour_end=request.auto_report_hour_end,
            )

            if updated_settings is None:
                api_logger.error(f"❌ Failed to update settings for chat {request.chat_id}")
                return JSONResponse(
                    status_code=500,
                    content={"success": False, "message": "Failed to update settings", "timestamp": get_timestamp()},
                )

            api_logger.debug(f"ℹ️ Updated existing settings for chat {request.chat_id}")
        else:
            # ИСПОЛЬЗУЕМ create() МЕТОД РЕПОЗИТОРИЯ
            await _settings_repo.create(
                session=session,
                chat_id=request.chat_id,
                silence_start=request.silence_start,
                silence_end=request.silence_end,
                silence_enabled=request.silence_enabled,
                notify_errors=request.notify_errors,
                notify_periodic_tasks=request.notify_periodic_tasks,
                notify_task_execution=request.notify_task_execution,
                notify_system=request.notify_system,
                notification_level=request.notification_level,
                grouping_enabled=request.grouping_enabled,
                grouping_window_minutes=request.grouping_window_minutes,
                auto_reports_enabled=request.auto_reports_enabled,
                auto_report_interval=request.auto_report_interval,
                auto_report_hour_start=request.auto_report_hour_start,
                auto_report_hour_end=request.auto_report_hour_end,
            )
            api_logger.debug(f"ℹ️ Created new settings for chat {request.chat_id}")

        # Коммит выполняется автоматически через репозиторий
        # Но для надежности делаем явный коммит
        await session.commit()

        api_logger.info(f"✅ Notification settings updated for chat {request.chat_id}")

        return JSONResponse(
            status_code=200,
            content={"success": True, "message": "Settings updated successfully", "timestamp": get_timestamp()},
        )

    except Exception as e:
        api_logger.error(f"❌ Failed to update notification settings: {e}", exc_info=True)
        await session.rollback()
        raise HTTPException(status_code=500, detail=str(e)) from e


@router.get("/settings/{chat_id}", summary="Получить настройки", description="Получение настроек уведомлений для чата")
@log_exceptions(api_logger)
async def get_notification_settings(
    chat_id: int,
    session: AsyncSession = Depends(get_session),
) -> JSONResponse:
    """Получение настроек уведомлений"""

    api_logger.info(f"⚙️ Getting notification settings for chat {chat_id}")

    try:
        # ИСПОЛЬЗУЕМ репозиторий ДЛЯ ПОЛУЧЕНИЯ НАСТРОЕК
        settings_obj = await _settings_repo.get_by_chat_id(session=session, chat_id=chat_id)

        if not settings_obj:
            api_logger.warning(f"⚠️ Settings not found for chat {chat_id}")
            return JSONResponse(
                status_code=404,
                content={"success": False, "message": "Settings not found", "timestamp": get_timestamp()},
            )

        api_logger.info(f"✅ Settings retrieved for chat {chat_id}")

        # Используем DTO или словарь для ответа
        return JSONResponse(
            status_code=200,
            content={
                "success": True,
                "settings": {
                    "silence_start": settings_obj.FSilenceStart,
                    "silence_end": settings_obj.FSilenceEnd,
                    "silence_enabled": settings_obj.FSilenceEnabled,
                    "notify_errors": settings_obj.FNotifyErrors,
                    "notify_periodic_tasks": settings_obj.FNotifyPeriodicTasks,
                    "notify_task_execution": settings_obj.FNotifyTaskExecution,
                    "notify_system": settings_obj.FNotifySystem,
                    "notification_level": settings_obj.FNotificationLevel.value,
                    "grouping_enabled": settings_obj.FGroupingEnabled,
                    "grouping_window_minutes": settings_obj.FGroupingWindowMinutes,
                    "auto_reports_enabled": settings_obj.FEnableAutoReports,
                    "auto_report_interval": settings_obj.FAutoReportInterval,
                    "auto_report_hour_start": settings_obj.FAutoReportHourStart,
                    "auto_report_hour_end": settings_obj.FAutoReportHourEnd,
                },
                "timestamp": get_timestamp(),
            },
        )

    except Exception as e:
        api_logger.error(f"❌ Failed to get notification settings: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e)) from e


@router.get(
    "/report/{chat_id}", summary="Сгенерировать отчет", description="Генерация автоматического отчета об ошибках"
)
@log_exceptions(api_logger)
async def generate_report(
    chat_id: int,
    session: AsyncSession = Depends(get_session),
) -> JSONResponse:
    """Генерация отчета об ошибках"""

    api_logger.info(f"📊 Generating report for chat {chat_id}")

    try:
        from ...services.notification_service import notification_service

        report = await notification_service.generate_auto_report(
            chat_id=chat_id,
            session=session,
        )

        api_logger.info(f"✅ Report generated for chat {chat_id}")

        return JSONResponse(status_code=200, content={"success": True, "report": report, "timestamp": get_timestamp()})

    except Exception as e:
        api_logger.error(f"❌ Failed to generate report: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e)) from e


__all__ = ["router"]
