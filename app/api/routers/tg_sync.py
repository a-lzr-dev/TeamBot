from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from ...db import db_manager
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


# ============ Вспомогательные функции ============


async def get_telegram_manager() -> Any:
    """Получение экземпляра TelegramManager"""
    try:
        # Ленивый импорт внутри функции для избежания циклических зависимостей
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


async def get_db_session() -> Any:
    """Получение сессии БД"""
    async with db_manager.get_session() as session:
        yield session


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
    session: AsyncSession = Depends(get_db_session),
) -> JSONResponse:
    """Синхронизация участников конкретного чата"""
    api_logger.info(f"🔄 Syncing chat {request.chat_id} (force={request.force})")

    try:
        # Ленивый импорт внутри функции
        from ...tg import tg_manager

        # Проверка доступности клиента
        status = await tg_manager.get_status()
        telethon_status = status.get("telethon", {})

        if not telethon_status.get("connected", False):
            raise HTTPException(
                status_code=503, detail="Telegram client not available. Telethon client is required for sync."
            )

        # Синхронизация чата
        result = await tg_manager.sync_chat(chat_id=request.chat_id, session=session, force=request.force)

        if result.get("success", False):
            api_logger.info(f"✅ Chat {request.chat_id} synced successfully")

            return JSONResponse(
                status_code=200,
                content={
                    "success": True,
                    "chat_id": request.chat_id,
                    "processed": result.get("processed", 0),
                    "added": result.get("added", 0),
                    "deactivated": result.get("deactivated", 0),
                    "errors": result.get("errors", 0),
                    "from_cache": result.get("from_cache", False),
                    "message": f"Chat {request.chat_id} synced successfully",
                    "timestamp": get_timestamp(),
                },
            )
        else:
            error_msg = result.get("error", "Unknown error")
            api_logger.error(f"❌ Failed to sync chat {request.chat_id}: {error_msg}")

            return JSONResponse(
                status_code=500,
                content={
                    "success": False,
                    "chat_id": request.chat_id,
                    "processed": result.get("processed", 0),
                    "added": 0,
                    "deactivated": 0,
                    "errors": 1,
                    "from_cache": False,
                    "message": f"Failed to sync chat: {error_msg}",
                    "timestamp": get_timestamp(),
                },
            )

    except HTTPException:
        raise
    except Exception as e:
        api_logger.error(f"❌ Failed to sync chat {request.chat_id}: {e}", exc_info=True)
        return JSONResponse(
            status_code=500,
            content={
                "success": False,
                "chat_id": request.chat_id,
                "processed": 0,
                "added": 0,
                "deactivated": 0,
                "errors": 1,
                "from_cache": False,
                "message": f"Internal error: {str(e)}",
                "timestamp": get_timestamp(),
            },
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
        status = await tg_manager.get_status()
        telethon_status = status.get("telethon", {})

        if not telethon_status.get("connected", False):
            raise HTTPException(
                status_code=503, detail="Telegram client not available. Telethon client is required for sync."
            )

        # Проверка типа аккаунта
        account_type = status.get("account_type", "unknown")
        if account_type == "bot":
            raise HTTPException(
                status_code=400, detail="Cannot sync all chats with bot account. Use /sync/chat for individual chats."
            )

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

            return JSONResponse(
                status_code=200,
                content={
                    "success": True,
                    "message": "All chats synced successfully",
                    "processed_chats": result.get("processed", {}).get("chats", 0),
                    "processed_members": result.get("processed", {}).get("members", 0),
                    "added_chats": result.get("added", {}).get("chats", 0),
                    "added_members": result.get("added", {}).get("members", 0),
                    "deactivated_chats": result.get("deactivated", {}).get("chats", 0),
                    "deactivated_members": result.get("deactivated", {}).get("members", 0),
                    "errors_chats": result.get("errors", {}).get("chats", 0),
                    "errors_members": result.get("errors", {}).get("members", 0),
                    "skipped": result.get("skipped", 0),
                    "duration_seconds": result.get("duration_seconds"),
                    "timestamp": get_timestamp(),
                },
            )
        else:
            error_msg = result.get("error", "Unknown error")
            api_logger.error(f"❌ Failed to sync all chats: {error_msg}")

            return JSONResponse(
                status_code=500,
                content={
                    "success": False,
                    "message": f"Failed to sync all chats: {error_msg}",
                    "processed_chats": 0,
                    "processed_members": 0,
                    "added_chats": 0,
                    "added_members": 0,
                    "deactivated_chats": 0,
                    "deactivated_members": 0,
                    "errors_chats": 1,
                    "errors_members": 0,
                    "skipped": 0,
                    "duration_seconds": None,
                    "timestamp": get_timestamp(),
                },
            )

    except HTTPException:
        raise
    except Exception as e:
        api_logger.error(f"❌ Failed to sync all chats: {e}", exc_info=True)
        return JSONResponse(
            status_code=500,
            content={
                "success": False,
                "message": f"Internal error: {str(e)}",
                "processed_chats": 0,
                "processed_members": 0,
                "added_chats": 0,
                "added_members": 0,
                "deactivated_chats": 0,
                "deactivated_members": 0,
                "errors_chats": 1,
                "errors_members": 0,
                "skipped": 0,
                "duration_seconds": None,
                "timestamp": get_timestamp(),
            },
        )


@router.get("/status", summary="Статус синхронизации", description="Получить информацию о последней синхронизации")
@log_exceptions(api_logger)
async def get_sync_status() -> JSONResponse:
    """Получение статуса синхронизации"""
    api_logger.info("📊 Getting sync status...")

    try:
        # Ленивый импорт внутри функции
        from ...tg import tg_manager

        status = await tg_manager.get_status()
        sync_status = status.get("sync", {})

        return JSONResponse(
            status_code=200,
            content={
                "success": True,
                "last_sync": sync_status.get("last_sync"),
                "total_syncs": sync_status.get("metrics", {}).get("total_syncs", 0),
                "failed_syncs": sync_status.get("metrics", {}).get("failed_syncs", 0),
                "total_chats_synced": sync_status.get("metrics", {}).get("total_chats_synced", 0),
                "total_members_synced": sync_status.get("metrics", {}).get("total_members_synced", 0),
                "cache_size": sync_status.get("cache_size", 0),
                "is_syncing": False,
                "timestamp": get_timestamp(),
            },
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
        # Ленивый импорт внутри функции
        from ...tg import tg_manager

        await tg_manager.clear_sync_cache(chat_id)

        return JSONResponse(
            status_code=200,
            content={
                "success": True,
                "message": f"Cache cleared for {chat_id if chat_id else 'all chats'}",
                "timestamp": get_timestamp(),
            },
        )

    except Exception as e:
        api_logger.error(f"❌ Failed to clear cache: {e}", exc_info=True)
        return JSONResponse(status_code=500, content={"success": False, "error": str(e), "timestamp": get_timestamp()})


__all__ = [
    "router",
]
