from datetime import datetime, timedelta
from typing import Any

from sqlalchemy import and_, func, select, update
from sqlalchemy.engine import Result
from sqlalchemy.ext.asyncio import AsyncSession

from ...exceptions import log_exceptions
from ...logger import db_logger
from ...models import (
    ChatMemberModel,
    ChatMemberStatus,
    ChatMessageModel,
    ChatModel,
    ChatType,
    UserChatMemberModel,
    UserModel,
    datetime_now,
)


def normalize_chat_id(chat_id: int) -> int:
    """Нормализация ID чата. Для супергрупп ID может быть отрицательным"""
    return chat_id


class ChatRepository:
    """Репозиторий для работы с чатами (независимый)"""

    @staticmethod
    @log_exceptions(db_logger)
    async def _parse_chat_type(chat_type: str | ChatType) -> ChatType:
        """Безопасное преобразование chat_type в ChatType"""
        if isinstance(chat_type, ChatType):
            return chat_type

        if isinstance(chat_type, str):
            normalized = chat_type.lower().strip()

            mapping = {
                "private": ChatType.PRIVATE,
                "group": ChatType.GROUP,
                "supergroup": ChatType.SUPERGROUP,
                "channel": ChatType.CHANNEL,
                "sender": ChatType.SENDER,
            }

            if normalized in mapping:
                return mapping[normalized]

            try:
                return ChatType(normalized)
            except ValueError:
                db_logger.warning(f"⚠️ Unknown chat type: {chat_type}, using PRIVATE")
                return ChatType.PRIVATE

        db_logger.warning(f"⚠️ Invalid chat type: {chat_type}, using PRIVATE")
        return ChatType.PRIVATE

    @staticmethod
    @log_exceptions(db_logger)
    async def _parse_member_status(status: str | ChatMemberStatus) -> ChatMemberStatus:
        """Безопасное преобразование status в ChatMemberStatus"""
        if isinstance(status, ChatMemberStatus):
            return status

        if isinstance(status, str):
            normalized = status.lower().strip()

            mapping = {
                "creator": ChatMemberStatus.CREATOR,
                "administrator": ChatMemberStatus.ADMINISTRATOR,
                "member": ChatMemberStatus.MEMBER,
                "restricted": ChatMemberStatus.RESTRICTED,
                "left": ChatMemberStatus.LEFT,
                "kicked": ChatMemberStatus.KICKED,
            }

            if normalized in mapping:
                return mapping[normalized]

            try:
                return ChatMemberStatus(normalized)
            except ValueError:
                db_logger.warning(f"⚠️ Unknown member status: {status}, using MEMBER")
                return ChatMemberStatus.MEMBER

        db_logger.warning(f"⚠️ Invalid member status: {status}, using MEMBER")
        return ChatMemberStatus.MEMBER

    @staticmethod
    @log_exceptions(db_logger)
    async def save_chat(
        session: AsyncSession, *, chat_id: int, chat_type: str, title: str | None = None, is_active: bool = True
    ) -> ChatModel:
        """Сохранение информации о чате"""
        chat_type_enum = await ChatRepository._parse_chat_type(chat_type)

        chat = ChatModel(FID=chat_id, FTitle=title, FType=chat_type_enum, FFlagActive=is_active)

        merged_chat: ChatModel = await session.merge(chat)
        await session.flush()
        return merged_chat

    @staticmethod
    @log_exceptions(db_logger)
    async def save_chat_member(
        session: AsyncSession, *, user_id: int, chat_id: int, status: str, is_active: bool = True
    ) -> ChatMemberModel:
        """Сохранение информации об участнике чата"""
        status_enum: ChatMemberStatus = await ChatRepository._parse_member_status(status)

        member = await ChatRepository.get_chat_member_by_keys(session, user_id=user_id, chat_id=chat_id)
        if member:
            member.FStatus = status_enum
            member.FFlagActive = is_active
        elif is_active:
            member = ChatMemberModel(FK_User=user_id, FK_Chat=chat_id, FStatus=status_enum)
            session.add(member)
        else:
            member = ChatMemberModel(FK_User=user_id, FK_Chat=chat_id, FStatus=status_enum, FFlagActive=False)
            session.add(member)
        await session.flush()
        return member

    @staticmethod
    @log_exceptions(db_logger)
    async def remove_chat_member(session: AsyncSession, user_id: int, chat_id: int) -> bool:
        """Удаление участника из чата"""
        result = await session.execute(
            update(ChatMemberModel)
            .where(
                ChatMemberModel.FK_User == user_id,
                ChatMemberModel.FK_Chat == chat_id,
                ChatMemberModel.FFlagActive.is_(True),
            )
            .values(FFlagActive=False, FStatus=ChatMemberStatus.LEFT)
        )
        await session.commit()
        # Используем rowcount из результата
        return result.rowcount > 0 if hasattr(result, "rowcount") else False

    @staticmethod
    @log_exceptions(db_logger)
    async def get_chats(
        session: AsyncSession, *, chat_id: int | None = None, is_active: bool | None = None
    ) -> list[ChatModel]:
        """Получение списка чатов"""
        query = select(ChatModel)

        if chat_id is not None:
            query = query.where(ChatModel.FID == chat_id)

        if is_active is not None:
            query = query.where(ChatModel.FFlagActive == is_active)

        result: Result = await session.execute(query)
        chats: list[ChatModel] = list(result.scalars().all())
        return chats

    @staticmethod
    @log_exceptions(db_logger)
    async def get_chat_by_id(session: AsyncSession, chat_id: int) -> ChatModel | None:
        """Получение чата по ID"""
        stmt = select(ChatModel).where(ChatModel.FID == chat_id)
        result: Result = await session.execute(stmt)
        chat: ChatModel | None = result.scalar_one_or_none()
        return chat

    @staticmethod
    @log_exceptions(db_logger)
    async def get_chat_member_by_keys(session: AsyncSession, *, user_id: int, chat_id: int) -> ChatMemberModel | None:
        """Получение записи участника чата по внешним ключам"""
        stmt = select(ChatMemberModel).where(
            and_(ChatMemberModel.FK_User == user_id, ChatMemberModel.FK_Chat == chat_id)
        )
        result: Result = await session.execute(stmt)
        member: ChatMemberModel | None = result.scalar_one_or_none()
        return member

    @staticmethod
    @log_exceptions(db_logger)
    async def get_user_chat_members(
        session: AsyncSession, *, chat_id: int | None = None, is_active: bool | None = None
    ) -> list[UserChatMemberModel]:
        """Получение списка участников чата"""
        query = select(
            ChatMemberModel.FK_User.label("FID"),
            UserModel.FUserName,
            UserModel.FFirstName,
            UserModel.FLastName,
            UserModel.FFlagBot,
            ChatMemberModel.FStatus,
        ).join(UserModel, ChatMemberModel.FK_User == UserModel.FID)

        if chat_id is not None:
            query = query.where(ChatMemberModel.FK_Chat == chat_id)

        if is_active is not None:
            query = query.where(ChatMemberModel.FFlagActive == is_active)

        result: Result = await session.execute(query)
        members: list[UserChatMemberModel] = [UserChatMemberModel.from_row(row) for row in result.all()]
        return members

    @staticmethod
    @log_exceptions(db_logger)
    async def get_active_member_ids(
        session: AsyncSession,
        chat_id: int,
    ) -> set[int]:
        """
        Получение ID активных участников чата.

        Args:
            session: Сессия БД
            chat_id: ID чата

        Returns:
            set[int]: Множество ID активных участников
        """
        stmt = select(ChatMemberModel.FK_User).where(
            ChatMemberModel.FK_Chat == chat_id,
            ChatMemberModel.FFlagActive.is_(True),
        )
        result = await session.execute(stmt)
        return {row[0] for row in result.all()}

    @staticmethod
    @log_exceptions(db_logger)
    async def deactivate_missing_members(
        session: AsyncSession,
        chat_id: int,
        active_user_ids: set[int],
    ) -> int:
        """
        Деактивация участников чата, которых нет в списке активных.

        Args:
            session: Сессия БД
            chat_id: ID чата
            active_user_ids: Множество ID активных пользователей

        Returns:
            int: Количество деактивированных участников
        """
        if not active_user_ids:
            # Если список пуст - деактивируем всех
            stmt = (
                update(ChatMemberModel)
                .where(
                    ChatMemberModel.FK_Chat == chat_id,
                    ChatMemberModel.FFlagActive.is_(True),
                )
                .values(
                    FFlagActive=False,
                    FStatus=ChatMemberStatus.LEFT,
                )
            )
        else:
            stmt = (
                update(ChatMemberModel)
                .where(
                    ChatMemberModel.FK_Chat == chat_id,
                    ChatMemberModel.FFlagActive.is_(True),
                    ChatMemberModel.FK_User.not_in(active_user_ids),
                )
                .values(
                    FFlagActive=False,
                    FStatus=ChatMemberStatus.LEFT,
                )
            )

        result = await session.execute(stmt)
        await session.flush()

        deleted = result.rowcount if hasattr(result, "rowcount") else 0
        if deleted > 0:
            db_logger.debug(f"🗑️ Deactivated {deleted} members in chat {chat_id}")

        return deleted

    @staticmethod
    @log_exceptions(db_logger)
    async def update_members_status(
        session: AsyncSession,
        chat_id: int,
        user_ids: list[int],
        status: ChatMemberStatus,
    ) -> int:
        """
        Массовое обновление статуса участников.

        Args:
            session: Сессия БД
            chat_id: ID чата
            user_ids: Список ID пользователей
            status: Новый статус

        Returns:
            int: Количество обновленных участников
        """
        if not user_ids:
            return 0

        stmt = (
            update(ChatMemberModel)
            .where(
                ChatMemberModel.FK_Chat == chat_id,
                ChatMemberModel.FK_User.in_(user_ids),
                ChatMemberModel.FFlagActive.is_(True),
            )
            .values(
                FStatus=status,
                FDateUpdated=datetime_now(),
            )
        )

        result = await session.execute(stmt)
        await session.flush()

        updated = result.rowcount if hasattr(result, "rowcount") else 0
        if updated > 0:
            db_logger.debug(f"🔄 Updated {updated} members status to {status.value} in chat {chat_id}")

        return updated

    @staticmethod
    @log_exceptions(db_logger)
    async def deactivate_missing_chats(
        session: AsyncSession,
        active_chat_ids: set[int],
    ) -> int:
        """
        Деактивация чатов, которых нет в списке активных.

        Args:
            session: Сессия БД
            active_chat_ids: Множество ID активных чатов

        Returns:
            int: Количество деактивированных чатов
        """
        if not active_chat_ids:
            # Если список пуст - деактивируем все чаты
            stmt = update(ChatModel).where(ChatModel.FFlagActive.is_(True)).values(FFlagActive=False)
        else:
            stmt = (
                update(ChatModel)
                .where(
                    ChatModel.FFlagActive.is_(True),
                    ChatModel.FID.not_in(active_chat_ids),
                )
                .values(FFlagActive=False)
            )

        result = await session.execute(stmt)
        await session.flush()

        deleted = result.rowcount if hasattr(result, "rowcount") else 0
        if deleted > 0:
            db_logger.debug(f"🗑️ Deactivated {deleted} chats")

        return deleted

    @staticmethod
    @log_exceptions(db_logger)
    async def update_sync_time(
        session: AsyncSession,
        chat_id: int,
    ) -> None:
        """
        Обновление времени синхронизации чата.

        Args:
            session: Сессия БД
            chat_id: ID чата
        """
        stmt = update(ChatModel).where(ChatModel.FID == chat_id).values(FDateSynced=datetime_now())
        await session.execute(stmt)
        await session.flush()

    @staticmethod
    @log_exceptions(db_logger)
    async def update_member_sync_time(
        session: AsyncSession,
        user_id: int,
        chat_id: int,
    ) -> None:
        """
        Обновление времени синхронизации участника.

        Args:
            session: Сессия БД
            user_id: ID пользователя
            chat_id: ID чата
        """
        stmt = (
            update(ChatMemberModel)
            .where(
                ChatMemberModel.FK_User == user_id,
                ChatMemberModel.FK_Chat == chat_id,
            )
            .values(FDateUpdated=datetime_now())
        )
        await session.execute(stmt)
        await session.flush()

    @staticmethod
    @log_exceptions(db_logger)
    async def deactivate_missing_chat_message(
        session: AsyncSession,
        message_id: int,
        chat_id: int | None = None,
        deleted_by_message_id: int | None = None,
        deleted_by_type: str = "system",
    ) -> bool:
        """Деактивация сообщения в чате"""
        try:
            query = select(ChatMessageModel).where(ChatMessageModel.FID == message_id)
            if chat_id is not None:
                query = query.where(ChatMessageModel.FK_Chat == chat_id)

            result: Result = await session.execute(query)
            message: ChatMessageModel | None = result.scalar_one_or_none()

            if message and not message.FFlagDeleted:
                message.FFlagDeleted = True
                message.FDateDeleted = datetime_now()
                message.FK_DeletedByMessage = deleted_by_message_id
                message.FDeletedByType = deleted_by_type
                await session.commit()
                db_logger.debug(f"✅ Message {message_id} marked as deleted (by {deleted_by_type})")
                return True

            return False

        except Exception as e:
            db_logger.error(f"❌ Failed to mark message {message_id} as deleted: {e}")
            await session.rollback()
            raise

    @staticmethod
    @log_exceptions(db_logger)
    async def get_messages(
        session: AsyncSession,
        chat_id: int | None = None,
        include_deleted: bool = False,
        limit: int = 100,
        offset: int = 0,
        from_date: datetime | None = None,
        to_date: datetime | None = None,
    ) -> list[ChatMessageModel]:
        """Получение сообщений с возможностью фильтрации"""
        query = select(ChatMessageModel)

        if chat_id is not None:
            query = query.where(ChatMessageModel.FK_Chat == chat_id)

        if not include_deleted:
            query = query.where(ChatMessageModel.FFlagDeleted.is_(False))

        if from_date:
            query = query.where(ChatMessageModel.FDateSent >= from_date)

        if to_date:
            query = query.where(ChatMessageModel.FDateSent <= to_date)

        query = query.order_by(ChatMessageModel.FDateSent.desc())
        query = query.limit(limit).offset(offset)

        result: Result = await session.execute(query)
        messages: list[ChatMessageModel] = list(result.scalars().all())
        return messages

    @staticmethod
    @log_exceptions(db_logger)
    async def get_deleted_messages_stats(
        session: AsyncSession, chat_id: int | None = None, days: int = 7
    ) -> dict[str, Any]:
        """Получение статистики по удаленным сообщениям"""
        query = select(
            func.count(ChatMessageModel.FID).label("total_deleted"),
            func.date(ChatMessageModel.FDateDeleted).label("deleted_date"),
        ).where(ChatMessageModel.FFlagDeleted.is_(True))

        if chat_id is not None:
            query = query.where(ChatMessageModel.FK_Chat == chat_id)

        if days:
            from_date = datetime.now() - timedelta(days=days)
            query = query.where(ChatMessageModel.FDateDeleted >= from_date)

        query = query.group_by(func.date(ChatMessageModel.FDateDeleted))
        query = query.order_by(func.date(ChatMessageModel.FDateDeleted).desc())

        result: Result = await session.execute(query)
        rows = result.all()

        total = 0
        by_day = {}
        for row in rows:
            # Используем индексы для доступа к значениям
            total_deleted = row[0]  # Первая колонка - total_deleted
            deleted_date = row[1]  # Вторая колонка - deleted_date

            if total_deleted is not None:
                total += int(total_deleted)

            if deleted_date:
                by_day[str(deleted_date)] = int(total_deleted) if total_deleted is not None else 0

        return {
            "total": total,
            "by_day": by_day,
        }

    @staticmethod
    @log_exceptions(db_logger)
    async def get_deleted_messages_with_initiator(
        session: AsyncSession, chat_id: int | None = None, limit: int = 50, offset: int = 0
    ) -> list[dict[str, Any]]:
        """Получение удаленных сообщений с информацией об инициаторе удаления"""
        query = select(ChatMessageModel, ChatMessageModel.FK_DeletedByMessage.label("initiator_message_id")).where(
            ChatMessageModel.FFlagDeleted.is_(True)
        )

        if chat_id is not None:
            query = query.where(ChatMessageModel.FK_Chat == chat_id)

        query = query.order_by(ChatMessageModel.FDateDeleted.desc())
        query = query.limit(limit).offset(offset)

        result: Result = await session.execute(query)
        rows = result.all()

        deleted_messages: list[dict[str, Any]] = []
        for row in rows:
            msg = row[0]
            deleted_messages.append(
                {
                    "id": msg.FID,
                    "chat_id": msg.FK_Chat,
                    "user_id": msg.fk_user,
                    "text": msg.FText[:100] + "..." if msg.FText and len(msg.FText) > 100 else msg.FText,
                    "deleted_at": msg.FDateDeleted.isoformat() + "Z" if msg.FDateDeleted else None,
                    "deleted_by_type": msg.FDeletedByType,
                    "initiator_message_id": msg.FK_DeletedByMessage,
                    "is_bulk_delete": msg.FK_DeletedByMessage is None and msg.FDeletedByType == "system",
                }
            )

        return deleted_messages

    @staticmethod
    @log_exceptions(db_logger)
    async def get_deletion_stats_by_initiator(
        session: AsyncSession, chat_id: int | None = None, days: int = 7
    ) -> dict[str, Any]:
        """Статистика удалений по типу инициатора"""
        query = select(ChatMessageModel.FDeletedByType, func.count(ChatMessageModel.FID).label("count")).where(
            ChatMessageModel.FFlagDeleted.is_(True)
        )

        if chat_id is not None:
            query = query.where(ChatMessageModel.FK_Chat == chat_id)

        if days:
            from_date = datetime.now() - timedelta(days=days)
            query = query.where(ChatMessageModel.FDateDeleted >= from_date)

        query = query.group_by(ChatMessageModel.FDeletedByType)

        result: Result = await session.execute(query)
        rows = result.all()

        by_type: dict[str, int] = {}
        total = 0
        for row in rows:
            # Используем индексы для доступа к значениям
            deleted_by_type = row[0] or "unknown"
            count_value = row[1]

            count = int(count_value) if count_value is not None else 0
            by_type[deleted_by_type] = count
            total += count

        stats = {
            "by_type": by_type,
            "total": total,
            "period_days": days,
        }

        return stats

    @staticmethod
    @log_exceptions(db_logger)
    async def restore_deleted_message(session: AsyncSession, message_id: int, chat_id: int | None = None) -> bool:
        """Восстановление удаленного сообщения"""
        try:
            query = select(ChatMessageModel).where(
                ChatMessageModel.FID == message_id, ChatMessageModel.FFlagDeleted.is_(True)
            )
            if chat_id is not None:
                query = query.where(ChatMessageModel.FK_Chat == chat_id)

            result: Result = await session.execute(query)
            message: ChatMessageModel | None = result.scalar_one_or_none()

            if message:
                message.FFlagDeleted = False
                message.FDateDeleted = None
                message.FK_DeletedByMessage = None
                message.FDeletedByType = None
                await session.commit()
                db_logger.info(f"✅ Message {message_id} restored")
                return True

            return False

        except Exception as e:
            db_logger.error(f"❌ Failed to restore message {message_id}: {e}")
            await session.rollback()
            raise


__all__ = [
    "ChatRepository",
    "normalize_chat_id",
]
