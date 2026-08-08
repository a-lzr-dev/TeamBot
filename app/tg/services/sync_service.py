import contextlib
from datetime import datetime, timedelta
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession
from telethon import TelegramClient
from telethon.errors import FloodWaitError
from telethon.tl.functions.channels import GetParticipantsRequest
from telethon.tl.functions.messages import GetFullChatRequest

from ...config import settings
from ...core.converters import (
    chat_type_from_dialog,
    chat_type_to_str,
    member_status_from_telethon,
    user_info_from_telethon,
)
from ...db.repositories.chats import ChatRepository, normalize_chat_id
from ...db.repositories.users import UserRepository
from ...exceptions import log_exceptions
from ...logger import tg_logger
from ...models import ChatMemberStatus, ChatModel, UserChatMemberModel, datetime_now
from .interfaces import ISyncService

SyncStats = dict[str, bool | int | str | list | dict | None]


class SyncService(ISyncService):
    """Единый сервис синхронизации для Telegram"""

    def __init__(self, telethon_client: Any) -> None:
        """Инициализация сервиса синхронизации"""
        self._client = telethon_client
        self._sync_engine = ChatSyncEngine()
        self._last_sync_time: datetime | None = None
        self._initialized = False

        # Кеш для участников чатов
        self._cache: dict[int, tuple[datetime, list[dict[str, Any]]]] = {}
        self._cache_ttl = getattr(settings, "SYNC_CACHE_TTL_SECONDS", 60)

        # Метрики
        self._metrics: dict[str, Any] = {
            "total_syncs": 0,
            "failed_syncs": 0,
            "total_chats_synced": 0,
            "total_members_synced": 0,
            "last_sync_duration": 0,
            "errors": [],
        }

        tg_logger.debug("✅ SyncService instance created")

    async def initialize(self) -> None:
        """Инициализация сервиса."""
        if self._initialized:
            return

        if not self._client.client:
            await self._client.initialize()

        self._initialized = True
        tg_logger.info("✅ Sync Service initialized")

    @log_exceptions(tg_logger)
    async def sync_chat_members(self, chat_id: int, session: AsyncSession, force: bool = False) -> dict[str, Any]:  # type: ignore[override]
        """Синхронизация участников конкретного чата"""
        if not self._initialized:
            await self.initialize()

        if not self._client.client:
            return {"success": False, "error": "Client not initialized", "chat_id": chat_id}

        # Проверка кеша
        if not force:
            cached = await self._get_cached_members(chat_id)
            if cached is not None:
                tg_logger.debug(f"✅ Using cached members for chat {chat_id}")
                return {
                    "success": True,
                    "chat_id": chat_id,
                    "from_cache": True,
                    "members_count": len(cached),
                    "members": cached,
                }

        start_time = datetime_now()
        self._metrics["total_syncs"] += 1

        try:
            # Делегирование ядру синхронизации
            result = await self._sync_engine.sync_chat_members(
                client=self._client.client, chat_id=chat_id, session=session
            )

            # Обновление метрик
            self._metrics["total_chats_synced"] += 1
            self._metrics["total_members_synced"] += result.get("processed", 0)
            self._metrics["last_sync_duration"] = (datetime_now() - start_time).total_seconds()

            # Обновление кеша
            if result.get("success", False):
                await self._update_cache(chat_id, result.get("members", []))

            return {"success": True, "chat_id": chat_id, "from_cache": False, **result}

        except FloodWaitError as e:
            self._metrics["failed_syncs"] += 1
            self._metrics["errors"].append(
                {"chat_id": chat_id, "error": f"Flood wait: {e.seconds}s", "timestamp": datetime_now().isoformat()}
            )

            tg_logger.warning(f"⏳ Flood wait for chat {chat_id}: {e.seconds}s")
            return {
                "success": False,
                "error": f"Flood wait: {e.seconds}s",
                "chat_id": chat_id,
                "retry_after": e.seconds,
            }

        except Exception as e:
            self._metrics["failed_syncs"] += 1
            self._metrics["errors"].append(
                {"chat_id": chat_id, "error": str(e), "timestamp": datetime_now().isoformat()}
            )

            tg_logger.error(f"❌ Failed to sync chat {chat_id}: {e}", exc_info=True)
            return {"success": False, "error": str(e), "chat_id": chat_id}

    @log_exceptions(tg_logger)
    async def sync_all_chats(  # type: ignore
        self,
        session: AsyncSession,
        force: bool = False,
        max_chats: int | None = None,
        chat_types: list[str] | None = None,
    ) -> dict[str, Any]:
        """Синхронизация всех чатов"""
        if not self._initialized:
            await self.initialize()

        if not self._client.client:
            return {"success": False, "error": "Client not initialized"}

        # Проверка необходимости синхронизации
        if not force and self._last_sync_time:
            time_since_sync = datetime_now() - self._last_sync_time
            if time_since_sync < timedelta(minutes=5):
                tg_logger.debug("⏳ Skipping sync, last sync was recent")
                return {
                    "success": True,
                    "skipped": True,
                    "last_sync": self._last_sync_time.isoformat(),
                    "message": "Last sync was less than 5 minutes ago",
                }

        start_time = datetime_now()
        self._metrics["total_syncs"] += 1

        try:
            # Делегирование ядру синхронизации
            result = await self._sync_engine.sync_all_chats(
                client=self._client.client, session=session, max_chats=max_chats, chat_types=chat_types
            )

            # Обновление метрик
            self._metrics["total_chats_synced"] += result.get("processed", {}).get("chats", 0)
            self._metrics["total_members_synced"] += result.get("processed", {}).get("members", 0)
            self._metrics["last_sync_duration"] = (datetime_now() - start_time).total_seconds()

            self._last_sync_time = datetime_now()

            return {"success": True, "duration_seconds": self._metrics["last_sync_duration"], **result}

        except Exception as e:
            self._metrics["failed_syncs"] += 1
            self._metrics["errors"].append({"error": str(e), "timestamp": datetime_now().isoformat()})

            tg_logger.error(f"❌ Failed to sync all chats: {e}", exc_info=True)
            return {"success": False, "error": str(e)}

    async def get_last_sync_time(self) -> datetime | None:
        """Получение времени последней синхронизации"""
        return self._last_sync_time

    async def get_status(self) -> dict[str, Any]:
        """Получение статуса сервиса"""
        return {
            "initialized": self._initialized,
            "client_available": bool(self._client.client),
            "last_sync": self._last_sync_time.isoformat() if self._last_sync_time else None,
            "service": "sync",
            "cache_size": len(self._cache),
            "metrics": {
                "total_syncs": self._metrics["total_syncs"],
                "failed_syncs": self._metrics["failed_syncs"],
                "total_chats_synced": self._metrics["total_chats_synced"],
                "total_members_synced": self._metrics["total_members_synced"],
                "last_sync_duration": self._metrics["last_sync_duration"],
                "recent_errors": self._metrics["errors"][-5:] if self._metrics["errors"] else [],
            },
        }

    async def health_check(self) -> bool:
        """Проверка здоровья сервиса"""
        if not self._initialized:
            return False

        try:
            return bool(await self._client.is_connected())
        except Exception:
            return False

    async def clear_cache(self, chat_id: int | None = None) -> None:
        """Очистка кеша"""
        if chat_id is not None:
            self._cache.pop(chat_id, None)
            tg_logger.debug(f"✅ Cache cleared for chat {chat_id}")
        else:
            self._cache.clear()
            tg_logger.debug("✅ All cache cleared")

    async def _get_cached_members(self, chat_id: int) -> list[dict[str, Any]] | None:
        """Получение кешированных участников чата"""
        if chat_id not in self._cache:
            return None

        cached_time, members = self._cache[chat_id]
        if (datetime_now() - cached_time).seconds < self._cache_ttl:
            return members

        # Кеш устарел
        del self._cache[chat_id]
        return None

    async def _update_cache(self, chat_id: int, members: list[dict[str, Any]]) -> None:
        """Обновление кеша участников чата"""
        self._cache[chat_id] = (datetime_now(), members)

    async def reset_metrics(self) -> None:
        """Сброс метрик"""
        self._metrics = {
            "total_syncs": 0,
            "failed_syncs": 0,
            "total_chats_synced": 0,
            "total_members_synced": 0,
            "last_sync_duration": 0,
            "errors": [],
        }
        tg_logger.info("✅ Sync metrics reset")


class ChatSyncEngine:
    """Ядро синхронизации - бизнес-логика без зависимостей от клиентов"""

    @staticmethod
    def _create_error_stats(
        error_message: str, chat_id: int | None = None, retry_after: int | None = None
    ) -> dict[str, Any]:
        """Создание стандартной структуры для ошибок"""
        stats: dict[str, Any] = {
            "success": False,
            "error": error_message,
            "processed": 0,
            "added": 0,
            "deactivated": 0,
            "errors": 1,
            "members": [],
        }

        if chat_id is not None:
            stats["chat_id"] = chat_id

        if retry_after is not None:
            stats["retry_after"] = retry_after

        return stats

    @staticmethod
    @log_exceptions(tg_logger)
    async def sync_chat_members(client: TelegramClient, chat_id: int, session: AsyncSession) -> dict[str, Any]:
        """Синхронизация участников чата"""
        normalized_chat_id = normalize_chat_id(chat_id)
        tg_logger.debug(f"🔄 Syncing chat {chat_id} (normalized: {normalized_chat_id})...")

        stats: dict[str, Any] = {
            "success": True,
            "processed": 0,
            "added": 0,
            "deactivated": 0,
            "errors": 0,
            "members": [],
        }

        try:
            # Получение участников из Telegram
            members = await ChatSyncEngine._get_chat_members_from_telegram(client, normalized_chat_id)

            if not members:
                tg_logger.warning(f"⚠️ No members found for chat {chat_id}")
                return ChatSyncEngine._create_error_stats(error_message="No members found", chat_id=chat_id)

            active_ids = {member.FID for member in members}
            stats["members"] = [
                {
                    "id": member.FID,
                    "username": member.FUserName,
                    "first_name": member.FFirstName,
                    "last_name": member.FLastName,
                    "is_bot": member.FFlagBot,
                    "status": member.FStatus.value if hasattr(member.FStatus, "value") else str(member.FStatus),
                }
                for member in members
            ]

            # Получение участников из БД
            db_members = await ChatRepository.get_user_chat_members(session, chat_id=normalized_chat_id, is_active=True)
            db_members_ids = {member.FID for member in db_members}

            # Деактивирование отсутствующих участников
            deactivated_count = 0
            for db_member in db_members:
                if db_member.FID not in active_ids:
                    db_member.FFlagActive = False
                    deactivated_count += 1

            stats["deactivated"] = deactivated_count

            # Добавление новых участников
            added_count = 0
            processed_count = 0

            for member in members:
                try:
                    await UserRepository.save_user(
                        session=session,
                        user_id=member.FID,
                        is_bot=member.FFlagBot,
                        first_name=member.FFirstName or "",
                        last_name=member.FLastName,
                        username=member.FUserName,
                    )

                    is_new = member.FID not in db_members_ids

                    await ChatRepository.save_chat_member(
                        session=session,
                        user_id=member.FID,
                        chat_id=normalized_chat_id,
                        status=member.FStatus.value if hasattr(member.FStatus, "value") else str(member.FStatus),
                        is_active=True,
                    )

                    if is_new:
                        added_count += 1
                    processed_count += 1

                except Exception as e:
                    tg_logger.error(f"❌ Failed to save member {member.FID}: {e}", exc_info=True)
                    stats["errors"] += 1

            stats["processed"] = processed_count
            stats["added"] = added_count

            # Обновление времени синхронизации чата
            chat = await session.get(ChatModel, normalized_chat_id)
            if chat:
                chat.FDateSynced = datetime_now()

            await session.commit()

            tg_logger.info(
                f"✅ Chat {chat_id} synced: "
                f"processed={processed_count}, "
                f"added={added_count}, "
                f"deactivated={deactivated_count}, "
                f"errors={stats['errors']}"
            )

            return stats

        except FloodWaitError as e:
            tg_logger.warning(f"⏳ Flood wait for chat {chat_id}: {e.seconds}s")
            await session.rollback()
            return ChatSyncEngine._create_error_stats(
                error_message=f"Flood wait: {e.seconds}s", chat_id=chat_id, retry_after=e.seconds
            )

        except Exception as e:
            tg_logger.error(f"❌ Failed to sync chat {chat_id}: {e}", exc_info=True)
            await session.rollback()
            return ChatSyncEngine._create_error_stats(error_message=str(e), chat_id=chat_id)

    @staticmethod
    @log_exceptions(tg_logger)
    async def sync_all_chats(
        client: TelegramClient, session: AsyncSession, max_chats: int | None = None, chat_types: list[str] | None = None
    ) -> dict[str, Any]:
        """Синхронизация всех чатов"""
        tg_logger.debug("🚀 Syncing all chats...")

        stats: dict[str, Any] = {
            "success": True,
            "processed": {"chats": 0, "members": 0},
            "added": {"chats": 0, "members": 0},
            "deactivated": {"chats": 0, "members": 0},
            "skipped": 0,
            "errors": {"chats": 0, "members": 0},
            "chats_synced": [],
        }

        try:
            if settings.is_bot_account:
                tg_logger.warning("⚠️ Cannot sync all chats with bot account")
                stats["success"] = False
                stats["error"] = "Bot account cannot sync all chats. Use /chats/{chat_id}/sync for individual chats."
                return stats

            # Проверка подключения клиента
            if not client.is_connected():
                tg_logger.warning("⚠️ Client not connected")
                stats["success"] = False
                stats["error"] = "Telegram client not connected"
                return stats

            # Получение чатов из Telegram
            chats = await ChatSyncEngine._get_chats_from_telegram(client, max_chats=max_chats, chat_types=chat_types)

            if not chats:
                tg_logger.info("ℹ️ No chats found")
                return stats

            # Получение чатов из БД
            db_chats = await ChatRepository.get_chats(session, is_active=True)
            db_chats_ids = {chat.FID for chat in db_chats}

            active_ids = {chat.FID for chat in chats}

            # Деактивирование отсутствующих чатов
            deactivated_chats = 0
            for db_chat in db_chats:
                if db_chat.FID not in active_ids:
                    db_chat.FFlagActive = False
                    deactivated_chats += 1

            stats["deactivated"]["chats"] = deactivated_chats

            # Синхронизация каждого чата
            for chat in chats:
                try:
                    is_new = chat.FID not in db_chats_ids

                    await ChatRepository.save_chat(
                        session=session,
                        chat_id=chat.FID,
                        chat_type=chat_type_to_str(chat.FType),
                        title=chat.FTitle,
                        is_active=chat.FFlagActive,
                    )

                    if chat.FFlagActive:
                        # Проверка, нужно ли синхронизировать участников
                        should_sync = True
                        if chat.FDateSynced is not None:
                            time_since_sync = datetime_now() - chat.FDateSynced
                            if time_since_sync <= timedelta(minutes=10):
                                should_sync = False

                        if should_sync:
                            # Синхронизация участников
                            members_result = await ChatSyncEngine.sync_chat_members(
                                client=client, chat_id=chat.FID, session=session
                            )

                            if members_result.get("success", False):
                                stats["processed"]["members"] += members_result.get("processed", 0)
                                stats["added"]["members"] += members_result.get("added", 0)
                                stats["deactivated"]["members"] += members_result.get("deactivated", 0)
                                stats["errors"]["members"] += members_result.get("errors", 0)
                            else:
                                stats["errors"]["members"] += 1
                                tg_logger.warning(
                                    f"⚠️ Failed to sync members for chat {chat.FID}: "
                                    f"{members_result.get('error', 'Unknown error')}"
                                )

                            if is_new:
                                stats["added"]["chats"] += 1
                            stats["processed"]["chats"] += 1

                            stats["chats_synced"].append(
                                {
                                    "chat_id": chat.FID,
                                    "title": chat.FTitle,
                                    "status": "success" if members_result.get("success", False) else "partial",
                                    "error": members_result.get("error") if not members_result.get("success") else None,
                                }
                            )
                        else:
                            stats["skipped"] += 1
                    else:
                        stats["skipped"] += 1

                except Exception as e:
                    tg_logger.error(f"❌ Sync error (chat={chat.FID}): {e}", exc_info=True)
                    stats["errors"]["chats"] += 1
                    stats["chats_synced"].append(
                        {"chat_id": chat.FID, "title": chat.FTitle, "status": "error", "error": str(e)}
                    )

            await session.commit()

            tg_logger.info(
                f"✅ Sync all chats completed: "
                f"chats={stats['processed']['chats']}, "
                f"members={stats['processed']['members']}"
            )

            return stats

        except Exception as e:
            tg_logger.error(f"❌ Failed to sync all chats: {e}", exc_info=True)
            await session.rollback()
            stats["success"] = False
            stats["error"] = str(e)
            return stats

    @staticmethod
    async def _get_chat_members_from_telegram(client: TelegramClient, chat_id: int) -> list[UserChatMemberModel]:
        """Получение участников чата из Telegram"""
        normalized_chat_id = normalize_chat_id(chat_id)

        try:
            chat_entity = await client.get_entity(normalized_chat_id)
        except Exception as e:
            tg_logger.error(f"❌ Failed to get chat entity {chat_id}: {e}", exc_info=True)
            return []

        all_members = []

        try:
            # Проверка типа чата
            is_channel = hasattr(chat_entity, "channel") and chat_entity.channel
            is_megagroup = hasattr(chat_entity, "megagroup") and chat_entity.megagroup
            is_group = hasattr(chat_entity, "group") and chat_entity.group

            # Для супергрупп и каналов используем GetParticipantsRequest
            if is_channel or is_megagroup:
                tg_logger.debug(f"🔄 Getting members for channel/supergroup: {chat_id}")

                offset = 0
                limit = 1000

                while True:
                    try:
                        result = await client(
                            GetParticipantsRequest(
                                channel=chat_entity, filter="search", offset=offset, limit=limit, hash=0
                            )
                        )

                        if not result.users:
                            break

                        for user in result.users:
                            try:
                                # Определение статуса участника
                                status = ChatMemberStatus.MEMBER
                                for participant in result.participants:
                                    if hasattr(participant, "user_id") and participant.user_id == user.id:
                                        status = member_status_from_telethon(participant)
                                        break

                                user_info = user_info_from_telethon(user)

                                member = UserChatMemberModel(
                                    FID=user_info["user_id"],
                                    FUserName=user_info["username"] or f"user_{user_info['user_id']}",
                                    FFirstName=user_info["first_name"] or "",
                                    FLastName=user_info["last_name"],
                                    FFlagBot=user_info["is_bot"],
                                    FStatus=status,
                                )
                                all_members.append(member)
                            except Exception as e:
                                tg_logger.warning(f"⚠️ Processing user failed (user={user.id}): {e}")
                                continue

                        offset += limit

                    except FloodWaitError as e:
                        tg_logger.warning(f"⏳ Flood wait: {e.seconds} seconds")
                        raise
                    except Exception as e:
                        tg_logger.error(f"❌ Getting participants failed: {e}", exc_info=True)
                        break

            # Для обычных групп используем get_participants
            elif is_group:
                tg_logger.debug(f"🔄 Getting members for regular group: {chat_id}")

                try:
                    full_chat = await client(GetFullChatRequest(chat_entity.id))
                    participants = (
                        full_chat.full_chat.participants.participants if full_chat.full_chat.participants else []
                    )

                    for participant in participants:
                        try:
                            user_id = participant.user_id if hasattr(participant, "user_id") else participant.id
                            user = await client.get_entity(user_id)

                            status = member_status_from_telethon(participant)
                            user_info = user_info_from_telethon(user)

                            member = UserChatMemberModel(
                                FID=user_info["user_id"],
                                FUserName=user_info["username"] or f"user_{user_info['user_id']}",
                                FFirstName=user_info["first_name"] or "",
                                FLastName=user_info["last_name"],
                                FFlagBot=user_info["is_bot"],
                                FStatus=status,
                            )
                            all_members.append(member)
                        except Exception as e:
                            tg_logger.warning(f"⚠️ Processing participant failed: {e}")
                            continue

                except Exception as e:
                    tg_logger.error(f"❌ Failed to get group participants: {e}", exc_info=True)

            # Для приватных чатов
            else:
                tg_logger.debug(f"🔄 Getting members for private chat: {chat_id}")
                try:
                    me = await client.get_me()
                    user_info = user_info_from_telethon(me)

                    member = UserChatMemberModel(
                        FID=user_info["user_id"],
                        FUserName=user_info["username"] or f"user_{user_info['user_id']}",
                        FFirstName=user_info["first_name"] or "",
                        FLastName=user_info["last_name"],
                        FFlagBot=user_info["is_bot"],
                        FStatus=ChatMemberStatus.CREATOR,
                    )
                    all_members.append(member)

                    # Добавление другого участника для приватного чата
                    if normalized_chat_id != me.id:
                        try:
                            other = await client.get_entity(normalized_chat_id)
                            user_info = user_info_from_telethon(other)

                            member = UserChatMemberModel(
                                FID=user_info["user_id"],
                                FUserName=user_info["username"] or f"user_{user_info['user_id']}",
                                FFirstName=user_info["first_name"] or "",
                                FLastName=user_info["last_name"],
                                FFlagBot=user_info["is_bot"],
                                FStatus=ChatMemberStatus.MEMBER,
                            )
                            all_members.append(member)
                        except Exception as e:
                            tg_logger.warning(f"⚠️ Failed to get other user: {e}")

                except Exception as e:
                    tg_logger.error(f"❌ Failed to get private chat members: {e}", exc_info=True)

        except Exception as e:
            tg_logger.error(f"❌ Failed to get chat members for {chat_id}: {e}", exc_info=True)

        tg_logger.info(f"✅ Chat members loaded: chat={chat_id}, count={len(all_members)}")
        return all_members

    @staticmethod
    async def _get_chats_from_telegram(
        client: TelegramClient, max_chats: int | None = None, chat_types: list[str] | None = None
    ) -> list[ChatModel]:
        """Получение списка чатов из Telegram. Возвращает только те чаты, где присутствует бот"""
        if settings.is_bot_account:
            tg_logger.warning("⚠️ get_chats() called with bot account")
            return []

        from ..manager import tg_manager

        bot = tg_manager.aiogram_client.bot
        if not bot:
            tg_logger.warning("⚠️ Aiogram bot not available")
            return await ChatSyncEngine._get_all_chats_from_telegram(client, max_chats, chat_types)

        try:
            bot_me = await bot.get_me()
            bot_id = bot_me.id
            bot_username = bot_me.username
            tg_logger.debug(f"✅ Bot ID: {bot_id}, Username: @{bot_username}")
        except Exception as e:
            tg_logger.error(f"❌ Failed to get bot info: {e}")
            return []

        all_chats = []
        processed = 0

        try:
            async for dialog in client.iter_dialogs():
                if max_chats and processed >= max_chats:
                    break

                try:
                    # Пропускаем диалоги с пользователями (личные чаты)
                    if dialog.is_user:
                        continue

                    # Проверяем, есть ли бот в чате через Aiogram
                    bot_in_chat = await ChatSyncEngine._check_bot_in_chat_aiogram(bot, dialog.id)

                    if not bot_in_chat:
                        tg_logger.debug(f"⏭️ Bot not in chat: {dialog.name} (ID: {dialog.id})")
                        continue

                    chat_type = chat_type_from_dialog(dialog)

                    # Фильтр по типам
                    if chat_types:
                        type_value = chat_type.value if hasattr(chat_type, "value") else str(chat_type)
                        if type_value not in chat_types:
                            continue

                    count_members = None
                    if dialog.is_group or dialog.is_channel:
                        with contextlib.suppress(Exception):
                            count_members = (
                                dialog.entity.participants_count
                                if hasattr(dialog.entity, "participants_count")
                                else None
                            )

                    chat_model = ChatModel(
                        FID=normalize_chat_id(dialog.id),
                        FType=chat_type,
                        FTitle=dialog.name,
                        FCountMembers=count_members,
                        FFlagActive=True,
                    )
                    all_chats.append(chat_model)
                    processed += 1

                    tg_logger.debug(f"✅ Added chat: {dialog.name} (ID: {dialog.id})")

                except Exception as e:
                    tg_logger.warning(f"⚠️ Chat processing error (chat={dialog.id}): {e}")
                    continue

        except Exception as e:
            tg_logger.error(f"❌ Failed to get chats: {e}", exc_info=True)
            return []

        tg_logger.info(f"✅ Chats loaded: {len(all_chats)} (filtered to chats with bot)")
        return all_chats

    @staticmethod
    async def _check_bot_in_chat_aiogram(bot: Any, chat_id: int) -> bool:
        """Проверка, присутствует ли бот в чате через Aiogram"""
        try:
            bot_member = await bot.get_chat_member(chat_id, bot.id)

            # Проверка статуса
            status = bot_member.status
            status_str = status.value if hasattr(status, "value") else str(status)

            # Бот в чате, если статус не "left" и не "kicked"
            is_in_chat = status_str not in ["left", "kicked"]

            if is_in_chat:
                tg_logger.debug(f"✅ Bot is in chat {chat_id} (status: {status_str})")
            else:
                tg_logger.debug(f"⏭️ Bot not in chat {chat_id} (status: {status_str})")

            return is_in_chat

        except Exception as e:
            # Если ошибка - скорее всего бота нет в чате
            error_str = str(e).lower()
            if "bot is not a member" in error_str or "user not found" in error_str:
                tg_logger.debug(f"⏭️ Bot not in chat {chat_id}")
            else:
                tg_logger.debug(f"⚠️ Error checking bot in chat {chat_id}: {e}")
            return False

    @staticmethod
    async def _check_bot_in_chat(client: TelegramClient, chat_entity: Any, bot_id: int) -> bool:
        """Проверка, присутствует ли бот в чате через Telethon"""
        try:
            participants = await client.get_participants(chat_entity, limit=200)

            return any(participant.id == bot_id for participant in participants)

        except Exception:
            # Если не удалось получить участников - предполагаем, что бота нет
            return False

    @staticmethod
    async def _get_all_chats_from_telegram(
        client: TelegramClient, max_chats: int | None = None, chat_types: list[str] | None = None
    ) -> list[ChatModel]:
        """Fallback метод - получает все чаты без фильтрации по наличию бота"""
        all_chats = []
        processed = 0

        try:
            async for dialog in client.iter_dialogs():
                if max_chats and processed >= max_chats:
                    break

                try:
                    chat_type = chat_type_from_dialog(dialog)

                    if chat_types:
                        type_value = chat_type.value if hasattr(chat_type, "value") else str(chat_type)
                        if type_value not in chat_types:
                            continue

                    count_members = None
                    if dialog.is_group or dialog.is_channel:
                        with contextlib.suppress(Exception):
                            count_members = (
                                dialog.entity.participants_count
                                if hasattr(dialog.entity, "participants_count")
                                else None
                            )

                    chat_model = ChatModel(
                        FID=normalize_chat_id(dialog.id),
                        FType=chat_type,
                        FTitle=dialog.name,
                        FCountMembers=count_members,
                        FFlagActive=True,
                    )
                    all_chats.append(chat_model)
                    processed += 1

                except Exception as e:
                    tg_logger.warning(f"⚠️ Chat processing error (chat={dialog.id}): {e}")
                    continue

        except Exception as e:
            tg_logger.error(f"❌ Failed to get all chats: {e}", exc_info=True)
            return []

        return all_chats


__all__ = [
    "SyncService",
    "ChatSyncEngine",
]
