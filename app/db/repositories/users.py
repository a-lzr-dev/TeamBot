"""
Репозиторий для работы с пользователями Telegram (TUsers) и их связями с Avanpost.

Содержит методы для:
1. Базовых операций с пользователями (создание, обновление, поиск)
2. Работы со связями пользователей с Avanpost
3. Проверки авторизации и аутентификации
4. Статистики пользователей
"""

from typing import Any, Optional

from sqlalchemy import func, select
from sqlalchemy.engine import Result
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from ...logger import db_logger
from ...models import (
    AvanpostUserModel,
    ChatMessageModel,
    ErrorModel,
    UserModel,
    datetime_now,
)
from ...utils.decorators import log_exceptions


class UserRepository:
    """
    Репозиторий для работы с пользователями.
    """

    # ==================== 1. БАЗОВЫЕ ОПЕРАЦИИ ====================

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
        """
        Сохранение пользователя (создание или обновление).

        Args:
            session: Сессия БД
            user_id: ID пользователя в Telegram
            chat_id: ID чата (опционально)
            first_name: Имя
            last_name: Фамилия
            username: Username
            is_bot: Является ли ботом
            phone: Номер телефона

        Returns:
            UserModel: Сохраненная модель пользователя

        Raises:
            ValueError: Если user_id невалидный
        """
        if not user_id or user_id <= 0:
            raise ValueError(f"Invalid user_id: {user_id}")

        if not username:
            username = f"user_{user_id}"

        db_logger.info(f"💾 [save_user] Saving user {user_id}")

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
                db_logger.info(f"✅ [save_user] Updated user {user_id}")
            else:
                db_logger.debug(f"ℹ️ [save_user] User {user_id} already exists")
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
            db_logger.info(f"✅ [save_user] Created new user {user_id}")

        return user

    @staticmethod
    @log_exceptions(db_logger)
    async def get_user_by_id(session: AsyncSession, user_id: int) -> UserModel | None:
        """
        Получение пользователя по ID.

        Args:
            session: Сессия БД
            user_id: ID пользователя

        Returns:
            UserModel | None: Найденный пользователь или None
        """
        if not user_id or user_id <= 0:
            return None

        db_logger.info(f"🔍 [get_user_by_id] Getting user by ID: {user_id}")

        user: UserModel | None = await session.get(UserModel, user_id)

        if user:
            db_logger.info(f"✅ [get_user_by_id] Found user {user_id}")
        else:
            db_logger.warning(f"⚠️ [get_user_by_id] User {user_id} not found")

        return user

    @staticmethod
    @log_exceptions(db_logger)
    async def get_user_by_phone(session: AsyncSession, phone: str) -> UserModel | None:
        """
        Получение пользователя по номеру телефона.

        Args:
            session: Сессия БД
            phone: Номер телефона

        Returns:
            UserModel | None: Найденный пользователь или None
        """
        if not phone:
            db_logger.debug("ℹ️ [get_user_by_phone] No phone provided")
            return None

        db_logger.info(f"🔍 [get_user_by_phone] Getting user by phone: {phone}")

        stmt = select(UserModel).where(UserModel.FPhone == phone)

        db_logger.debug(f"📝 SQL: {stmt.compile(compile_kwargs={'literal_binds': True})}")

        result: Result = await session.execute(stmt)
        user: UserModel | None = result.scalar_one_or_none()

        if user:
            db_logger.info(f"✅ [get_user_by_phone] Found user {user.FID} for phone {phone}")
        else:
            db_logger.warning(f"⚠️ [get_user_by_phone] No user found for phone {phone}")

        return user

    # ==================== 2. ПОИСК И СПИСКИ ПОЛЬЗОВАТЕЛЕЙ ====================

    @staticmethod
    @log_exceptions(db_logger)
    async def get_all_users(
        session: AsyncSession,
        limit: int | None = None,
        offset: int = 0,
    ) -> list[UserModel]:
        """
        Получение списка всех пользователей.

        Args:
            session: Сессия БД
            limit: Лимит записей
            offset: Смещение

        Returns:
            list[UserModel]: Список пользователей
        """
        db_logger.info(f"📋 [get_all_users] Getting all users (limit={limit}, offset={offset})")

        stmt = select(UserModel).order_by(UserModel.FID).offset(offset)
        if limit:
            stmt = stmt.limit(limit)

        db_logger.debug(f"📝 SQL: {stmt.compile(compile_kwargs={'literal_binds': True})}")

        result: Result = await session.execute(stmt)
        users: list[UserModel] = list(result.scalars().all())

        db_logger.info(f"✅ [get_all_users] Found {len(users)} users")
        return users

    @staticmethod
    @log_exceptions(db_logger)
    async def get_authorized_users(
        session: AsyncSession,
        limit: int | None = None,
        offset: int = 0,
    ) -> list[UserModel]:
        """
        Получение списка авторизованных пользователей.

        Использует EXISTS для проверки наличия связи с AvanpostUser.

        Args:
            session: Сессия БД
            limit: Лимит записей
            offset: Смещение

        Returns:
            list[UserModel]: Список авторизованных пользователей
        """
        db_logger.info(f"📋 [get_authorized_users] Getting authorized users (limit={limit}, offset={offset})")

        from sqlalchemy import exists

        from ...models import AvanpostUserLinkModel

        # Подзапрос для проверки наличия связи
        has_avanpost_link = exists().where(AvanpostUserLinkModel.FK_Link == UserModel.FID)

        stmt = select(UserModel).where(has_avanpost_link).order_by(UserModel.FID).offset(offset)

        if limit:
            stmt = stmt.limit(limit)

        db_logger.debug(f"📝 SQL: {stmt.compile(compile_kwargs={'literal_binds': True})}")

        result: Result = await session.execute(stmt)
        users: list[UserModel] = list(result.scalars().all())

        db_logger.info(f"✅ [get_authorized_users] Found {len(users)} authorized users")
        return users

    @staticmethod
    @log_exceptions(db_logger)
    async def get_authorized_users_count(session: AsyncSession) -> int:
        """
        Получение количества авторизованных пользователей.

        Использует AvanpostUserLinkModel для подсчета связей.

        Args:
            session: Сессия БД

        Returns:
            int: Количество авторизованных пользователей
        """
        db_logger.info("📊 [get_authorized_users_count] Getting authorized users count")

        try:
            from ...models import AvanpostUserLinkModel

            # Подсчет количества записей в AvanpostUserLinkModel
            stmt = (
                select(func.count())
                .select_from(AvanpostUserLinkModel)
                .where(AvanpostUserLinkModel.FK_Link.is_not(None))
            )

            db_logger.debug(f"📝 SQL: {stmt.compile(compile_kwargs={'literal_binds': True})}")

            result = await session.execute(stmt)
            count = result.scalar() or 0

            db_logger.info(f"✅ [get_authorized_users_count] Authorized users count: {count}")
            return count

        except Exception as e:
            db_logger.error(f"❌ [get_authorized_users_count] Failed to get authorized users count: {e}", exc_info=True)
            return 0

    @staticmethod
    @log_exceptions(db_logger)
    async def search_users(
        session: AsyncSession,
        query: str,
        limit: int = 20,
    ) -> list[UserModel]:
        """
        Поиск пользователей по имени, фамилии или username.

        Args:
            session: Сессия БД
            query: Поисковый запрос
            limit: Лимит записей

        Returns:
            list[UserModel]: Список найденных пользователей
        """
        if not query or not query.strip():
            db_logger.debug("ℹ️ [search_users] Empty query")
            return []

        db_logger.info(f"🔍 [search_users] Searching users by: {query}")

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

        db_logger.debug(f"📝 SQL: {stmt.compile(compile_kwargs={'literal_binds': True})}")

        result: Result = await session.execute(stmt)
        users: list[UserModel] = list(result.scalars().all())

        db_logger.info(f"✅ [search_users] Found {len(users)} users matching '{query}'")
        return users

    # ==================== 3. РАБОТА С AVANPOST ПОЛЬЗОВАТЕЛЯМИ ====================

    @staticmethod
    @log_exceptions(db_logger)
    async def get_all_avanpost_users(
        session: AsyncSession,
        limit: int | None = None,
        offset: int = 0,
    ) -> list[AvanpostUserModel]:
        """
        Получение всех пользователей Avanpost (TAvanpostUsers).

        Args:
            session: Сессия БД
            limit: Лимит записей
            offset: Смещение

        Returns:
            list[AvanpostUserModel]: Список пользователей Avanpost
        """
        db_logger.info(f"📋 [get_all_avanpost_users] Getting all Avanpost users (limit={limit}, offset={offset})")

        stmt = (
            select(AvanpostUserModel)
            .options(selectinload(AvanpostUserModel.user_link))
            .order_by(AvanpostUserModel.FID)
            .offset(offset)
        )

        if limit:
            stmt = stmt.limit(limit)

        db_logger.debug(f"📝 SQL: {stmt.compile(compile_kwargs={'literal_binds': True})}")

        result = await session.execute(stmt)
        users = list(result.scalars().all())

        db_logger.info(f"✅ [get_all_avanpost_users] Found {len(users)} Avanpost users")
        return users

    @staticmethod
    @log_exceptions(db_logger)
    async def get_avanpost_user_data(
        session: AsyncSession,
        avanpost_user_id: int,
    ) -> dict[str, Any] | None:
        """
        Получение данных пользователя из TAvanpostUsers.

        Args:
            session: Сессия БД (main)
            avanpost_user_id: ID пользователя в TAvanpostUsers

        Returns:
            dict | None: Данные пользователя или None
        """
        if not avanpost_user_id or avanpost_user_id <= 0:
            return None

        db_logger.info(f"🔍 [get_avanpost_user_data] Getting Avanpost user data for ID: {avanpost_user_id}")

        try:
            stmt = select(AvanpostUserModel).where(AvanpostUserModel.FID == avanpost_user_id)

            db_logger.debug(f"📝 SQL: {stmt.compile(compile_kwargs={'literal_binds': True})}")

            result = await session.execute(stmt)
            user = result.scalar_one_or_none()

            if not user:
                db_logger.warning(f"⚠️ [get_avanpost_user_data] Avanpost user {avanpost_user_id} not found")
                return None

            user_data = {
                "FID": user.FID,
                "FK_Contact": user.FK_Contact,
                "FK_MenuGroup": user.FK_MenuGroup,
                "FK_Owner": user.FK_Owner,
                "FK_MotorCade": user.FK_MotorCade,
                "FK_Language": user.FK_Language,
                "FName": user.FName,
                "FPhone": user.FPhone,
            }

            db_logger.info(f"✅ [get_avanpost_user_data] Found Avanpost user {avanpost_user_id}")
            return user_data

        except Exception as e:
            db_logger.error(f"❌ [get_avanpost_user_data] Failed to get Avanpost user data: {e}", exc_info=True)
            return None

    @staticmethod
    @log_exceptions(db_logger)
    async def get_avanpost_user_by_telegram_id(
        session: AsyncSession,
        telegram_user_id: int,
    ) -> AvanpostUserModel | None:
        """
        Получение AvanpostUser по Telegram ID.

        Использует цепочку: User -> AvanpostUserLink -> AvanpostUser

        Args:
            session: Сессия БД (main)
            telegram_user_id: ID пользователя в Telegram (TUsers.FID)

        Returns:
            AvanpostUserModel | None: Модель AvanpostUser или None
        """
        if not telegram_user_id or telegram_user_id <= 0:
            return None

        db_logger.info(
            f"🔍 [get_avanpost_user_by_telegram_id] Getting Avanpost user for Telegram ID: {telegram_user_id}"
        )

        try:
            from sqlalchemy.orm import selectinload

            from ...models import AvanpostUserLinkModel

            # Загрузка AvanpostUser через цепочку связей
            stmt = (
                select(AvanpostUserModel)
                .join(AvanpostUserLinkModel, AvanpostUserModel.FID == AvanpostUserLinkModel.FK_Parent)
                .where(AvanpostUserLinkModel.FK_Link == telegram_user_id)
                .options(selectinload(AvanpostUserModel.user_link))
            )

            db_logger.debug(f"📝 SQL: {stmt.compile(compile_kwargs={'literal_binds': True})}")

            result = await session.execute(stmt)
            user: AvanpostUserModel | None = result.scalar_one_or_none()

            if user:
                db_logger.info(
                    f"✅ [get_avanpost_user_by_telegram_id] Found AvanpostUser {user.FID} for telegram user {telegram_user_id}"
                )
            else:
                db_logger.warning(
                    f"⚠️ [get_avanpost_user_by_telegram_id] No AvanpostUser found for telegram user {telegram_user_id}"
                )

            return user

        except Exception as e:
            db_logger.error(f"❌ [get_avanpost_user_by_telegram_id] Failed: {e}", exc_info=True)
            return None

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
            db_logger.error(f"❌ [create_avanpost_user] Invalid avanpost_user_id: {avanpost_user_id}")
            return None

        db_logger.info(f"🆕 [create_avanpost_user] Creating AvanpostUser {avanpost_user_id}")

        try:
            user = AvanpostUserModel(
                FID=avanpost_user_id,
                FK_Contact=fk_contact,
                FK_Language=fk_language[:2] if fk_language else "RU",
                FK_MenuGroup=fk_menugroup,
                FK_Owner=fk_owner,
                FK_MotorCade=fk_motorcade,
                FK_User=telegram_user_id,
                FName=fname[:50] if fname else None,
                FPhone=fphone[:30] if fphone else None,
            )
            session.add(user)
            await session.flush()

            db_logger.info(
                f"✅ [create_avanpost_user] Created AvanpostUser {avanpost_user_id} with contact {fk_contact}"
            )
            return user

        except Exception as e:
            db_logger.error(f"❌ [create_avanpost_user] Failed to create AvanpostUser: {e}", exc_info=True)
            return None

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
        Создание или обновление пользователя Avanpost.

        Args:
            session: Сессия БД (main)
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
            db_logger.error(f"❌ [create_or_update_avanpost_user] Invalid avanpost_user_id: {avanpost_user_id}")
            return False, None

        db_logger.info(
            f"🔄 [create_or_update_avanpost_user] Creating/updating AvanpostUser {avanpost_user_id} for user {telegram_user_id}"
        )

        try:
            # 1. Проверка существования пользователя в TUsers
            user = await UserRepository.get_user_by_id(session, telegram_user_id)
            if not user:
                db_logger.error(f"❌ [create_or_update_avanpost_user] User {telegram_user_id} not found")
                return False, None

            # 2. Проверка существования записи в TAvanpostUsers по FID
            stmt = select(AvanpostUserModel).where(AvanpostUserModel.FID == avanpost_user_id)

            db_logger.debug(f"📝 SQL: {stmt.compile(compile_kwargs={'literal_binds': True})}")

            result = await session.execute(stmt)
            avanpost_user = result.scalar_one_or_none()

            if avanpost_user:
                # Обновление существующей записи
                db_logger.info(f"🔄 [create_or_update_avanpost_user] Updating existing AvanpostUser {avanpost_user_id}")

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

                # Обновление связи с Telegram пользователем
                avanpost_user.FK_User = telegram_user_id

                await session.flush()
                db_logger.info(f"✅ [create_or_update_avanpost_user] Updated AvanpostUser {avanpost_user.FID}")
                return True, avanpost_user

            # 3. Создание нового AvanpostUser
            db_logger.info(f"🆕 [create_or_update_avanpost_user] Creating new AvanpostUser {avanpost_user_id}")

            new_user = AvanpostUserModel(
                FID=avanpost_user_id,
                FK_User=telegram_user_id,
                FK_Contact=fk_contact,
                FK_MenuGroup=fk_menugroup,
                FK_Owner=fk_owner,
                FK_MotorCade=fk_motorcade,
                FK_Language=fk_language[:2] if fk_language else "RU",
                FName=fname[:50] if fname else None,
                FPhone=fphone[:30] if fphone else None,
            )
            session.add(new_user)
            await session.flush()

            db_logger.info(f"✅ [create_or_update_avanpost_user] Created AvanpostUser {avanpost_user_id}")
            return True, new_user

        except Exception as e:
            db_logger.error(f"❌ [create_or_update_avanpost_user] Failed: {e}", exc_info=True)
            return False, None

    @staticmethod
    @log_exceptions(db_logger)
    async def create_or_update_avanpost_user_upsert(
        session: AsyncSession,
        telegram_user_id: int,
        avanpost_user_id: int,
        telegram_user_required: bool = True,
        fk_contact: int | None = None,
        fk_language: str | None = None,
        fk_menugroup: int | None = None,
        fk_owner: int | None = None,
        fk_motorcade: int | None = None,
        fname: str | None = None,
        fphone: str | None = None,
    ) -> tuple[bool, AvanpostUserModel | None]:
        """
        Создание или обновление связи пользователя с Avanpost через UPSERT.

        Работает с новой структурой:
        - TAvanpostUsers (данные)
        - TAvanpostUsersLinks (связь с Telegram)

        Args:
            session: Сессия БД (main)
            telegram_user_id: ID пользователя в Telegram
            avanpost_user_id: ID пользователя в Avanpost
            telegram_user_required: Требуется ли Telegram пользователь
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
            db_logger.error(f"❌ [create_or_update_avanpost_user_upsert] Invalid avanpost_user_id: {avanpost_user_id}")
            return False, None

        if telegram_user_required and (not telegram_user_id or telegram_user_id <= 0):
            db_logger.error(f"❌ [create_or_update_avanpost_user_upsert] Invalid telegram_user_id: {telegram_user_id}")
            return False, None

        db_logger.info(
            f"🔄 [create_or_update_avanpost_user_upsert] UPSERT AvanpostUser: avanpost_id={avanpost_user_id}, telegram_id={telegram_user_id}"
        )

        try:
            from sqlalchemy.dialects.postgresql import insert

            from ...models import AvanpostUserLinkModel, AvanpostUserModel

            # 1. UPSERT для TAvanpostUsers (данные из Avanpost)
            user_values: dict[str, Any] = {
                "FID": avanpost_user_id,
                "FK_Language": fk_language or "RU",
            }

            if fk_contact is not None:
                user_values["FK_Contact"] = fk_contact
            if fk_menugroup is not None:
                user_values["FK_MenuGroup"] = fk_menugroup
            if fk_owner is not None:
                user_values["FK_Owner"] = fk_owner
            if fk_motorcade is not None:
                user_values["FK_MotorCade"] = fk_motorcade
            if fname is not None:
                user_values["FName"] = fname
            if fphone is not None:
                user_values["FPhone"] = fphone

            user_stmt = insert(AvanpostUserModel).values(**user_values)
            user_stmt = user_stmt.on_conflict_do_update(
                index_elements=["FID"],
                set_={k: v for k, v in user_values.items() if k != "FID"},
            )

            db_logger.debug(f"📝 SQL (UPSERT user): {user_stmt.compile(compile_kwargs={'literal_binds': True})}")

            await session.execute(user_stmt)
            db_logger.debug(f"✅ TAvanpostUsers upserted: {avanpost_user_id}")

            # 2. UPSERT для TAvanpostUsersLinks (связь с Telegram)
            # Проверка, есть ли уже связь
            link_stmt = select(AvanpostUserLinkModel).where(AvanpostUserLinkModel.FK_Parent == avanpost_user_id)

            db_logger.debug(f"📝 SQL (check link): {link_stmt.compile(compile_kwargs={'literal_binds': True})}")

            result = await session.execute(link_stmt)
            existing_link = result.scalar_one_or_none()

            if existing_link:
                # Обновление существующей связи
                if existing_link.FK_Link != telegram_user_id:
                    existing_link.FK_Link = telegram_user_id
                    await session.flush()
                    db_logger.debug(f"✅ TAvanpostUsersLinks updated: {avanpost_user_id} -> {telegram_user_id}")
            else:
                # Создание новой связи
                new_link = AvanpostUserLinkModel(
                    FK_Parent=avanpost_user_id,
                    FK_Link=telegram_user_id,
                )
                session.add(new_link)
                await session.flush()
                db_logger.debug(f"✅ TAvanpostUsersLinks created: {avanpost_user_id} -> {telegram_user_id}")

            # 3. Получение созданной/обновленной записи пользователя Avanpost
            result_user = await session.execute(
                select(AvanpostUserModel).where(AvanpostUserModel.FID == avanpost_user_id)
            )
            user = result_user.scalar_one_or_none()

            if user:
                db_logger.info(
                    f"✅ [create_or_update_avanpost_user_upsert] UPSERT AvanpostUser {avanpost_user_id} for user {telegram_user_id}"
                )
                return True, user
            else:
                db_logger.error(
                    f"❌ [create_or_update_avanpost_user_upsert] Failed to get AvanpostUser {avanpost_user_id}"
                )
                return False, None

        except Exception as e:
            db_logger.error(f"❌ [create_or_update_avanpost_user_upsert] Failed: {e}", exc_info=True)
            await session.rollback()
            return False, None

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

        db_logger.info(
            f"🔄 [update_avanpost_user_telegram_link] Updating link: Avanpost {avanpost_user_id} -> Telegram {telegram_user_id}"
        )

        try:
            stmt = select(AvanpostUserModel).where(AvanpostUserModel.FID == avanpost_user_id)

            db_logger.debug(f"📝 SQL: {stmt.compile(compile_kwargs={'literal_binds': True})}")

            result = await session.execute(stmt)
            user = result.scalar_one_or_none()

            if not user:
                db_logger.warning(f"⚠️ [update_avanpost_user_telegram_link] AvanpostUser {avanpost_user_id} not found")
                return False

            user.FK_User = telegram_user_id
            await session.flush()

            db_logger.info(f"✅ [update_avanpost_user_telegram_link] Updated AvanpostUser.FK_User = {telegram_user_id}")
            return True

        except Exception as e:
            db_logger.error(f"❌ [update_avanpost_user_telegram_link] Failed: {e}", exc_info=True)
            return False

    @staticmethod
    @log_exceptions(db_logger)
    async def get_user_with_avanpost(
        session: AsyncSession,
        user_id: int,
    ) -> UserModel | None:
        """
        Получение пользователя с предзагруженной связью с Avanpost.

        Args:
            session: Сессия БД
            user_id: ID пользователя в Telegram

        Returns:
            UserModel | None: Пользователь с загруженной связью или None
        """
        if not user_id or user_id <= 0:
            return None

        db_logger.info(f"🔍 [get_user_with_avanpost] Getting user {user_id} with Avanpost link")

        try:
            from sqlalchemy.orm import selectinload

            from ...models import AvanpostUserLinkModel

            # Загрузка пользователя с двумя уровнями связей
            stmt = (
                select(UserModel)
                .where(UserModel.FID == user_id)
                .options(selectinload(UserModel.avanpost_link).selectinload(AvanpostUserLinkModel.avanpost_user))
            )

            db_logger.debug(f"📝 SQL: {stmt.compile(compile_kwargs={'literal_binds': True})}")

            result = await session.execute(stmt)
            user = result.scalar_one_or_none()

            if user is None:
                db_logger.warning(f"⚠️ [get_user_with_avanpost] User {user_id} not found")
                return None

            if not isinstance(user, UserModel):
                return None

            db_logger.info(f"✅ [get_user_with_avanpost] Found user {user_id}")
            return user

        except Exception as e:
            db_logger.error(f"❌ [get_user_with_avanpost] Failed: {e}", exc_info=True)
            return None

    @staticmethod
    @log_exceptions(db_logger)
    async def get_user_group_id(
        session: AsyncSession,
        user_id: int,
    ) -> int | None:
        """
        Получение ID группы действий пользователя.

        Использует цепочку: User -> AvanpostUserLink -> AvanpostUser -> FK_MenuGroup

        Args:
            session: Сессия БД (main)
            user_id: ID пользователя в Telegram (TUsers.FID)

        Returns:
            int | None: ID группы действий (FK_MenuGroup) или None
        """
        if not user_id or user_id <= 0:
            return None

        db_logger.info(f"🔍 [get_user_group_id] Getting group ID for user {user_id}")

        try:
            from sqlalchemy import select
            from sqlalchemy.orm import selectinload

            from ...models import AvanpostUserLinkModel

            # Загрузка пользователя с предзагрузкой связей
            stmt = (
                select(UserModel)
                .where(UserModel.FID == user_id)
                .options(selectinload(UserModel.avanpost_link).selectinload(AvanpostUserLinkModel.avanpost_user))
            )

            db_logger.debug(f"📝 SQL: {stmt.compile(compile_kwargs={'literal_binds': True})}")

            result = await session.execute(stmt)
            user = result.scalar_one_or_none()

            if not user:
                db_logger.warning(f"⚠️ [get_user_group_id] User {user_id} not found")
                return None

            # Проверка наличия связи
            if not user.avanpost_link or user.avanpost_link.FK_Link is None:
                db_logger.debug(f"ℹ️ [get_user_group_id] User {user_id} is not authenticated (no link)")
                return None

            # Получение группы из AvanpostUser
            if user.avanpost_link.avanpost_user:
                group_id = user.avanpost_link.avanpost_user.FK_MenuGroup
                if group_id is not None:
                    db_logger.info(f"✅ [get_user_group_id] User {user_id} has group {group_id}")
                else:
                    db_logger.debug(f"ℹ️ [get_user_group_id] User {user_id} has no group assigned")

                # Явная проверка типа для mypy
                if not isinstance(group_id, int):
                    return None

                return group_id

            db_logger.debug(f"ℹ️ [get_user_group_id] User {user_id} has no AvanpostUser record")
            return None

        except Exception as e:
            db_logger.error(f"❌ [get_user_group_id] Failed: {e}", exc_info=True)
            return None

    # ==================== 4. ПРОВЕРКА АВТОРИЗАЦИИ ====================

    @staticmethod
    @log_exceptions(db_logger)
    async def is_user_authorized(
        session: AsyncSession,
        user_id: int,
    ) -> bool:
        """
        Проверка авторизации пользователя.

        Проверяет наличие связи в AvanpostUserLinkModel.

        Args:
            session: Сессия БД
            user_id: ID пользователя в Telegram (TUsers.FID)

        Returns:
            bool: True если пользователь авторизован
        """
        if not user_id or user_id <= 0:
            return False

        db_logger.info(f"🔍 [is_user_authorized] Checking authorization for user {user_id}")

        try:
            from ...models import AvanpostUserLinkModel

            stmt = select(AvanpostUserLinkModel).where(AvanpostUserLinkModel.FK_Link == user_id)

            db_logger.debug(f"📝 SQL: {stmt.compile(compile_kwargs={'literal_binds': True})}")

            result = await session.execute(stmt)
            authorized = result.first() is not None

            db_logger.info(f"✅ [is_user_authorized] User {user_id} authorized: {authorized}")
            return authorized

        except Exception as e:
            db_logger.error(f"❌ [is_user_authorized] Failed: {e}", exc_info=True)
            return False

    @staticmethod
    @log_exceptions(db_logger)
    async def is_user_authenticated(
        session: AsyncSession,
        user_id: int,
    ) -> bool:
        """
        Проверка аутентификации пользователя с обновлением времени активности.

        Args:
            session: Сессия БД
            user_id: ID пользователя в Telegram (TUsers.FID)

        Returns:
            bool: True если пользователь аутентифицирован
        """
        if not user_id or user_id <= 0:
            return False

        db_logger.info(f"🔍 [is_user_authenticated] Checking authentication for user {user_id}")

        try:
            from sqlalchemy.orm import selectinload

            # Загрузка пользователя с предзагрузкой связи
            stmt = select(UserModel).where(UserModel.FID == user_id).options(selectinload(UserModel.avanpost_link))

            db_logger.debug(f"📝 SQL: {stmt.compile(compile_kwargs={'literal_binds': True})}")

            result = await session.execute(stmt)
            user = result.scalar_one_or_none()

            # Проверка наличия связи
            if user and user.avanpost_link and user.avanpost_link.FK_Link is not None:
                # Обновление времени последней активности
                user.FDateLastActivity = datetime_now()
                await session.flush()
                db_logger.info(f"✅ [is_user_authenticated] User {user_id} is authenticated")
                return True

            db_logger.info(f"❌ [is_user_authenticated] User {user_id} is NOT authenticated")
            return False

        except Exception as e:
            db_logger.error(f"❌ [is_user_authenticated] Failed: {e}", exc_info=True)
            return False

    @staticmethod
    @log_exceptions(db_logger)
    async def get_authenticated_user(
        session: AsyncSession,
        user_id: int,
    ) -> Optional["UserModel"]:
        """
        Получение аутентифицированного пользователя.

        Загружает пользователя с предзагруженной связью Avanpost
        и обновляет время последней активности.

        Args:
            session: Сессия БД
            user_id: ID пользователя в Telegram (TUsers.FID)

        Returns:
            UserModel | None: Аутентифицированный пользователь или None
        """
        if not user_id or user_id <= 0:
            return None

        db_logger.info(f"🔍 [get_authenticated_user] Getting authenticated user {user_id}")

        try:
            from sqlalchemy.orm import selectinload

            from ...models import AvanpostUserLinkModel

            # Загрузка пользователя с предзагрузкой связи
            stmt = (
                select(UserModel)
                .where(UserModel.FID == user_id)
                .options(selectinload(UserModel.avanpost_link).selectinload(AvanpostUserLinkModel.avanpost_user))
            )

            db_logger.debug(f"📝 SQL: {stmt.compile(compile_kwargs={'literal_binds': True})}")

            result = await session.execute(stmt)
            user = result.scalar_one_or_none()

            if user and user.avanpost_link and user.avanpost_link.FK_Link is not None:
                # Обновление времени последней активности
                user.FDateLastActivity = datetime_now()
                await session.flush()

                # Явная проверка типа для mypy
                if not isinstance(user, UserModel):
                    return None

                db_logger.info(f"✅ [get_authenticated_user] Found authenticated user {user_id}")
                return user

            db_logger.warning(f"⚠️ [get_authenticated_user] User {user_id} is not authenticated")
            return None

        except Exception as e:
            db_logger.error(f"❌ [get_authenticated_user] Failed: {e}", exc_info=True)
            return None

    @staticmethod
    @log_exceptions(db_logger)
    async def get_authenticated_user_with_avanpost(
        session: AsyncSession,
        user_id: int,
    ) -> Optional["UserModel"]:
        """
        Получение аутентифицированного пользователя с AvanpostUser.

        Является синонимом get_authenticated_user для обратной совместимости.

        Args:
            session: Сессия БД
            user_id: ID пользователя в Telegram

        Returns:
            UserModel | None: Аутентифицированный пользователь или None
        """
        return await UserRepository.get_authenticated_user(session, user_id)  # type: ignore[no-any-return]

    # ==================== 5. ОБНОВЛЕНИЕ ДАННЫХ ====================

    @staticmethod
    @log_exceptions(db_logger)
    async def update_last_activity(
        session: AsyncSession,
        user_id: int,
    ) -> bool:
        """
        Обновление времени последней активности пользователя.

        Args:
            session: Сессия БД
            user_id: ID пользователя

        Returns:
            bool: Успешно ли обновлено
        """
        if not user_id or user_id <= 0:
            return False

        db_logger.info(f"🔄 [update_last_activity] Updating last activity for user {user_id}")

        user: UserModel | None = await session.get(UserModel, user_id)
        if user:
            user.FDateLastActivity = datetime_now()
            await session.flush()
            db_logger.info(f"✅ [update_last_activity] Updated last activity for user {user_id}")
            return True

        db_logger.warning(f"⚠️ [update_last_activity] User {user_id} not found")
        return False

    @staticmethod
    @log_exceptions(db_logger)
    async def logout_user(
        session: AsyncSession,
        user_id: int,
    ) -> bool:
        """
        Выход пользователя из системы.

        Удаляет связь с AvanpostUser и очищает Telegram данные.

        Args:
            session: Сессия БД
            user_id: ID пользователя

        Returns:
            bool: Успешно ли выполнен выход
        """
        if not user_id or user_id <= 0:
            return False

        db_logger.info(f"🚪 [logout_user] Logging out user {user_id}")

        # Использование метода с предзагрузкой
        user = await UserRepository.get_user_with_avanpost(session, user_id)

        if not user:
            db_logger.warning(f"⚠️ [logout_user] User {user_id} not found for logout")
            return False

        # Удаление связи с AvanpostUser
        if user.avanpost_user:
            await session.delete(user.avanpost_user)
            db_logger.info(f"✅ [logout_user] Deleted AvanpostUser for user {user_id}")

        # Очистка Telegram данных
        user.FK_Chat = None
        user.FDateUpdated = datetime_now()

        await session.flush()
        db_logger.info(f"✅ [logout_user] User {user_id} logged out")
        return True

    @staticmethod
    @log_exceptions(db_logger)
    async def clear_telegram_data(
        session: AsyncSession,
        user_id: int,
    ) -> bool:
        """
        Очистка Telegram данных пользователя.

        Удаляет связь с AvanpostUser.

        Args:
            session: Сессия БД
            user_id: ID пользователя

        Returns:
            bool: Успешно ли выполнена очистка
        """
        if not user_id or user_id <= 0:
            return False

        db_logger.info(f"🧹 [clear_telegram_data] Clearing Telegram data for user {user_id}")

        user: UserModel | None = await session.get(UserModel, user_id)
        if not user:
            db_logger.warning(f"⚠️ [clear_telegram_data] User {user_id} not found")
            return False

        if user.avanpost_user:
            # Удаление записи из TAvanpostUsers для этого пользователя
            await session.delete(user.avanpost_user)
            db_logger.info(f"✅ [clear_telegram_data] Deleted AvanpostUser for user {user_id}")

        user.FK_Chat = None
        user.FDateUpdated = datetime_now()
        await session.flush()

        db_logger.info(f"✅ [clear_telegram_data] Cleared Telegram data for user {user_id}")
        return True

    # ==================== 6. СТАТИСТИКА ====================

    @staticmethod
    @log_exceptions(db_logger)
    async def get_user_stats(
        session: AsyncSession,
        user_id: int,
    ) -> dict[str, Any]:
        """
        Получение статистики пользователя.

        Включает:
        - Количество сообщений
        - Количество решенных ошибок
        - Информацию об авторизации

        Args:
            session: Сессия БД
            user_id: ID пользователя

        Returns:
            dict: Статистика пользователя
        """
        db_logger.info(f"📊 [get_user_stats] Getting stats for user {user_id}")

        user: UserModel | None = await session.get(UserModel, user_id)
        if not user:
            db_logger.warning(f"⚠️ [get_user_stats] User {user_id} not found")
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

        stats = {
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

        db_logger.info(
            f"✅ [get_user_stats] Stats for user {user_id}: messages={messages_count}, errors={errors_resolved}"
        )
        return stats


__all__ = ["UserRepository"]
