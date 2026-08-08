from sqlalchemy import func, select
from sqlalchemy.engine import Result
from sqlalchemy.ext.asyncio import AsyncSession

from ...exceptions import log_exceptions
from ...logger import db_logger
from ...models import ChatMessageModel, ErrorModel, UserModel, datetime_now


class UserRepository:
    """Репозиторий для работы с пользователями"""

    # ==================== ОСНОВНЫЕ МЕТОДЫ ====================

    @staticmethod
    @log_exceptions(db_logger)
    async def save_user(
        session: AsyncSession,
        user_id: int,
        chat_id: int | None = None,
        avanpost_id: int | None = None,
        avanpost_group_id: int | None = None,
        first_name: str | None = None,
        last_name: str | None = None,
        username: str | None = None,
        is_bot: bool = False,
        phone: str | None = None,
    ) -> UserModel:
        """Сохранение пользователя и возврат модели"""
        if not user_id or user_id <= 0:
            raise ValueError(f"Invalid user_id: {user_id}")

        if not username:
            username = f"user_{user_id}"

        user: UserModel | None = await session.get(UserModel, user_id)

        if user:
            updated = False

            if chat_id is not None and user.FK_Chat != chat_id:
                user.FK_Chat = chat_id
                updated = True

            if avanpost_id is not None and avanpost_id != user.FID:
                user.FK_Avanpost = avanpost_id
                updated = True

            if avanpost_group_id is not None and user.FK_AvanpostGroup != avanpost_group_id:
                user.FK_AvanpostGroup = avanpost_group_id
                updated = True

            if first_name is not None and user.FFirstName != first_name:
                user.FFirstName = first_name
                updated = True

            if last_name is not None and user.FLastName != last_name:
                user.FLastName = last_name
                updated = True

            if username is not None and user.FUserName != username:
                user.FUserName = username
                updated = True

            if user.FFlagBot != is_bot:
                user.FFlagBot = is_bot
                updated = True

            if phone is not None and user.FPhone != phone:
                user.FPhone = phone
                updated = True

            if updated:
                user.FDateUpdated = datetime_now()
                await session.flush()
                db_logger.debug(f"✅ Updated user {user_id}")
            else:
                db_logger.debug(f"ℹ️ User {user_id} already exists")
        else:
            user = UserModel(
                FID=user_id,
                FK_Chat=chat_id,
                FK_Avanpost=avanpost_id,
                FK_AvanpostGroup=avanpost_group_id,
                FUserName=username,
                FFirstName=first_name or "",
                FLastName=last_name,
                FFlagBot=is_bot,
                FPhone=phone,
                FDateCreated=datetime_now(),
                FDateUpdated=datetime_now(),
                FDateLastActivity=datetime_now(),
            )
            session.add(user)
            await session.flush()
            db_logger.info(f"✅ Created new user {user_id}")

        return user

    # ==================== МЕТОДЫ ПОИСКА ====================

    @staticmethod
    @log_exceptions(db_logger)
    async def get_user_by_id(session: AsyncSession, user_id: int) -> UserModel | None:
        """Получение пользователя по FID"""
        if not user_id or user_id <= 0:
            return None

        user: UserModel | None = await session.get(UserModel, user_id)
        return user

    @staticmethod
    @log_exceptions(db_logger)
    async def get_user_by_phone(session: AsyncSession, phone: str) -> UserModel | None:
        """Получение пользователя по номеру телефона"""
        if not phone:
            return None

        stmt = select(UserModel).where(UserModel.FPhone == phone)
        result: Result = await session.execute(stmt)
        user: UserModel | None = result.scalar_one_or_none()
        return user

    @staticmethod
    @log_exceptions(db_logger)
    async def get_users_by_group(session: AsyncSession, group_id: int) -> list[UserModel]:
        """Получение списка пользователей по ID группы"""
        if not group_id:
            return []

        stmt = select(UserModel).where(UserModel.FK_AvanpostGroup == group_id)
        result: Result = await session.execute(stmt)
        users: list[UserModel] = list(result.scalars().all())
        return users

    @staticmethod
    @log_exceptions(db_logger)
    async def get_authorized_users(session: AsyncSession, limit: int | None = None, offset: int = 0) -> list[UserModel]:
        """Получение списка авторизованных пользователей"""
        stmt = select(UserModel).where(UserModel.FK_Avanpost.is_not(None)).order_by(UserModel.FID).offset(offset)

        if limit:
            stmt = stmt.limit(limit)

        result: Result = await session.execute(stmt)
        users: list[UserModel] = list(result.scalars().all())
        return users

    @staticmethod
    @log_exceptions(db_logger)
    async def get_all_users(session: AsyncSession, limit: int | None = None, offset: int = 0) -> list[UserModel]:
        """Получение списка всех пользователей"""
        stmt = select(UserModel).order_by(UserModel.FID).offset(offset)
        if limit:
            stmt = stmt.limit(limit)

        result: Result = await session.execute(stmt)
        users: list[UserModel] = list(result.scalars().all())
        return users

    @staticmethod
    @log_exceptions(db_logger)
    async def search_users(session: AsyncSession, query: str, limit: int = 20) -> list[UserModel]:
        """Поиск пользователей по имени, фамилии или username"""
        if not query or not query.strip():
            return []

        search_pattern = f"%{query.strip()}%"

        stmt = (
            select(UserModel)
            .where(
                (UserModel.FUserName.ilike(search_pattern))
                | (UserModel.FFirstName.ilike(search_pattern))
                | (UserModel.FLastName.ilike(search_pattern))
            )
            .limit(limit)
        )

        result: Result = await session.execute(stmt)
        users: list[UserModel] = list(result.scalars().all())
        return users

    # ==================== МЕТОДЫ ПРОВЕРКИ ====================

    @staticmethod
    @log_exceptions(db_logger)
    async def is_user_authorized(session: AsyncSession, user_id: int) -> bool:
        """Проверка авторизации пользователя по Telegram ID"""
        if not user_id or user_id <= 0:
            return False

        from sqlalchemy import and_

        stmt = select(UserModel).where(and_(UserModel.FID == user_id, UserModel.FK_Avanpost.is_not(None)))
        result: Result = await session.execute(stmt)
        return result.first() is not None

    # ==================== МЕТОДЫ ОБНОВЛЕНИЯ ====================

    @staticmethod
    @log_exceptions(db_logger)
    async def update_last_activity(session: AsyncSession, user_id: int) -> bool:
        """Обновление времени последней активности пользователя"""
        if not user_id or user_id <= 0:
            return False

        user: UserModel | None = await session.get(UserModel, user_id)
        if user:
            user.FDateLastActivity = datetime_now()
            await session.flush()
            return True
        return False

    @staticmethod
    @log_exceptions(db_logger)
    async def clear_telegram_data(session: AsyncSession, user_id: int) -> bool:
        """Очистка Telegram данных пользователя (выход из системы)"""
        if not user_id or user_id <= 0:
            return False

        user: UserModel | None = await session.get(UserModel, user_id)
        if not user:
            return False

        user.FK_Chat = None
        user.FK_Avanpost = None
        user.FK_AvanpostGroup = None
        user.FDateUpdated = datetime_now()
        await session.flush()
        db_logger.info(f"✅ Cleared Telegram data for user {user_id}")
        return True

    # ==================== МЕТОДЫ СТАТИСТИКИ ====================

    @staticmethod
    @log_exceptions(db_logger)
    async def get_user_stats(session: AsyncSession, user_id: int) -> dict:
        """Получение статистики пользователя"""
        user: UserModel | None = await session.get(UserModel, user_id)
        if not user:
            return {}

        messages_count: int = (
            await session.scalar(
                select(func.count()).select_from(ChatMessageModel).where(ChatMessageModel.FK_User == user_id)
            )
            or 0
        )

        errors_resolved: int = (
            await session.scalar(select(func.count()).select_from(ErrorModel).where(ErrorModel.FResolvedBy == user_id))
            or 0
        )

        return {
            "user_id": user_id,
            "username": user.FUserName,
            "fullname": user.fullname,
            "is_authenticated": user.is_authenticated,
            "messages_count": messages_count,
            "errors_resolved": errors_resolved,
            "last_activity": user.FDateLastActivity.isoformat() if user.FDateLastActivity else None,
            "created_at": user.FDateCreated.isoformat() if user.FDateCreated else None,
            "group_id": user.FK_AvanpostGroup,
        }


__all__ = ["UserRepository"]
