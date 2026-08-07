from datetime import datetime

from fastapi import APIRouter, HTTPException
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from ...config import settings
from ...db import db_manager
from ...exceptions import log_exceptions
from ...logger import api_logger
from ...models import ErrorCategory, ErrorSeverity
from ...services.error_service import error_service
from ...utils.datetime import get_timestamp

router = APIRouter(prefix="/errors", tags=["Errors"])


# ============ Pydantic модели ============


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


# ============ Вспомогательные функции ============

# def _get_default_chat_id() -> Optional[int]:
#     """Получение дефолтного чата для отправки сообщения об ошибке (первый из списка)"""
#     support_chats = getattr(settings, 'SUPPORT_CHAT_IDS', [])
#     if support_chats and isinstance(support_chats, list) and len(support_chats) > 0:
#         return support_chats[0]
#     return None


def _get_all_support_chats() -> list:
    """Получение всех чатов поддержки"""
    support_chats = getattr(settings, "SUPPORT_CHAT_IDS", [])
    if isinstance(support_chats, list):
        return support_chats
    if isinstance(support_chats, str):
        try:
            import ast

            if support_chats.startswith("[") and support_chats.endswith("]"):
                result = ast.literal_eval(support_chats)
                if isinstance(result, list):
                    return result
        except (ValueError, SyntaxError):
            pass
        # Если через запятую
        if "," in support_chats:
            return [int(x.strip()) for x in support_chats.split(",") if x.strip()]
    return []


# async def _send_error_notification(error_model: ErrorModel) -> None:
#     """Отправка уведомления об ошибке в чаты техподдержки."""
#     try:
#         await log_handler_service.send_notification(error_model)
#         api_logger.debug(f"✅ Notification sent for error {error_model.FID}")
#     except Exception as e:
#         api_logger.error(f"❌ Failed to send notification for error {error_model.FID}: {e}")


async def _get_error_message_count(error_id: int) -> int:
    """Получение количества сообщений, связанных с ошибкой"""
    try:
        from sqlalchemy import func, select

        from ...models import ErrorMessageLinkModel

        async with db_manager.get_session() as session:
            stmt = (
                select(func.count())
                .select_from(ErrorMessageLinkModel)
                .where(ErrorMessageLinkModel.FK_Error == error_id)
            )
            result = await session.execute(stmt)
            return result.scalar() or 0
    except Exception as e:
        api_logger.error(f"❌ Failed to get message count: {e}")
        return 0


# ============ Эндпоинты ============


@router.post(
    "/external", summary="Зарегистрировать внешнюю ошибку", description="Регистрация ошибки из внешней системы"
)
@log_exceptions(api_logger)
async def register_external_error(request: ErrorRequest) -> JSONResponse:
    """Регистрация внешней ошибки"""

    api_logger.info(f"📝 Registering external error: {request.error_code} from {request.source_system}")

    try:
        async with db_manager.get_session() as session:
            chat_ids = request.chat_ids
            if not chat_ids:
                chat_ids = _get_all_support_chats()
                if chat_ids:
                    api_logger.debug(f"ℹ️ Using default chat_ids from settings: {chat_ids}")

            if not chat_ids:
                api_logger.warning("⚠️ No chat_ids provided, message will not be sent to Telegram")

            api_logger.info(f"📨 Will send to {len(chat_ids) if chat_ids else 0} chats: {chat_ids}")

            # Сохранение ошибки (с отправкой в Telegram во все чаты)
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

            # Получение количества связанных сообщений
            message_count = await _get_error_message_count(error.FID)

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
async def resolve_error(error_id: int, request: ErrorResolveRequest) -> JSONResponse:
    """Решение ошибки"""

    api_logger.info(f"🔧 Resolving error {error_id} by user {request.resolved_by}")

    try:
        async with db_manager.get_session() as session:
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
async def reopen_error(error_id: int) -> JSONResponse:
    """Переоткрытие ошибки"""

    api_logger.info(f"🔁 Reopening error {error_id}")

    try:
        async with db_manager.get_session() as session:
            success, message = await error_service.reopen_error(error_id=error_id, session=session)

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
    start_date: datetime | None = None, end_date: datetime | None = None, category: ErrorCategory | None = None
) -> JSONResponse:
    """Получение статистики ошибок"""

    api_logger.info("📊 Getting error stats")

    try:
        async with db_manager.get_session() as session:
            stats = await error_service.get_error_stats(
                start_date=start_date, end_date=end_date, category=category, session=session
            )

            return JSONResponse(
                status_code=200, content={"success": True, "stats": stats, "timestamp": get_timestamp()}
            )

    except Exception as e:
        api_logger.error(f"❌ Failed to get error stats: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e)) from e


@router.get(
    "/user/{user_id}/stats", summary="Статистика пользователя", description="Статистика пользователя по решению ошибок"
)
@log_exceptions(api_logger)
async def get_user_stats(user_id: int) -> JSONResponse:
    """Получение статистики пользователя"""

    api_logger.info(f"📊 Getting user stats for user {user_id}")

    try:
        async with db_manager.get_session() as session:
            stats = await error_service.get_user_stats(user_id=user_id, session=session)

            return JSONResponse(
                status_code=200, content={"success": True, "stats": stats, "timestamp": get_timestamp()}
            )

    except Exception as e:
        api_logger.error(f"❌ Failed to get user stats: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e)) from e


@router.put("/settings", summary="Настройки уведомлений", description="Обновление настроек уведомлений для чата")
@log_exceptions(api_logger)
async def update_notification_settings(request: ChatNotificationSettingsRequest) -> JSONResponse:
    """Обновление настроек уведомлений"""

    api_logger.info(f"⚙️ Updating notification settings for chat {request.chat_id}")

    try:
        from sqlalchemy import select

        from ...models import ChatNotificationSettingsModel

        async with db_manager.get_session() as session:
            stmt = select(ChatNotificationSettingsModel).where(ChatNotificationSettingsModel.FK_Chat == request.chat_id)
            result = await session.execute(stmt)
            settings = result.scalar_one_or_none()

            if settings:
                settings.FSilenceStart = request.silence_start
                settings.FSilenceEnd = request.silence_end
                settings.FSilenceEnabled = request.silence_enabled
                settings.FNotifyErrors = request.notify_errors
                settings.FNotifyPeriodicTasks = request.notify_periodic_tasks
                settings.FNotifyTaskExecution = request.notify_task_execution
                settings.FNotifySystem = request.notify_system
                settings.FNotificationLevel = request.notification_level
                settings.FGroupingEnabled = request.grouping_enabled
                settings.FGroupingWindowMinutes = request.grouping_window_minutes
                settings.FEnableAutoReports = request.auto_reports_enabled
                settings.FAutoReportInterval = request.auto_report_interval
                settings.FAutoReportHourStart = request.auto_report_hour_start
                settings.FAutoReportHourEnd = request.auto_report_hour_end
                api_logger.debug(f"ℹ️ Updated existing settings for chat {request.chat_id}")
            else:
                settings = ChatNotificationSettingsModel(
                    FK_Chat=request.chat_id,
                    FSilenceStart=request.silence_start,
                    FSilenceEnd=request.silence_end,
                    FSilenceEnabled=request.silence_enabled,
                    FNotifyErrors=request.notify_errors,
                    FNotifyPeriodicTasks=request.notify_periodic_tasks,
                    FNotifyTaskExecution=request.notify_task_execution,
                    FNotifySystem=request.notify_system,
                    FNotificationLevel=request.notification_level,
                    FGroupingEnabled=request.grouping_enabled,
                    FGroupingWindowMinutes=request.grouping_window_minutes,
                    FEnableAutoReports=request.auto_reports_enabled,
                    FAutoReportInterval=request.auto_report_interval,
                    FAutoReportHourStart=request.auto_report_hour_start,
                    FAutoReportHourEnd=request.auto_report_hour_end,
                )
                session.add(settings)
                api_logger.debug(f"ℹ️ Created new settings for chat {request.chat_id}")

            await session.commit()

            api_logger.info(f"✅ Notification settings updated for chat {request.chat_id}")

            return JSONResponse(
                status_code=200,
                content={"success": True, "message": "Settings updated successfully", "timestamp": get_timestamp()},
            )

    except Exception as e:
        api_logger.error(f"❌ Failed to update notification settings: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e)) from e


@router.get("/settings/{chat_id}", summary="Получить настройки", description="Получение настроек уведомлений для чата")
@log_exceptions(api_logger)
async def get_notification_settings(chat_id: int) -> JSONResponse:
    """Получение настроек уведомлений"""

    api_logger.info(f"⚙️ Getting notification settings for chat {chat_id}")

    try:
        from sqlalchemy import select

        from ...models import ChatNotificationSettingsModel

        async with db_manager.get_session() as session:
            stmt = select(ChatNotificationSettingsModel).where(ChatNotificationSettingsModel.FK_Chat == chat_id)
            result = await session.execute(stmt)
            settings = result.scalar_one_or_none()

            if not settings:
                api_logger.warning(f"⚠️ Settings not found for chat {chat_id}")
                return JSONResponse(
                    status_code=404,
                    content={"success": False, "message": "Settings not found", "timestamp": get_timestamp()},
                )

            api_logger.info(f"✅ Settings retrieved for chat {chat_id}")

            return JSONResponse(
                status_code=200,
                content={
                    "success": True,
                    "settings": {
                        "silence_start": settings.FSilenceStart,
                        "silence_end": settings.FSilenceEnd,
                        "silence_enabled": settings.FSilenceEnabled,
                        "notify_errors": settings.FNotifyErrors,
                        "notify_periodic_tasks": settings.FNotifyPeriodicTasks,
                        "notify_task_execution": settings.FNotifyTaskExecution,
                        "notify_system": settings.FNotifySystem,
                        "notification_level": settings.FNotificationLevel.value,
                        "grouping_enabled": settings.FGroupingEnabled,
                        "grouping_window_minutes": settings.FGroupingWindowMinutes,
                        "auto_reports_enabled": settings.FEnableAutoReports,
                        "auto_report_interval": settings.FAutoReportInterval,
                        "auto_report_hour_start": settings.FAutoReportHourStart,
                        "auto_report_hour_end": settings.FAutoReportHourEnd,
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
async def generate_report(chat_id: int) -> JSONResponse:
    """Генерация отчета об ошибках"""

    api_logger.info(f"📊 Generating report for chat {chat_id}")

    try:
        from ...services.notification_service import notification_service

        async with db_manager.get_session() as session:
            report = await notification_service.generate_auto_report(chat_id=chat_id, session=session)

            api_logger.info(f"✅ Report generated for chat {chat_id}")

            return JSONResponse(
                status_code=200, content={"success": True, "report": report, "timestamp": get_timestamp()}
            )

    except Exception as e:
        api_logger.error(f"❌ Failed to generate report: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e)) from e
