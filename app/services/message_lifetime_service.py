"""
Сервис для управления временем жизни сообщений.

Назначение:
    Автоматическое удаление сообщений с истёкшим сроком жизни из базы данных
    и из Telegram. Предотвращает накопление устаревших сообщений.

Основные функции:
    1. Периодическая проверка сообщений с истёкшим сроком жизни
    2. Удаление истёкших сообщений из Telegram
    3. Пометка истёкших сообщений как удалённых в базе данных
    4. Принудительная проверка по запросу
    5. Сбор статистики по удалённым сообщениям

Технические особенности:
    - Асинхронный фоновый воркер с настраиваемым интервалом
    - Пакетная обработка для оптимизации производительности
    - Интеграция с Telegram Bot API для удаления сообщений
    - Graceful shutdown с корректной остановкой воркера
    - Детальная статистика работы

Архитектура:
    - Использует asyncio.Task для фонового выполнения
    - Работает через репозиторий MessageRepository
    - Интегрируется с BotManager для удаления из Telegram
"""

import asyncio
import contextlib
from typing import Any

from ..db import db_manager
from ..db.repositories import MessageRepository
from ..logger import app_logger
from ..models import datetime_now
from ..utils.decorators import log_exceptions

# ============================================================
# 1. РЕПОЗИТОРИЙ (СИНГЛТОН)
# ============================================================

_message_repo = MessageRepository()


# ============================================================
# 2. ОСНОВНОЙ КЛАСС СЕРВИСА
# ============================================================


class MessageLifetimeService:
    """
    Сервис для управления временем жизни сообщений.

    Предоставляет методы для:
    - Периодической проверки и удаления истёкших сообщений
    - Принудительной проверки по запросу
    - Получения статистики

    Attributes:
        _is_running (bool): Флаг работы сервиса
        _task (asyncio.Task | None): Задача фонового воркера
        CHECK_INTERVAL (int): Интервал проверки в секундах
        BATCH_SIZE (int): Размер пакета для обработки
        DEFAULT_LIFETIME (int): Время жизни по умолчанию в секундах
        _stats (dict[str, Any]): Статистика работы сервиса
    """

    def __init__(self) -> None:
        """Инициализация сервиса управления временем жизни сообщений."""
        self._is_running = False
        self._task: asyncio.Task | None = None

        from ..config import settings

        # Настройки из конфигурации
        self.CHECK_INTERVAL = getattr(settings, "MESSAGE_LIFETIME_CHECK_INTERVAL", 60)  # Интервал проверки
        self.BATCH_SIZE = getattr(settings, "MESSAGE_LIFETIME_BATCH_SIZE", 1000)  # Размер пакета
        self.DEFAULT_LIFETIME = getattr(settings, "MESSAGE_LIFETIME_DEFAULT_SECONDS", 604800)  # 7 дней

        # Статистика работы сервиса
        self._stats: dict[str, Any] = {
            "total_checked": 0,  # Всего проведено проверок
            "total_expired": 0,  # Всего найдено истёкших сообщений
            "total_deleted": 0,  # Всего помечено удалёнными в БД
            "total_bot_deleted": 0,  # Всего удалено из Telegram
            "last_check": None,  # Время последней проверки
        }

    # ============================================================
    # 2.1. СВОЙСТВА
    # ============================================================

    @property
    def is_running(self) -> bool:
        """
        Проверка, запущен ли сервис.

        Returns:
            bool: True если сервис запущен
        """
        return self._is_running

    # ============================================================
    # 2.2. УПРАВЛЕНИЕ ЖИЗНЕННЫМ ЦИКЛОМ
    # ============================================================

    async def start(self) -> None:
        """
        Запуск сервиса.

        Создаёт фоновую задачу для периодической проверки и удаления
        истёкших сообщений.
        """
        if self._is_running:
            app_logger.warning("⚠️ MessageLifetimeService already running")
            return

        self._is_running = True
        self._task = asyncio.create_task(self._check_loop())
        app_logger.info(f"✅ MessageLifetimeService started (interval={self.CHECK_INTERVAL}s)")

    async def stop(self) -> None:
        """
        Остановка сервиса.

        Корректно завершает фоновую задачу и освобождает ресурсы.
        """
        self._is_running = False

        if self._task and not self._task.done():
            self._task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._task

        app_logger.info("⛔ MessageLifetimeService stopped")

    # ============================================================
    # 2.3. ФОНОВЫЙ ВОРКЕР
    # ============================================================

    async def _check_loop(self) -> None:
        """
        Фоновый цикл проверки истёкших сообщений.

        Постоянно выполняется в фоне, периодически проверяет наличие
        истёкших сообщений и удаляет их.
        """
        app_logger.debug("🔄 MessageLifetimeService check loop started")

        while self._is_running:
            try:
                await self._check_expired_messages()
                await asyncio.sleep(self.CHECK_INTERVAL)
            except asyncio.CancelledError:
                app_logger.debug("ℹ️ MessageLifetimeService cancelled")
                break
            except Exception as e:
                app_logger.error(f"❌ MessageLifetimeService error: {e}", exc_info=True)
                await asyncio.sleep(self.CHECK_INTERVAL)

    # ============================================================
    # 2.4. ПРОВЕРКА И УДАЛЕНИЕ ИСТЕКШИХ СООБЩЕНИЙ
    # ============================================================

    @log_exceptions(app_logger)
    async def _check_expired_messages(self) -> None:
        """
        Проверка и удаление истёкших сообщений.

        Находит сообщения с истёкшим сроком жизни, удаляет их из Telegram
        и помечает как удалённые в базе данных.
        """
        app_logger.debug("🔍 Checking expired messages...")

        async with db_manager.get_session() as session:
            try:
                # 1. Получение истёкших сообщений
                expired_messages = await _message_repo.get_expired_messages(
                    session=session,
                    limit=self.BATCH_SIZE,
                )

                # 2. Обновление статистики
                self._stats["total_checked"] = self._stats.get("total_checked", 0) + 1
                self._stats["last_check"] = datetime_now()

                # 3. Если нет истёкших сообщений - выходим
                if not expired_messages:
                    app_logger.debug("✅ No expired messages found")
                    return

                message_ids = [msg.FID for msg in expired_messages]

                app_logger.info(f"📊 Found {len(message_ids)} expired messages to delete")
                self._stats["total_expired"] = self._stats.get("total_expired", 0) + len(message_ids)

                # 4. Удаление из Telegram
                bot_deleted = await self._delete_messages_from_telegram(expired_messages)
                self._stats["total_bot_deleted"] = self._stats.get("total_bot_deleted", 0) + bot_deleted

                # 5. Пометка как удалённых в БД
                deleted_count = await _message_repo.mark_messages_as_deleted(
                    session=session,
                    message_ids=message_ids,
                    deleted_by_type="expired",
                )

                self._stats["total_deleted"] = self._stats.get("total_deleted", 0) + deleted_count

                # 6. Логирование результата
                app_logger.info(
                    f"✅ Marked {deleted_count} expired messages as deleted in DB "
                    f"(bot_deleted: {bot_deleted}, "
                    f"total: {self._stats['total_deleted']})"
                )

                # 7. Логирование выборки для отладки
                if deleted_count > 0:
                    sample_ids = message_ids[:5]
                    app_logger.debug(f"📝 Sample expired messages: {sample_ids}")

                # 8. Если есть ещё сообщения, они будут обработаны в следующем цикле
                if len(message_ids) >= self.BATCH_SIZE:
                    app_logger.debug("🔄 More expired messages pending, will continue next cycle")

            except Exception as e:
                app_logger.error(f"❌ Failed to check expired messages: {e}", exc_info=True)
                await session.rollback()
                raise

    # ============================================================
    # 2.5. УДАЛЕНИЕ ИЗ TELEGRAM
    # ============================================================

    @staticmethod
    async def _delete_messages_from_telegram(messages: list[Any]) -> int:
        """
        Удаление сообщений из Telegram.

        Args:
            messages: Список сообщений для удаления

        Returns:
            int: Количество успешно удалённых сообщений
        """
        bot_deleted = 0

        try:
            from ..bot.dependencies import get_bot_manager

            bot_manager = get_bot_manager()

            # Проверка статуса бота
            status = await bot_manager.get_status()
            if not status.get("is_running", False):
                app_logger.warning("⚠️ Bot manager not running, skipping Bot deletion")
                return 0

            # Удаление каждого сообщения
            for msg in messages:
                try:
                    delete_result = await bot_manager.delete_message_by_id(
                        chat_id=msg.FK_Chat,
                        message_id=msg.FID,
                    )
                    if delete_result.get("success"):
                        bot_deleted += 1
                        app_logger.debug(f"✅ Deleted expired message {msg.FID} by Bot")
                    else:
                        app_logger.warning(
                            f"⚠️ Failed to delete expired message {msg.FID} by Bot: {delete_result.get('error')}"
                        )
                except Exception as e:
                    app_logger.warning(f"⚠️ Error deleting expired message {msg.FID} by Bot: {e}")

        except Exception as e:
            app_logger.error(f"❌ Failed to delete expired messages by Bot: {e}")

        if bot_deleted > 0:
            app_logger.info(f"✅ Deleted {bot_deleted} expired messages from Telegram")

        return bot_deleted

    # ============================================================
    # 2.6. СТАТИСТИКА
    # ============================================================

    @log_exceptions(app_logger)
    async def get_stats(self) -> dict[str, Any]:
        """
        Получение полной статистики работы сервиса.

        Returns:
            dict[str, Any]: Статистика с полями:
                - message_stats: Статистика из базы данных
                - service: Статистика работы сервиса
        """
        # Получение статистики из БД
        async with db_manager.get_session() as session:
            stats = await _message_repo.get_message_lifetime_stats(session)

        # Форматирование времени последней проверки
        last_check = self._stats.get("last_check")
        last_check_str = last_check.isoformat() + "Z" if last_check else None

        return {
            **stats,
            "service": {
                "is_running": self._is_running,
                "check_interval": self.CHECK_INTERVAL,
                "batch_size": self.BATCH_SIZE,
                "default_lifetime": self.DEFAULT_LIFETIME,
                "total_checked": self._stats.get("total_checked", 0),
                "total_expired": self._stats.get("total_expired", 0),
                "total_deleted": self._stats.get("total_deleted", 0),
                "total_bot_deleted": self._stats.get("total_bot_deleted", 0),
                "last_check": last_check_str,
            },
        }

    # ============================================================
    # 2.7. ПРИНУДИТЕЛЬНАЯ ПРОВЕРКА
    # ============================================================

    @log_exceptions(app_logger)
    async def force_check(self) -> dict[str, int]:
        """
        Принудительная проверка и удаление истёкших сообщений.

        Отличается от обычной проверки увеличенным лимитом (BATCH_SIZE * 10)
        для полной очистки по запросу.

        Returns:
            dict[str, int]: Результат проверки с полями:
                - deleted: Количество удалённых в БД
                - found: Количество найденных истёкших
                - bot_deleted: Количество удалённых из Telegram
        """
        app_logger.info("🔄 Force check expired messages...")

        async with db_manager.get_session() as session:
            # 1. Получение истёкших сообщений (увеличенный лимит)
            expired_messages = await _message_repo.get_expired_messages(
                session=session,
                limit=self.BATCH_SIZE * 10,
            )

            if not expired_messages:
                return {"deleted": 0, "found": 0, "bot_deleted": 0}

            message_ids = [msg.FID for msg in expired_messages]

            # 2. Удаление из Telegram
            bot_deleted = await self._delete_messages_from_telegram(expired_messages)

            # 3. Пометка как удалённых в БД
            deleted_count = await _message_repo.mark_messages_as_deleted(
                session=session,
                message_ids=message_ids,
                deleted_by_type="expired_force",
            )

            # 4. Обновление статистики
            self._stats["total_deleted"] = self._stats.get("total_deleted", 0) + deleted_count
            self._stats["total_bot_deleted"] = self._stats.get("total_bot_deleted", 0) + bot_deleted

            app_logger.info(f"✅ Force check: deleted {deleted_count} messages in DB (bot_deleted: {bot_deleted})")

            return {
                "deleted": deleted_count,
                "found": len(message_ids),
                "bot_deleted": bot_deleted,
            }


message_lifetime_service = MessageLifetimeService()

__all__ = [
    "message_lifetime_service",
    "MessageLifetimeService",
]
