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
        stmt = (
            select(AvanpostUserModel)
            .options(selectinload(AvanpostUserModel.user_link))
            .order_by(AvanpostUserModel.FID)
            .offset(offset)
        )

        if limit:
            stmt = stmt.limit(limit)

        result = await session.execute(stmt)
        return list(result.scalars().all())

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
        """
        Получение списка авторизованных пользователей.

        Использует EXISTS для проверки наличия связи, что быстрее, чем JOIN,
        если не нужно выбирать данные из связанной таблицы.
        """
        from sqlalchemy import exists

        from ...models import AvanpostUserLinkModel

        # Подзапрос для проверки наличия связи
        has_avanpost_link = exists().where(AvanpostUserLinkModel.FK_Link == UserModel.FID)

        stmt = select(UserModel).where(has_avanpost_link).order_by(UserModel.FID).offset(offset)

        if limit:
            stmt = stmt.limit(limit)

        result: Result = await session.execute(stmt)
        users: list[UserModel] = list(result.scalars().all())
        return users

    @staticmethod
    @log_exceptions(db_logger)
    async def get_authorized_users_count(session: AsyncSession) -> int:
        """
        Получение количества авторизованных пользователей
        (у которых есть связь с AvanpostUser).

        Использует новую структуру AvanpostUserLinkModel для подсчёта.

        Args:
            session: Сессия БД

        Returns:
            int: Количество авторизованных пользователей
        """
        try:
            from ...models import AvanpostUserLinkModel

            # Подсчет количество записей в AvanpostUserLinkModel
            stmt = (
                select(func.count())
                .select_from(AvanpostUserLinkModel)
                .where(AvanpostUserLinkModel.FK_Link.is_not(None))
            )
            result = await session.execute(stmt)
            count = result.scalar() or 0

            db_logger.debug(f"📊 Authorized users count: {count}")
            return count

        except Exception as e:
            db_logger.error(f"❌ Failed to get authorized users count: {e}", exc_info=True)
            return 0

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
        Получение AvanpostUser по Telegram ID через новую структуру.

        Использует цепочку: User -> AvanpostUserLink -> AvanpostUser

        Args:
            session: Сессия БД (main)
            telegram_user_id: ID пользователя в Telegram (TUsers.FID)

        Returns:
            AvanpostUserModel | None: Модель AvanpostUser или None
        """
        if not telegram_user_id or telegram_user_id <= 0:
            return None

        try:
            from sqlalchemy.orm import selectinload

            from ...models import AvanpostUserLinkModel

            # Загружаем AvanpostUser через цепочку связей
            stmt = (
                select(AvanpostUserModel)
                .join(AvanpostUserLinkModel, AvanpostUserModel.FID == AvanpostUserLinkModel.FK_Parent)
                .where(AvanpostUserLinkModel.FK_Link == telegram_user_id)
                .options(selectinload(AvanpostUserModel.user_link))
            )
            result = await session.execute(stmt)
            user: AvanpostUserModel | None = result.scalar_one_or_none()

            if user:
                db_logger.debug(f"✅ Found AvanpostUser {user.FID} for telegram user {telegram_user_id}")
            else:
                db_logger.debug(f"ℹ️ No AvanpostUser found for telegram user {telegram_user_id}")

            return user

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
        Сначала проверяет существование записи по FID, если есть - обновляет, если нет - создает.
        """
        if not avanpost_user_id or avanpost_user_id <= 0:
            db_logger.error(f"❌ Invalid avanpost_user_id: {avanpost_user_id}")
            return False, None

        #        if not telegram_user_id or telegram_user_id <= 0:
        #            db_logger.error(f"❌ Invalid telegram_user_id: {telegram_user_id}")
        #            return False, None

        try:
            # 1. Проверка существования пользователя в TUsers
            user = await UserRepository.get_user_by_id(session, telegram_user_id)
            if not user:
                db_logger.error(f"❌ User {telegram_user_id} not found")
                return False, None

            # 2. Проверка существования записи в TAvanpostUsers по FID (а не по FK_User!)
            stmt = select(AvanpostUserModel).where(AvanpostUserModel.FID == avanpost_user_id)
            result = await session.execute(stmt)
            avanpost_user = result.scalar_one_or_none()

            if avanpost_user:
                # ОБНОВЛЕНИЕ существующей записи
                db_logger.info(f"🔄 Updating existing AvanpostUser with FID={avanpost_user_id}")

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

                # ВСЕГДА обновляем связь с Telegram пользователем
                avanpost_user.FK_User = telegram_user_id

                await session.flush()
                db_logger.info(f"✅ Updated AvanpostUser {avanpost_user.FID} for user {telegram_user_id}")
                return True, avanpost_user

            # 3. СОЗДАНИЕ нового AvanpostUser (если записи с таким FID нет)
            db_logger.info(f"🆕 Creating new AvanpostUser with FID={avanpost_user_id}")

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

            db_logger.info(f"✅ Created AvanpostUser {avanpost_user_id} for user {telegram_user_id}")
            return True, new_user

        except Exception as e:
            db_logger.error(f"❌ Failed to create/update AvanpostUser: {e}", exc_info=True)
            return False, None

    # ==================== МЕТОДЫ ДЛЯ РАБОТЫ С AVANPOST (с предзагрузкой) ====================

    @staticmethod
    @log_exceptions(db_logger)
    async def get_user_with_avanpost(session: AsyncSession, user_id: int) -> UserModel | None:
        """
        Получение пользователя с предзагруженной связью с Avanpost.
        Использует новую структуру: User -> AvanpostUserLink -> AvanpostUser
        """
        if not user_id or user_id <= 0:
            return None

        try:
            from sqlalchemy.orm import selectinload

            from ...models import AvanpostUserLinkModel

            # Загрузка пользователя с двумя уровнями связей
            stmt = (
                select(UserModel)
                .where(UserModel.FID == user_id)
                .options(selectinload(UserModel.avanpost_link).selectinload(AvanpostUserLinkModel.avanpost_user))
            )
            result = await session.execute(stmt)
            user = result.scalar_one_or_none()

            if user is None:
                return None

            if not isinstance(user, UserModel):
                return None

            return user

        except Exception as e:
            db_logger.error(f"❌ Failed to get user with Avanpost: {e}", exc_info=True)
            return None

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
        Работает с новой структурой: TAvanpostUsers (данные) + TAvanpostUsersLinks (связь).
        """
        if not avanpost_user_id or avanpost_user_id <= 0:
            db_logger.error(f"❌ Invalid avanpost_user_id: {avanpost_user_id}")
            return False, None

        if telegram_user_required and (not telegram_user_id or telegram_user_id <= 0):
            db_logger.error(f"❌ Invalid telegram_user_id: {telegram_user_id}")
            return False, None

        try:
            from sqlalchemy.dialects.postgresql import insert

            from ...models import AvanpostUserLinkModel, AvanpostUserModel

            db_logger.debug(f"🔄 UPSERT AvanpostUser: avanpost_id={avanpost_user_id}, telegram_id={telegram_user_id}")

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
            await session.execute(user_stmt)
            db_logger.debug(f"✅ TAvanpostUsers upserted: {avanpost_user_id}")

            # 2. UPSERT для TAvanpostUsersLinks (связь с Telegram)
            # Проверка, есть ли уже связь
            link_stmt = select(AvanpostUserLinkModel).where(AvanpostUserLinkModel.FK_Parent == avanpost_user_id)
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
                db_logger.info(f"✅ UPSERT AvanpostUser {avanpost_user_id} for user {telegram_user_id}")
                return True, user
            else:
                db_logger.error(f"❌ Failed to get AvanpostUser {avanpost_user_id}")
                return False, None

        except Exception as e:
            db_logger.error(f"❌ Failed to UPSERT AvanpostUser: {e}", exc_info=True)
            await session.rollback()
            return False, None

    @staticmethod
    @log_exceptions(db_logger)
    async def get_user_group_id(session: AsyncSession, user_id: int) -> int | None:
        """
        Получение ID группы действий пользователя через новую структуру.

        Использует цепочку: User -> AvanpostUserLink -> AvanpostUser -> FK_MenuGroup

        Args:
            session: Сессия БД (main)
            user_id: ID пользователя в Telegram (TUsers.FID)

        Returns:
            int | None: ID группы действий (FK_MenuGroup) или None
        """
        if not user_id or user_id <= 0:
            return None

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
            result = await session.execute(stmt)
            user = result.scalar_one_or_none()

            if not user:
                db_logger.debug(f"ℹ️ User {user_id} not found")
                return None

            # Проверка наличия связи
            if not user.avanpost_link or user.avanpost_link.FK_Link is None:
                db_logger.debug(f"ℹ️ User {user_id} is not authenticated (no link)")
                return None

            # Получение группы из AvanpostUser
            if user.avanpost_link.avanpost_user:
                group_id = user.avanpost_link.avanpost_user.FK_MenuGroup
                if group_id is not None:
                    db_logger.debug(f"✅ User {user_id} has group {group_id}")
                else:
                    db_logger.debug(f"ℹ️ User {user_id} has no group assigned")

                # Явная проверка типа для mypy
                if not isinstance(group_id, int):
                    return None

                return group_id

            db_logger.debug(f"ℹ️ User {user_id} has no AvanpostUser record")
            return None

        except Exception as e:
            db_logger.error(f"❌ Failed to get user group ID: {e}", exc_info=True)
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
        """
        Проверка авторизации пользователя по наличию связи в AvanpostUserLinkModel.

        Args:
            session: Сессия БД
            user_id: ID пользователя в Telegram (TUsers.FID)

        Returns:
            bool: True если пользователь авторизован (есть связь с Avanpost)
        """
        if not user_id or user_id <= 0:
            return False

        try:
            from ...models import AvanpostUserLinkModel

            stmt = select(AvanpostUserLinkModel).where(AvanpostUserLinkModel.FK_Link == user_id)
            result = await session.execute(stmt)
            return result.first() is not None

        except Exception as e:
            db_logger.error(f"❌ Failed to check user authorization: {e}", exc_info=True)
            return False

    @staticmethod
    @log_exceptions(db_logger)
    async def is_user_authenticated(session: AsyncSession, user_id: int) -> bool:
        """
        Проверка авторизации пользователя с обновлением времени активности.
        Использует новую структуру AvanpostUserLinkModel.

        Args:
            session: Сессия БД
            user_id: ID пользователя в Telegram (TUsers.FID)

        Returns:
            bool: True если пользователь авторизован (есть связь с Avanpost)
        """
        if not user_id or user_id <= 0:
            return False

        try:
            from sqlalchemy.orm import selectinload

            # Загружзка пользователя с предзагрузкой связи
            stmt = select(UserModel).where(UserModel.FID == user_id).options(selectinload(UserModel.avanpost_link))
            result = await session.execute(stmt)
            user = result.scalar_one_or_none()

            # Проверка наличия связи
            if user and user.avanpost_link and user.avanpost_link.FK_Link is not None:
                # Обновление времени последней активности
                user.FDateLastActivity = datetime_now()
                await session.flush()
                return True

            return False

        except Exception as e:
            db_logger.error(f"❌ Failed to check user authentication: {e}", exc_info=True)
            return False

    @staticmethod
    @log_exceptions(db_logger)
    async def get_authenticated_user(session: AsyncSession, user_id: int) -> UserModel | None:
        """
        Получение пользователя с предзагруженной связью Avanpost.
        Используется для проверки авторизации с обновлением времени активности.

        Args:
            session: Сессия БД
            user_id: ID пользователя в Telegram (TUsers.FID)

        Returns:
            UserModel | None: Пользователь с загруженной связью или None
        """
        if not user_id or user_id <= 0:
            return None

        try:
            from sqlalchemy.orm import selectinload

            from ...models import AvanpostUserLinkModel

            # Загрузка пользователя с предзагрузкой связи
            stmt = (
                select(UserModel)
                .where(UserModel.FID == user_id)
                .options(selectinload(UserModel.avanpost_link).selectinload(AvanpostUserLinkModel.avanpost_user))
            )
            result = await session.execute(stmt)
            user = result.scalar_one_or_none()

            if user and user.avanpost_link and user.avanpost_link.FK_Link is not None:
                # Обновление времени последней активности
                user.FDateLastActivity = datetime_now()
                await session.flush()

                # Явная проверка типа для mypy
                if not isinstance(user, UserModel):
                    return None

                return user

            return None

        except Exception as e:
            db_logger.error(f"❌ Failed to get authenticated user: {e}", exc_info=True)
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
