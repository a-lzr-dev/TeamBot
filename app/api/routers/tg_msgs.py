from datetime import timedelta
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field, field_validator

from ...config import settings
from ...db.repositories import ChatRepository, MessageRepository
from ...exceptions import log_exceptions
from ...logger import api_logger
from ...models import ChatType, MessageType, datetime_now
from ...utils import get_timestamp
from ..dependencies import get_session

router = APIRouter(prefix="/tg/msgs", tags=["Telegram Messages"])


# ============ Pydantic модели ============


class SendMessageRequest(BaseModel):
    """Модель запроса для отправки сообщения"""

    chat_id: int | None = Field(None, description="ID чата в Telegram (обязателен, если send_to_all=false)")
    message_type: MessageType = Field(default=MessageType.BOT_RESPONSE, description="Тип сообщения")
    text: str = Field(..., description="Тип сообщения", min_length=1, max_length=4096)
    parse_mode: str | None = Field(None, description="Режим парсинга: 'HTML', 'Markdown', 'MarkdownV2' или None")
    disable_web_page_preview: bool = Field(False, description="Отключить предпросмотр ссылок")
    disable_notification: bool = Field(False, description="Отключить уведомление")
    protect_content: bool = Field(False, description="Защитить содержимое от пересылки")
    reply_to_message_id: int | None = Field(None, description="ID сообщения, на которое отвечаем")
    allow_sender: bool = Field(True, description="Разрешить отправку от имени пользователя (если доступно)")
    lifetime_seconds: int | None = Field(
        None, description="Время жизни сообщения в секундах (если указано, сообщение будет автоматически удалено)"
    )

    # Параметры для отправки во все чаты
    send_to_all: bool = Field(False, description="Отправить сообщение во все активные чаты (игнорирует chat_id)")
    chat_types: list[ChatType] | None = Field(None, description="Типы чатов для отправки (только при send_to_all=true)")
    exclude_chat_ids: list[int] | None = Field(
        None, description="ID чатов, которые нужно исключить (только при send_to_all=true)"
    )

    @field_validator("parse_mode")
    @classmethod
    def validate_parse_mode(cls, v: str | None) -> str | None:
        if v is not None:
            v_upper = v.upper()
            if v_upper not in ["HTML", "MARKDOWN", "MARKDOWN_V2"]:
                raise ValueError('parse_mode must be "HTML", "Markdown", "MarkdownV2" or None')
            return v_upper
        return None

    @field_validator("lifetime_seconds")
    @classmethod
    def validate_lifetime(cls, v: int | None) -> int | None:
        if v is not None:
            if v < 10:
                raise ValueError("lifetime_seconds must be at least 10 seconds")
            if v > 2592000:  # 30 дней
                raise ValueError("lifetime_seconds must not exceed 30 days (2592000 seconds)")
        return v


class SendMessageResponse(BaseModel):
    """Модель ответа для отправки сообщения"""

    success: bool = Field(..., description="Успешность отправки")
    message_id: int | None = Field(None, description="ID отправленного сообщения")
    chat_id: int | None = Field(None, description="ID чата")
    text: str = Field(..., description="Текст сообщения (обрезанный для ответа)")
    timestamp: str = Field(..., description="Время отправки")
    error: str | None = Field(None, description="Сообщение об ошибке")
    client: str | None = Field(None, description="Клиент, через который отправлено")
    is_bot: bool | None = Field(None, description="Отправлено через бота или пользователя")
    lifetime_seconds: int | None = Field(None, description="Время жизни сообщения")
    expires_at: str | None = Field(None, description="Время истечения сообщения")


class BatchSendMessageResponse(BaseModel):
    """Модель ответа для массовой отправки"""

    total: int = Field(..., description="Всего сообщений")
    successful: int = Field(..., description="Успешно отправлено")
    failed: int = Field(..., description="Не удалось отправить")
    results: list[SendMessageResponse] = Field(..., description="Результаты отправки каждого сообщения")
    timestamp: str = Field(..., description="Время отправки")
    is_batch: bool = Field(True, description="Признак пакетной отправки")


class SendMessageToAllResponse(BaseModel):
    """Модель ответа для отправки во все чаты"""

    success: bool = Field(..., description="Успешность операции")
    total_chats: int = Field(..., description="Всего чатов")
    success_count: int = Field(..., description="Успешно отправлено")
    failed_count: int = Field(..., description="Не удалось отправить")
    failed_chats: list[dict[str, Any]] = Field(default_factory=list, description="Список чатов с ошибками")
    timestamp: str = Field(..., description="Время отправки")


class ErrorResponse(BaseModel):
    """Модель ответа при ошибке"""

    success: bool = Field(default=False, description="Успешность операции")
    error: str = Field(..., description="Сообщение об ошибке")
    timestamp: str = Field(..., description="Время ошибки")


class SetLifetimeRequest(BaseModel):
    """Модель запроса для установки времени жизни"""

    message_id: int = Field(..., description="ID сообщения")
    lifetime_seconds: int = Field(..., description="Время жизни в секундах", ge=10, le=2592000)


class BatchSetLifetimeRequest(BaseModel):
    """Модель запроса для установки времени жизни нескольким сообщениям"""

    message_ids: list[int] = Field(..., description="Список ID сообщений", min_length=1, max_length=100)
    lifetime_seconds: int | None = Field(None, description="Время жизни в секундах", ge=10, le=2592000)


# ============ УНИВЕРСАЛЬНАЯ МОДЕЛЬ ЗАПРОСА ============


class UnifiedSendRequest(BaseModel):
    """
    Универсальная модель для отправки сообщений.
    Поддерживает три формата:

    1. Прямой объект (одно сообщение):
       {
           "chat_id": -1001234567890,
           "text": "Hello, world!"
       }

    2. С оберткой messages (одно сообщение):
       {
           "messages": {
               "chat_id": -1001234567890,
               "text": "Hello, world!"
           }
       }

    3. Массив сообщений:
       {
           "messages": [
               {"chat_id": -1001234567890, "text": "Message 1"},
               {"chat_id": -1001234567890, "text": "Message 2"}
           ]
       }

    4. Отправка во все чаты:
       {
           "send_to_all": true,
           "text": "Hello, everyone!"
       }
    """

    messages: SendMessageRequest | list[SendMessageRequest] | None = Field(
        None, description="Одно сообщение или массив сообщений"
    )

    # Прямые поля для отправки одного сообщения без обертки
    chat_id: int | None = Field(None, description="ID чата в Telegram")
    text: str | None = Field(None, description="Текст сообщения")
    parse_mode: str | None = Field(None, description="Режим парсинга")
    disable_web_page_preview: bool | None = Field(None, description="Отключить предпросмотр ссылок")
    disable_notification: bool | None = Field(None, description="Отключить уведомление")
    protect_content: bool | None = Field(None, description="Защитить содержимое от пересылки")
    reply_to_message_id: int | None = Field(None, description="ID сообщения, на которое отвечаем")
    allow_sender: bool | None = Field(None, description="Разрешить отправку от имени пользователя")
    send_to_all: bool | None = Field(None, description="Отправить во все чаты")
    chat_types: list[ChatType] | None = Field(None, description="Типы чатов для отправки")
    exclude_chat_ids: list[int] | None = Field(None, description="ID чатов для исключения")
    lifetime_seconds: int | None = Field(None, description="Время жизни сообщения в секундах")

    def get_messages(self) -> list[SendMessageRequest]:
        """Преобразует входные данные в список сообщений"""
        # Если есть messages в обертке
        if self.messages is not None:
            if isinstance(self.messages, SendMessageRequest):
                return [self.messages]
            elif isinstance(self.messages, list):
                return self.messages

        # Если есть прямые поля (без обертки)
        if self.text is not None:
            # Определяем send_to_all
            send_to_all = self.send_to_all if self.send_to_all is not None else (self.chat_id is None)

            # Создаем словарь с данными
            data: dict[str, Any] = {
                "chat_id": self.chat_id,
                "text": self.text,
                "parse_mode": self.parse_mode,
                "disable_web_page_preview": self.disable_web_page_preview or False,
                "disable_notification": self.disable_notification or False,
                "protect_content": self.protect_content or False,
                "reply_to_message_id": self.reply_to_message_id,
                "allow_sender": self.allow_sender or True,
                "send_to_all": send_to_all,
                "chat_types": self.chat_types,
                "exclude_chat_ids": self.exclude_chat_ids,
                "lifetime_seconds": self.lifetime_seconds,
            }

            # Если send_to_all=True, удаляем chat_id из данных
            if send_to_all:
                data.pop("chat_id", None)

            msg = SendMessageRequest(**data)
            return [msg]

        return []

    def is_batch(self) -> bool:
        """Проверка, является ли запрос пакетным"""
        if self.messages is not None:
            return isinstance(self.messages, list)
        return False


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
        api_logger.error(f"Failed to get Telegram manager: {e}")
        raise HTTPException(status_code=503, detail="Telegram service unavailable") from e


async def send_single_message(tg_manager: Any, msg: SendMessageRequest, _: int | None = None) -> SendMessageResponse:
    """Отправка одного сообщения через TelegramManager с поддержкой времени жизни"""
    try:
        result = await tg_manager.send_message(
            chat_id=msg.chat_id,
            message_type=msg.message_type,
            text=msg.text,
            parse_mode=msg.parse_mode,
            disable_web_page_preview=msg.disable_web_page_preview,
            disable_notification=msg.disable_notification,
            protect_content=msg.protect_content,
            reply_to_message_id=msg.reply_to_message_id,
            allow_sender=msg.allow_sender,
            lifetime_seconds=msg.lifetime_seconds,
        )

        text_preview = msg.text[:100] + "..." if len(msg.text) > 100 else msg.text

        if result.get("success"):
            api_logger.info(f"Message sent to chat {msg.chat_id}")

            # Вычисляем время истечения
            expires_at = None
            if msg.lifetime_seconds:
                expires_at = (datetime_now() + timedelta(seconds=msg.lifetime_seconds)).isoformat() + "Z"

            return SendMessageResponse(
                success=True,
                message_id=result.get("message_id"),
                chat_id=msg.chat_id,
                text=text_preview,
                timestamp=get_timestamp(),
                error=None,
                client=result.get("client"),
                is_bot=result.get("client") == "aiogram",
                lifetime_seconds=msg.lifetime_seconds,
                expires_at=expires_at,
            )
        else:
            error_msg = result.get("error", "Unknown error")
            api_logger.error(f"Failed to send message: {error_msg}")
            return SendMessageResponse(
                success=False,
                message_id=None,
                chat_id=msg.chat_id,
                text=text_preview,
                timestamp=get_timestamp(),
                error=error_msg,
                client=None,
                is_bot=None,
                lifetime_seconds=None,
                expires_at=None,
            )

    except Exception as e:
        api_logger.error(f"Failed to send message: {e}", exc_info=True)
        text_preview = msg.text[:100] + "..." if len(msg.text) > 100 else msg.text
        return SendMessageResponse(
            success=False,
            message_id=None,
            chat_id=msg.chat_id,
            text=text_preview,
            timestamp=get_timestamp(),
            error=f"Internal server error: {str(e)}",
            client=None,
            is_bot=None,
            lifetime_seconds=None,
            expires_at=None,
        )


async def send_message_to_all_chats(tg_manager: Any, msg: SendMessageRequest, session: Any) -> SendMessageToAllResponse:
    """Отправка сообщения во все чаты с поддержкой времени жизни"""
    try:
        # Получение всех активных чатов из БД через репозиторий
        chats = await ChatRepository.get_chats(session, is_active=True)

        # Фильтр по типам чатов
        if msg.chat_types:
            chat_type_values = [ct.value for ct in msg.chat_types]
            chats = [c for c in chats if c.FType in chat_type_values]

        # Исключение указанных чатов
        if msg.exclude_chat_ids:
            chats = [c for c in chats if c.FID not in msg.exclude_chat_ids]

        if not chats:
            api_logger.warning("No active chats found for sending")
            return SendMessageToAllResponse(
                success=True, total_chats=0, success_count=0, failed_count=0, failed_chats=[], timestamp=get_timestamp()
            )

        api_logger.info(f"📊 Found {len(chats)} chats to send")

        # Отправка сообщения в каждый чат
        success_count = 0
        failed_chats: list[dict[str, Any]] = []

        for chat in chats:
            try:
                result = await tg_manager.send_message(
                    chat_id=chat.FID,
                    message_type=msg.message_type,
                    text=msg.text,
                    parse_mode=msg.parse_mode,
                    disable_web_page_preview=msg.disable_web_page_preview,
                    disable_notification=msg.disable_notification,
                    protect_content=msg.protect_content,
                    allow_sender=msg.allow_sender,
                    lifetime_seconds=msg.lifetime_seconds,
                )

                if result.get("success"):
                    success_count += 1
                    api_logger.debug(f"✅ Message sent to chat {chat.FID}")
                else:
                    error_msg = result.get("error", "Unknown error")
                    api_logger.warning(f"⚠️ Failed to send to chat {chat.FID}: {error_msg}")
                    failed_chats.append(
                        {"chat_id": chat.FID, "title": chat.FTitle or f"Chat {chat.FID}", "error": error_msg}
                    )

            except Exception as e:
                api_logger.error(f"❌ Error sending to chat {chat.FID}: {e}")
                failed_chats.append({"chat_id": chat.FID, "title": chat.FTitle or f"Chat {chat.FID}", "error": str(e)})

        total_chats = len(chats)
        failed_count = len(failed_chats)

        api_logger.info(f"✅ Message sent to {success_count}/{total_chats} chats")

        return SendMessageToAllResponse(
            success=failed_count == 0,
            total_chats=total_chats,
            success_count=success_count,
            failed_count=failed_count,
            failed_chats=failed_chats[:10],
            timestamp=get_timestamp(),
        )

    except Exception as e:
        api_logger.error(f"❌ Failed to send message to all chats: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Failed to send message to all chats: {str(e)}") from e


# ============ УНИВЕРСАЛЬНЫЙ ЭНДПОИНТ ============


@router.post(
    "/send",
    response_model=SendMessageResponse | BatchSendMessageResponse | SendMessageToAllResponse | ErrorResponse,
    summary="Отправить сообщение(я) в Telegram",
    description="""
    Универсальный эндпоинт для отправки сообщений в Telegram.

    Поддерживает 4 формата:

    1. Прямой объект (без обертки):
       {
           "chat_id": -1001234567890,
           "text": "Hello, world!",
           "parse_mode": "HTML",
           "lifetime_seconds": 300
       }

    2. С оберткой messages (одно сообщение):
       {
           "messages": {
               "chat_id": -1001234567890,
               "text": "Hello, world!",
               "parse_mode": "HTML",
               "lifetime_seconds": 300
           }
       }

    3. Массив сообщений:
       {
           "messages": [
               {
                   "chat_id": -1001234567890,
                   "text": "Message 1",
                   "parse_mode": "HTML",
                   "lifetime_seconds": 300
               },
               {
                   "chat_id": -1001234567890,
                   "text": "Message 2",
                   "parse_mode": "HTML"
               }
           ]
       }

    4. Отправка во все чаты:
       {
           "send_to_all": true,
           "text": "Hello, everyone!",
           "parse_mode": "HTML",
           "chat_types": ["group", "supergroup"],
           "exclude_chat_ids": [-1001234567890],
           "lifetime_seconds": 600
       }
    """,
)
@log_exceptions(api_logger)
async def send_message_unified(
    request: UnifiedSendRequest,
    tg_manager: Any = Depends(get_telegram_manager),
    session: Any = Depends(get_session),
) -> JSONResponse:
    """Универсальная отправка сообщений"""
    messages = request.get_messages()
    is_batch = request.is_batch()

    if not messages:
        api_logger.warning("No messages to send")
        return JSONResponse(
            status_code=400,
            content=ErrorResponse(
                error="No messages to send. Please provide either 'messages' field or direct message fields.",
                timestamp=get_timestamp(),
            ).model_dump(),
        )

    # Проверка: если одно сообщение и send_to_all=true
    if len(messages) == 1:
        msg = messages[0]
        if msg.send_to_all:
            # Отправка во все чаты
            result = await send_message_to_all_chats(tg_manager, msg, session)
            return JSONResponse(status_code=200, content=result.model_dump())

    # Проверка на пакетную отправку
    if is_batch and len(messages) > 100:
        api_logger.warning(f"Too many messages: {len(messages)} > 100")
        return JSONResponse(
            status_code=400,
            content=ErrorResponse(
                error="Too many messages. Maximum 100 messages per request.", timestamp=get_timestamp()
            ).model_dump(),
        )

    api_logger.info(f"Sending {len(messages)} message(s) (batch={is_batch})")

    # Отправка одного сообщения
    if not is_batch and len(messages) == 1:
        result = await send_single_message(tg_manager, messages[0])
        status_code = 200 if result.success else 400
        return JSONResponse(status_code=status_code, content=result.model_dump())

    # Отправка массива сообщений
    results: list[SendMessageResponse] = []
    successful = 0
    failed = 0
    errors: list[dict[str, Any]] = []

    for idx, msg in enumerate(messages, 1):
        result = await send_single_message(tg_manager, msg, idx)
        results.append(result.model_dump())

        if result.success:
            successful += 1
        else:
            failed += 1
            if result.error:
                errors.append({"index": idx, "chat_id": msg.chat_id, "error": result.error})

    api_logger.info(f"Batch completed: {successful} successful, {failed} failed")

    if errors:
        api_logger.warning(f"Batch errors: {len(errors)} messages failed")

    response = BatchSendMessageResponse(
        total=len(messages),
        successful=successful,
        failed=failed,
        results=results,
        timestamp=get_timestamp(),
        is_batch=True,
    )

    if failed == 0:
        status_code = 200
    elif successful > 0:
        status_code = 207
    else:
        status_code = 400

    return JSONResponse(status_code=status_code, content=response.model_dump())


# ============ ЭНДПОИНТЫ ДЛЯ УПРАВЛЕНИЯ ВРЕМЕНЕМ ЖИЗНИ ============


@router.post(
    "/messages/lifetime",
    summary="Установить время жизни сообщения",
    description="Устанавливает время жизни для сообщения. По истечении времени сообщение будет автоматически удалено.",
)
@log_exceptions(api_logger)
async def set_message_lifetime(
    request: SetLifetimeRequest,
    session: Any = Depends(get_session),
) -> JSONResponse:
    """Установка времени жизни сообщения"""
    api_logger.info(f"⏰ Setting lifetime for message {request.message_id}: {request.lifetime_seconds}s")

    try:
        result = await MessageRepository.set_message_lifetime(
            session=session, message_id=request.message_id, lifetime_seconds=request.lifetime_seconds
        )

        if result:
            expires_at = datetime_now() + timedelta(seconds=request.lifetime_seconds)
            return JSONResponse(
                status_code=200,
                content={
                    "success": True,
                    "message_id": request.message_id,
                    "lifetime_seconds": request.lifetime_seconds,
                    "expires_at": expires_at.isoformat() + "Z",
                    "timestamp": get_timestamp(),
                },
            )
        else:
            return JSONResponse(
                status_code=404,
                content={
                    "success": False,
                    "error": f"Message {request.message_id} not found or already deleted",
                    "timestamp": get_timestamp(),
                },
            )

    except Exception as e:
        api_logger.error(f"Failed to set lifetime: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e)) from e


@router.post(
    "/messages/lifetime/batch",
    summary="Установить время жизни для нескольких сообщений",
    description="Устанавливает время жизни для списка сообщений",
)
@log_exceptions(api_logger)
async def set_messages_lifetime_batch(
    request: BatchSetLifetimeRequest,
    session: Any = Depends(get_session),
) -> JSONResponse:
    """Установка времени жизни для нескольких сообщений"""
    # Проверяем, что lifetime_seconds указан
    if request.lifetime_seconds is None:
        raise HTTPException(status_code=400, detail="lifetime_seconds is required for batch operation")

    api_logger.info(f"⏰ Setting lifetime for {len(request.message_ids)} messages")

    try:
        success_count = 0
        failed_count = 0

        for message_id in request.message_ids:
            result = await MessageRepository.set_message_lifetime(
                session=session,
                message_id=message_id,
                lifetime_seconds=request.lifetime_seconds,
            )
            if result:
                success_count += 1
            else:
                failed_count += 1

        return JSONResponse(
            status_code=200,
            content={
                "success": True,
                "total": len(request.message_ids),
                "success_count": success_count,
                "failed_count": failed_count,
                "timestamp": get_timestamp(),
            },
        )

    except Exception as e:
        api_logger.error(f"Failed to set lifetimes: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e)) from e


@router.get(
    "/messages/lifetime/stats",
    summary="Статистика по времени жизни сообщений",
    description="Получение статистики по времени жизни сообщений",
)
@log_exceptions(api_logger)
async def get_message_lifetime_stats(
    chat_id: int | None = None,
    session: Any = Depends(get_session),
) -> JSONResponse:
    """Получение статистики по времени жизни"""
    api_logger.info(f"📊 Getting message lifetime stats for chat {chat_id or 'all'}")

    try:
        stats = await MessageRepository.get_message_lifetime_stats(session=session, chat_id=chat_id)

        return JSONResponse(status_code=200, content={"success": True, "stats": stats, "timestamp": get_timestamp()})

    except Exception as e:
        api_logger.error(f"Failed to get stats: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e)) from e


@router.post(
    "/messages/lifetime/force-check",
    summary="Принудительная проверка истекших сообщений",
    description="Принудительно проверяет и помечает истекшие сообщения",
)
@log_exceptions(api_logger)
async def force_check_expired_messages() -> JSONResponse:
    """Принудительная проверка истекших сообщений"""
    from ...services.message_lifetime_service import message_lifetime_service

    api_logger.info("🔄 Force check expired messages requested")

    try:
        result = await message_lifetime_service.force_check()

        return JSONResponse(
            status_code=200,
            content={
                "success": True,
                "deleted": result["deleted"],
                "found": result["found"],
                "timestamp": get_timestamp(),
            },
        )

    except Exception as e:
        api_logger.error(f"Failed to force check: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e)) from e


@router.get(
    "/messages/lifetime/{message_id}",
    summary="Получить информацию о времени жизни сообщения",
    description="Возвращает информацию о времени жизни сообщения",
)
@log_exceptions(api_logger)
async def get_message_lifetime_info(
    message_id: int,
    session: Any = Depends(get_session),
) -> JSONResponse:
    """Получение информации о времени жизни сообщения"""
    api_logger.info(f"📊 Getting lifetime info for message {message_id}")

    try:
        # Используем репозиторий для получения сообщения
        message = await MessageRepository.get_message_by_id(session, message_id)

        if not message:
            raise HTTPException(status_code=404, detail=f"Message {message_id} not found")

        if message.FFlagDeleted:
            return JSONResponse(
                status_code=200,
                content={
                    "success": True,
                    "message_id": message_id,
                    "is_deleted": True,
                    "deleted_at": message.FDateDeleted.isoformat() + "Z" if message.FDateDeleted else None,
                    "deleted_by": message.FDeletedByType,
                    "timestamp": get_timestamp(),
                },
            )

        is_expired = False
        if message.FExpiresAt:
            is_expired = message.FExpiresAt <= datetime_now()

        return JSONResponse(
            status_code=200,
            content={
                "success": True,
                "message_id": message_id,
                "is_deleted": False,
                "lifetime_seconds": message.FLifetimeSeconds,
                "expires_at": message.FExpiresAt.isoformat() + "Z" if message.FExpiresAt else None,
                "is_expired": is_expired,
                "time_remaining": int((message.FExpiresAt - datetime_now()).total_seconds())
                if message.FExpiresAt and not is_expired
                else 0,
                "timestamp": get_timestamp(),
            },
        )

    except HTTPException:
        raise
    except Exception as e:
        api_logger.error(f"Failed to get lifetime info: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e)) from e


# ============ ЭНДПОИНТЫ ДЛЯ РАБОТЫ С УДАЛЕННЫМИ СООБЩЕНИЯМИ ============


@router.get(
    "/messages/deleted",
    summary="Получить статистику удаленных сообщений",
    description="Возвращает статистику по удаленным сообщениям",
)
@log_exceptions(api_logger)
async def get_deleted_messages_stats(
    chat_id: int | None = None,
    days: int = getattr(settings, "API_STATS_DAYS", 7),
    session: Any = Depends(get_session),
) -> JSONResponse:
    """Получение статистики по удаленным сообщениям."""
    api_logger.info(f"Getting deleted messages stats for chat {chat_id or 'all'}")

    try:
        stats = await ChatRepository.get_deleted_messages_stats(session=session, chat_id=chat_id, days=days)

        return JSONResponse(status_code=200, content={"success": True, "stats": stats, "timestamp": get_timestamp()})

    except Exception as e:
        api_logger.error(f"Failed to get deleted messages stats: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Failed to get deleted messages stats: {str(e)}") from e


@router.get(
    "/messages/deleted/list",
    summary="Получить список удаленных сообщений",
    description="Возвращает список удаленных сообщений",
)
@log_exceptions(api_logger)
async def get_deleted_messages(
    chat_id: int | None = None,
    limit: int = getattr(settings, "API_DEFAULT_PAGE_SIZE", 50),
    offset: int = 0,
    session: Any = Depends(get_session),
) -> JSONResponse:
    """Получение списка удаленных сообщений."""
    api_logger.info(f"Getting deleted messages for chat {chat_id or 'all'}")

    try:
        # Используем репозиторий для получения сообщений
        messages = await ChatRepository.get_messages(
            session=session, chat_id=chat_id, include_deleted=True, limit=limit, offset=offset
        )

        deleted_messages = [m for m in messages if m.FFlagDeleted]

        result = []
        for msg in deleted_messages:
            result.append(
                {
                    "id": msg.FID,
                    "chat_id": msg.FK_Chat,
                    "user_id": msg.FK_User,
                    "text": msg.FText[:100] + "..." if msg.FText and len(msg.FText) > 100 else msg.FText,
                    "type": msg.FK_MessageType.value if msg.FK_MessageType else "unknown",
                    "sent_at": msg.FDateSent.isoformat() + "Z" if msg.FDateSent else None,
                    "deleted_at": msg.FDateDeleted.isoformat() + "Z" if msg.FDateDeleted else None,
                    "deleted_by_type": msg.FDeletedByType,
                    "initiator_message_id": msg.FK_DeletedByMessage,
                    "had_lifetime": msg.FLifetimeSeconds is not None,
                    "lifetime_seconds": msg.FLifetimeSeconds,
                    "expired_at": msg.FExpiresAt.isoformat() + "Z" if msg.FExpiresAt else None,
                }
            )

        return JSONResponse(
            status_code=200,
            content={"success": True, "total": len(result), "messages": result, "timestamp": get_timestamp()},
        )

    except Exception as e:
        api_logger.error(f"Failed to get deleted messages: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Failed to get deleted messages: {str(e)}") from e


@router.get(
    "/messages/deleted/with-initiator",
    summary="Получить удаленные сообщения с инициаторами",
    description="Возвращает список удаленных сообщений с информацией об инициаторе удаления",
)
@log_exceptions(api_logger)
async def get_deleted_messages_with_initiator(
    chat_id: int | None = None,
    limit: int = getattr(settings, "API_DEFAULT_PAGE_SIZE", 50),
    offset: int = 0,
    session: Any = Depends(get_session),
) -> JSONResponse:
    """Получение удаленных сообщений с информацией об инициаторе."""
    api_logger.info(f"Getting deleted messages with initiator for chat {chat_id or 'all'}")

    try:
        messages = await ChatRepository.get_deleted_messages_with_initiator(
            session=session, chat_id=chat_id, limit=limit, offset=offset
        )

        return JSONResponse(
            status_code=200,
            content={"success": True, "total": len(messages), "messages": messages, "timestamp": get_timestamp()},
        )

    except Exception as e:
        api_logger.error(f"Failed to get deleted messages with initiator: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Failed to get deleted messages: {str(e)}") from e


@router.get(
    "/messages/deletion-stats",
    summary="Статистика удалений по типам",
    description="Возвращает статистику удалений по типам инициаторов",
)
@log_exceptions(api_logger)
async def get_deletion_stats_by_initiator(
    chat_id: int | None = None,
    days: int = getattr(settings, "API_STATS_DAYS", 7),
    session: Any = Depends(get_session),
) -> JSONResponse:
    """Получение статистики удалений по типам инициаторов."""
    api_logger.info(f"Getting deletion stats for chat {chat_id or 'all'}")

    try:
        stats = await ChatRepository.get_deletion_stats_by_initiator(session=session, chat_id=chat_id, days=days)

        return JSONResponse(status_code=200, content={"success": True, "stats": stats, "timestamp": get_timestamp()})

    except Exception as e:
        api_logger.error(f"Failed to get deletion stats: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Failed to get deletion stats: {str(e)}") from e


@router.get(
    "/messages/{message_id}/deletion-info",
    summary="Информация об удалении сообщения",
    description="Возвращает информацию о том, когда и кем было удалено сообщение",
)
@log_exceptions(api_logger)
async def get_message_deletion_info(
    message_id: int,
    session: Any = Depends(get_session),
) -> JSONResponse:
    """Получение информации об удалении сообщения."""
    api_logger.info(f"Getting deletion info for message {message_id}")

    try:
        # Используем репозиторий для получения сообщения
        message = await MessageRepository.get_message_by_id(session, message_id)

        if not message:
            raise HTTPException(status_code=404, detail=f"Message {message_id} not found")

        if not message.FFlagDeleted:
            return JSONResponse(
                status_code=200,
                content={
                    "success": True,
                    "is_deleted": False,
                    "message": "Message is not deleted",
                    "timestamp": get_timestamp(),
                },
            )

        # Получение инициатора удаления (если есть)
        initiator_info = None
        if message.FK_DeletedByMessage:
            initiator = await MessageRepository.get_message_by_id(session, message.FK_DeletedByMessage)
            if initiator:
                initiator_info = {
                    "message_id": initiator.FID,
                    "text": initiator.FText[:100] + "..."
                    if initiator.FText and len(initiator.FText) > 100
                    else initiator.FText,
                    "sent_at": initiator.FDateSent.isoformat() + "Z" if initiator.FDateSent else None,
                }

        return JSONResponse(
            status_code=200,
            content={
                "success": True,
                "is_deleted": True,
                "deleted_at": message.FDateDeleted.isoformat() + "Z" if message.FDateDeleted else None,
                "deleted_by_type": message.FDeletedByType,
                "initiator_message": initiator_info,
                "timestamp": get_timestamp(),
            },
        )

    except HTTPException:
        raise
    except Exception as e:
        api_logger.error(f"Failed to get deletion info: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Failed to get deletion info: {str(e)}") from e


@router.post(
    "/messages/restore/{message_id}",
    summary="Восстановить сообщение",
    description="Восстанавливает ранее удаленное сообщение (отменяет отметку удаления)",
)
@log_exceptions(api_logger)
async def restore_deleted_message(
    message_id: int,
    chat_id: int | None = None,
    session: Any = Depends(get_session),
) -> JSONResponse:
    """Восстановление удаленного сообщения."""
    api_logger.info(f"Restoring message {message_id}")

    try:
        result = await ChatRepository.restore_deleted_message(session=session, message_id=message_id, chat_id=chat_id)

        if result:
            return JSONResponse(
                status_code=200,
                content={
                    "success": True,
                    "message_id": message_id,
                    "message": "Message restored successfully",
                    "timestamp": get_timestamp(),
                },
            )
        else:
            raise HTTPException(status_code=404, detail=f"Deleted message {message_id} not found")

    except HTTPException:
        raise
    except Exception as e:
        api_logger.error(f"Failed to restore message {message_id}: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Failed to restore message: {str(e)}") from e


@router.delete("/{message_id}", summary="Удалить сообщение", description="Удаляет сообщение из чата Telegram")
@log_exceptions(api_logger)
async def delete_message(
    message_id: int,
    chat_id: int,
    tg_manager: Any = Depends(get_telegram_manager),
) -> JSONResponse:
    """Удаление сообщения из чата Telegram."""
    api_logger.info(f"Deleting message {message_id} from chat {chat_id}")

    try:
        result = await tg_manager.delete_message_by_id(chat_id=chat_id, message_id=message_id)

        if result.get("success"):
            api_logger.info(f"Message {message_id} deleted from chat {chat_id}")
            return JSONResponse(
                status_code=200,
                content={"success": True, "message_id": message_id, "chat_id": chat_id, "timestamp": get_timestamp()},
            )
        else:
            error_msg = result.get("error", "Unknown error")
            api_logger.error(f"Failed to delete message {message_id}: {error_msg}")
            return JSONResponse(
                status_code=400,
                content={
                    "success": False,
                    "message_id": message_id,
                    "chat_id": chat_id,
                    "error": error_msg,
                    "timestamp": get_timestamp(),
                },
            )

    except Exception as e:
        api_logger.error(f"Failed to delete message {message_id}: {e}", exc_info=True)
        return JSONResponse(
            status_code=500,
            content={
                "success": False,
                "message_id": message_id,
                "chat_id": chat_id,
                "error": f"Internal server error: {str(e)}",
                "timestamp": get_timestamp(),
            },
        )


@router.get("/status", summary="Получить статус Telegram", description="Возвращает статус Telegram клиентов")
@log_exceptions(api_logger)
async def get_telegram_status(
    tg_manager: Any = Depends(get_telegram_manager),
) -> JSONResponse:
    """Получение статуса Telegram клиентов."""
    api_logger.info("Getting Telegram status...")

    try:
        status = await tg_manager.get_status()

        return JSONResponse(status_code=200, content={"success": True, "status": status, "timestamp": get_timestamp()})
    except Exception as e:
        api_logger.error(f"Failed to get Telegram status: {e}", exc_info=True)
        return JSONResponse(status_code=500, content={"success": False, "error": str(e), "timestamp": get_timestamp()})


@router.get("/chats", summary="Получить список чатов", description="Возвращает список всех активных чатов")
@log_exceptions(api_logger)
async def get_chats(
    is_active: bool | None = True,
    session: Any = Depends(get_session),
) -> JSONResponse:
    """Получение списка чатов из базы данных."""
    api_logger.info("Getting chats list...")

    try:
        chats = await ChatRepository.get_chats(session, is_active=is_active)

        result = []
        for chat in chats:
            members = await ChatRepository.get_user_chat_members(session, chat_id=chat.FID, is_active=True)

            # Получение количества сообщений через репозиторий
            messages_count = await MessageRepository.get_message_count_by_chat(session, chat.FID)

            result.append(
                {
                    "chat_id": chat.FID,
                    "title": chat.FTitle or f"Chat {chat.FID}",
                    "type": chat.FType.value if chat.FType else "unknown",
                    "is_active": chat.FFlagActive,
                    "members_count": len(members),
                    "messages_count": messages_count,
                    "last_activity": chat.FDateUpdated.isoformat() + "Z" if chat.FDateUpdated else None,
                    "last_sync": chat.FDateSynced.isoformat() + "Z" if chat.FDateSynced else None,
                }
            )

        api_logger.info(f"Found {len(result)} chats")

        return JSONResponse(status_code=200, content=result)

    except Exception as e:
        api_logger.error(f"Failed to get chats: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Failed to get chats: {str(e)}") from e


@router.get(
    "/chats/{chat_id}", summary="Получить информацию о чате", description="Возвращает информацию о конкретном чате"
)
@log_exceptions(api_logger)
async def get_chat_info(
    chat_id: int,
    session: Any = Depends(get_session),
) -> JSONResponse:
    """Получение детальной информации о чате."""
    api_logger.info(f"Getting chat info for {chat_id}...")

    try:
        # Получение чата через репозиторий
        chats = await ChatRepository.get_chats(session, chat_id=chat_id)

        if not chats:
            raise HTTPException(status_code=404, detail=f"Chat {chat_id} not found")

        chat = chats[0]

        members = await ChatRepository.get_user_chat_members(session, chat_id=chat.FID, is_active=True)

        # Получение количества сообщений через репозиторий
        messages_count = await MessageRepository.get_message_count_by_chat(session, chat.FID)

        # Получение последних сообщений через репозиторий
        recent_messages_list = []
        recent_messages = await MessageRepository.get_messages_by_chat(
            session=session, chat_id=chat.FID, limit=10, include_deleted=True
        )
        for msg in recent_messages:
            recent_messages_list.append(
                {
                    "id": msg.FID,
                    "text": msg.FText[:100] + "..." if msg.FText and len(msg.FText) > 100 else msg.FText,
                    "type": msg.FK_MessageType.value if msg.FK_MessageType else "unknown",
                    "date": msg.FDateSent.isoformat() + "Z" if msg.FDateSent else None,
                    "is_deleted": msg.FFlagDeleted,
                    "has_lifetime": msg.FLifetimeSeconds is not None,
                    "expires_at": msg.FExpiresAt.isoformat() + "Z" if msg.FExpiresAt else None,
                }
            )

        result = {
            "chat_id": chat.FID,
            "title": chat.FTitle or f"Chat {chat.FID}",
            "type": chat.FType.value if chat.FType else "unknown",
            "is_active": chat.FFlagActive,
            "members_count": len(members),
            "messages_count": messages_count,
            "last_activity": chat.FDateUpdated.isoformat() + "Z" if chat.FDateUpdated else None,
            "last_sync": chat.FDateSynced.isoformat() + "Z" if chat.FDateSynced else None,
            "recent_messages": recent_messages_list[:5],
        }

        api_logger.info(f"Chat info retrieved for {chat_id}")

        return JSONResponse(status_code=200, content=result)

    except HTTPException:
        raise
    except Exception as e:
        api_logger.error(f"Failed to get chat info: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Failed to get chat info: {str(e)}") from e


@router.get("/stats", summary="Получить статистику", description="Получает общую статистику по чатам и сообщениям")
@log_exceptions(api_logger)
async def get_stats(
    session: Any = Depends(get_session),
) -> JSONResponse:
    """Получение общей статистики по чатам и сообщениям."""
    api_logger.info("Getting stats...")

    try:
        # Статистика отдается через репозитории
        from ...db.repositories.stats import StatsRepository

        stats = await StatsRepository.get_full_stats(session)

        return JSONResponse(
            status_code=200,
            content={
                "success": True,
                "stats": stats,
                "timestamp": get_timestamp(),
            },
        )

    except Exception as e:
        api_logger.error(f"Failed to get stats: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Failed to get stats: {str(e)}") from e


__all__ = [
    "router",
    "SendMessageRequest",
    "SendMessageResponse",
    "BatchSendMessageResponse",
    "SendMessageToAllResponse",
    "UnifiedSendRequest",
    "ErrorResponse",
    "SetLifetimeRequest",
    "BatchSetLifetimeRequest",
]
