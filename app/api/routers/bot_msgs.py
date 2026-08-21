"""
Модуль роутера для управления сообщениями Telegram бота.

Этот модуль предоставляет API эндпоинты для работы с сообщениями в Telegram:
- Отправка сообщений (одиночных, массовых, во все чаты)
- Управление временем жизни сообщений (автоудаление)
- Просмотр и восстановление удаленных сообщений
- Получение статистики по сообщениям и чатам
- Управление чатами и их участниками

Все эндпоинты используют общий префикс /bot/msgs и требуют аутентификации.
Модуль интегрируется с BotManager для работы с Telegram API и репозиториями
для работы с базой данных.

Роуты:
    POST /send - Универсальная отправка сообщений
    POST /messages/lifetime - Установка времени жизни сообщения
    POST /messages/lifetime/batch - Массовая установка времени жизни
    GET /messages/lifetime/stats - Статистика по времени жизни
    POST /messages/lifetime/force-check - Принудительная проверка истекших
    GET /messages/lifetime/{message_id} - Информация о времени жизни
    GET /messages/deleted - Статистика удаленных сообщений
    GET /messages/deleted/list - Список удаленных сообщений
    GET /messages/deleted/with-initiator - Удаленные с инициаторами
    GET /messages/deletion-stats - Статистика удалений по типам
    GET /messages/{message_id}/deletion-info - Информация об удалении
    POST /messages/restore/{message_id} - Восстановление сообщения
    DELETE /{message_id} - Удаление сообщения из Telegram
    GET /status - Статус Telegram клиентов
    GET /chats - Список чатов
    GET /chats/{chat_id} - Информация о чате
    GET /stats - Общая статистика
"""

from __future__ import annotations

from datetime import timedelta
from typing import TYPE_CHECKING, Any

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field, field_validator

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

    from ...bot import BotManager

from ...bot.dependencies import get_bot_manager
from ...config import settings
from ...db.repositories import ChatRepository, MessageRepository, StatsRepository
from ...dtos import ChatDetailDTO, ChatDTO, DeletedMessageDTO
from ...logger import api_logger
from ...models import ChatType, MessageType, datetime_now
from ...services.message_lifetime_service import message_lifetime_service
from ...utils import get_timestamp
from ...utils.decorators import log_exceptions
from ..dependencies import get_session

# Создание роутера с префиксом /bot/msgs и тегом для документации
router = APIRouter(prefix="/bot/msgs", tags=["Bot Messages"])

# Репозитории (создаются один раз на уровне модуля для переиспользования)
_chat_repo = ChatRepository()
_message_repo = MessageRepository()
_stats_repo = StatsRepository()


class SendMessageRequest(BaseModel):
    """
    Модель запроса для отправки сообщения в Telegram.

    Поддерживает отправку как в конкретный чат, так и во все чаты.
    Включает все параметры, доступные в Telegram Bot API.
    """

    chat_id: int | None = Field(None, description="ID чата в Telegram (обязателен, если send_to_all=false)")
    message_type: MessageType = Field(default=MessageType.BOT_RESPONSE, description="Тип сообщения для классификации")
    text: str = Field(..., description="Текст сообщения", min_length=1, max_length=4096)
    parse_mode: str | None = Field(None, description="Режим парсинга: 'HTML', 'Markdown', 'MarkdownV2' или None")
    disable_web_page_preview: bool = Field(False, description="Отключить предпросмотр ссылок")
    disable_notification: bool = Field(False, description="Отключить уведомление у получателей")
    protect_content: bool = Field(False, description="Защитить содержимое от пересылки")
    reply_to_message_id: int | None = Field(None, description="ID сообщения, на которое отвечаем (цитирование)")
    allow_sender: bool = Field(True, description="Разрешить отправку от имени пользователя (если доступно)")
    lifetime_seconds: int | None = Field(
        None, description="Время жизни сообщения в секундах (автоудаление)", ge=10, le=2592000
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
        """
        Валидация режима парсинга.

        Args:
            v: Режим парсинга

        Returns:
            str | None: Валидный режим в верхнем регистре

        Raises:
            ValueError: Если режим не поддерживается
        """
        if v is not None:
            v_upper = v.upper()
            if v_upper not in ["HTML", "MARKDOWN", "MARKDOWN_V2"]:
                raise ValueError('parse_mode must be "HTML", "Markdown", "MarkdownV2" or None')
            return v_upper
        return None

    @field_validator("lifetime_seconds")
    @classmethod
    def validate_lifetime(cls, v: int | None) -> int | None:
        """
        Валидация времени жизни сообщения.

        Args:
            v: Время жизни в секундах

        Returns:
            int | None: Валидное время жизни

        Raises:
            ValueError: Если время выходит за допустимые пределы
        """
        if v is not None:
            if v < 10:
                raise ValueError("lifetime_seconds must be at least 10 seconds")
            if v > 2592000:  # 30 дней
                raise ValueError("lifetime_seconds must not exceed 30 days (2592000 seconds)")
        return v


class SendMessageResponse(BaseModel):
    """Модель ответа для успешной отправки одного сообщения."""

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
    """Модель ответа для массовой отправки сообщений."""

    total: int = Field(..., description="Всего сообщений в запросе")
    successful: int = Field(..., description="Успешно отправлено")
    failed: int = Field(..., description="Не удалось отправить")
    results: list[dict[str, Any]] = Field(..., description="Результаты отправки каждого сообщения")
    timestamp: str = Field(..., description="Время отправки")
    is_batch: bool = Field(True, description="Признак пакетной отправки")


class SendMessageToAllResponse(BaseModel):
    """Модель ответа для отправки сообщения во все чаты."""

    success: bool = Field(..., description="Успешность операции")
    total_chats: int = Field(..., description="Всего чатов для отправки")
    success_count: int = Field(..., description="Успешно отправлено")
    failed_count: int = Field(..., description="Не удалось отправить")
    failed_chats: list[dict[str, Any]] = Field(default_factory=list, description="Список чатов с ошибками (макс. 10)")
    timestamp: str = Field(..., description="Время отправки")


class ErrorResponse(BaseModel):
    """Стандартная модель ответа при ошибке."""

    success: bool = Field(default=False, description="Успешность операции (всегда False)")
    error: str = Field(..., description="Сообщение об ошибке")
    timestamp: str = Field(..., description="Время ошибки")


class SetLifetimeRequest(BaseModel):
    """Модель запроса для установки времени жизни одному сообщению."""

    message_id: int = Field(..., description="ID сообщения")
    lifetime_seconds: int = Field(..., description="Время жизни в секундах", ge=10, le=2592000)


class BatchSetLifetimeRequest(BaseModel):
    """Модель запроса для установки времени жизни нескольким сообщениям."""

    message_ids: list[int] = Field(..., description="Список ID сообщений", min_length=1, max_length=100)
    lifetime_seconds: int | None = Field(None, description="Время жизни в секундах", ge=10, le=2592000)


class UnifiedSendRequest(BaseModel):
    """
    Универсальная модель для отправки сообщений.

    Поддерживает три формата:
    1. Прямой объект (одно сообщение)
    2. С оберткой messages (одно сообщение)
    3. Массив сообщений (пакетная отправка)
    4. Отправка во все чаты (send_to_all=true)
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
        """
        Преобразование входных данных в список сообщений.

        Обрабатывает все поддерживаемые форматы:
        - Прямые поля -> одно сообщение
        - messages с объектом -> одно сообщение
        - messages со списком -> список сообщений

        Returns:
            list[SendMessageRequest]: Список сообщений для отправки
        """
        # Если есть messages в обертке
        if self.messages is not None:
            if isinstance(self.messages, SendMessageRequest):
                return [self.messages]
            elif isinstance(self.messages, list):
                return self.messages

        # Если есть прямые поля (без обертки)
        if self.text is not None:
            send_to_all = self.send_to_all if self.send_to_all is not None else (self.chat_id is None)

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

            if send_to_all:
                data.pop("chat_id", None)

            msg = SendMessageRequest(**data)
            return [msg]

        return []

    def is_batch(self) -> bool:
        """
        Проверка, является ли запрос пакетным.

        Returns:
            bool: True если запрос содержит массив сообщений
        """
        if self.messages is not None:
            return isinstance(self.messages, list)
        return False


# ============ ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ ============


async def _get_bot_manager() -> BotManager:
    """
    Получение экземпляра BotManager с проверкой статуса.

    Returns:
        BotManager: Экземпляр менеджера бота

    Raises:
        HTTPException: Если бот не запущен (HTTP 503)
    """
    bot_manager = get_bot_manager()
    status = await bot_manager.get_status()
    if not status.get("is_running", False):
        raise HTTPException(status_code=503, detail="Bot service not available")
    return bot_manager


async def _send_single_message(
    bot_manager: BotManager,
    msg: SendMessageRequest,
) -> SendMessageResponse:
    """
    Отправка одного сообщения через BotManager.

    Args:
        bot_manager: Экземпляр менеджера бота
        msg: Данные сообщения для отправки

    Returns:
        SendMessageResponse: Результат отправки
    """
    try:
        send_result = await bot_manager.send_message(
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

        if send_result.get("success"):
            api_logger.info(f"Message sent to chat {msg.chat_id}")

            expires_at = None
            if msg.lifetime_seconds:
                expires_at = (datetime_now() + timedelta(seconds=msg.lifetime_seconds)).isoformat() + "Z"

            return SendMessageResponse(
                success=True,
                message_id=send_result.get("message_id"),
                chat_id=msg.chat_id,
                text=text_preview,
                timestamp=get_timestamp(),
                error=None,
                client=send_result.get("client"),
                is_bot=send_result.get("client") == "aiogram",
                lifetime_seconds=msg.lifetime_seconds,
                expires_at=expires_at,
            )
        else:
            error_msg = send_result.get("error", "Unknown error")
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


async def _send_message_to_all_chats(
    bot_manager: BotManager,
    msg: SendMessageRequest,
    session: AsyncSession,
) -> SendMessageToAllResponse:
    """
    Отправка сообщения во все активные чаты.

    Поддерживает фильтрацию по типам чатов и исключение указанных чатов.

    Args:
        bot_manager: Экземпляр менеджера бота
        msg: Данные сообщения с параметрами фильтрации
        session: Асинхронная сессия SQLAlchemy

    Returns:
        SendMessageToAllResponse: Результат отправки во все чаты
    """
    try:
        # Получение всех активных чатов
        chats = await _chat_repo.get_chats(session, is_active=True)

        # Фильтр по типам чатов
        if msg.chat_types:
            chat_type_values = [ct.value for ct in msg.chat_types]
            chats = [c for c in chats if c.FType.value in chat_type_values]

        # Исключение указанных чатов
        if msg.exclude_chat_ids:
            chats = [c for c in chats if c.FID not in msg.exclude_chat_ids]

        if not chats:
            api_logger.warning("No active chats found for sending")
            return SendMessageToAllResponse(
                success=True,
                total_chats=0,
                success_count=0,
                failed_count=0,
                failed_chats=[],
                timestamp=get_timestamp(),
            )

        api_logger.info(f"📊 Found {len(chats)} chats to send")

        # Отправка сообщения в каждый чат
        success_count = 0
        failed_chats: list[dict[str, Any]] = []

        for chat in chats:
            try:
                result = await bot_manager.send_message(
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
                        {
                            "chat_id": chat.FID,
                            "title": chat.FTitle or f"Chat {chat.FID}",
                            "error": error_msg,
                        }
                    )

            except Exception as e:
                api_logger.error(f"❌ Error sending to chat {chat.FID}: {e}")
                failed_chats.append(
                    {
                        "chat_id": chat.FID,
                        "title": chat.FTitle or f"Chat {chat.FID}",
                        "error": str(e),
                    }
                )

        total_chats = len(chats)
        failed_count = len(failed_chats)

        api_logger.info(f"✅ Message sent to {success_count}/{total_chats} chats")

        return SendMessageToAllResponse(
            success=failed_count == 0,
            total_chats=total_chats,
            success_count=success_count,
            failed_count=failed_count,
            failed_chats=failed_chats[:10],  # Ограничиваем количество ошибок в ответе
            timestamp=get_timestamp(),
        )

    except Exception as e:
        api_logger.error(f"❌ Failed to send message to all chats: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Failed to send message to all chats: {str(e)}") from e


# ============ ЭНДПОИНТЫ ============


@router.post(
    "/send",
    response_model=SendMessageResponse | BatchSendMessageResponse | SendMessageToAllResponse | ErrorResponse,
    summary="Отправить сообщение(я) в Telegram",
    description="""Универсальный эндпоинт для отправки сообщений в Telegram.

Поддерживает:
- Отправку одного сообщения
- Отправку массива сообщений (до 100)
- Отправку во все активные чаты
- Установку времени жизни сообщений

Форматы запроса:
1. Прямой объект: {"chat_id": 123, "text": "Hello"}
2. Обертка messages: {"messages": {"chat_id": 123, "text": "Hello"}}
3. Массив: {"messages": [{"chat_id": 123, "text": "Msg1"}, ...]}
4. Во все чаты: {"send_to_all": true, "text": "Hello everyone"}
""",
)
@log_exceptions(api_logger)
async def send_message_unified(
    request: UnifiedSendRequest,
    session: AsyncSession = Depends(get_session),
) -> JSONResponse:
    """
    Универсальная отправка сообщений в Telegram.

    Автоматически определяет формат запроса и отправляет сообщения
    соответствующим образом.

    Args:
        request: Универсальный запрос с сообщениями
        session: Асинхронная сессия SQLAlchemy

    Returns:
        JSONResponse: Результат отправки с соответствующим статус-кодом
    """
    messages = request.get_messages()
    is_batch = request.is_batch()

    # Проверка наличия сообщений
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
            bot_manager = await _get_bot_manager()
            result = await _send_message_to_all_chats(bot_manager, msg, session)
            return JSONResponse(status_code=200, content=result.model_dump())

    # Проверка лимита для пакетной отправки
    if is_batch and len(messages) > 100:
        api_logger.warning(f"Too many messages: {len(messages)} > 100")
        return JSONResponse(
            status_code=400,
            content=ErrorResponse(
                error="Too many messages. Maximum 100 messages per request.",
                timestamp=get_timestamp(),
            ).model_dump(),
        )

    api_logger.info(f"Sending {len(messages)} message(s) (batch={is_batch})")

    bot_manager = await _get_bot_manager()

    # Отправка одного сообщения
    if not is_batch and len(messages) == 1:
        single_result = await _send_single_message(bot_manager, messages[0])
        status_code = 200 if single_result.success else 400
        return JSONResponse(status_code=status_code, content=single_result.model_dump())

    # Отправка массива сообщений
    results: list[dict[str, Any]] = []
    successful = 0
    failed = 0

    for msg in messages:
        single_result = await _send_single_message(bot_manager, msg)
        results.append(single_result.model_dump())

        if single_result.success:
            successful += 1
        else:
            failed += 1

    api_logger.info(f"Batch completed: {successful} successful, {failed} failed")

    response = BatchSendMessageResponse(
        total=len(messages),
        successful=successful,
        failed=failed,
        results=results,
        timestamp=get_timestamp(),
        is_batch=True,
    )

    # Выбор статус-кода в зависимости от результатов
    if failed == 0:
        status_code = 200
    elif successful > 0:
        status_code = 207  # Multi-Status
    else:
        status_code = 400

    return JSONResponse(status_code=status_code, content=response.model_dump())


@router.post(
    "/messages/lifetime",
    summary="Установить время жизни сообщения",
    description="Устанавливает время жизни для сообщения. По истечении времени сообщение будет автоматически удалено.",
)
@log_exceptions(api_logger)
async def set_message_lifetime(
    request: SetLifetimeRequest,
    session: AsyncSession = Depends(get_session),
) -> JSONResponse:
    """
    Установка времени жизни для одного сообщения.

    Args:
        request: Запрос с ID сообщения и временем жизни
        session: Асинхронная сессия SQLAlchemy

    Returns:
        JSONResponse: Результат операции с информацией об истечении
    """
    api_logger.info(f"⏰ Setting lifetime for message {request.message_id}: {request.lifetime_seconds}s")

    try:
        result = await _message_repo.set_message_lifetime(
            session=session,
            message_id=request.message_id,
            lifetime_seconds=request.lifetime_seconds,
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
    description="Устанавливает время жизни для списка сообщений (макс. 100)",
)
@log_exceptions(api_logger)
async def set_messages_lifetime_batch(
    request: BatchSetLifetimeRequest,
    session: AsyncSession = Depends(get_session),
) -> JSONResponse:
    """
    Массовая установка времени жизни для нескольких сообщений.

    Args:
        request: Запрос со списком ID сообщений и временем жизни
        session: Асинхронная сессия SQLAlchemy

    Returns:
        JSONResponse: Результат операции с количеством успешных обновлений
    """
    if request.lifetime_seconds is None:
        raise HTTPException(status_code=400, detail="lifetime_seconds is required for batch operation")

    api_logger.info(f"⏰ Setting lifetime for {len(request.message_ids)} messages")

    try:
        success_count = 0
        failed_count = 0

        for message_id in request.message_ids:
            result = await _message_repo.set_message_lifetime(
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
    description="Получение статистики по времени жизни сообщений для чата или всех чатов",
)
@log_exceptions(api_logger)
async def get_message_lifetime_stats(
    chat_id: int | None = None,
    session: AsyncSession = Depends(get_session),
) -> JSONResponse:
    """
    Получение статистики по времени жизни сообщений.

    Args:
        chat_id: ID чата (опционально, для фильтрации)
        session: Асинхронная сессия SQLAlchemy

    Returns:
        JSONResponse: Статистика с количеством сообщений по времени жизни
    """
    api_logger.info(f"📊 Getting message lifetime stats for chat {chat_id or 'all'}")

    try:
        stats = await _message_repo.get_message_lifetime_stats(session=session, chat_id=chat_id)

        return JSONResponse(
            status_code=200,
            content={"success": True, "stats": stats, "timestamp": get_timestamp()},
        )

    except Exception as e:
        api_logger.error(f"Failed to get stats: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e)) from e


@router.post(
    "/messages/lifetime/force-check",
    summary="Принудительная проверка истекших сообщений",
    description="Принудительно проверяет и помечает истекшие сообщения для удаления",
)
@log_exceptions(api_logger)
async def force_check_expired_messages() -> JSONResponse:
    """
    Принудительная проверка истекших сообщений.

    Запускает проверку всех сообщений с истекшим временем жизни
    и помечает их для удаления.

    Returns:
        JSONResponse: Количество найденных и помеченных сообщений
    """
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
    description="Возвращает информацию о времени жизни сообщения и его статусе",
)
@log_exceptions(api_logger)
async def get_message_lifetime_info(
    message_id: int,
    session: AsyncSession = Depends(get_session),
) -> JSONResponse:
    """
    Получение детальной информации о времени жизни сообщения.

    Args:
        message_id: ID сообщения
        session: Асинхронная сессия SQLAlchemy

    Returns:
        JSONResponse: Информация о времени жизни, статусе удаления, оставшемся времени

    Raises:
        HTTPException: Если сообщение не найдено
    """
    api_logger.info(f"📊 Getting lifetime info for message {message_id}")

    try:
        message = await _message_repo.get_message_by_id(session, message_id)

        if not message:
            raise HTTPException(status_code=404, detail=f"Message {message_id} not found")

        # Если сообщение уже удалено
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

        # Проверка истекло ли сообщение
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


@router.get(
    "/messages/deleted",
    summary="Получить статистику удаленных сообщений",
    description="Возвращает статистику по удаленным сообщениям за указанный период",
)
@log_exceptions(api_logger)
async def get_deleted_messages_stats(
    chat_id: int | None = None,
    days: int = getattr(settings, "API_STATS_DAYS", 7),
    session: AsyncSession = Depends(get_session),
) -> JSONResponse:
    """
    Получение статистики по удаленным сообщениям.

    Args:
        chat_id: ID чата (опционально, для фильтрации)
        days: Количество дней для анализа
        session: Асинхронная сессия SQLAlchemy

    Returns:
        JSONResponse: Статистика удалений с разбивкой по дням
    """
    api_logger.info(f"Getting deleted messages stats for chat {chat_id or 'all'}")

    try:
        stats = await _chat_repo.get_deleted_messages_stats(session=session, chat_id=chat_id, days=days)

        return JSONResponse(
            status_code=200,
            content={"success": True, "stats": stats, "timestamp": get_timestamp()},
        )

    except Exception as e:
        api_logger.error(f"Failed to get deleted messages stats: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Failed to get deleted messages stats: {str(e)}") from e


@router.get(
    "/messages/deleted/list",
    summary="Получить список удаленных сообщений",
    description="Возвращает список удаленных сообщений с пагинацией",
)
@log_exceptions(api_logger)
async def get_deleted_messages(
    chat_id: int | None = None,
    limit: int = getattr(settings, "API_DEFAULT_PAGE_SIZE", 50),
    offset: int = 0,
    session: AsyncSession = Depends(get_session),
) -> JSONResponse:
    """
    Получение списка удаленных сообщений.

    Args:
        chat_id: ID чата (опционально, для фильтрации)
        limit: Максимальное количество записей
        offset: Смещение для пагинации
        session: Асинхронная сессия SQLAlchemy

    Returns:
        JSONResponse: Список удаленных сообщений
    """
    api_logger.info(f"Getting deleted messages for chat {chat_id or 'all'}")

    try:
        messages = await _chat_repo.get_messages(
            session=session,
            chat_id=chat_id,
            include_deleted=True,
            limit=limit,
            offset=offset,
        )

        # Преобразование в DTO
        deleted_messages = []
        for msg in messages:
            if msg.FFlagDeleted:
                msg_dto = DeletedMessageDTO.from_model(msg)
                deleted_messages.append(msg_dto.to_dict())

        return JSONResponse(
            status_code=200,
            content={
                "success": True,
                "total": len(deleted_messages),
                "messages": deleted_messages,
                "timestamp": get_timestamp(),
            },
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
    session: AsyncSession = Depends(get_session),
) -> JSONResponse:
    """
    Получение удаленных сообщений с информацией об инициаторе.

    Возвращает не только сами сообщения, но и кто их удалил.

    Args:
        chat_id: ID чата (опционально, для фильтрации)
        limit: Максимальное количество записей
        offset: Смещение для пагинации
        session: Асинхронная сессия SQLAlchemy

    Returns:
        JSONResponse: Список удаленных сообщений с инициаторами
    """
    api_logger.info(f"Getting deleted messages with initiator for chat {chat_id or 'all'}")

    try:
        messages = await _chat_repo.get_deleted_messages_with_initiator(
            session=session, chat_id=chat_id, limit=limit, offset=offset
        )

        return JSONResponse(
            status_code=200,
            content={
                "success": True,
                "total": len(messages),
                "messages": messages,
                "timestamp": get_timestamp(),
            },
        )

    except Exception as e:
        api_logger.error(f"Failed to get deleted messages with initiator: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Failed to get deleted messages: {str(e)}") from e


@router.get(
    "/messages/deletion-stats",
    summary="Статистика удалений по типам",
    description="Возвращает статистику удалений по типам инициаторов (бот, пользователь, система)",
)
@log_exceptions(api_logger)
async def get_deletion_stats_by_initiator(
    chat_id: int | None = None,
    days: int = getattr(settings, "API_STATS_DAYS", 7),
    session: AsyncSession = Depends(get_session),
) -> JSONResponse:
    """
    Получение статистики удалений по типам инициаторов.

    Args:
        chat_id: ID чата (опционально, для фильтрации)
        days: Количество дней для анализа
        session: Асинхронная сессия SQLAlchemy

    Returns:
        JSONResponse: Статистика с разбивкой по типам инициаторов
    """
    api_logger.info(f"Getting deletion stats for chat {chat_id or 'all'}")

    try:
        stats = await _chat_repo.get_deletion_stats_by_initiator(session=session, chat_id=chat_id, days=days)

        return JSONResponse(
            status_code=200,
            content={"success": True, "stats": stats, "timestamp": get_timestamp()},
        )

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
    session: AsyncSession = Depends(get_session),
) -> JSONResponse:
    """
    Получение детальной информации об удалении сообщения.

    Args:
        message_id: ID сообщения
        session: Асинхронная сессия SQLAlchemy

    Returns:
        JSONResponse: Информация об удалении (время, инициатор, причина)

    Raises:
        HTTPException: Если сообщение не найдено
    """
    api_logger.info(f"Getting deletion info for message {message_id}")

    try:
        message = await _message_repo.get_message_by_id(session, message_id)

        if not message:
            raise HTTPException(status_code=404, detail=f"Message {message_id} not found")

        # Если сообщение не удалено
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
            initiator = await _message_repo.get_message_by_id(session, message.FK_DeletedByMessage)
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
    session: AsyncSession = Depends(get_session),
) -> JSONResponse:
    """
    Восстановление удаленного сообщения.

    Отменяет флаг удаления и восстанавливает сообщение в базе данных.

    Args:
        message_id: ID сообщения для восстановления
        chat_id: ID чата (опционально, для проверки)
        session: Асинхронная сессия SQLAlchemy

    Returns:
        JSONResponse: Результат операции

    Raises:
        HTTPException: Если сообщение не найдено
    """
    api_logger.info(f"Restoring message {message_id}")

    try:
        result = await _chat_repo.restore_deleted_message(session=session, message_id=message_id, chat_id=chat_id)

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


@router.delete(
    "/{message_id}",
    summary="Удалить сообщение",
    description="Удаляет сообщение из чата Telegram",
)
@log_exceptions(api_logger)
async def delete_message(
    message_id: int,
    chat_id: int,
) -> JSONResponse:
    """
    Удаление сообщения из чата Telegram через Bot API.

    Args:
        message_id: ID сообщения для удаления
        chat_id: ID чата, из которого удаляется сообщение

    Returns:
        JSONResponse: Результат операции
    """
    api_logger.info(f"Deleting message {message_id} from chat {chat_id}")

    try:
        bot_manager = await _get_bot_manager()
        result = await bot_manager.delete_message_by_id(chat_id=chat_id, message_id=message_id)

        if result.get("success"):
            api_logger.info(f"Message {message_id} deleted from chat {chat_id}")
            return JSONResponse(
                status_code=200,
                content={
                    "success": True,
                    "message_id": message_id,
                    "chat_id": chat_id,
                    "timestamp": get_timestamp(),
                },
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


@router.get(
    "/status",
    summary="Получить статус Telegram",
    description="Возвращает статус Telegram клиентов (ботов) и их состояние",
)
@log_exceptions(api_logger)
async def get_telegram_status() -> JSONResponse:
    """
    Получение статуса Telegram клиентов.

    Returns:
        JSONResponse: Информация о статусе ботов и подключениях
    """
    api_logger.info("Getting Telegram status...")

    try:
        bot_manager = await _get_bot_manager()
        status = await bot_manager.get_status()

        return JSONResponse(
            status_code=200,
            content={"success": True, "status": status, "timestamp": get_timestamp()},
        )

    except HTTPException:
        raise
    except Exception as e:
        api_logger.error(f"Failed to get Telegram status: {e}", exc_info=True)
        return JSONResponse(
            status_code=500,
            content={"success": False, "error": str(e), "timestamp": get_timestamp()},
        )


@router.get(
    "/chats",
    summary="Получить список чатов",
    description="Возвращает список всех активных чатов с информацией об участниках и количестве сообщений",
)
@log_exceptions(api_logger)
async def get_chats(
    is_active: bool | None = True,
    session: AsyncSession = Depends(get_session),
) -> JSONResponse:
    """
    Получение списка чатов с детальной информацией.

    Args:
        is_active: Фильтр по активности (True - только активные)
        session: Асинхронная сессия SQLAlchemy

    Returns:
        JSONResponse: Список чатов с метаинформацией
    """
    api_logger.info("Getting chats list...")

    try:
        chats = await _chat_repo.get_chats(session, is_active=is_active)

        result = []
        for chat in chats:
            members = await _chat_repo.get_user_chat_members(session, chat_id=chat.FID, is_active=True)
            messages_count = await _message_repo.get_message_count_by_chat(session, chat.FID)

            chat_dto = ChatDTO.from_model(
                chat=chat,
                members_count=len(members),
                messages_count=messages_count,
            )
            result.append(chat_dto.to_dict())

        api_logger.info(f"Found {len(result)} chats")
        return JSONResponse(status_code=200, content=result)

    except Exception as e:
        api_logger.error(f"Failed to get chats: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Failed to get chats: {str(e)}") from e


@router.get(
    "/chats/{chat_id}",
    summary="Получить информацию о чате",
    description="Возвращает детальную информацию о конкретном чате с последними сообщениями",
)
@log_exceptions(api_logger)
async def get_chat_info(
    chat_id: int,
    session: AsyncSession = Depends(get_session),
) -> JSONResponse:
    """
    Получение детальной информации о чате.

    Возвращает информацию о чате, участниках, количестве сообщений
    и последние 10 сообщений.

    Args:
        chat_id: ID чата
        session: Асинхронная сессия SQLAlchemy

    Returns:
        JSONResponse: Детальная информация о чате

    Raises:
        HTTPException: Если чат не найден
    """
    api_logger.info(f"Getting chat info for {chat_id}...")

    try:
        chats = await _chat_repo.get_chats(session, chat_id=chat_id)

        if not chats:
            raise HTTPException(status_code=404, detail=f"Chat {chat_id} not found")

        chat = chats[0]

        members = await _chat_repo.get_user_chat_members(session, chat_id=chat.FID, is_active=True)
        messages_count = await _message_repo.get_message_count_by_chat(session, chat.FID)
        recent_messages = await _message_repo.get_messages_by_chat(
            session=session, chat_id=chat.FID, limit=10, include_deleted=True
        )

        chat_detail_dto = ChatDetailDTO.from_model(
            chat=chat,
            members_count=len(members),
            messages_count=messages_count,
            recent_messages=recent_messages,
        )

        api_logger.info(f"Chat info retrieved for {chat_id}")
        return JSONResponse(status_code=200, content=chat_detail_dto.to_dict())

    except HTTPException:
        raise
    except Exception as e:
        api_logger.error(f"Failed to get chat info: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Failed to get chat info: {str(e)}") from e


@router.get(
    "/stats",
    summary="Получить статистику",
    description="Получает общую статистику по чатам, сообщениям, пользователям и активности",
)
@log_exceptions(api_logger)
async def get_stats(
    session: AsyncSession = Depends(get_session),
) -> JSONResponse:
    """
    Получение общей статистики по системе.

    Включает:
    - Количество чатов
    - Количество сообщений
    - Количество пользователей
    - Активность по дням
    - Распределение по типам чатов

    Args:
        session: Асинхронная сессия SQLAlchemy

    Returns:
        JSONResponse: Полная статистика системы
    """
    api_logger.info("Getting stats...")

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
        api_logger.error(f"Failed to get stats: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Failed to get stats: {str(e)}") from e


__all__ = ["router"]
