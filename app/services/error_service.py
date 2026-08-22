"""
Сервис управления ошибками.

Отвечает за:
1. Логирование ошибок из разных компонентов приложения
2. Управление внешними ошибками из других систем
3. Решение и переоткрытие ошибок
4. Получение статистики по ошибкам
5. Удаление сообщений, связанных с ошибками
6. Отправку уведомлений об ошибках в Telegram
7. Группировку и дедупликацию ошибок
"""

from datetime import datetime
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from ..db import db_manager
from ..db.repositories import AvanpostRepository, ErrorRepository, MessageRepository
from ..dtos.error import CreateErrorDTO, ErrorNotificationDTO
from ..logger import app_logger
from ..models import (
    ChatMessageModel,
    ErrorCategory,
    ErrorModel,
    ErrorSeverity,
    ErrorStatus,
    MessageType,
)
from ..utils.decorators import log_exceptions

# ============================================================
# РЕПОЗИТОРИИ (СИНГЛТОНЫ)
# ============================================================

# Репозитории создаются один раз на уровне модуля для переиспользования
_error_repo = ErrorRepository()  # Репозиторий для работы с ошибками
_message_repo = MessageRepository()  # Репозиторий для работы с сообщениями
_avanpost_repo = AvanpostRepository()  # Репозиторий для работы с Avanpost


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
        """
        Инициализация сервиса ошибок.

        Создает кеш для группировки ошибок с настраиваемым TTL.
        """
        self._group_cache: dict[str, dict] = {}
        from ..config import settings

        self._cache_ttl = getattr(settings, "ERROR_GROUP_CACHE_TTL_SECONDS", 300)

    # ============================================================
    # ВСПОМОГАТЕЛЬНЫЕ МЕТОДЫ
    # ============================================================

    @staticmethod
    def _to_str_with_value(value: Any | None, default: str) -> str:
        """
        Безопасное преобразование значения с атрибутом value в строку.

        Args:
            value: Значение для преобразования
            default: Значение по умолчанию

        Returns:
            str: Строковое представление значения
        """
        if value is None:
            return default
        if hasattr(value, "value"):
            val = value.value
            if val is None:
                return default
            return str(val)
        return str(value)

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
            component: Имя компонента

        Returns:
            ErrorCategory: Определенная категория
        """
        component_lower = component.lower()
        if "api" in component_lower or "bot" in component_lower:
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
            ErrorSeverity: Определенная серьезность
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
            str | None: Текст traceback или None
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
            context: Контекст ошибки

        Returns:
            str | None: Отформатированные детали
        """
        details = [f"Component: {component}", f"Error type: {type(error).__name__}"]
        if context:
            details.append("Context:")
            details.extend(f"  {key}: {value}" for key, value in context.items())
        return "\n".join(details)

    # ============================================================
    # ЛОГИРОВАНИЕ ОШИБОК
    # ============================================================

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
            session: Сессия БД (опционально)
            component: Компонент, в котором произошла ошибка
            user_id: ID пользователя (опционально)
            chat_id: ID чата (опционально)
            message_id: ID сообщения (опционально)
            category: Категория ошибки (опционально)
            severity: Серьезность ошибки (опционально)
            context: Дополнительный контекст

        Returns:
            tuple[ErrorModel | None, ChatMessageModel | None]: (модель ошибки, модель сообщения)
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
            component: Компонент
            user_id: ID пользователя
            chat_id: ID чата
            message_id: ID сообщения
            category: Категория
            severity: Серьезность
            context: Контекст

        Returns:
            tuple[ErrorModel | None, ChatMessageModel | None]: (модель ошибки, модель сообщения)
        """
        category_enum = self._validate_category(category)
        severity_enum = self._validate_severity(severity)

        # Подготовка данных ошибки
        error_type = type(error).__name__
        error_message = str(error) or error_type
        error_code = error_type[:50]

        details = self._format_details(error, component, context)
        traceback_text = self._get_traceback(error)

        # Создание ошибки в БД
        error_model = await _error_repo.create_error(
            session=session,
            error_code=error_code,
            error_message=error_message,
            source_system="TeamBot",
            source_module=component,
            category=category_enum,
            severity=severity_enum,
            user_id=user_id,
            details=details,
            group_hash=_error_repo.create_group_hash(error_code, error_message, component),
        )

        # Сохранение сообщения в чате (если указан chat_id)
        chat_message = None
        if chat_id and await _error_repo.chat_exists(session, chat_id):
            chat_message = await _error_repo.save_message(
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

        # Связывание ошибки с сообщением
        if error_model and chat_message:
            await _error_repo.link_message(
                session=session,
                error_id=error_model.FID,
                message_id=chat_message.FID,
            )

        await session.commit()

        return error_model, chat_message

    # ============================================================
    # ЛОГИРОВАНИЕ ВНЕШНИХ ОШИБОК
    # ============================================================

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
        Логирование внешней ошибки из другой системы.

        Args:
            error_code: Код ошибки
            error_message: Сообщение об ошибке
            source_system: Система-источник
            session: Сессия БД (опционально)
            user_id: ID пользователя (опционально)
            user_login: Логин пользователя (опционально)
            category: Категория ошибки (опционально)
            severity: Серьезность ошибки (опционально)
            details: Детали ошибки (опционально)
            source_module: Модуль-источник (опционально)
            chat_ids: Список ID чатов для отправки уведомлений (опционально)
            send_to_telegram: Отправлять ли уведомление в Telegram

        Returns:
            ErrorModel: Созданная или обновленная модель ошибки
        """
        category_str = self._to_str_with_value(category, "external")
        severity_str = self._to_str_with_value(severity, "error")

        if session is None:
            async with db_manager.get_session() as new_session:
                return await self._log_external_error_impl(
                    create_dto=CreateErrorDTO(
                        error_code=error_code,
                        error_message=error_message,
                        source_system=source_system,
                        source_module=source_module,
                        category=category_str,
                        severity=severity_str,
                        user_id=user_id,
                        user_login=user_login,
                        details=details,
                        chat_ids=chat_ids,
                        send_to_telegram=send_to_telegram,
                    ),
                    session=new_session,
                )
        else:
            return await self._log_external_error_impl(
                create_dto=CreateErrorDTO(
                    error_code=error_code,
                    error_message=error_message,
                    source_system=source_system,
                    source_module=source_module,
                    category=category_str,
                    severity=severity_str,
                    user_id=user_id,
                    user_login=user_login,
                    details=details,
                    chat_ids=chat_ids,
                    send_to_telegram=send_to_telegram,
                ),
                session=session,
            )

    async def _log_external_error_impl(
        self,
        create_dto: CreateErrorDTO,
        session: AsyncSession,
    ) -> ErrorModel:
        """
        Реализация логирования внешней ошибки.

        Args:
            create_dto: DTO для создания ошибки
            session: Сессия БД

        Returns:
            ErrorModel: Созданная или обновленная модель ошибки
        """
        category_enum = self._validate_category(create_dto.category)
        severity_enum = self._validate_severity(create_dto.severity)

        # Создание хеша для группировки
        group_hash = _error_repo.create_group_hash(
            create_dto.error_code,
            create_dto.error_message,
            create_dto.source_system,
        )

        # Поиск существующей ошибки через репозиторий
        existing = await _error_repo.find_existing_error(
            session=session,
            group_hash=group_hash,
        )

        if existing:
            # Очистка старых сообщений
            await self._cleanup_old_messages(session, existing)

            # Обновление существующей ошибки через репозиторий
            updated_error = await _error_repo.increment_occurrences(
                session=session,
                error_id=existing.FID,
                details=create_dto.details,
            )

            if updated_error is None:
                app_logger.error(f"Failed to update error {existing.FID}, creating new one")
                error = await _error_repo.create_error(
                    session=session,
                    error_code=create_dto.error_code,
                    error_message=create_dto.error_message,
                    source_system=create_dto.source_system,
                    source_module=create_dto.source_module,
                    category=category_enum,
                    severity=severity_enum,
                    user_id=create_dto.user_id,
                    user_login=create_dto.user_login,
                    details=create_dto.details,
                    group_hash=group_hash,
                )
                await session.commit()
                await session.refresh(error)

                if create_dto.send_to_telegram:
                    from ..services.log_handler_service import log_handler_service

                    await log_handler_service.send_notification(error)

                return error  # type: ignore[no-any-return]

            existing = updated_error

            # Отправка в указанные чаты
            if create_dto.chat_ids and create_dto.send_to_telegram:
                notification_dto = ErrorNotificationDTO.from_model(existing)
                for chat_id in create_dto.chat_ids:
                    message_id = await self._send_error_notification(
                        chat_id=chat_id,
                        notification_dto=notification_dto,
                        is_repeat=True,
                    )
                    if message_id:
                        await _error_repo.link_message(
                            session=session,
                            error_id=existing.FID,
                            message_id=message_id,
                        )

            await session.commit()
            await session.refresh(existing)

            if create_dto.send_to_telegram:
                from ..services.log_handler_service import log_handler_service

                await log_handler_service.send_notification(existing)

            # Явное приведение типа для mypy
            return existing  # type: ignore[no-any-return]

        # Создание новой ошибки через репозиторий
        error = await _error_repo.create_error(
            session=session,
            error_code=create_dto.error_code,
            error_message=create_dto.error_message,
            source_system=create_dto.source_system,
            source_module=create_dto.source_module,
            category=category_enum,
            severity=severity_enum,
            user_id=create_dto.user_id,
            user_login=create_dto.user_login,
            details=create_dto.details,
            group_hash=group_hash,
        )

        # Отправка в указанные чаты
        if create_dto.chat_ids and create_dto.send_to_telegram:
            notification_dto = ErrorNotificationDTO.from_model(error)
            for chat_id in create_dto.chat_ids:
                message_id = await self._send_error_notification(
                    chat_id=chat_id,
                    notification_dto=notification_dto,
                    is_repeat=False,
                )
                if message_id:
                    await _error_repo.link_message(
                        session=session,
                        error_id=error.FID,
                        message_id=message_id,
                    )

        await session.commit()
        await session.refresh(error)

        app_logger.info(
            f"✅ External error saved: ID={error.FID}, Code={error.FErrorCode}, "
            f"Sent to {len(create_dto.chat_ids or [])} chats"
        )

        if create_dto.send_to_telegram:
            from ..services.log_handler_service import log_handler_service

            await log_handler_service.send_notification(error)

        # Явное приведение типа для mypy
        return error  # type: ignore[no-any-return]

    # ============================================================
    # ОТПРАВКА УВЕДОМЛЕНИЙ
    # ============================================================

    @staticmethod
    async def _send_error_notification(
        chat_id: int,
        notification_dto: ErrorNotificationDTO,
        is_repeat: bool = False,
        lifetime_seconds: int | None = None,
    ) -> int | None:
        """
        Отправка уведомления об ошибке в Telegram.

        Args:
            chat_id: ID чата
            notification_dto: DTO для уведомления
            is_repeat: Является ли это повторным уведомлением
            lifetime_seconds: Время жизни сообщения

        Returns:
            int | None: ID отправленного сообщения или None
        """
        try:
            from ..bot.dependencies import get_bot_manager

            bot_manager = get_bot_manager()

            # Форматирование сообщения через DTO
            message = notification_dto.format_message()

            # Добавление пометки о повторе
            if is_repeat and notification_dto.count_occurrences > 1:
                message = f"🔄 **Повтор ошибки #{notification_dto.id}**\n" + message

            result = await bot_manager.send_message(
                chat_id=chat_id,
                message_type=MessageType.SYSTEM_ALERT,
                text=message,
                parse_mode="HTML",
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

    # ============================================================
    # УПРАВЛЕНИЕ ОШИБКАМИ
    # ============================================================

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
            session: Сессия БД (опционально)
            check_procedure: Хранимая процедура для проверки существования ошибки

        Returns:
            tuple[bool, str | None]: (успех, сообщение об ошибке)
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
            resolved_by: ID пользователя
            session: Сессия БД
            check_procedure: Хранимая процедура

        Returns:
            tuple[bool, str | None]: (успех, сообщение об ошибке)
        """
        error = await _error_repo.get_error_by_id(session, error_id)

        if not error:
            return False, "Error not found"

        if error.FStatus == ErrorStatus.RESOLVED:
            return False, "Error already resolved"

        if check_procedure:
            try:
                async with db_manager.get_session("avanpost") as mssql_session:
                    exists = await _avanpost_repo.check_error_exists_by_procedure(
                        session=mssql_session,
                        error_code=error.FErrorCode,
                        check_procedure=check_procedure,
                    )

                    if exists:
                        return False, "Error still exists in external system"

            except Exception as e:
                app_logger.error(f"Failed to check error via procedure: {e}")
                return False, f"Check failed: {str(e)}"

        # Решение ошибки через репозиторий
        return await _error_repo.resolve_error(  # type: ignore[no-any-return]
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
            session: Сессия БД (опционально)

        Returns:
            tuple[bool, str | None]: (успех, сообщение об ошибке)
        """
        if session is None:
            async with db_manager.get_session() as new_session:
                return await _error_repo.reopen_error(session=new_session, error_id=error_id)  # type: ignore[no-any-return]
        else:
            return await _error_repo.reopen_error(session=session, error_id=error_id)  # type: ignore[no-any-return]

    # ============================================================
    # УДАЛЕНИЕ СООБЩЕНИЙ ОШИБКИ
    # ============================================================

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
            session: Сессия БД (опционально)
            delete_from_telegram: Удалять ли сообщения из Telegram

        Returns:
            dict[str, Any]: Результат операции
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
            dict[str, Any]: Результат операции
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
            error = await _error_repo.get_error_by_id(session, error_id)
            if not error:
                result["errors"].append(f"Error {error_id} not found")
                app_logger.warning(f"⚠️ Error {error_id} not found")
                return result

            messages = await _error_repo.get_linked_messages(session, error_id)

            if not messages:
                app_logger.info(f"ℹ️ No messages linked to error {error_id}")
                result["success"] = True
                result["messages_found"] = 0
                return result

            result["messages_found"] = len(messages)

            # Удаление из Telegram
            if delete_from_telegram:
                telethon_deleted = await self._delete_messages_from_bot(messages)
                result["messages_deleted_telegram"] = telethon_deleted

            # Использование репозитория для массового удаления в БД
            message_ids = [msg.FID for msg in messages]
            db_deleted = await _message_repo.mark_messages_deleted_by_ids(
                session=session,
                message_ids=message_ids,
                deleted_by_type="error_cleanup",
            )
            result["messages_deleted_db"] = db_deleted

            # Удаление связей через репозиторий
            links_deleted = await _error_repo.unlink_all_messages(session, error_id)
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

    # ============================================================
    # СТАТИСТИКА
    # ============================================================

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
            session: Сессия БД (опционально)
            start_date: Начальная дата
            end_date: Конечная дата
            category: Категория ошибок

        Returns:
            dict[str, Any]: Статистика ошибок
        """
        category_enum = self._validate_category(category) if category is not None else None

        if session is None:
            async with db_manager.get_session() as new_session:
                return await _error_repo.get_stats(  # type: ignore[no-any-return]
                    session=new_session,
                    start_date=start_date,
                    end_date=end_date,
                    category=category_enum,
                )
        else:
            return await _error_repo.get_stats(  # type: ignore[no-any-return]
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
            session: Сессия БД (опционально)

        Returns:
            dict[str, Any]: Статистика пользователя
        """
        if session is None:
            async with db_manager.get_session() as new_session:
                return await _error_repo.get_user_stats(  # type: ignore[no-any-return]
                    session=new_session,
                    user_id=user_id,
                )
        else:
            return await _error_repo.get_user_stats(  # type: ignore[no-any-return]
                session=session,
                user_id=user_id,
            )

    # ============================================================
    # ОЧИСТКА СТАРЫХ СООБЩЕНИЙ
    # ============================================================

    async def _cleanup_old_messages(self, session: AsyncSession, error: ErrorModel) -> None:
        """
        Очистка старых сообщений, связанных с ошибкой.

        Args:
            session: Сессия БД
            error: Модель ошибки
        """
        app_logger.info(f"🧹 Cleaning up old messages for existing error {error.FID}")

        try:
            messages = await _error_repo.get_linked_messages(session, error.FID)

            if messages:
                app_logger.info(f"📊 Found {len(messages)} old messages for error {error.FID}")

                # Удаление из Telegram
                deleted_from_telegram = await self._delete_messages_from_bot(messages)
                if deleted_from_telegram > 0:
                    app_logger.info(f"✅ Deleted {deleted_from_telegram} old messages from Telegram")

                # Использование репозитория для массового удаления в БД
                message_ids = [msg.FID for msg in messages]
                db_deleted = await _message_repo.mark_messages_deleted_by_ids(
                    session=session,
                    message_ids=message_ids,
                    deleted_by_type="error_repeat_cleanup",
                )

                # Удаление связей через репозиторий
                links_deleted = await _error_repo.unlink_all_messages(session, error.FID)

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
    async def _delete_messages_from_bot(messages: list[ChatMessageModel]) -> int:
        """
        Удаление сообщений Bot-ом.

        Args:
            messages: Список сообщений для удаления

        Returns:
            int: Количество удаленных сообщений
        """
        deleted = 0
        try:
            from ..bot.dependencies import get_bot_manager

            bot_manager = get_bot_manager()
            status = await bot_manager.get_status()

            if status.get("is_running", False):
                for message in messages:
                    try:
                        delete_result = await bot_manager.delete_message_by_id(
                            chat_id=message.FK_Chat,
                            message_id=message.FID,
                        )
                        if delete_result.get("success"):
                            deleted += 1
                            app_logger.debug(f"✅ Deleted message {message.FID} by Bot")
                        else:
                            app_logger.debug(f"⚠️ Failed to delete message {message.FID}: {delete_result.get('error')}")
                    except Exception as e:
                        app_logger.warning(f"⚠️ Error deleting message {message.FID}: {e}")

                if deleted > 0:
                    app_logger.info(f"✅ Deleted {deleted} messages by Bot")
            else:
                app_logger.warning("⚠️ Bot manager not running, skipping Bot deletion")

        except Exception as e:
            app_logger.warning(f"⚠️ Failed to delete messages by Bot: {e}")

        return deleted


error_service = ErrorService()

__all__ = [
    "ErrorService",
    "error_service",
]
