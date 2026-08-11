from datetime import datetime
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from ..db import db_manager
from ..db.repositories import ErrorRepository
from ..exceptions import log_exceptions
from ..logger import app_logger
from ..models import (
    ChatMessageModel,
    ErrorCategory,
    ErrorModel,
    ErrorSeverity,
    ErrorStatus,
    MessageType,
    datetime_now,
)


class ErrorService:
    """
    Сервис для управления ошибками.

    Предоставляет методы для:
    - Логирования ошибок из разных источников
    - Управления внешними ошибками
    - Решения и переоткрытия ошибок
    - Получения статистики
    - Удаления сообщений, связанных с ошибками
    """

    def __init__(self) -> None:
        """Инициализация сервиса ошибок"""
        self._group_cache: dict[str, dict] = {}
        from ..config import settings

        self._cache_ttl = getattr(settings, "ERROR_GROUP_CACHE_TTL_SECONDS", 300)

    @log_exceptions(app_logger)
    async def log_error(
        self,
        error: Exception,
        session: AsyncSession | None = None,
        *,
        component: str = "app",
        user_id: int | None = None,
        chat_id: int | None = None,
        message_id: int | None = None,
        category: Any | None = None,
        severity: Any | None = None,
        context: dict[str, Any] | None = None,
    ) -> tuple[ErrorModel | None, ChatMessageModel | None]:
        """
        Логирование ошибки из любого компонента приложения.

        Args:
            error: Исключение
            session: Сессия БД (опционально, будет создана автоматически)
            component: Компонент, в котором произошла ошибка
            user_id: ID пользователя
            chat_id: ID чата
            message_id: ID сообщения
            category: Категория ошибки
            severity: Степень серьезности
            context: Дополнительный контекст

        Returns:
            tuple[ErrorModel | None, ChatMessageModel | None]: Созданные модель ошибки и сообщение
        """
        if session is None:
            async with db_manager.get_session() as new_session:
                return await self._log_error_impl(
                    error=error,
                    session=new_session,
                    component=component,
                    user_id=user_id,
                    chat_id=chat_id,
                    message_id=message_id,
                    category=category,
                    severity=severity,
                    context=context,
                )
        else:
            return await self._log_error_impl(
                error=error,
                session=session,
                component=component,
                user_id=user_id,
                chat_id=chat_id,
                message_id=message_id,
                category=category,
                severity=severity,
                context=context,
            )

    async def _log_error_impl(
        self,
        error: Exception,
        session: AsyncSession,
        *,
        component: str = "app",
        user_id: int | None = None,
        chat_id: int | None = None,
        message_id: int | None = None,
        category: Any | None = None,
        severity: Any | None = None,
        context: dict[str, Any] | None = None,
    ) -> tuple[ErrorModel | None, ChatMessageModel | None]:
        """
        Реализация логирования ошибки.

        Args:
            error: Исключение
            session: Сессия БД
            component: Компонент, в котором произошла ошибка
            user_id: ID пользователя
            chat_id: ID чата
            message_id: ID сообщения
            category: Категория ошибки
            severity: Степень серьезности
            context: Дополнительный контекст

        Returns:
            tuple[ErrorModel | None, ChatMessageModel | None]: Созданные модель ошибки и сообщение
        """
        category_enum = self._validate_category(category)
        severity_enum = self._validate_severity(severity)

        error_type = type(error).__name__
        error_message = str(error) or error_type
        error_code = error_type[:50]

        details = self._format_details(error, component, context)
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
        if chat_id and await ErrorRepository.chat_exists(session, chat_id):
            chat_message = await ErrorRepository.save_message(
                session=session,
                chat_id=chat_id,
                error_type=error_type,
                error_message=error_message,
                user_id=user_id,
                message_id=message_id,
                traceback_text=traceback_text,
                category=category_enum,
                error_id=error_model.FID if error_model else None,
                component=component,
            )

        if error_model and chat_message:
            await ErrorRepository.link_message(
                session=session,
                error_id=error_model.FID,
                message_id=chat_message.FID,
            )

        await session.commit()

        return error_model, chat_message

    @log_exceptions(app_logger)
    async def log_external_error(
        self,
        error_code: str,
        error_message: str,
        source_system: str,
        session: AsyncSession | None = None,
        *,
        user_id: int | None = None,
        user_login: str | None = None,
        category: Any | None = None,
        severity: Any | None = None,
        details: str | None = None,
        source_module: str | None = None,
        chat_ids: list[int] | None = None,
        send_to_telegram: bool = True,
    ) -> ErrorModel:
        """
        Логирование внешней ошибки из другой системы с отправкой в несколько чатов.

        Args:
            error_code: Код ошибки
            error_message: Сообщение об ошибке
            source_system: Система-источник
            session: Сессия БД (опционально, будет создана автоматически)
            user_id: ID пользователя
            user_login: Логин пользователя
            category: Категория ошибки
            severity: Степень серьезности
            details: Детали ошибки
            source_module: Модуль-источник
            chat_ids: Список ID чатов для отправки
            send_to_telegram: Отправлять ли в Telegram

        Returns:
            ErrorModel: Созданная или обновленная ошибка
        """
        if session is None:
            async with db_manager.get_session() as new_session:
                return await self._log_external_error_impl(
                    error_code=error_code,
                    error_message=error_message,
                    source_system=source_system,
                    session=new_session,
                    user_id=user_id,
                    user_login=user_login,
                    category=category,
                    severity=severity,
                    details=details,
                    source_module=source_module,
                    chat_ids=chat_ids,
                    send_to_telegram=send_to_telegram,
                )
        else:
            return await self._log_external_error_impl(
                error_code=error_code,
                error_message=error_message,
                source_system=source_system,
                session=session,
                user_id=user_id,
                user_login=user_login,
                category=category,
                severity=severity,
                details=details,
                source_module=source_module,
                chat_ids=chat_ids,
                send_to_telegram=send_to_telegram,
            )

    async def _log_external_error_impl(
        self,
        error_code: str,
        error_message: str,
        source_system: str,
        session: AsyncSession,
        *,
        user_id: int | None = None,
        user_login: str | None = None,
        category: Any | None = None,
        severity: Any | None = None,
        details: str | None = None,
        source_module: str | None = None,
        chat_ids: list[int] | None = None,
        send_to_telegram: bool = True,
    ) -> ErrorModel:
        """
        Реализация логирования внешней ошибки.

        Args:
            error_code: Код ошибки
            error_message: Сообщение об ошибке
            source_system: Система-источник
            session: Сессия БД
            user_id: ID пользователя
            user_login: Логин пользователя
            category: Категория ошибки
            severity: Степень серьезности
            details: Детали ошибки
            source_module: Модуль-источник
            chat_ids: Список ID чатов для отправки
            send_to_telegram: Отправлять ли в Telegram

        Returns:
            ErrorModel: Созданная или обновленная ошибка
        """
        category_enum = self._validate_category(category)
        severity_enum = self._validate_severity(severity)

        group_hash = ErrorRepository.create_group_hash(error_code, error_message, source_system)

        # Поиск существующей ошибки
        existing = await ErrorRepository.find_existing_error(
            session=session,
            group_hash=group_hash,
        )

        if existing:
            # Очистка старых сообщений перед обновлением
            await self._cleanup_old_messages(session, existing)

            # Обновление существующей ошибки
            updated_error = await ErrorRepository.increment_occurrences(
                session=session,
                error_id=existing.FID,
                details=details,
            )

            if updated_error is None:
                app_logger.error(f"Failed to update error {existing.FID}, creating new one")
                error = await ErrorRepository.create_error(
                    session=session,
                    error_code=error_code,
                    error_message=error_message,
                    source_system=source_system,
                    source_module=source_module,
                    category=category_enum,
                    severity=severity_enum,
                    user_id=user_id,
                    user_login=user_login,
                    details=details,
                    group_hash=group_hash,
                )
                await session.commit()
                await session.refresh(error)

                # Отправка уведомления через LogHandlerService
                if send_to_telegram:
                    from ..services.log_handler_service import log_handler_service

                    await log_handler_service.send_notification(error)

                return error

            existing = updated_error

            # Отправка в указанные чаты (если есть)
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

                    if message_id:
                        await ErrorRepository.link_message(
                            session=session,
                            error_id=existing.FID,
                            message_id=message_id,
                        )

            await session.commit()
            await session.refresh(existing)

            # Отправка уведомления через LogHandlerService (для всех случаев, если send_to_telegram=True)
            if send_to_telegram:
                from ..services.log_handler_service import log_handler_service

                await log_handler_service.send_notification(existing)

            return existing

        # Создание новой ошибки
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

        error = await ErrorRepository.create_error(
            session=session,
            error_code=error_code,
            error_message=error_message,
            source_system=source_system,
            source_module=source_module,
            category=category_enum,
            severity=severity_enum,
            user_id=user_id,
            user_login=user_login,
            details=details,
            group_hash=group_hash,
        )

        for sent in sent_messages:
            await ErrorRepository.link_message(
                session=session,
                error_id=error.FID,
                message_id=sent["message_id"],
            )

        await session.commit()
        await session.refresh(error)

        app_logger.info(
            f"✅ External error saved: ID={error.FID}, Code={error.FErrorCode}, Sent to {len(sent_messages)} chats"
        )

        if send_to_telegram:
            from ..services.log_handler_service import log_handler_service

            await log_handler_service.send_notification(error)

        return error

    @log_exceptions(app_logger)
    async def check_and_resolve_error(
        self,
        error_id: int,
        resolved_by: int,
        session: AsyncSession | None = None,
        check_procedure: str | None = None,
    ) -> tuple[bool, str | None]:
        """
        Проверка и решение ошибки.

        Args:
            error_id: ID ошибки
            resolved_by: ID пользователя, решающего ошибку
            session: Сессия БД (опционально, будет создана автоматически)
            check_procedure: Имя хранимой процедуры для проверки

        Returns:
            tuple[bool, str | None]: (успех, сообщение)
        """
        if session is None:
            async with db_manager.get_session() as new_session:
                return await self._check_and_resolve_error_impl(
                    error_id=error_id,
                    resolved_by=resolved_by,
                    session=new_session,
                    check_procedure=check_procedure,
                )
        else:
            return await self._check_and_resolve_error_impl(
                error_id=error_id,
                resolved_by=resolved_by,
                session=session,
                check_procedure=check_procedure,
            )

    @staticmethod
    async def _check_and_resolve_error_impl(
        error_id: int,
        resolved_by: int,
        session: AsyncSession,
        check_procedure: str | None = None,
    ) -> tuple[bool, str | None]:
        """
        Реализация проверки и решения ошибки.

        Args:
            error_id: ID ошибки
            resolved_by: ID пользователя, решающего ошибку
            session: Сессия БД
            check_procedure: Имя хранимой процедуры для проверки

        Returns:
            tuple[bool, str | None]: (успех, сообщение)
        """
        error = await ErrorRepository.get_error_by_id(session, error_id)

        if not error:
            return False, "Error not found"

        if error.FStatus == ErrorStatus.RESOLVED:
            return False, "Error already resolved"

        if check_procedure:
            try:
                from ..db.repositories import AvanpostRepository

                async with db_manager.get_session("avanpost") as mssql_session:
                    exists = await AvanpostRepository.check_error_exists_by_procedure(
                        session=mssql_session,
                        error_code=error.FErrorCode,
                        check_procedure=check_procedure,
                    )

                    if exists:
                        return False, "Error still exists in external system"

            except Exception as e:
                app_logger.error(f"Failed to check error via procedure: {e}")
                return False, f"Check failed: {str(e)}"

        return await ErrorRepository.resolve_error(
            session=session,
            error_id=error_id,
            resolved_by=resolved_by,
        )

    @log_exceptions(app_logger)
    async def reopen_error(
        self,
        error_id: int,
        session: AsyncSession | None = None,
    ) -> tuple[bool, str | None]:
        """
        Переоткрытие ранее решенной ошибки.

        Args:
            error_id: ID ошибки
            session: Сессия БД (опционально, будет создана автоматически)

        Returns:
            tuple[bool, str | None]: (успех, сообщение)
        """
        if session is None:
            async with db_manager.get_session() as new_session:
                return await ErrorRepository.reopen_error(session=new_session, error_id=error_id)
        else:
            return await ErrorRepository.reopen_error(session=session, error_id=error_id)

    @log_exceptions(app_logger)
    async def delete_error_messages(
        self,
        error_id: int,
        session: AsyncSession | None = None,
        delete_from_telegram: bool = True,
    ) -> dict[str, Any]:
        """
        Удаление всех сообщений, связанных с ошибкой.

        Args:
            error_id: ID ошибки
            session: Сессия БД (опционально, будет создана автоматически)
            delete_from_telegram: Удалять ли сообщения из Telegram

        Returns:
            dict: Результат операции
        """
        if session is None:
            async with db_manager.get_session() as new_session:
                return await self._delete_error_messages_impl(
                    error_id=error_id,
                    session=new_session,
                    delete_from_telegram=delete_from_telegram,
                )
        else:
            return await self._delete_error_messages_impl(
                error_id=error_id,
                session=session,
                delete_from_telegram=delete_from_telegram,
            )

    async def _delete_error_messages_impl(
        self,
        error_id: int,
        session: AsyncSession,
        delete_from_telegram: bool = True,
    ) -> dict[str, Any]:
        """
        Реализация удаления всех сообщений, связанных с ошибкой.

        Args:
            error_id: ID ошибки
            session: Сессия БД
            delete_from_telegram: Удалять ли сообщения из Telegram

        Returns:
            dict: Результат операции
        """
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
            error = await ErrorRepository.get_error_by_id(session, error_id)
            if not error:
                result["errors"].append(f"Error {error_id} not found")
                app_logger.warning(f"⚠️ Error {error_id} not found")
                return result

            messages = await ErrorRepository.get_linked_messages(session, error_id)

            if not messages:
                app_logger.info(f"ℹ️ No messages linked to error {error_id}")
                result["success"] = True
                result["messages_found"] = 0
                return result

            result["messages_found"] = len(messages)

            if delete_from_telegram:
                telethon_deleted = await self._delete_messages_from_telegram(messages)
                result["messages_deleted_telegram"] = telethon_deleted

            db_deleted = 0
            for message in messages:
                if not message.FFlagDeleted:
                    message.FFlagDeleted = True
                    message.FDateDeleted = datetime_now()
                    message.FDeletedByType = "error_cleanup"
                    message.FK_DeletedByMessage = None
                    db_deleted += 1

            result["messages_deleted_db"] = db_deleted

            links_deleted = await ErrorRepository.unlink_all_messages(session, error_id)
            result["links_deleted"] = links_deleted

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

    @log_exceptions(app_logger)
    async def get_error_stats(
        self,
        session: AsyncSession | None = None,
        start_date: datetime | None = None,
        end_date: datetime | None = None,
        category: Any | None = None,
    ) -> dict[str, Any]:
        """
        Получение статистики ошибок.

        Args:
            session: Сессия БД (опционально, будет создана автоматически)
            start_date: Начальная дата
            end_date: Конечная дата
            category: Категория ошибки

        Returns:
            dict: Статистика
        """
        category_enum = self._validate_category(category) if category is not None else None

        if session is None:
            async with db_manager.get_session() as new_session:
                return await ErrorRepository.get_stats(
                    session=new_session,
                    start_date=start_date,
                    end_date=end_date,
                    category=category_enum,
                )
        else:
            return await ErrorRepository.get_stats(
                session=session,
                start_date=start_date,
                end_date=end_date,
                category=category_enum,
            )

    @log_exceptions(app_logger)
    async def get_user_stats(
        self,
        user_id: int,
        session: AsyncSession | None = None,
    ) -> dict[str, Any]:
        """
        Получение статистики пользователя по решению ошибок.

        Args:
            user_id: ID пользователя
            session: Сессия БД (опционально, будет создана автоматически)

        Returns:
            dict: Статистика пользователя
        """
        if session is None:
            async with db_manager.get_session() as new_session:
                return await ErrorRepository.get_user_stats(
                    session=new_session,
                    user_id=user_id,
                )
        else:
            return await ErrorRepository.get_user_stats(
                session=session,
                user_id=user_id,
            )

    @staticmethod
    def _validate_category(category: Any | None) -> ErrorCategory:
        """
        Валидация категории ошибки.

        Args:
            category: Категория для валидации

        Returns:
            ErrorCategory: Валидная категория
        """
        if category is None:
            return ErrorCategory.ARBITRARY
        if isinstance(category, ErrorCategory):
            return category
        if isinstance(category, str):
            try:
                return ErrorCategory(category)
            except ValueError:
                app_logger.warning(f"⚠️ Unknown error category: {category}, using ARBITRARY")
                return ErrorCategory.ARBITRARY
        return ErrorCategory.ARBITRARY

    @staticmethod
    def _validate_severity(severity: Any | None) -> ErrorSeverity:
        """
        Валидация серьезности ошибки.

        Args:
            severity: Серьезность для валидации

        Returns:
            ErrorSeverity: Валидная серьезность
        """
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

    @staticmethod
    def _determine_category(component: str) -> ErrorCategory:
        """
        Определение категории по компоненту.

        Args:
            component: Название компонента

        Returns:
            ErrorCategory: Категория ошибки
        """
        component_lower = component.lower()
        if "api" in component_lower or "tg" in component_lower or "telegram" in component_lower:
            return ErrorCategory.TASK_EXECUTION
        elif "db" in component_lower or "database" in component_lower:
            return ErrorCategory.SYSTEM
        else:
            return ErrorCategory.ARBITRARY

    @staticmethod
    def _determine_severity(error: Exception) -> ErrorSeverity:
        """
        Определение серьезности по типу ошибки.

        Args:
            error: Исключение

        Returns:
            ErrorSeverity: Степень серьезности
        """
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
        """
        Получение traceback ошибки.

        Args:
            error: Исключение

        Returns:
            str | None: Текст traceback
        """
        import traceback

        try:
            tb_lines = traceback.format_exception(type(error), error, error.__traceback__)
            return "".join(tb_lines)[:1000]
        except Exception:
            return None

    @staticmethod
    def _format_details(error: Exception, component: str, context: dict[str, Any] | None) -> str | None:
        """
        Форматирование деталей ошибки.

        Args:
            error: Исключение
            component: Компонент
            context: Дополнительный контекст

        Returns:
            str | None: Отформатированные детали
        """
        details = [f"Component: {component}", f"Error type: {type(error).__name__}"]
        if context:
            details.append("Context:")
            details.extend(f"  {key}: {value}" for key, value in context.items())
        return "\n".join(details)

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
        """
        Форматирование сообщения для внешней ошибки.

        Args:
            error_code: Код ошибки
            error_message: Сообщение об ошибке
            source_system: Система-источник
            source_module: Модуль-источник
            user_id: ID пользователя
            user_login: Логин пользователя
            details: Детали ошибки
            is_repeat: Является ли повторением
            repeat_count: Количество повторений

        Returns:
            str: Отформатированное сообщение
        """
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

    async def _cleanup_old_messages(self, session: AsyncSession, error: ErrorModel) -> None:
        """
        Очистка старых сообщений, связанных с ошибкой.

        Args:
            session: Сессия БД
            error: Модель ошибки
        """
        app_logger.info(f"🧹 Cleaning up old messages for existing error {error.FID}")

        try:
            messages = await ErrorRepository.get_linked_messages(session, error.FID)

            if messages:
                app_logger.info(f"📊 Found {len(messages)} old messages for error {error.FID}")

                deleted_from_telegram = await self._delete_messages_from_telegram(messages)
                if deleted_from_telegram > 0:
                    app_logger.info(f"✅ Deleted {deleted_from_telegram} old messages from Telegram")

                db_deleted = 0
                for message in messages:
                    if not message.FFlagDeleted:
                        message.FFlagDeleted = True
                        message.FDateDeleted = datetime_now()
                        message.FDeletedByType = "error_repeat_cleanup"
                        message.FK_DeletedByMessage = None
                        db_deleted += 1

                links_deleted = await ErrorRepository.unlink_all_messages(session, error.FID)

                app_logger.info(
                    f"✅ Cleanup complete for error {error.FID}: "
                    f"telegram_deleted={deleted_from_telegram}, "
                    f"db_deleted={db_deleted}, "
                    f"links_deleted={links_deleted}"
                )
            else:
                app_logger.debug(f"ℹ️ No old messages to clean up for error {error.FID}")

        except Exception as e:
            app_logger.error(f"❌ Failed to cleanup old messages for error {error.FID}: {e}")

    @staticmethod
    async def _delete_messages_from_telegram(messages: list[ChatMessageModel]) -> int:
        """
        Удаление сообщений из Telegram.

        Args:
            messages: Список сообщений

        Returns:
            int: Количество удаленных сообщений
        """
        deleted = 0
        try:
            from ..tg import tg_manager

            status = await tg_manager.get_status()

            if status.get("is_running", False):
                for message in messages:
                    try:
                        delete_result = await tg_manager.delete_message_by_id(
                            chat_id=message.FK_Chat,
                            message_id=message.FID,
                        )
                        if delete_result.get("success"):
                            deleted += 1
                            app_logger.debug(f"✅ Deleted message {message.FID} from Telegram")
                        else:
                            app_logger.debug(f"⚠️ Failed to delete message {message.FID}: {delete_result.get('error')}")
                    except Exception as e:
                        app_logger.warning(f"⚠️ Error deleting message {message.FID}: {e}")

                if deleted > 0:
                    app_logger.info(f"✅ Deleted {deleted} messages from Telegram")
            else:
                app_logger.warning("⚠️ Telegram manager not running, skipping Telegram deletion")

        except Exception as e:
            app_logger.warning(f"⚠️ Failed to delete messages from Telegram: {e}")

        return deleted

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
        lifetime_seconds: int | None = None,
    ) -> int | None:
        """
        Отправка сообщения об ошибке в Telegram.

        Args:
            chat_id: ID чата
            error_code: Код ошибки
            error_message: Сообщение об ошибке
            source_system: Система-источник
            source_module: Модуль-источник
            user_id: ID пользователя
            user_login: Логин пользователя
            details: Детали ошибки
            is_repeat: Является ли повторением
            repeat_count: Количество повторений
            lifetime_seconds: Срок жизни

        Returns:
            int | None: ID отправленного сообщения или None
        """
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
                lifetime_seconds=lifetime_seconds,
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
    async def _save_to_errors(
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
        """
        Сохранение ошибки в TErrors.

        Args:
            session: Сессия БД
            error_code: Код ошибки
            error_message: Сообщение об ошибке
            error_type: Тип ошибки
            details: Детали ошибки
            traceback_text: Текст traceback
            category: Категория ошибки
            severity: Степень серьезности
            user_id: ID пользователя
            component: Компонент
            context: Дополнительный контекст

        Returns:
            ErrorModel | None: Созданная или обновленная ошибка
        """
        try:
            group_hash = ErrorRepository.create_group_hash(error_code, error_message, component)

            existing = await ErrorRepository.find_existing_error(
                session=session,
                group_hash=group_hash,
            )

            if existing:
                return await ErrorRepository.increment_occurrences(
                    session=session,
                    error_id=existing.FID,
                    details=details,
                )

            return await ErrorRepository.create_error(
                session=session,
                error_code=error_code,
                error_message=error_message,
                source_system="TeamBot",
                source_module=component,
                category=category,
                severity=severity,
                user_id=user_id,
                details=details,
                group_hash=group_hash,
            )

        except Exception as e:
            app_logger.error(f"Failed to save to TErrors: {e}")
            return None


error_service = ErrorService()

__all__ = [
    "ErrorService",
    "error_service",
]
