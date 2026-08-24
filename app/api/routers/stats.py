"""Модуль маршрутов для получения статистики через API.

Предоставляет API эндпоинты для получения статистики системы:
- Полная статистика (чаты, пользователи, сообщения, топ-чаты)
- Статистика чатов (всего, активные, по типам)
- Статистика пользователей (всего, авторизованные, активные за 24ч)
- Статистика сообщений (по типам, по дням, удаленные, с временем жизни)
- Статистика ошибок (по статусам, категориям, серьезности)
- Статистика напоминаний (всего, активные, завершенные, зашифрованные, общие)
- Статистика заявок на автоматизацию (по статусам, приоритетам)
- Системная статистика (версия, Python, платформа, uptime)
- Статистика таблиц БД (количество записей во всех таблицах main)

Все эндпоинты используют общий префикс /stats.
"""

from fastapi import APIRouter, Depends, Query
from fastapi.responses import JSONResponse
from sqlalchemy.ext.asyncio import AsyncSession

from ...db.repositories import StatsRepository
from ...logger import api_logger
from ...utils.datetime import get_timestamp
from ...utils.decorators import log_exceptions
from ..dependencies import get_session

# ============================================================
# РОУТЕР И РЕПОЗИТОРИЙ
# ============================================================

router = APIRouter(prefix="/stats", tags=["Stats"])
_stats_repo = StatsRepository()


# ============================================================
# 1. ПОЛНАЯ СТАТИСТИКА
# ============================================================


@router.get(
    "/full",
    summary="Полная статистика системы",
    description="Возвращает полную статистику по всем компонентам системы: чаты, пользователи, сообщения, топ-чаты",
)
@log_exceptions(api_logger)
async def get_full_stats(
    session: AsyncSession = Depends(get_session),
) -> JSONResponse:
    """Получение полной статистики системы.

    Args:
        session: Асинхронная сессия SQLAlchemy

    Returns:
        JSONResponse: Полная статистика системы
    """
    api_logger.info("📊 Getting full system stats")

    try:
        stats = await _stats_repo.get_full_stats(session)

        return JSONResponse(
            status_code=200,
            content={
                "success": True,
                "stats": stats,
                "timestamp": get_timestamp(),
            },
        )

    except Exception as e:
        api_logger.error(f"❌ Failed to get full stats: {e}", exc_info=True)
        return JSONResponse(
            status_code=500,
            content={
                "success": False,
                "error": f"Failed to get full stats: {str(e)}",
                "timestamp": get_timestamp(),
            },
        )


# ============================================================
# 2. СТАТИСТИКА ЧАТОВ
# ============================================================


@router.get(
    "/chats",
    summary="Статистика чатов",
    description="Возвращает статистику по чатам: общее количество, активные, неактивные, распределение по типам",
)
@log_exceptions(api_logger)
async def get_chats_stats(
    session: AsyncSession = Depends(get_session),
) -> JSONResponse:
    """Получение статистики по чатам.

    Returns:
        JSONResponse: Статистика по чатам
    """
    api_logger.info("📊 Getting chats stats")

    try:
        stats = await _stats_repo.get_chats_stats(session)

        return JSONResponse(
            status_code=200,
            content={
                "success": True,
                "stats": stats,
                "timestamp": get_timestamp(),
            },
        )

    except Exception as e:
        api_logger.error(f"❌ Failed to get chats stats: {e}", exc_info=True)
        return JSONResponse(
            status_code=500,
            content={
                "success": False,
                "error": f"Failed to get chats stats: {str(e)}",
                "timestamp": get_timestamp(),
            },
        )


# ============================================================
# 3. СТАТИСТИКА ПОЛЬЗОВАТЕЛЕЙ
# ============================================================


@router.get(
    "/users",
    summary="Статистика пользователей",
    description="Возвращает статистику по пользователям: всего, авторизованные, активные за 24 часа",
)
@log_exceptions(api_logger)
async def get_users_stats(
    session: AsyncSession = Depends(get_session),
) -> JSONResponse:
    """Получение статистики по пользователям.

    Returns:
        JSONResponse: Статистика по пользователям
    """
    api_logger.info("📊 Getting users stats")

    try:
        stats = await _stats_repo.get_users_stats(session)

        return JSONResponse(
            status_code=200,
            content={
                "success": True,
                "stats": stats,
                "timestamp": get_timestamp(),
            },
        )

    except Exception as e:
        api_logger.error(f"❌ Failed to get users stats: {e}", exc_info=True)
        return JSONResponse(
            status_code=500,
            content={
                "success": False,
                "error": f"Failed to get users stats: {str(e)}",
                "timestamp": get_timestamp(),
            },
        )


# ============================================================
# 4. СТАТИСТИКА СООБЩЕНИЙ
# ============================================================


@router.get(
    "/messages",
    summary="Статистика сообщений",
    description="Возвращает статистику по сообщениям: всего, по типам, по дням, удаленные, с временем жизни",
)
@log_exceptions(api_logger)
async def get_messages_stats(
    session: AsyncSession = Depends(get_session),
) -> JSONResponse:
    """Получение статистики по сообщениям.

    Returns:
        JSONResponse: Статистика по сообщениям
    """
    api_logger.info("📊 Getting messages stats")

    try:
        stats = await _stats_repo.get_messages_stats(session)

        return JSONResponse(
            status_code=200,
            content={
                "success": True,
                "stats": stats,
                "timestamp": get_timestamp(),
            },
        )

    except Exception as e:
        api_logger.error(f"❌ Failed to get messages stats: {e}", exc_info=True)
        return JSONResponse(
            status_code=500,
            content={
                "success": False,
                "error": f"Failed to get messages stats: {str(e)}",
                "timestamp": get_timestamp(),
            },
        )


# ============================================================
# 5. СТАТИСТИКА ОШИБОК
# ============================================================


@router.get(
    "/errors",
    summary="Статистика ошибок",
    description="Возвращает статистику по ошибкам: всего, по статусам, по категориям, по серьезности",
)
@log_exceptions(api_logger)
async def get_errors_stats(
    session: AsyncSession = Depends(get_session),
) -> JSONResponse:
    """Получение статистики по ошибкам.

    Returns:
        JSONResponse: Статистика по ошибкам
    """
    api_logger.info("📊 Getting errors stats")

    try:
        stats = await _stats_repo.get_errors_stats(session)

        return JSONResponse(
            status_code=200,
            content={
                "success": True,
                "stats": stats,
                "timestamp": get_timestamp(),
            },
        )

    except Exception as e:
        api_logger.error(f"❌ Failed to get errors stats: {e}", exc_info=True)
        return JSONResponse(
            status_code=500,
            content={
                "success": False,
                "error": f"Failed to get errors stats: {str(e)}",
                "timestamp": get_timestamp(),
            },
        )


# ============================================================
# 6. СТАТИСТИКА НАПОМИНАНИЙ
# ============================================================


@router.get(
    "/reminders",
    summary="Статистика напоминаний",
    description="Возвращает статистику по напоминаниям: всего, активные, завершенные, зашифрованные, общие",
)
@log_exceptions(api_logger)
async def get_reminders_stats(
    user_id: int | None = Query(None, description="ID пользователя (опционально, для фильтрации)"),
    session: AsyncSession = Depends(get_session),
) -> JSONResponse:
    """Получение статистики по напоминаниям.

    Args:
        user_id: ID пользователя (опционально, для фильтрации)
        session: Асинхронная сессия SQLAlchemy

    Returns:
        JSONResponse: Статистика по напоминаниям
    """
    api_logger.info(f"📊 Getting reminders stats for user {user_id or 'all'}")

    try:
        stats = await _stats_repo.get_reminders_stats(session, user_id)

        return JSONResponse(
            status_code=200,
            content={
                "success": True,
                "stats": stats,
                "timestamp": get_timestamp(),
            },
        )

    except Exception as e:
        api_logger.error(f"❌ Failed to get reminders stats: {e}", exc_info=True)
        return JSONResponse(
            status_code=500,
            content={
                "success": False,
                "error": f"Failed to get reminders stats: {str(e)}",
                "timestamp": get_timestamp(),
            },
        )


# ============================================================
# 7. СТАТИСТИКА АВТОМАТИЗАЦИИ
# ============================================================


@router.get(
    "/automation",
    summary="Статистика заявок на автоматизацию",
    description="Возвращает статистику по заявкам на автоматизацию: всего, по статусам, по приоритетам",
)
@log_exceptions(api_logger)
async def get_automation_stats(
    user_id: int | None = Query(None, description="ID пользователя (опционально, для фильтрации)"),
    session: AsyncSession = Depends(get_session),
) -> JSONResponse:
    """Получение статистики по заявкам на автоматизацию.

    Args:
        user_id: ID пользователя (опционально, для фильтрации)
        session: Асинхронная сессия SQLAlchemy

    Returns:
        JSONResponse: Статистика по заявкам
    """
    api_logger.info(f"📊 Getting automation stats for user {user_id or 'all'}")

    try:
        stats = await _stats_repo.get_automation_stats(session, user_id)

        return JSONResponse(
            status_code=200,
            content={
                "success": True,
                "stats": stats,
                "timestamp": get_timestamp(),
            },
        )

    except Exception as e:
        api_logger.error(f"❌ Failed to get automation stats: {e}", exc_info=True)
        return JSONResponse(
            status_code=500,
            content={
                "success": False,
                "error": f"Failed to get automation stats: {str(e)}",
                "timestamp": get_timestamp(),
            },
        )


# ============================================================
# 8. СИСТЕМНАЯ СТАТИСТИКА
# ============================================================


@router.get(
    "/system",
    summary="Системная статистика",
    description="Возвращает системную статистику: версия, Python, платформа, uptime, состояние компонентов",
)
@log_exceptions(api_logger)
async def get_system_stats() -> JSONResponse:
    """Получение системной статистики.

    Returns:
        JSONResponse: Системная статистика
    """
    api_logger.info("📊 Getting system stats")

    try:
        stats = await _stats_repo.get_system_stats()

        return JSONResponse(
            status_code=200,
            content={
                "success": True,
                "stats": stats,
                "timestamp": get_timestamp(),
            },
        )

    except Exception as e:
        api_logger.error(f"❌ Failed to get system stats: {e}", exc_info=True)
        return JSONResponse(
            status_code=500,
            content={
                "success": False,
                "error": f"Failed to get system stats: {str(e)}",
                "timestamp": get_timestamp(),
            },
        )


# ============================================================
# 9. СТАТИСТИКА ТАБЛИЦ БАЗЫ ДАННЫХ
# ============================================================


@router.get(
    "/db",
    summary="Статистика таблиц БД",
    description="Возвращает количество записей во всех таблицах базы данных main",
)
@log_exceptions(api_logger)
async def get_db_stats(
    session: AsyncSession = Depends(get_session),
) -> JSONResponse:
    """Получение статистики по таблицам БД.

    Возвращает количество записей в каждой таблице базы данных main,
    отсортированных по убыванию.

    Args:
        session: Асинхронная сессия SQLAlchemy

    Returns:
        JSONResponse: Статистика таблиц БД
    """
    api_logger.info("📊 Getting DB table stats")

    try:
        stats = await _stats_repo.get_table_stats(session)

        return JSONResponse(
            status_code=200,
            content={
                "success": True,
                "stats": stats,
                "timestamp": get_timestamp(),
            },
        )

    except Exception as e:
        api_logger.error(f"❌ Failed to get DB stats: {e}", exc_info=True)
        return JSONResponse(
            status_code=500,
            content={
                "success": False,
                "error": f"Failed to get DB stats: {str(e)}",
                "timestamp": get_timestamp(),
            },
        )


# ============================================================
# 10. КОМБИНИРОВАННАЯ СТАТИСТИКА (ВСЕ ВИДЫ)
# ============================================================


@router.get(
    "/all",
    summary="Все виды статистики",
    description="Возвращает все виды статистики в одном ответе",
)
@log_exceptions(api_logger)
async def get_all_stats(
    session: AsyncSession = Depends(get_session),
) -> JSONResponse:
    """Получение всех видов статистики в одном ответе.

    Args:
        session: Асинхронная сессия SQLAlchemy

    Returns:
        JSONResponse: Все виды статистики
    """
    api_logger.info("📊 Getting all stats")

    try:
        full_stats = await _stats_repo.get_full_stats(session)
        chats_stats = await _stats_repo.get_chats_stats(session)
        users_stats = await _stats_repo.get_users_stats(session)
        messages_stats = await _stats_repo.get_messages_stats(session)
        errors_stats = await _stats_repo.get_errors_stats(session)
        reminders_stats = await _stats_repo.get_reminders_stats(session)
        automation_stats = await _stats_repo.get_automation_stats(session)
        system_stats = await _stats_repo.get_system_stats()
        table_stats = await _stats_repo.get_table_stats(session)

        return JSONResponse(
            status_code=200,
            content={
                "success": True,
                "stats": {
                    "full": full_stats,
                    "chats": chats_stats,
                    "users": users_stats,
                    "messages": messages_stats,
                    "errors": errors_stats,
                    "reminders": reminders_stats,
                    "automation": automation_stats,
                    "system": system_stats,
                    "db_tables": table_stats,
                },
                "timestamp": get_timestamp(),
            },
        )

    except Exception as e:
        api_logger.error(f"❌ Failed to get all stats: {e}", exc_info=True)
        return JSONResponse(
            status_code=500,
            content={
                "success": False,
                "error": f"Failed to get all stats: {str(e)}",
                "timestamp": get_timestamp(),
            },
        )


__all__ = ["router"]
