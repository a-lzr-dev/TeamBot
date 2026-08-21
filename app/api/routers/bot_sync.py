"""
Модуль роутера для синхронизации чатов и участников с Telegram.

Этот модуль предоставляет API эндпоинты для синхронизации данных
между Telegram и локальной базой данных:
- Синхронизация участников конкретного чата
- Синхронизация всех чатов (только для пользовательских аккаунтов)
- Получение статуса синхронизации
- Очистка кеша синхронизации

Все эндпоинты используют общий префикс /bot/sync и требуют аутентификации.
Модуль интегрируется с BotManager для работы с Telegram API.

Важно: Синхронизация всех чатов доступна только для пользовательских
аккаунтов (не ботов). Боты могут синхронизировать только отдельные чаты.

Роуты:
    POST /chat - Синхронизация участников чата
    POST /all - Синхронизация всех чатов
    GET /status - Статус синхронизации
    DELETE /cache - Очистка кеша синхронизации
"""

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from ...api.dependencies import get_session
from ...bot.dependencies import get_bot_manager
from ...bot.manager import BotManager
from ...logger import api_logger
from ...models import ChatType
from ...utils import get_timestamp
from ...utils.decorators import log_exceptions

# Создание роутера с префиксом /bot/sync и тегом для документации
router = APIRouter(prefix="/bot/sync", tags=["Bot Sync"])


class SyncChatRequest(BaseModel):
    """
    Модель запроса для синхронизации одного чата.

    Используется в эндпоинте /chat для указания чата и параметров синхронизации.
    """

    chat_id: int = Field(..., description="ID чата для синхронизации")
    force: bool = Field(False, description="Принудительная синхронизация (игнорировать кеш)")


class SyncChatResponse(BaseModel):
    """Модель ответа для синхронизации одного чата."""

    success: bool = Field(..., description="Успешность синхронизации")
    chat_id: int = Field(..., description="ID чата")
    processed: int = Field(0, description="Всего обработано участников")
    added: int = Field(0, description="Добавлено новых участников")
    deactivated: int = Field(0, description="Деактивировано участников")
    errors: int = Field(0, description="Количество ошибок при обработке")
    from_cache: bool = Field(False, description="Использован кеш (данные из памяти)")
    message: str | None = Field(None, description="Сообщение о результате")
    timestamp: str = Field(..., description="Время синхронизации")


class SyncAllChatsRequest(BaseModel):
    """
    Модель запроса для синхронизации всех чатов.

    Используется в эндпоинте /all для управления массовой синхронизацией.
    """

    force: bool = Field(False, description="Принудительная синхронизация (игнорировать кеш)")
    max_chats: int | None = Field(None, description="Максимальное количество чатов для синхронизации (ограничение)")
    chat_types: list[ChatType] | None = Field(None, description="Типы чатов для синхронизации (фильтрация)")


class SyncAllChatsResponse(BaseModel):
    """Модель ответа для синхронизации всех чатов."""

    success: bool = Field(..., description="Успешность синхронизации")
    message: str = Field(..., description="Сообщение о результате")
    processed_chats: int = Field(0, description="Обработано чатов")
    processed_members: int = Field(0, description="Обработано участников")
    added_chats: int = Field(0, description="Добавлено новых чатов")
    added_members: int = Field(0, description="Добавлено новых участников")
    deactivated_chats: int = Field(0, description="Деактивировано чатов")
    deactivated_members: int = Field(0, description="Деактивировано участников")
    errors_chats: int = Field(0, description="Ошибок при синхронизации чатов")
    errors_members: int = Field(0, description="Ошибок при синхронизации участников")
    skipped: int = Field(0, description="Пропущено чатов (по различным причинам)")
    duration_seconds: float | None = Field(None, description="Длительность синхронизации в секундах")
    timestamp: str = Field(..., description="Время синхронизации")


class SyncStatusResponse(BaseModel):
    """Модель ответа для статуса синхронизации."""

    success: bool = Field(..., description="Успешность операции")
    last_sync: str | None = Field(None, description="Время последней синхронизации")
    total_syncs: int = Field(0, description="Всего выполнено синхронизаций")
    failed_syncs: int = Field(0, description="Неудачных синхронизаций")
    total_chats_synced: int = Field(0, description="Всего синхронизировано чатов")
    total_members_synced: int = Field(0, description="Всего синхронизировано участников")
    cache_size: int = Field(0, description="Размер кеша синхронизации")
    is_syncing: bool = Field(False, description="Идет ли синхронизация в данный момент")
    timestamp: str = Field(..., description="Время запроса")


class ClearCacheResponse(BaseModel):
    """Модель ответа для очистки кеша синхронизации."""

    success: bool = Field(..., description="Успешность операции")
    message: str = Field(..., description="Сообщение о результате")
    timestamp: str = Field(..., description="Время операции")


# ============ Вспомогательные функции ============


async def _get_bot_manager_with_check() -> BotManager:
    """
    Получение экземпляра BotManager с проверкой статуса.

    Проверяет, что бот запущен и доступен для операций синхронизации.

    Returns:
        BotManager: Экземпляр менеджера бота

    Raises:
        HTTPException: Если бот недоступен (HTTP 503)
    """
    try:
        bot_manager = get_bot_manager()
        status = await bot_manager.get_status()
        if not status.get("is_running", False):
            raise HTTPException(status_code=503, detail="Bot service not available")
        return bot_manager
    except HTTPException:
        raise
    except Exception as e:
        api_logger.error(f"❌ Failed to get Bot manager: {e}")
        raise HTTPException(status_code=503, detail="Bot service unavailable") from e


async def _check_telethon_availability(bot_manager: BotManager) -> None:
    """
    Проверка доступности Telethon клиента.

    Telethon требуется для синхронизации участников чатов.

    Args:
        bot_manager: Экземпляр BotManager

    Raises:
        HTTPException: Если Telethon клиент недоступен (HTTP 503)
    """
    status = await bot_manager.get_status()
    telethon_status = status.get("telethon", {})

    if not telethon_status.get("connected", False):
        raise HTTPException(status_code=503, detail="Bot client not available. Telethon client is required for sync.")


async def _check_account_type(bot_manager: BotManager) -> str:
    """
    Проверка типа аккаунта для синхронизации всех чатов.

    Синхронизация всех чатов доступна только для пользовательских аккаунтов.

    Args:
        bot_manager: Экземпляр BotManager

    Returns:
        str: Тип аккаунта ('user' или 'bot')

    Raises:
        HTTPException: Если аккаунт является ботом (HTTP 400)
    """
    status = await bot_manager.get_status()
    account_type = status.get("account_type", "unknown")
    account_type_str: str = str(account_type) if account_type is not None else "unknown"

    if account_type_str == "bot":
        raise HTTPException(
            status_code=400, detail="Cannot sync all chats with bot account. Use /sync/chat for individual chats."
        )

    return account_type_str


# ============ Эндпоинты ============


@router.post(
    "/chat",
    response_model=SyncChatResponse,
    summary="Синхронизировать чат",
    description="Синхронизирует участников указанного чата с базой данных",
)
@log_exceptions(api_logger)
async def sync_chat(
    request: SyncChatRequest,
    session: AsyncSession = Depends(get_session),
) -> JSONResponse:
    """
    Синхронизация участников конкретного чата.

    Получает список участников чата через Telegram API и обновляет
    базу данных, добавляя новых участников и деактивируя отсутствующих.

    Args:
        request: Запрос с ID чата и параметрами синхронизации
        session: Асинхронная сессия SQLAlchemy

    Returns:
        JSONResponse: Результат синхронизации с детальной статистикой

    Raises:
        HTTPException: При ошибках доступа к боту или отсутствии клиента
    """
    api_logger.info(f"🔄 Syncing chat {request.chat_id} (force={request.force})")

    try:
        # Получение и проверка менеджера бота
        bot_manager = await _get_bot_manager_with_check()
        await _check_telethon_availability(bot_manager)

        # Выполнение синхронизации чата
        result = await bot_manager.sync_chat(chat_id=request.chat_id, session=session, force=request.force)

        if result.get("success", False):
            api_logger.info(f"✅ Chat {request.chat_id} synced successfully")

            return JSONResponse(
                status_code=200,
                content=SyncChatResponse(
                    success=True,
                    chat_id=request.chat_id,
                    processed=result.get("processed", 0),
                    added=result.get("added", 0),
                    deactivated=result.get("deactivated", 0),
                    errors=result.get("errors", 0),
                    from_cache=result.get("from_cache", False),
                    message=f"Chat {request.chat_id} synced successfully",
                    timestamp=get_timestamp(),
                ).model_dump(),
            )
        else:
            error_msg = result.get("error", "Unknown error")
            api_logger.error(f"❌ Failed to sync chat {request.chat_id}: {error_msg}")

            return JSONResponse(
                status_code=500,
                content=SyncChatResponse(
                    success=False,
                    chat_id=request.chat_id,
                    processed=result.get("processed", 0),
                    added=0,
                    deactivated=0,
                    errors=1,
                    from_cache=False,
                    message=f"Failed to sync chat: {error_msg}",
                    timestamp=get_timestamp(),
                ).model_dump(),
            )

    except HTTPException:
        raise
    except Exception as e:
        api_logger.error(f"❌ Failed to sync chat {request.chat_id}: {e}", exc_info=True)
        return JSONResponse(
            status_code=500,
            content=SyncChatResponse(
                success=False,
                chat_id=request.chat_id,
                processed=0,
                added=0,
                deactivated=0,
                errors=1,
                from_cache=False,
                message=f"Internal error: {str(e)}",
                timestamp=get_timestamp(),
            ).model_dump(),
        )


@router.post(
    "/all",
    response_model=SyncAllChatsResponse,
    summary="Синхронизировать все чаты",
    description="""
    Синхронизирует все чаты, в которых присутствует бот.

    **Важно:** Только для пользовательских аккаунтов!
    Для ботов используйте синхронизацию отдельных чатов (/sync/chat).

    Процесс:
    1. Получение списка всех диалогов через Telegram API
    2. Для каждого диалога синхронизация участников
    3. Обновление базы данных с добавлением/деактивацией

    Поддерживает фильтрацию по типам чатов и ограничение количества.
    """,
)
@log_exceptions(api_logger)
async def sync_all_chats(
    request: SyncAllChatsRequest,
) -> JSONResponse:
    """
    Синхронизация всех чатов, в которых участвует аккаунт.

    Доступно только для пользовательских аккаунтов (не ботов).
    Проходит по всем диалогам и синхронизирует участников каждого.

    Args:
        request: Запрос с параметрами синхронизации

    Returns:
        JSONResponse: Агрегированный результат синхронизации всех чатов

    Raises:
        HTTPException: При ошибках доступа к боту или если аккаунт является ботом
    """
    api_logger.info(f"🔄 Syncing all chats (force={request.force})")

    try:
        # Получение и проверка менеджера бота
        bot_manager = await _get_bot_manager_with_check()

        # Проверка доступности клиента
        await _check_telethon_availability(bot_manager)

        # Проверка типа аккаунта (только для пользователей)
        await _check_account_type(bot_manager)

        # Преобразование ChatType в строковое представление для API
        chat_types_str: list[str] | None = None
        if request.chat_types:
            chat_types_str = [ct.value for ct in request.chat_types]

        # Выполнение синхронизации всех чатов
        result = await bot_manager.sync_all_chats(
            force=request.force, max_chats=request.max_chats, chat_types=chat_types_str
        )

        if result.get("success", False):
            api_logger.info("✅ All chats synced successfully")

            processed = result.get("processed", {})
            added = result.get("added", {})
            deactivated = result.get("deactivated", {})
            errors = result.get("errors", {})

            return JSONResponse(
                status_code=200,
                content=SyncAllChatsResponse(
                    success=True,
                    message="All chats synced successfully",
                    processed_chats=processed.get("chats", 0),
                    processed_members=processed.get("members", 0),
                    added_chats=added.get("chats", 0),
                    added_members=added.get("members", 0),
                    deactivated_chats=deactivated.get("chats", 0),
                    deactivated_members=deactivated.get("members", 0),
                    errors_chats=errors.get("chats", 0),
                    errors_members=errors.get("members", 0),
                    skipped=result.get("skipped", 0),
                    duration_seconds=result.get("duration_seconds"),
                    timestamp=get_timestamp(),
                ).model_dump(),
            )
        else:
            error_msg = result.get("error", "Unknown error")
            api_logger.error(f"❌ Failed to sync all chats: {error_msg}")

            return JSONResponse(
                status_code=500,
                content=SyncAllChatsResponse(
                    success=False,
                    message=f"Failed to sync all chats: {error_msg}",
                    processed_chats=0,
                    processed_members=0,
                    added_chats=0,
                    added_members=0,
                    deactivated_chats=0,
                    deactivated_members=0,
                    errors_chats=1,
                    errors_members=0,
                    skipped=0,
                    duration_seconds=None,
                    timestamp=get_timestamp(),
                ).model_dump(),
            )

    except HTTPException:
        raise
    except Exception as e:
        api_logger.error(f"❌ Failed to sync all chats: {e}", exc_info=True)
        return JSONResponse(
            status_code=500,
            content=SyncAllChatsResponse(
                success=False,
                message=f"Internal error: {str(e)}",
                processed_chats=0,
                processed_members=0,
                added_chats=0,
                added_members=0,
                deactivated_chats=0,
                deactivated_members=0,
                errors_chats=1,
                errors_members=0,
                skipped=0,
                duration_seconds=None,
                timestamp=get_timestamp(),
            ).model_dump(),
        )


@router.get(
    "/status",
    summary="Статус синхронизации",
    description="Получить информацию о последней синхронизации и метриках",
)
@log_exceptions(api_logger)
async def get_sync_status() -> JSONResponse:
    """
    Получение статуса и метрик синхронизации.

    Возвращает информацию о:
    - Времени последней синхронизации
    - Количестве выполненных синхронизаций
    - Общем количестве синхронизированных чатов и участников
    - Размере кеша синхронизации

    Returns:
        JSONResponse: Статус синхронизации с метриками
    """
    api_logger.info("📊 Getting sync status...")

    try:
        # Получение менеджера бота
        bot_manager = await _get_bot_manager_with_check()

        # Получение статуса из менеджера
        status = await bot_manager.get_status()
        sync_status = status.get("sync", {})

        return JSONResponse(
            status_code=200,
            content=SyncStatusResponse(
                success=True,
                last_sync=sync_status.get("last_sync"),
                total_syncs=sync_status.get("metrics", {}).get("total_syncs", 0),
                failed_syncs=sync_status.get("metrics", {}).get("failed_syncs", 0),
                total_chats_synced=sync_status.get("metrics", {}).get("total_chats_synced", 0),
                total_members_synced=sync_status.get("metrics", {}).get("total_members_synced", 0),
                cache_size=sync_status.get("cache_size", 0),
                is_syncing=False,  # В текущей реализации синхронизация синхронна
                timestamp=get_timestamp(),
            ).model_dump(),
        )

    except HTTPException:
        raise
    except Exception as e:
        api_logger.error(f"❌ Failed to get sync status: {e}", exc_info=True)
        return JSONResponse(status_code=500, content={"success": False, "error": str(e), "timestamp": get_timestamp()})


@router.delete(
    "/cache",
    summary="Очистить кеш синхронизации",
    description="Очищает кеш синхронизации для указанного чата или всех чатов",
)
@log_exceptions(api_logger)
async def clear_sync_cache(chat_id: int | None = None) -> JSONResponse:
    """
    Очистка кеша синхронизации.

    Кеш хранит информацию об участниках чатов для ускорения повторных
    синхронизаций. Очистка кеша полезна при смене данных в Telegram.

    Args:
        chat_id: ID чата для очистки (если None - очистка всех чатов)

    Returns:
        JSONResponse: Результат очистки кеша
    """
    api_logger.info(f"🧹 Clearing sync cache (chat_id={chat_id or 'all'})")

    try:
        # Получение менеджера бота
        bot_manager = await _get_bot_manager_with_check()

        # Очистка кеша
        await bot_manager.clear_sync_cache(chat_id)

        return JSONResponse(
            status_code=200,
            content=ClearCacheResponse(
                success=True,
                message=f"Cache cleared for {chat_id if chat_id else 'all chats'}",
                timestamp=get_timestamp(),
            ).model_dump(),
        )

    except HTTPException:
        raise
    except Exception as e:
        api_logger.error(f"❌ Failed to clear cache: {e}", exc_info=True)
        return JSONResponse(status_code=500, content={"success": False, "error": str(e), "timestamp": get_timestamp()})


__all__ = ["router"]
