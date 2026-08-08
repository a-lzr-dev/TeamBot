from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from ...api.dependencies import get_session
from ...exceptions import log_exceptions
from ...logger import api_logger
from ...models import ChatType
from ...utils import get_timestamp

router = APIRouter(prefix="/tg/sync", tags=["Telegram Sync"])


# ============ Pydantic модели ============


class SyncChatRequest(BaseModel):
    """Модель запроса для синхронизации чата"""

    chat_id: int = Field(..., description="ID чата для синхронизации")
    force: bool = Field(False, description="Принудительная синхронизация (игнорировать кеш)")


class SyncChatResponse(BaseModel):
    """Модель ответа для синхронизации чата"""

    success: bool = Field(..., description="Успешность синхронизации")
    chat_id: int = Field(..., description="ID чата")
    processed: int = Field(0, description="Обработано участников")
    added: int = Field(0, description="Добавлено новых участников")
    deactivated: int = Field(0, description="Деактивировано участников")
    errors: int = Field(0, description="Количество ошибок")
    from_cache: bool = Field(False, description="Использован кеш")
    message: str | None = Field(None, description="Сообщение о результате")
    timestamp: str = Field(..., description="Время синхронизации")


class SyncAllChatsRequest(BaseModel):
    """Модель запроса для синхронизации всех чатов"""

    force: bool = Field(False, description="Принудительная синхронизация")
    max_chats: int | None = Field(None, description="Максимальное количество чатов для синхронизации")
    chat_types: list[ChatType] | None = Field(None, description="Типы чатов для синхронизации")


class SyncAllChatsResponse(BaseModel):
    """Модель ответа для синхронизации всех чатов"""

    success: bool = Field(..., description="Успешность синхронизации")
    message: str = Field(..., description="Сообщение о результате")
    processed_chats: int = Field(0, description="Обработано чатов")
    processed_members: int = Field(0, description="Обработано участников")
    added_chats: int = Field(0, description="Добавлено чатов")
    added_members: int = Field(0, description="Добавлено участников")
    deactivated_chats: int = Field(0, description="Деактивировано чатов")
    deactivated_members: int = Field(0, description="Деактивировано участников")
    errors_chats: int = Field(0, description="Ошибок при синхронизации чатов")
    errors_members: int = Field(0, description="Ошибок при синхронизации участников")
    skipped: int = Field(0, description="Пропущено чатов")
    duration_seconds: float | None = Field(None, description="Длительность синхронизации")
    timestamp: str = Field(..., description="Время синхронизации")


class SyncStatusResponse(BaseModel):
    """Модель ответа для статуса синхронизации"""

    success: bool = Field(..., description="Успешность операции")
    last_sync: str | None = Field(None, description="Время последней синхронизации")
    total_syncs: int = Field(0, description="Всего синхронизаций")
    failed_syncs: int = Field(0, description="Неудачных синхронизаций")
    total_chats_synced: int = Field(0, description="Всего синхронизировано чатов")
    total_members_synced: int = Field(0, description="Всего синхронизировано участников")
    cache_size: int = Field(0, description="Размер кеша")
    is_syncing: bool = Field(False, description="Идет ли синхронизация")
    timestamp: str = Field(..., description="Время запроса")


class ClearCacheResponse(BaseModel):
    """Модель ответа для очистки кеша"""

    success: bool = Field(..., description="Успешность операции")
    message: str = Field(..., description="Сообщение о результате")
    timestamp: str = Field(..., description="Время операции")


# ============ Вспомогательные функции ============


async def get_telegram_manager() -> Any:
    """Получение экземпляра TelegramManager"""
    try:
        from ...tg import tg_manager

        status = await tg_manager.get_status()
        if not status.get("is_running", False):
            raise HTTPException(status_code=503, detail="Telegram service not available")
        return tg_manager
    except HTTPException:
        raise
    except Exception as e:
        api_logger.error(f"❌ Failed to get Telegram manager: {e}")
        raise HTTPException(status_code=503, detail="Telegram service unavailable") from e


async def check_telethon_availability(tg_manager: Any) -> None:
    """
    Проверка доступности Telethon клиента.

    Args:
        tg_manager: Экземпляр TelegramManager

    Raises:
        HTTPException: Если Telethon клиент недоступен
    """
    status = await tg_manager.get_status()
    telethon_status = status.get("telethon", {})

    if not telethon_status.get("connected", False):
        raise HTTPException(
            status_code=503, detail="Telegram client not available. Telethon client is required for sync."
        )


async def check_account_type(tg_manager: Any) -> str:
    """
    Проверка типа аккаунта.

    Args:
        tg_manager: Экземпляр TelegramManager

    Returns:
        str: Тип аккаунта

    Raises:
        HTTPException: Если аккаунт бот
    """
    status = await tg_manager.get_status()
    account_type = status.get("account_type", "unknown")
    account_type_str: str = str(account_type) if account_type is not None else "unknown"

    if account_type_str == "bot":
        raise HTTPException(
            status_code=400, detail="Cannot sync all chats with bot account. Use /sync/chat for individual chats."
        )

    return account_type_str


# ============ ЭНДПОИНТЫ СИНХРОНИЗАЦИИ ============


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
    """Синхронизация участников конкретного чата"""
    api_logger.info(f"🔄 Syncing chat {request.chat_id} (force={request.force})")

    try:
        from ...tg import tg_manager

        # Проверка доступности клиента
        await check_telethon_availability(tg_manager)

        # Синхронизация чата
        result = await tg_manager.sync_chat(chat_id=request.chat_id, session=session, force=request.force)

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
    """,
)
@log_exceptions(api_logger)
async def sync_all_chats(
    request: SyncAllChatsRequest,
) -> JSONResponse:
    """Синхронизация всех чатов"""
    api_logger.info(f"🔄 Syncing all chats (force={request.force})")

    try:
        from ...tg import tg_manager

        # Проверка доступности клиента
        await check_telethon_availability(tg_manager)

        # Проверка типа аккаунта
        await check_account_type(tg_manager)

        # Преобразование ChatType в строку
        chat_types_str = None
        if request.chat_types:
            chat_types_str = [ct.value for ct in request.chat_types]

        # Синхронизация всех чатов
        result = await tg_manager.sync_all_chats(
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


@router.get("/status", summary="Статус синхронизации", description="Получить информацию о последней синхронизации")
@log_exceptions(api_logger)
async def get_sync_status() -> JSONResponse:
    """Получение статуса синхронизации"""
    api_logger.info("📊 Getting sync status...")

    try:
        from ...tg import tg_manager

        status = await tg_manager.get_status()
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
                is_syncing=False,
                timestamp=get_timestamp(),
            ).model_dump(),
        )

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
    """Очистка кеша синхронизации"""
    api_logger.info(f"🧹 Clearing sync cache (chat_id={chat_id or 'all'})")

    try:
        from ...tg import tg_manager

        await tg_manager.clear_sync_cache(chat_id)

        return JSONResponse(
            status_code=200,
            content=ClearCacheResponse(
                success=True,
                message=f"Cache cleared for {chat_id if chat_id else 'all chats'}",
                timestamp=get_timestamp(),
            ).model_dump(),
        )

    except Exception as e:
        api_logger.error(f"❌ Failed to clear cache: {e}", exc_info=True)
        return JSONResponse(status_code=500, content={"success": False, "error": str(e), "timestamp": get_timestamp()})


__all__ = [
    "router",
    "SyncChatRequest",
    "SyncChatResponse",
    "SyncAllChatsRequest",
    "SyncAllChatsResponse",
    "SyncStatusResponse",
    "ClearCacheResponse",
]
