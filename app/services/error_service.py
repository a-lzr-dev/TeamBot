from datetime import datetime, timedelta
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from ..db import db_manager
from ..exceptions import log_exceptions
from ..logger import app_logger
from ..models import (
    ChatMessageModel,
    ChatModel,
    ErrorCategory,
    ErrorMessageLinkModel,
    ErrorModel,
    ErrorSeverity,
    ErrorStatus,
    MessageSource,
    MessageType,
    datetime_now,
)


class ErrorService:
    """Сервис для управления ошибками"""

    def __init__(self) -> None:
        self._group_cache: dict[str, dict] = {}
        from ..config import settings

        self._cache_ttl = getattr(settings, "ERROR_GROUP_CACHE_TTL_SECONDS", 300)

    # ============ ВСПОМОГАТЕЛЬНЫЙ МЕТОД ДЛЯ ВАЛИДАЦИИ КАТЕГОРИИ ============

    @staticmethod
    def _validate_category(category: Any | None) -> ErrorCategory:
        """
        Валидация категории ошибки.
        Преобразует строку в ErrorCategory или возвращает значение по умолчанию.
        """
        if category is None:
            return ErrorCategory.ARBITRARY

        # Если уже ErrorCategory
        if isinstance(category, ErrorCategory):
            return category

        # Если строка
        if isinstance(category, str):
            try:
                return ErrorCategory(category)
            except ValueError:
                app_logger.warning(f"⚠️ Unknown error category: {category}, using ARBITRARY")
                return ErrorCategory.ARBITRARY

        # Если что-то другое
        return ErrorCategory.ARBITRARY

    @staticmethod
    def _validate_severity(severity: Any | None) -> ErrorSeverity:
        """Валидация серьезности ошибки"""
        if severity is None:
            return ErrorSeverity.ERROR

        if isinstance(severity, ErrorSeverity):
            return severity

        if isinstance(severity, str):
            try:
                return ErrorSeverity(severity)
            except ValueError:
                app_logger.warning(f"⚠️ Unknown error severity: {severity}, using ERROR")
                return ErrorSeverity.ERROR

        return ErrorSeverity.ERROR

    # ============ ОСНОВНОЙ МЕТОД ДЛЯ ЛОГИРОВАНИЯ ============

    @log_exceptions(app_logger)
    async def log_error(
        self,
        error: Exception,
        *,
        component: str = "app",
        user_id: int | None = None,
        chat_id: int | None = None,
        message_id: int | None = None,
        category: Any | None = None,
        severity: Any | None = None,
        context: dict[str, Any] | None = None,
        session: AsyncSession | None = None,
    ) -> tuple[ErrorModel | None, ChatMessageModel | None]:
        """Метод для логирования ошибок"""
        if session is None:
            async with db_manager.get_session() as sess:
                return await self.log_error(
                    error=error,
                    component=component,
                    user_id=user_id,
                    chat_id=chat_id,
                    message_id=message_id,
                    category=category,
                    severity=severity,
                    context=context,
                    session=sess,
                )

        # Валидация категории и серьезности
        category_enum = self._validate_category(category)
        severity_enum = self._validate_severity(severity)

        # Подготовка данных
        error_type = type(error).__name__
        error_message = str(error) or error_type
        error_code = error_type[:50]

        # Сбор деталей
        details = self._format_details(error, component, context)

        # Получение traceback
        traceback_text = self._get_traceback(error)

        error_model = await self._save_to_errors(
            session=session,
            error_code=error_code,
            error_message=error_message,
            error_type=error_type,
            details=details,
            traceback_text=traceback_text,
            category=category_enum,
            severity=severity_enum,
            user_id=user_id,
            component=component,
            context=context,
        )

        chat_message = None
        if chat_id and await self._chat_exists(session, chat_id):
            chat_message = await self._save_to_chat_messages(
                session=session,
                error=error,
                error_type=error_type,
                error_message=error_message,
                traceback_text=traceback_text,
                category=category_enum,
                user_id=user_id,
                chat_id=chat_id,
                message_id=message_id,
                component=component,
                context=context,
                error_id=error_model.FID if error_model else None,
            )

        if error_model and chat_message:
            link = ErrorMessageLinkModel(FK_Error=error_model.FID, FK_Message=chat_message.FID)
            session.add(link)
            await session.flush()

        await session.commit()

        return error_model, chat_message

    # ============ МЕТОД ДЛЯ ВНЕШНИХ ОШИБОК ============

    @log_exceptions(app_logger)
    async def log_external_error(
        self,
        error_code: str,
        error_message: str,
        source_system: str,
        *,
        user_id: int | None = None,
        user_login: str | None = None,
        category: Any | None = None,
        severity: Any | None = None,
        details: str | None = None,
        source_module: str | None = None,
        chat_ids: list[int] | None = None,
        send_to_telegram: bool = True,
        session: AsyncSession | None = None,
    ) -> ErrorModel:
        """Логирование внешней ошибки из другой системы с отправкой в несколько чатов"""
        if session is None:
            async with db_manager.get_session() as sess:
                return await self.log_external_error(
                    error_code=error_code,
                    error_message=error_message,
                    source_system=source_system,
                    user_id=user_id,
                    user_login=user_login,
                    category=category,
                    severity=severity,
                    details=details,
                    source_module=source_module,
                    chat_ids=chat_ids,
                    send_to_telegram=send_to_telegram,
                    session=sess,
                )

        # Валидация категории и серьезности
        category_enum = self._validate_category(category)
        severity_enum = self._validate_severity(severity)

        # Создание хеша для группировки
        group_hash = self._create_group_hash(error_code, error_message, source_system)

        # Поиск существующей ошибки
        stmt = select(ErrorModel).where(
            ErrorModel.FGroupHash == group_hash, ErrorModel.FStatus.in_([ErrorStatus.NEW, ErrorStatus.IN_PROGRESS])
        )
        result = await session.execute(stmt)
        existing: ErrorModel | None = result.scalar_one_or_none()

        if existing:
            # ============ УДАЛЕНИЕ СТАРЫХ СООБЩЕНИЙ ============
            app_logger.info(f"🧹 Cleaning up old messages for existing error {existing.FID}")

            try:
                # Получение всех связей для этой ошибки
                stmt = select(ErrorMessageLinkModel).where(ErrorMessageLinkModel.FK_Error == existing.FID)
                links_result = await session.execute(stmt)
                links = links_result.scalars().all()

                if links:
                    app_logger.info(f"📊 Found {len(links)} old links for error {existing.FID}")

                    # Получение всех связанных сообщений
                    message_ids = [link.FK_Message for link in links]
                    stmt = select(ChatMessageModel).where(ChatMessageModel.FID.in_(message_ids))
                    messages_result = await session.execute(stmt)
                    messages = messages_result.scalars().all()

                    # 1. Удаление сообщений из Telegram
                    deleted_from_telegram = 0
                    try:
                        from ..tg import tg_manager

                        status = await tg_manager.get_status()

                        if status.get("is_running", False):
                            for message in messages:
                                try:
                                    delete_result = await tg_manager.delete_message_by_id(
                                        chat_id=message.FK_Chat, message_id=message.FID
                                    )
                                    if delete_result.get("success"):
                                        deleted_from_telegram += 1
                                        app_logger.debug(f"✅ Deleted old message {message.FID} from Telegram")
                                    else:
                                        app_logger.debug(
                                            f"⚠️ Failed to delete old message {message.FID}: {delete_result.get('error')}"
                                        )
                                except Exception as e:
                                    app_logger.warning(f"⚠️ Error deleting old message {message.FID}: {e}")

                            if deleted_from_telegram > 0:
                                app_logger.info(f"✅ Deleted {deleted_from_telegram} old messages from Telegram")
                        else:
                            app_logger.warning("⚠️ Telegram manager not running, skipping Telegram deletion")

                    except Exception as e:
                        app_logger.warning(f"⚠️ Failed to delete old messages from Telegram: {e}")

                    # 2. Отметка сообщений как удаленных в БД
                    db_deleted = 0
                    for message in messages:
                        if not message.FFlagDeleted:
                            message.FFlagDeleted = True
                            message.FDateDeleted = datetime_now()
                            message.FDeletedByType = "error_repeat_cleanup"
                            message.FK_DeletedByMessage = None
                            db_deleted += 1
                            app_logger.debug(f"✅ Marked old message {message.FID} as deleted in DB")

                    # 3. Удаление связей
                    links_deleted = 0
                    for link in links:
                        await session.delete(link)
                        links_deleted += 1

                    app_logger.info(
                        f"✅ Cleanup complete for error {existing.FID}: "
                        f"telegram_deleted={deleted_from_telegram}, "
                        f"db_deleted={db_deleted}, "
                        f"links_deleted={links_deleted}"
                    )
                else:
                    app_logger.debug(f"ℹ️ No old messages to clean up for error {existing.FID}")

            except Exception as e:
                app_logger.error(f"❌ Failed to cleanup old messages for error {existing.FID}: {e}")

            # ============ ОБНОВЛЕНИЕ СУЩЕСТВУЮЩЕЙ ОШИБКИ ============
            existing.FCountOccurrences += 1
            existing.FLastOccurrence = datetime_now()
            if details:
                existing.FErrorDetails = details[:1000]
            await session.flush()

            # Отправка сообщений в Telegram во все чаты о повторении
            if chat_ids and send_to_telegram:
                for chat_id in chat_ids:
                    message_id = await self._send_error_message(
                        chat_id=chat_id,
                        error_code=error_code,
                        error_message=error_message,
                        source_system=source_system,
                        source_module=source_module,
                        user_id=user_id,
                        user_login=user_login,
                        details=details,
                        is_repeat=True,
                        repeat_count=existing.FCountOccurrences,
                    )

                    # Связь существующей ошибки с новым сообщением
                    if message_id:
                        stmt = select(ChatMessageModel).where(ChatMessageModel.FID == message_id)
                        result = await session.execute(stmt)
                        chat_message = result.scalar_one_or_none()

                        if chat_message:
                            # Проверка, нет ли уже такой связи
                            stmt = select(ErrorMessageLinkModel).where(
                                ErrorMessageLinkModel.FK_Error == existing.FID,
                                ErrorMessageLinkModel.FK_Message == chat_message.FID,
                            )
                            result = await session.execute(stmt)
                            link_exists = result.scalar_one_or_none()

                            if not link_exists:
                                link = ErrorMessageLinkModel(FK_Error=existing.FID, FK_Message=chat_message.FID)
                                session.add(link)
                                app_logger.info(
                                    f"✅ Linked existing error {existing.FID} with new message {chat_message.FID}"
                                )

            await session.commit()
            await session.refresh(existing)
            return existing

        # ============ НОВАЯ ОШИБКА ============

        # Отправка сообщений в Telegram во все чаты
        sent_messages = []
        if chat_ids and send_to_telegram:
            for chat_id in chat_ids:
                message_id = await self._send_error_message(
                    chat_id=chat_id,
                    error_code=error_code,
                    error_message=error_message,
                    source_system=source_system,
                    source_module=source_module,
                    user_id=user_id,
                    user_login=user_login,
                    details=details,
                    is_repeat=False,
                )
                if message_id:
                    sent_messages.append({"chat_id": chat_id, "message_id": message_id})

        # Создание новой ошибки
        error = ErrorModel(
            FErrorCode=error_code[:100],
            FErrorMessage=error_message[:500],
            FErrorDetails=details[:1000] if details else None,
            FSourceSystem=source_system[:100],
            FSourceModule=source_module[:100] if source_module else None,
            FCategory=category_enum,
            FSeverity=severity_enum,
            FStatus=ErrorStatus.NEW,
            FUserID=user_id,
            FUserLogin=user_login[:100] if user_login else None,
            FGroupHash=group_hash,
            FCountOccurrences=1,
            FFirstOccurrence=datetime_now(),
            FLastOccurrence=datetime_now(),
        )

        session.add(error)
        await session.flush()

        # Связь ошибки с сообщениями через таблицу связей
        for sent in sent_messages:
            stmt = select(ChatMessageModel).where(sent["message_id"] == ChatMessageModel.FID)
            result = await session.execute(stmt)
            chat_message = result.scalar_one_or_none()

            if chat_message and error.FID:
                link = ErrorMessageLinkModel(FK_Error=error.FID, FK_Message=chat_message.FID)
                session.add(link)
                app_logger.info(f"✅ Linked new error {error.FID} with message {chat_message.FID}")

        await session.commit()
        await session.refresh(error)

        app_logger.info(
            f"✅ External error saved: ID={error.FID}, Code={error.FErrorCode}, Sent to {len(sent_messages)} chats"
        )

        return error

    # ============ МЕТОД ДЛЯ УДАЛЕНИЯ СООБЩЕНИЙ, СВЯЗАННЫХ С ОШИБКОЙ ============

    @log_exceptions(app_logger)
    async def delete_error_messages(
        self, error_id: int, delete_from_telegram: bool = True, session: AsyncSession | None = None
    ) -> dict[str, Any]:
        """Удаление всех сообщений, связанных с ошибкой"""
        if session is None:
            async with db_manager.get_session() as sess:
                return await self.delete_error_messages(
                    error_id=error_id, delete_from_telegram=delete_from_telegram, session=sess
                )

        app_logger.info(f"🗑️ Deleting messages for error {error_id}")

        result: dict[str, Any] = {
            "success": False,
            "error_id": error_id,
            "messages_found": 0,
            "messages_deleted_db": 0,
            "messages_deleted_telegram": 0,
            "links_deleted": 0,
            "errors": [],
        }

        try:
            # 1. Проверка существования ошибки
            stmt = select(ErrorModel).where(error_id == ErrorModel.FID)
            error_result = await session.execute(stmt)
            error = error_result.scalar_one_or_none()

            if not error:
                result["errors"].append(f"Error {error_id} not found")
                app_logger.warning(f"⚠️ Error {error_id} not found")
                return result

            # 2. Получение всех связей для этой ошибки
            stmt = select(ErrorMessageLinkModel).where(ErrorMessageLinkModel.FK_Error == error_id)
            links_result = await session.execute(stmt)
            links = links_result.scalars().all()

            if not links:
                app_logger.info(f"ℹ️ No messages linked to error {error_id}")
                result["success"] = True
                result["messages_found"] = 0
                return result

            result["messages_found"] = len(links)
            app_logger.info(f"📊 Found {len(links)} links for error {error_id}")

            # 3. Получение всех сообщений
            message_ids = [link.FK_Message for link in links]
            stmt = select(ChatMessageModel).where(ChatMessageModel.FID.in_(message_ids))
            messages_result = await session.execute(stmt)
            messages = messages_result.scalars().all()

            # 4. Удаление сообщения из Telegram
            telethon_deleted = 0
            if delete_from_telegram:
                try:
                    from ..tg import tg_manager

                    # Проверка, запущен ли Telegram менеджер
                    status = await tg_manager.get_status()
                    if status.get("is_running", False):
                        for message in messages:
                            try:
                                # Попытка удалить сообщение из Telegram
                                delete_result = await tg_manager.delete_message_by_id(
                                    chat_id=message.FK_Chat, message_id=message.FID
                                )
                                if delete_result.get("success"):
                                    telethon_deleted += 1
                                    app_logger.debug(f"✅ Deleted message {message.FID} from Telegram")
                                else:
                                    app_logger.warning(
                                        f"⚠️ Failed to delete message {message.FID} from Telegram: {delete_result.get('error')}"
                                    )
                                    result["errors"].append(f"Failed to delete message {message.FID} from Telegram")
                            except Exception as e:
                                app_logger.error(f"❌ Error deleting message {message.FID} from Telegram: {e}")
                                result["errors"].append(f"Error deleting message {message.FID}: {str(e)}")
                    else:
                        app_logger.warning("⚠️ Telegram manager not running, skipping Telegram deletion")
                        result["errors"].append("Telegram manager not running")
                except Exception as e:
                    app_logger.error(f"❌ Failed to delete messages from Telegram: {e}")
                    result["errors"].append(f"Telegram deletion error: {str(e)}")

            result["messages_deleted_telegram"] = telethon_deleted

            # 5. Отметка сообщения как удаленные в БД
            db_deleted = 0
            for message in messages:
                if not message.FFlagDeleted:
                    message.FFlagDeleted = True
                    message.FDateDeleted = datetime_now()
                    message.FDeletedByType = "error_cleanup"
                    message.FK_DeletedByMessage = None
                    db_deleted += 1
                    app_logger.debug(f"✅ Marked message {message.FID} as deleted in DB")

            result["messages_deleted_db"] = db_deleted

            # 6. Удаление связи
            for link in links:
                await session.delete(link)
                result["links_deleted"] += 1

            await session.commit()

            result["success"] = True
            app_logger.info(
                f"✅ Successfully processed deletion for error {error_id}: "
                f"messages={result['messages_found']}, "
                f"db_deleted={result['messages_deleted_db']}, "
                f"telegram_deleted={result['messages_deleted_telegram']}, "
                f"links_deleted={result['links_deleted']}"
            )

            return result

        except Exception as e:
            app_logger.error(f"❌ Failed to delete messages for error {error_id}: {e}")
            await session.rollback()
            result["errors"].append(str(e))
            return result

    # ============ ВСПОМОГАТЕЛЬНЫЕ МЕТОДЫ ============

    @staticmethod
    async def _chat_exists(session: AsyncSession, chat_id: int) -> bool:
        """Проверка существования чата в БД"""
        if not chat_id:
            return False
        try:
            stmt = select(ChatModel).where(chat_id == ChatModel.FID)
            result = await session.execute(stmt)
            return result.scalar_one_or_none() is not None
        except Exception as e:
            app_logger.warning(f"⚠️ Failed to check chat existence: {e}")
            return False

    async def _send_error_message(
        self,
        chat_id: int,
        error_code: str,
        error_message: str,
        source_system: str,
        source_module: str | None = None,
        user_id: int | None = None,
        user_login: str | None = None,
        details: str | None = None,
        is_repeat: bool = False,
        repeat_count: int = 0,
    ) -> int | None:
        """Отправка сообщения об ошибке в Telegram"""
        try:
            from ..tg import tg_manager

            text = self._format_external_error_message(
                error_code=error_code,
                error_message=error_message,
                source_system=source_system,
                source_module=source_module,
                user_id=user_id,
                user_login=user_login,
                details=details,
                is_repeat=is_repeat,
                repeat_count=repeat_count,
            )

            result = await tg_manager.send_message(
                chat_id=chat_id,
                message_type=MessageType.SYSTEM_ALERT,
                text=text,
                parse_mode="Markdown",
                disable_notification=False,
            )

            if result.get("success"):
                message_id = result.get("message_id")
                if message_id is not None:
                    app_logger.info(f"✅ Message sent to chat {chat_id}, ID: {message_id}")
                    return int(message_id)
                return None
            else:
                app_logger.warning(f"⚠️ Failed to send message: {result.get('error')}")
                return None

        except Exception as e:
            app_logger.error(f"❌ Failed to send Telegram message: {e}")
            return None

    @staticmethod
    def _format_external_error_message(
        error_code: str,
        error_message: str,
        source_system: str,
        source_module: str | None = None,
        user_id: int | None = None,
        user_login: str | None = None,
        details: str | None = None,
        is_repeat: bool = False,
        repeat_count: int = 0,
    ) -> str:
        """Форматирование сообщения для внешней ошибки"""
        if is_repeat:
            message = "🔄 **Повтор внешней ошибки**\n\n"
            message += f"📊 **Повторов:** {repeat_count}\n\n"
        else:
            message = "🚨 **Внешняя ошибка**\n\n"

        message += f"🔑 **Код:** `{error_code}`\n"
        message += f"📝 **Сообщение:**\n```\n{error_message[:300]}\n```\n"
        message += f"🖥️ **Система:** {source_system}\n"

        if source_module:
            message += f"📦 **Модуль:** {source_module}\n"

        if user_login:
            message += f"👤 **Пользователь:** {user_login}\n"
        elif user_id:
            message += f"👤 **User ID:** {user_id}\n"

        if details:
            message += f"\n📎 **Детали:**\n```\n{details[:300]}\n```\n"

        message += f"\n📅 **Время:** {datetime_now().strftime('%d.%m.%Y %H:%M:%S')}"

        return message

    # ============ СОХРАНЕНИЕ В TErrors ============

    async def _save_to_errors(
        self,
        session: AsyncSession,
        error_code: str,
        error_message: str,
        error_type: str,
        details: str | None,
        traceback_text: str | None,
        category: ErrorCategory,
        severity: ErrorSeverity,
        user_id: int | None,
        component: str,
        context: dict[str, Any] | None,
    ) -> ErrorModel | None:
        """Сохранение в TErrors"""
        try:
            group_hash = self._create_group_hash(error_code, error_message, component)

            stmt = select(ErrorModel).where(
                ErrorModel.FGroupHash == group_hash, ErrorModel.FStatus.in_([ErrorStatus.NEW, ErrorStatus.IN_PROGRESS])
            )
            result = await session.execute(stmt)
            existing: ErrorModel | None = result.scalar_one_or_none()

            if existing:
                existing.FCountOccurrences += 1
                existing.FLastOccurrence = datetime_now()
                if details:
                    existing.FErrorDetails = details[:1000]
                return existing

            error = ErrorModel(
                FErrorCode=error_code,
                FErrorMessage=error_message[:500],
                FErrorDetails=details[:1000] if details else None,
                FSourceSystem="TeamBot",
                FSourceModule=component,
                FCategory=category,
                FSeverity=severity,
                FStatus=ErrorStatus.NEW,
                FUserID=user_id,
                FGroupHash=group_hash,
                FCountOccurrences=1,
                FFirstOccurrence=datetime_now(),
                FLastOccurrence=datetime_now(),
            )
            session.add(error)
            await session.flush()
            return error

        except Exception as e:
            app_logger.error(f"Failed to save to TErrors: {e}")
            return None

    # ============ СОХРАНЕНИЕ В TChatsMessages ============

    @staticmethod
    async def _save_to_chat_messages(
        session: AsyncSession,
        error: Exception,
        error_type: str,
        error_message: str,
        traceback_text: str | None,
        category: ErrorCategory,
        user_id: int | None,
        chat_id: int | None,
        message_id: int | None,
        component: str,
        context: dict[str, Any] | None,
        error_id: int | None,
    ) -> ChatMessageModel | None:
        """Сохранение в TChatsMessages"""
        try:
            if not chat_id:
                app_logger.warning("⚠️ Cannot save message: chat_id is None")
                return None

            message_text = f"❌ Ошибка в {component}: {error_type}"
            if error_message:
                message_text += f"\n{error_message[:200]}"
            if error_id:
                message_text += f"\nError ID: {error_id}"

            chat_message = ChatMessageModel(
                FID=message_id or 0,
                FK_Chat=chat_id,
                FK_User=user_id,
                FK_MessageType=MessageType.SYSTEM_ALERT,
                FSource=MessageSource.SYSTEM,
                FText=message_text[:4096],
                FErrorMessage=f"{error_type}: {error_message[:500]}",
                FErrorTraceback=traceback_text[:1000] if traceback_text else None,
                FCategory=category.value if category else "error",
                FDateSent=datetime_now(),
            )
            session.add(chat_message)
            await session.flush()
            return chat_message

        except Exception as e:
            app_logger.error(f"Failed to save to TChatsMessages: {e}")
            return None

    # ============ ВСПОМОГАТЕЛЬНЫЕ МЕТОДЫ ============

    @staticmethod
    def _determine_category(component: str) -> ErrorCategory:
        """Определение категории по компоненту"""
        component_lower = component.lower()
        if "api" in component_lower or "tg" in component_lower or "telegram" in component_lower:
            return ErrorCategory.TASK_EXECUTION
        elif "db" in component_lower or "database" in component_lower:
            return ErrorCategory.SYSTEM
        else:
            return ErrorCategory.ARBITRARY

    @staticmethod
    def _determine_severity(error: Exception) -> ErrorSeverity:
        """Определение серьезности по типу ошибки"""
        error_type = type(error).__name__.lower()
        critical_types = ["criticalerror", "fatalerror", "systemexit"]
        error_types = ["valueerror", "typeerror", "attributeerror", "keyerror", "indexerror", "runtimeerror"]

        if any(t in error_type for t in critical_types):
            return ErrorSeverity.CRITICAL
        elif any(t in error_type for t in error_types):
            return ErrorSeverity.ERROR
        else:
            return ErrorSeverity.ERROR

    @staticmethod
    def _get_traceback(error: Exception) -> str | None:
        """Получение traceback ошибки"""
        import traceback

        try:
            tb_lines = traceback.format_exception(type(error), error, error.__traceback__)
            return "".join(tb_lines)[:1000]
        except Exception:
            return None

    @staticmethod
    def _format_details(error: Exception, component: str, context: dict[str, Any] | None) -> str | None:
        """Форматирование деталей ошибки"""
        details = [f"Component: {component}", f"Error type: {type(error).__name__}"]
        if context:
            details.append("Context:")
            details.extend(f"  {key}: {value}" for key, value in context.items())
        return "\n".join(details)

    @staticmethod
    def _create_group_hash(error_code: str, error_message: str, source: str) -> str:
        """Создание хеша для группировки ошибок"""
        import hashlib

        content = f"{error_code}|{source}|{error_message[:100]}"
        return hashlib.md5(content.encode()).hexdigest()[:16]

    # ============ МЕТОДЫ ДЛЯ РАБОТЫ С ОШИБКАМИ ============

    @log_exceptions(app_logger)
    async def check_and_resolve_error(
        self, error_id: int, resolved_by: int, session: AsyncSession | None = None, check_procedure: str | None = None
    ) -> tuple[bool, str | None]:
        """Проверка и решение ошибки"""
        if session is None:
            async with db_manager.get_session() as sess:
                return await self.check_and_resolve_error(error_id, resolved_by, sess, check_procedure)

        stmt = select(ErrorModel).where(error_id == ErrorModel.FID)
        result = await session.execute(stmt)
        error: ErrorModel | None = result.scalar_one_or_none()

        if not error:
            return False, "Error not found"

        if error.FStatus == ErrorStatus.RESOLVED:
            return False, "Error already resolved"

        if check_procedure:
            try:
                async with db_manager.get_session("avanpost") as mssql_session:
                    sql = f"EXEC {check_procedure} @ErrorCode = :error_code"
                    result = await mssql_session.execute(sql, {"error_code": error.FErrorCode})
                    rows = result.fetchall()
                    if rows and len(rows) > 0:
                        return False, "Error still exists in external system"
            except Exception as e:
                app_logger.error(f"Failed to check error via procedure: {e}")
                return False, f"Check failed: {str(e)}"

        error.FStatus = ErrorStatus.RESOLVED
        error.FResolvedBy = resolved_by
        error.FResolvedAt = datetime_now()

        await session.commit()
        return True, "Error resolved successfully"

    @log_exceptions(app_logger)
    async def reopen_error(self, error_id: int, session: AsyncSession | None = None) -> tuple[bool, str | None]:
        """Переоткрытие ошибки"""
        if session is None:
            async with db_manager.get_session() as sess:
                return await self.reopen_error(error_id, sess)

        stmt = select(ErrorModel).where(error_id == ErrorModel.FID)
        result = await session.execute(stmt)
        error: ErrorModel | None = result.scalar_one_or_none()

        if not error:
            return False, "Error not found"

        if error.FStatus != ErrorStatus.RESOLVED:
            return False, "Error is not resolved"

        error.FStatus = ErrorStatus.REOPENED
        error.FReopenedCount += 1
        error.FReopenedAt = datetime_now()
        error.FResolvedBy = None
        error.FResolvedAt = None

        await session.commit()
        return True, "Error reopened"

    @log_exceptions(app_logger)
    async def get_error_stats(
        self,
        start_date: datetime | None = None,
        end_date: datetime | None = None,
        category: Any | None = None,
        session: AsyncSession | None = None,
    ) -> dict[str, Any]:
        """Получение статистики ошибок"""
        if session is None:
            async with db_manager.get_session() as sess:
                return await self.get_error_stats(start_date, end_date, category, sess)

        category_enum = self._validate_category(category) if category is not None else None

        if not start_date:
            start_date = datetime_now() - timedelta(days=7)
        if not end_date:
            end_date = datetime_now()

        stmt = select(
            func.count(ErrorModel.FID).label("total"),
            func.sum(ErrorModel.FCountOccurrences).label("total_occurrences"),
            func.count(ErrorModel.FID).filter(ErrorModel.FStatus == ErrorStatus.NEW).label("new"),
            func.count(ErrorModel.FID).filter(ErrorModel.FStatus == ErrorStatus.RESOLVED).label("resolved"),
        ).where(ErrorModel.FCreatedAt >= start_date, ErrorModel.FCreatedAt <= end_date)

        if category_enum is not None:
            stmt = stmt.where(ErrorModel.FCategory == category_enum)

        result = await session.execute(stmt)
        stats = result.first()

        return {
            "total": stats.total or 0,
            "total_occurrences": stats.total_occurrences or 0,
            "new": stats.new or 0,
            "resolved": stats.resolved or 0,
            "resolution_rate": (stats.resolved / stats.total * 100) if stats.total else 0,
            "period": {"start": start_date.isoformat(), "end": end_date.isoformat()},
        }

    @log_exceptions(app_logger)
    async def get_user_stats(self, user_id: int, session: AsyncSession | None = None) -> dict[str, Any]:
        """Получение статистики пользователя по решению ошибок"""
        if session is None:
            async with db_manager.get_session() as sess:
                return await self.get_user_stats(user_id, sess)

        total_stmt = select(
            func.count(ErrorModel.FID).label("total"),
            func.count(ErrorModel.FID).filter(ErrorModel.FStatus == ErrorStatus.RESOLVED).label("resolved"),
        ).where(ErrorModel.FResolvedBy == user_id)

        total_result = await session.execute(total_stmt)
        total_stats = total_result.first()

        return {
            "user_id": user_id,
            "total_solved": total_stats.resolved or 0,
            "total_errors": total_stats.total or 0,
            "success_rate": (total_stats.resolved / total_stats.total * 100) if total_stats.total else 0,
        }


error_service = ErrorService()
