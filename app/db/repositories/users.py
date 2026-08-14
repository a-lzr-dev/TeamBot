from typing import Any

from sqlalchemy import func, select
from sqlalchemy.engine import Result
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from ...exceptions import log_exceptions
from ...logger import db_logger
from ...models import (
    AvanpostUserModel,
    ChatMessageModel,
    ErrorModel,
    UserModel,
    datetime_now,
)


class UserRepository:
    """Репозиторий для работы с пользователями"""

    # ==================== ОСНОВНЫЕ МЕТОДЫ ====================

    @staticmethod
    @log_exceptions(db_logger)
    async def save_user(
        session: AsyncSession,
        user_id: int,
        chat_id: int | None = None,
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
    async def get_authorized_users(session: AsyncSession, limit: int | None = None, offset: int = 0) -> list[UserModel]:
        """Получение списка авторизованных пользователей (у которых есть AvanpostUser)"""
        stmt = (
            select(UserModel)
            .join(AvanpostUserModel, UserModel.FID == AvanpostUserModel.FK_User)
            .order_by(UserModel.FID)
            .offset(offset)
        )

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

    # ==================== МЕТОДЫ РАБОТЫ С AVANPOST USER ====================

    @staticmethod
    @log_exceptions(db_logger)
    async def get_avanpost_user_data(
        session: AsyncSession,
        avanpost_user_id: int,
    ) -> dict[str, Any] | None:
        """
        Получение данных пользователя из TAvanpostUsers (main БД).
        Использует SQLAlchemy ORM.

        Args:
            session: Сессия БД (main)
            avanpost_user_id: ID пользователя в TAvanpostUsers

        Returns:
            dict | None: Данные пользователя или None
        """
        if not avanpost_user_id or avanpost_user_id <= 0:
            return None

        try:
            stmt = select(AvanpostUserModel).where(AvanpostUserModel.FID == avanpost_user_id)
            result = await session.execute(stmt)
            user = result.scalar_one_or_none()

            if not user:
                return None

            return {
                "FID": user.FID,
                "FK_Contact": user.FK_Contact,
                "FK_MenuGroup": user.FK_MenuGroup,
                "FK_Owner": user.FK_Owner,
                "FK_MotorCade": user.FK_MotorCade,
                "FK_Language": user.FK_Language,
                "FName": user.FName,
                "FPhone": user.FPhone,
            }

        except Exception as e:
            db_logger.error(f"❌ Failed to get Avanpost user data: {e}", exc_info=True)
            return None

    @staticmethod
    @log_exceptions(db_logger)
    async def get_avanpost_user_by_telegram_id(
        session: AsyncSession,
        telegram_user_id: int,
    ) -> AvanpostUserModel | None:
        """
        Получение AvanpostUser по Telegram ID.

        Args:
            session: Сессия БД (main)
            telegram_user_id: ID пользователя в Telegram (TUsers.FID)

        Returns:
            AvanpostUserModel | None: Модель AvanpostUser или None
        """
        if not telegram_user_id or telegram_user_id <= 0:
            return None

        try:
            stmt = select(AvanpostUserModel).where(AvanpostUserModel.FK_User == telegram_user_id)
            result = await session.execute(stmt)
            return result.scalar_one_or_none()  # type: ignore[no-any-return]

        except Exception as e:
            db_logger.error(f"❌ Failed to get Avanpost user by Telegram ID: {e}", exc_info=True)
            return None

    @staticmethod
    @log_exceptions(db_logger)
    async def update_avanpost_user_telegram_link(
        session: AsyncSession,
        avanpost_user_id: int,
        telegram_user_id: int,
    ) -> bool:
        """
        Обновление связи AvanpostUser с Telegram пользователем.

        Args:
            session: Сессия БД (main)
            avanpost_user_id: ID пользователя в Avanpost
            telegram_user_id: ID пользователя в Telegram

        Returns:
            bool: Успешно ли обновлено
        """
        if not avanpost_user_id or avanpost_user_id <= 0:
            return False
        if not telegram_user_id or telegram_user_id <= 0:
            return False

        try:
            stmt = select(AvanpostUserModel).where(AvanpostUserModel.FID == avanpost_user_id)
            result = await session.execute(stmt)
            user = result.scalar_one_or_none()

            if not user:
                db_logger.warning(f"⚠️ AvanpostUser {avanpost_user_id} not found")
                return False

            user.FK_User = telegram_user_id
            await session.flush()

            db_logger.info(f"✅ Updated AvanpostUser.FK_User = {telegram_user_id} for user {avanpost_user_id}")
            return True

        except Exception as e:
            db_logger.error(f"❌ Failed to update AvanpostUser FK_User: {e}", exc_info=True)
            return False

    @staticmethod
    @log_exceptions(db_logger)
    async def create_avanpost_user(
        session: AsyncSession,
        avanpost_user_id: int,
        fk_contact: int | None = None,
        fk_language: str = "RU",
        fk_menugroup: int | None = None,
        fk_owner: int | None = None,
        fk_motorcade: int | None = None,
        fname: str | None = None,
        fphone: str | None = None,
        telegram_user_id: int | None = None,
    ) -> AvanpostUserModel | None:
        """
        Создание нового пользователя в TAvanpostUsers.

        Args:
            session: Сессия БД (main)
            avanpost_user_id: ID пользователя в Avanpost
            fk_contact: ID контакта
            fk_language: Код языка (по умолчанию 'RU')
            fk_menugroup: ID группы меню
            fk_owner: ID владельца
            fk_motorcade: ID моторкада
            fname: Имя
            fphone: Телефон
            telegram_user_id: ID пользователя в Telegram

        Returns:
            AvanpostUserModel | None: Созданная модель или None
        """
        if not avanpost_user_id or avanpost_user_id <= 0:
            db_logger.error(f"❌ Invalid avanpost_user_id: {avanpost_user_id}")
            return None

        try:
            user = AvanpostUserModel(
                FID=avanpost_user_id,
                FK_Contact=fk_contact,
                FK_Language=fk_language[:2] if fk_language else "ru",
                FK_MenuGroup=fk_menugroup,
                FK_Owner=fk_owner,
                FK_MotorCade=fk_motorcade,
                FK_User=telegram_user_id,
                FName=fname[:50] if fname else None,
                FPhone=fphone[:30] if fphone else None,
            )
            session.add(user)
            await session.flush()

            db_logger.info(f"✅ Created AvanpostUser {avanpost_user_id} with contact {fk_contact}")
            return user

        except Exception as e:
            db_logger.error(f"❌ Failed to create AvanpostUser: {e}", exc_info=True)
            return None

    # ==================== НОВЫЙ МЕТОД ДЛЯ СОЗДАНИЯ/ОБНОВЛЕНИЯ ====================

    @staticmethod
    @log_exceptions(db_logger)
    async def create_or_update_avanpost_user(
        session: AsyncSession,
        telegram_user_id: int,
        avanpost_user_id: int,
        fk_contact: int | None = None,
        fk_language: str = "RU",
        fk_menugroup: int | None = None,
        fk_owner: int | None = None,
        fk_motorcade: int | None = None,
        fname: str | None = None,
        fphone: str | None = None,
    ) -> tuple[bool, AvanpostUserModel | None]:
        """
        Создание или обновление связи пользователя с Avanpost.
        Сначала проверяет существование записи, если есть - обновляет, если нет - создает.

        Args:
            session: Сессия БД
            telegram_user_id: ID пользователя в Telegram
            avanpost_user_id: ID пользователя в Avanpost
            fk_contact: ID контакта
            fk_language: Код языка
            fk_menugroup: ID группы меню
            fk_owner: ID владельца
            fk_motorcade: ID моторкада
            fname: Имя
            fphone: Телефон

        Returns:
            tuple[bool, AvanpostUserModel | None]: (успех, модель пользователя)
        """
        if not avanpost_user_id or avanpost_user_id <= 0:
            db_logger.error(f"❌ Invalid avanpost_user_id: {avanpost_user_id}")
            return False, None

        if not telegram_user_id or telegram_user_id <= 0:
            db_logger.error(f"❌ Invalid telegram_user_id: {telegram_user_id}")
            return False, None

        try:
            # 1. Проверка существования пользователя в TUsers
            user = await UserRepository.get_user_by_id(session, telegram_user_id)
            if not user:
                db_logger.error(f"❌ User {telegram_user_id} not found")
                return False, None

            # 2. Проверка существования AvanpostUser
            avanpost_user = await UserRepository.get_avanpost_user_by_telegram_id(session, telegram_user_id)

            if avanpost_user:
                # Обновление существующей записи
                if fk_contact is not None:
                    avanpost_user.FK_Contact = fk_contact
                if fk_menugroup is not None:
                    avanpost_user.FK_MenuGroup = fk_menugroup
                if fk_owner is not None:
                    avanpost_user.FK_Owner = fk_owner
                if fk_motorcade is not None:
                    avanpost_user.FK_MotorCade = fk_motorcade
                if fk_language:
                    avanpost_user.FK_Language = fk_language[:2]
                if fname:
                    avanpost_user.FName = fname[:50]
                if fphone:
                    avanpost_user.FPhone = fphone[:30]

                # Всегда обновляем связь с Telegram
                avanpost_user.FK_User = telegram_user_id

                await session.flush()
                db_logger.info(f"✅ Updated AvanpostUser {avanpost_user.FID} for user {telegram_user_id}")
                return True, avanpost_user

            # 3. Создание нового AvanpostUser
            new_user = await UserRepository.create_avanpost_user(
                session=session,
                avanpost_user_id=avanpost_user_id,
                fk_contact=fk_contact,
                fk_language=fk_language,
                fk_menugroup=fk_menugroup,
                fk_owner=fk_owner,
                fk_motorcade=fk_motorcade,
                fname=fname,
                fphone=fphone,
                telegram_user_id=telegram_user_id,
            )

            if new_user:
                db_logger.info(f"✅ Created AvanpostUser {avanpost_user_id} for user {telegram_user_id}")
                return True, new_user
            else:
                db_logger.error(f"❌ Failed to create AvanpostUser {avanpost_user_id}")
                return False, None

        except Exception as e:
            db_logger.error(f"❌ Failed to create/update AvanpostUser: {e}", exc_info=True)
            return False, None

    # ==================== МЕТОДЫ ДЛЯ РАБОТЫ С AVANPOST (с предзагрузкой) ====================

    @staticmethod
    @log_exceptions(db_logger)
    async def get_user_with_avanpost(session: AsyncSession, user_id: int) -> UserModel | None:
        """Получение пользователя с предзагруженным AvanpostUser"""
        if not user_id or user_id <= 0:
            return None

        stmt = select(UserModel).where(UserModel.FID == user_id).options(selectinload(UserModel.avanpost_user))
        result = await session.execute(stmt)
        return result.scalar_one_or_none()  # type: ignore[no-any-return]

    @staticmethod
    @log_exceptions(db_logger)
    async def logout_user(session: AsyncSession, user_id: int) -> bool:
        """
        Выход пользователя из системы.
        Удаляет связь с AvanpostUser и очищает данные.
        """
        if not user_id or user_id <= 0:
            return False

        # Используем метод с предзагрузкой
        user = await UserRepository.get_user_with_avanpost(session, user_id)

        if not user:
            db_logger.warning(f"⚠️ User {user_id} not found for logout")
            return False

        # Удаляем связь с AvanpostUser
        if user.avanpost_user:
            await session.delete(user.avanpost_user)
            db_logger.info(f"✅ Deleted AvanpostUser for user {user_id}")

        # Очищаем Telegram данные
        user.FK_Chat = None
        user.FDateUpdated = datetime_now()

        await session.flush()
        db_logger.info(f"✅ User {user_id} logged out")
        return True

    @staticmethod
    @log_exceptions(db_logger)
    async def create_or_update_avanpost_user_upsert(
        session: AsyncSession,
        telegram_user_id: int,
        avanpost_user_id: int,
        fk_contact: int | None = None,
        fk_language: str = "RU",
        fk_menugroup: int | None = None,
        fk_owner: int | None = None,
        fk_motorcade: int | None = None,
        fname: str | None = None,
        fphone: str | None = None,
    ) -> tuple[bool, AvanpostUserModel | None]:
        """
        Создание или обновление связи пользователя с Avanpost через UPSERT (ON CONFLICT DO UPDATE).
        Использует прямой SQL INSERT ... ON CONFLICT.
        """
        if not avanpost_user_id or avanpost_user_id <= 0:
            db_logger.error(f"❌ Invalid avanpost_user_id: {avanpost_user_id}")
            return False, None

        if not telegram_user_id or telegram_user_id <= 0:
            db_logger.error(f"❌ Invalid telegram_user_id: {telegram_user_id}")
            return False, None

        try:
            from sqlalchemy.dialects.postgresql import insert

            from ...models import AvanpostUserModel

            # Подготовка данных
            values = {
                "FID": avanpost_user_id,
                "FK_User": telegram_user_id,
                "FK_Contact": fk_contact,
                "FK_MenuGroup": fk_menugroup,
                "FK_Owner": fk_owner,
                "FK_MotorCade": fk_motorcade,
                "FK_Language": fk_language[:2] if fk_language else "RU",
                "FName": fname[:50] if fname else None,
                "FPhone": fphone[:30] if fphone else None,
            }

            # UPSERT: INSERT ... ON CONFLICT (FID) DO UPDATE
            stmt = insert(AvanpostUserModel).values(**values)
            stmt = stmt.on_conflict_do_update(
                index_elements=["FID"],
                set_={
                    "FK_User": stmt.excluded.FK_User,
                    "FK_Contact": stmt.excluded.FK_Contact,
                    "FK_MenuGroup": stmt.excluded.FK_MenuGroup,
                    "FK_Owner": stmt.excluded.FK_Owner,
                    "FK_MotorCade": stmt.excluded.FK_MotorCade,
                    "FK_Language": stmt.excluded.FK_Language,
                    "FName": stmt.excluded.FName,
                    "FPhone": stmt.excluded.FPhone,
                },
            )

            await session.execute(stmt)
            await session.flush()

            # Получение созданной/обновленной записи
            result = await session.execute(select(AvanpostUserModel).where(AvanpostUserModel.FID == avanpost_user_id))
            user = result.scalar_one_or_none()

            if user:
                db_logger.info(f"✅ UPSERT AvanpostUser {avanpost_user_id} for user {telegram_user_id}")
                return True, user
            else:
                db_logger.error(f"❌ Failed to get AvanpostUser {avanpost_user_id}")
                return False, None

        except Exception as e:
            db_logger.error(f"❌ Failed to UPSERT AvanpostUser: {e}", exc_info=True)
            return False, None

    @staticmethod
    @log_exceptions(db_logger)
    async def get_user_group_id(session: AsyncSession, user_id: int) -> int | None:
        """Получение ID группы действий пользователя из AvanpostUser"""
        if not user_id or user_id <= 0:
            return None

        user = await UserRepository.get_user_with_avanpost(session, user_id)
        if user and user.avanpost_user:
            return user.avanpost_user.FK_MenuGroup  # type: ignore[no-any-return]

        return None

    @staticmethod
    @log_exceptions(db_logger)
    async def get_authenticated_user_with_avanpost(session: AsyncSession, user_id: int) -> UserModel | None:
        """
        Получение авторизованного пользователя с предзагруженным AvanpostUser.
        Обновляет время последней активности.
        """
        if not user_id or user_id <= 0:
            return None

        user = await UserRepository.get_user_with_avanpost(session, user_id)

        if user and user.avanpost_user:
            user.FDateLastActivity = datetime_now()
            await session.flush()
            return user

        return None

    # ==================== МЕТОДЫ ПРОВЕРКИ ====================

    @staticmethod
    @log_exceptions(db_logger)
    async def is_user_authorized(session: AsyncSession, user_id: int) -> bool:
        """Проверка авторизации пользователя по наличию AvanpostUser"""
        if not user_id or user_id <= 0:
            return False

        stmt = select(AvanpostUserModel).where(AvanpostUserModel.FK_User == user_id)
        result: Result = await session.execute(stmt)
        return result.first() is not None

    @staticmethod
    @log_exceptions(db_logger)
    async def is_user_authenticated(session: AsyncSession, user_id: int) -> bool:
        """
        Проверка авторизации пользователя с обновлением времени активности.
        Использует selectinload для предотвращения MissingGreenlet ошибки.

        Args:
            session: Сессия БД
            user_id: ID пользователя

        Returns:
            bool: True если пользователь авторизован (есть связь с AvanpostUser)
        """
        if not user_id or user_id <= 0:
            return False

        try:
            # Использование selectinload для жадной загрузки связи
            stmt = select(UserModel).where(UserModel.FID == user_id).options(selectinload(UserModel.avanpost_user))
            result = await session.execute(stmt)
            user = result.scalar_one_or_none()

            if user and user.avanpost_user:
                # Обновление времени последней активности
                user.FDateLastActivity = datetime_now()
                await session.flush()
                return True

            return False

        except Exception as e:
            db_logger.error(f"❌ Failed to check user authentication: {e}")
            return False

    @staticmethod
    @log_exceptions(db_logger)
    async def get_authenticated_user(session: AsyncSession, user_id: int) -> UserModel | None:
        """
        Получение пользователя с предзагруженной связью AvanpostUser.

        Args:
            session: Сессия БД
            user_id: ID пользователя

        Returns:
            UserModel | None: Пользователь с загруженной связью или None
        """
        if not user_id or user_id <= 0:
            return None

        try:
            stmt = select(UserModel).where(UserModel.FID == user_id).options(selectinload(UserModel.avanpost_user))
            result = await session.execute(stmt)
            user = result.scalar_one_or_none()

            if user:
                user.FDateLastActivity = datetime_now()
                await session.flush()

            return user  # type: ignore[no-any-return]

        except Exception as e:
            db_logger.error(f"❌ Failed to get authenticated user: {e}")
            return None

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
        """Очистка Telegram данных пользователя (выход из системы) - удаляем AvanpostUser связь"""
        if not user_id or user_id <= 0:
            return False

        user: UserModel | None = await session.get(UserModel, user_id)
        if not user:
            return False

        # Удаление связи с AvanpostUser
        if user.avanpost_user:
            # Удаление записи из TAvanpostUsers для этого пользователя
            await session.delete(user.avanpost_user)
            db_logger.info(f"✅ Deleted AvanpostUser for user {user_id}")

        user.FK_Chat = None
        user.FDateUpdated = datetime_now()
        await session.flush()
        db_logger.info(f"✅ Cleared Telegram data for user {user_id}")
        return True

    # ==================== МЕТОДЫ СТАТИСТИКИ ====================

    @staticmethod
    @log_exceptions(db_logger)
    async def get_user_stats(session: AsyncSession, user_id: int) -> dict[str, Any]:
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
            "avanpost_id": user.avanpost_id,
            "avanpost_group_id": user.avanpost_group_id,
            "messages_count": messages_count,
            "errors_resolved": errors_resolved,
            "last_activity": user.FDateLastActivity.isoformat() if user.FDateLastActivity else None,
            "created_at": user.FDateCreated.isoformat() if user.FDateCreated else None,
        }


__all__ = ["UserRepository"]
