import asyncio
import contextlib
from typing import Any

from ..db import MessageRepository, db_manager
from ..exceptions import log_exceptions
from ..logger import app_logger
from ..models import datetime_now


class MessageLifetimeService:
    """Сервис для управления временем жизни сообщений"""

    def __init__(self) -> None:
        self._is_running = False
        self._task: asyncio.Task | None = None

        from ..config import settings

        self.CHECK_INTERVAL = getattr(settings, "MESSAGE_LIFETIME_CHECK_INTERVAL", 60)
        self.BATCH_SIZE = getattr(settings, "MESSAGE_LIFETIME_BATCH_SIZE", 1000)
        self.DEFAULT_LIFETIME = getattr(settings, "MESSAGE_LIFETIME_DEFAULT_SECONDS", 604800)

        self._stats: dict[str, Any] = {
            "total_checked": 0,
            "total_expired": 0,
            "total_deleted": 0,
            "total_telegram_deleted": 0,
            "last_check": None,
        }

    @property
    def is_running(self) -> bool:
        return self._is_running

    async def start(self) -> None:
        if self._is_running:
            app_logger.warning("⚠️ MessageLifetimeService already running")
            return

        self._is_running = True
        self._task = asyncio.create_task(self._check_loop())
        app_logger.info(f"✅ MessageLifetimeService started (interval={self.CHECK_INTERVAL}s)")

    async def stop(self) -> None:
        self._is_running = False

        if self._task and not self._task.done():
            self._task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._task

        app_logger.info("⛔ MessageLifetimeService stopped")

    async def _check_loop(self) -> None:
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

    @log_exceptions(app_logger)
    async def _check_expired_messages(self) -> None:
        app_logger.debug("🔍 Checking expired messages...")

        async with db_manager.get_session() as session:
            try:
                expired_messages = await MessageRepository.get_expired_messages(session=session, limit=self.BATCH_SIZE)

                self._stats["total_checked"] = self._stats.get("total_checked", 0) + 1
                self._stats["last_check"] = datetime_now()

                if not expired_messages:
                    app_logger.debug("✅ No expired messages found")
                    return

                message_ids = [msg.FID for msg in expired_messages]

                app_logger.info(f"📊 Found {len(message_ids)} expired messages to delete")
                self._stats["total_expired"] = self._stats.get("total_expired", 0) + len(message_ids)

                telegram_deleted = 0
                try:
                    from ..tg import tg_manager

                    status = await tg_manager.get_status()
                    if status.get("is_running", False):
                        for msg in expired_messages:
                            try:
                                delete_result = await tg_manager.delete_message_by_id(
                                    chat_id=msg.FK_Chat, message_id=msg.FID
                                )
                                if delete_result.get("success"):
                                    telegram_deleted += 1
                                    app_logger.debug(f"✅ Deleted expired message {msg.FID} from Telegram")
                                else:
                                    app_logger.warning(
                                        f"⚠️ Failed to delete expired message {msg.FID} from Telegram: "
                                        f"{delete_result.get('error')}"
                                    )
                            except Exception as e:
                                app_logger.warning(f"⚠️ Error deleting expired message {msg.FID} from Telegram: {e}")
                    else:
                        app_logger.warning("⚠️ Telegram manager not running, skipping Telegram deletion")
                except Exception as e:
                    app_logger.error(f"❌ Failed to delete expired messages from Telegram: {e}")

                self._stats["total_telegram_deleted"] = self._stats.get("total_telegram_deleted", 0) + telegram_deleted

                deleted_count = await MessageRepository.mark_messages_as_deleted(
                    session=session, message_ids=message_ids, deleted_by_type="expired"
                )

                self._stats["total_deleted"] = self._stats.get("total_deleted", 0) + deleted_count

                app_logger.info(
                    f"✅ Marked {deleted_count} expired messages as deleted in DB "
                    f"(telegram_deleted: {telegram_deleted}, "
                    f"total: {self._stats['total_deleted']})"
                )

                if deleted_count > 0:
                    sample_ids = message_ids[:5]
                    app_logger.debug(f"📝 Sample expired messages: {sample_ids}")

                if len(message_ids) >= self.BATCH_SIZE:
                    app_logger.debug("🔄 More expired messages pending, will continue next cycle")

            except Exception as e:
                app_logger.error(f"❌ Failed to check expired messages: {e}", exc_info=True)
                await session.rollback()
                raise

    @log_exceptions(app_logger)
    async def get_stats(self) -> dict[str, Any]:
        async with db_manager.get_session() as session:
            stats = await MessageRepository.get_message_lifetime_stats(session)

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
                "total_telegram_deleted": self._stats.get("total_telegram_deleted", 0),
                "last_check": last_check_str,
            },
        }

    @log_exceptions(app_logger)
    async def force_check(self) -> dict[str, int]:
        app_logger.info("🔄 Force check expired messages...")

        async with db_manager.get_session() as session:
            expired_messages = await MessageRepository.get_expired_messages(
                session=session,
                limit=self.BATCH_SIZE * 10,
            )

            if not expired_messages:
                return {"deleted": 0, "found": 0, "telegram_deleted": 0}

            message_ids = [msg.FID for msg in expired_messages]

            telegram_deleted = 0
            try:
                from ..tg import tg_manager

                status = await tg_manager.get_status()
                if status.get("is_running", False):
                    for msg in expired_messages:
                        try:
                            delete_result = await tg_manager.delete_message_by_id(
                                chat_id=msg.FK_Chat, message_id=msg.FID
                            )
                            if delete_result.get("success"):
                                telegram_deleted += 1
                        except Exception as e:
                            app_logger.warning(f"⚠️ Error deleting expired message {msg.FID}: {e}")
                else:
                    app_logger.warning("⚠️ Telegram manager not running, skipping Telegram deletion")
            except Exception as e:
                app_logger.error(f"❌ Failed to delete expired messages from Telegram: {e}")

            deleted_count = await MessageRepository.mark_messages_as_deleted(
                session=session, message_ids=message_ids, deleted_by_type="expired_force"
            )

            self._stats["total_deleted"] = self._stats.get("total_deleted", 0) + deleted_count
            self._stats["total_telegram_deleted"] = self._stats.get("total_telegram_deleted", 0) + telegram_deleted

            app_logger.info(
                f"✅ Force check: deleted {deleted_count} messages in DB (telegram_deleted: {telegram_deleted})"
            )

            return {"deleted": deleted_count, "found": len(message_ids), "telegram_deleted": telegram_deleted}


message_lifetime_service = MessageLifetimeService()

__all__ = ["message_lifetime_service", "MessageLifetimeService"]
