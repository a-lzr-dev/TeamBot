from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from ...logger import db_logger
from ...models.avanpost import (
    AvanpostDirContactGroupModel,
    AvanpostDirLanguageModel,
)
from ...utils.decorators import log_exceptions


class DirLanguageRepository:
    """Репозиторий для работы с языками (TAvanpostDirLanguages)"""

    @staticmethod
    @log_exceptions(db_logger)
    async def get_by_id(
        session: AsyncSession,
        language_id: str,
    ) -> AvanpostDirLanguageModel | None:
        """
        Получение языка по ID.

        Args:
            session: Сессия БД
            language_id: ID языка (например, 'RU', 'EN')

        Returns:
            AvanpostDirLanguageModel | None: Модель языка или None
        """
        db_logger.info(f"🔍 [get_by_id] Getting language by ID: {language_id}")

        stmt = select(AvanpostDirLanguageModel).where(AvanpostDirLanguageModel.FID == language_id)

        db_logger.debug(f"📝 SQL: {stmt.compile(compile_kwargs={'literal_binds': True})}")

        result = await session.execute(stmt)
        language = result.scalar_one_or_none()

        if language:
            db_logger.info(f"✅ [get_by_id] Found language {language_id}")
        else:
            db_logger.warning(f"⚠️ [get_by_id] Language {language_id} not found")

        return language  # type: ignore[no-any-return]

    @staticmethod
    @log_exceptions(db_logger)
    async def get_all(
        session: AsyncSession,
        only_default: bool = False,
    ) -> list[AvanpostDirLanguageModel]:
        """
        Получение всех языков.

        Args:
            session: Сессия БД
            only_default: Только язык по умолчанию

        Returns:
            list[AvanpostDirLanguageModel]: Список языков
        """
        db_logger.info(f"📋 [get_all] Getting all languages: only_default={only_default}")

        stmt = select(AvanpostDirLanguageModel)

        if only_default:
            stmt = stmt.where(AvanpostDirLanguageModel.FFlagDefault.is_(True))

        stmt = stmt.order_by(AvanpostDirLanguageModel.FID)

        db_logger.debug(f"📝 SQL: {stmt.compile(compile_kwargs={'literal_binds': True})}")

        result = await session.execute(stmt)
        languages = list(result.scalars().all())

        db_logger.info(f"✅ [get_all] Found {len(languages)} languages")
        return languages

    @staticmethod
    @log_exceptions(db_logger)
    async def get_default_language(
        session: AsyncSession,
    ) -> AvanpostDirLanguageModel | None:
        """
        Получение языка по умолчанию.

        Args:
            session: Сессия БД

        Returns:
            AvanpostDirLanguageModel | None: Язык по умолчанию или None
        """
        db_logger.info("🔍 [get_default_language] Getting default language")

        stmt = select(AvanpostDirLanguageModel).where(AvanpostDirLanguageModel.FFlagDefault.is_(True))

        db_logger.debug(f"📝 SQL: {stmt.compile(compile_kwargs={'literal_binds': True})}")

        result = await session.execute(stmt)
        language = result.scalar_one_or_none()

        if language:
            db_logger.info(f"✅ [get_default_language] Found default language: {language.FID}")
        else:
            db_logger.warning("⚠️ [get_default_language] No default language found")

        return language  # type: ignore[no-any-return]

    @staticmethod
    @log_exceptions(db_logger)
    async def exists(
        session: AsyncSession,
        language_id: str,
    ) -> bool:
        """
        Проверка существования языка.

        Args:
            session: Сессия БД
            language_id: ID языка

        Returns:
            bool: True если язык существует
        """
        db_logger.info(f"🔍 [exists] Checking existence of language {language_id}")

        stmt = select(AvanpostDirLanguageModel).where(AvanpostDirLanguageModel.FID == language_id)

        db_logger.debug(f"📝 SQL: {stmt.compile(compile_kwargs={'literal_binds': True})}")

        result = await session.execute(stmt)
        exists = result.scalar_one_or_none() is not None

        db_logger.info(f"✅ [exists] Language {language_id} exists: {exists}")
        return exists

    @staticmethod
    @log_exceptions(db_logger)
    async def create(
        session: AsyncSession,
        language_id: str,
        is_default: bool = False,
    ) -> AvanpostDirLanguageModel:
        """
        Создание нового языка.

        Args:
            session: Сессия БД
            language_id: ID языка (например, 'RU')
            is_default: Является ли языком по умолчанию

        Returns:
            AvanpostDirLanguageModel: Созданная модель языка
        """
        db_logger.info(f"🆕 [create] Creating language: {language_id} (default={is_default})")

        language = AvanpostDirLanguageModel(
            FID=language_id,
            FFlagDefault=is_default,
        )
        session.add(language)
        await session.flush()
        await session.refresh(language)

        db_logger.info(f"✅ [create] Created language '{language_id}'")
        return language

    @staticmethod
    @log_exceptions(db_logger)
    async def create_or_update(
        session: AsyncSession,
        language_id: str,
        is_default: bool = False,
    ) -> AvanpostDirLanguageModel:
        """
        Создание или обновление языка (UPSERT).

        Args:
            session: Сессия БД
            language_id: ID языка
            is_default: Является ли языком по умолчанию

        Returns:
            AvanpostDirLanguageModel: Модель языка
        """
        db_logger.info(f"🔄 [create_or_update] Creating or updating language: {language_id}")

        # UPSERT: INSERT ... ON CONFLICT DO UPDATE
        stmt = insert(AvanpostDirLanguageModel).values(
            FID=language_id,
            FFlagDefault=is_default,
        )
        stmt = stmt.on_conflict_do_update(
            index_elements=["FID"],
            set_={
                "FFlagDefault": is_default,
            },
        )

        db_logger.debug(f"📝 SQL: {stmt.compile(compile_kwargs={'literal_binds': True})}")

        await session.execute(stmt)
        await session.flush()

        # Получаем созданную/обновленную запись
        language = await DirLanguageRepository.get_by_id(session, language_id)
        if language is None:
            raise RuntimeError(f"Failed to retrieve language after upsert: {language_id}")

        db_logger.info(f"✅ [create_or_update] Language {language_id} created or updated")
        return language  # type: ignore[no-any-return]

    @staticmethod
    @log_exceptions(db_logger)
    async def ensure_language(
        session: AsyncSession,
        language_id: str = "RU",
        is_default: bool = True,
    ) -> AvanpostDirLanguageModel:
        """
        Проверка существования языка и создание при необходимости.

        Args:
            session: Сессия БД
            language_id: ID языка (по умолчанию 'RU')
            is_default: Является ли языком по умолчанию

        Returns:
            AvanpostDirLanguageModel: Модель языка
        """
        db_logger.info(f"🔍 [ensure_language] Ensuring language {language_id} exists")

        # Проверяем существование
        existing = await DirLanguageRepository.get_by_id(session, language_id)

        if existing:
            # Обновляем флаг, если нужно
            if existing.FFlagDefault != is_default:
                existing.FFlagDefault = is_default
                await session.flush()
                db_logger.info(f"✅ [ensure_language] Updated language '{language_id}' (default={is_default})")
            return existing  # type: ignore[no-any-return]

        # Создаем новый язык
        db_logger.warning(f"⚠️ [ensure_language] Language '{language_id}' not found, creating...")
        return await DirLanguageRepository.create(session, language_id, is_default)  # type: ignore[no-any-return]

    @staticmethod
    @log_exceptions(db_logger)
    async def delete(
        session: AsyncSession,
        language_id: str,
    ) -> bool:
        """
        Удаление языка.

        Args:
            session: Сессия БД
            language_id: ID языка

        Returns:
            bool: True если язык был удален
        """
        db_logger.info(f"🗑️ [delete] Deleting language: {language_id}")

        language = await DirLanguageRepository.get_by_id(session, language_id)

        if not language:
            db_logger.warning(f"⚠️ [delete] Language {language_id} not found")
            return False

        # Проверка используемости языка
        # TODO: Добавить проверку на использование в других таблицах

        await session.delete(language)
        await session.flush()

        db_logger.info(f"✅ [delete] Deleted language '{language_id}'")
        return True

    @staticmethod
    @log_exceptions(db_logger)
    async def get_language_codes(
        session: AsyncSession,
    ) -> list[str]:
        """
        Получение списка всех кодов языков.

        Args:
            session: Сессия БД

        Returns:
            list[str]: Список кодов языков
        """
        db_logger.info("📋 [get_language_codes] Getting all language codes")

        stmt = select(AvanpostDirLanguageModel.FID).order_by(AvanpostDirLanguageModel.FID)

        db_logger.debug(f"📝 SQL: {stmt.compile(compile_kwargs={'literal_binds': True})}")

        result = await session.execute(stmt)
        codes = [row[0] for row in result.all()]

        db_logger.info(f"✅ [get_language_codes] Found {len(codes)} language codes")
        return codes


class DirContactGroupRepository:
    """Репозиторий для работы с группами контактов (TAvanpostDirContactsGroups)"""

    @staticmethod
    @log_exceptions(db_logger)
    async def get_by_id(
        session: AsyncSession,
        group_id: int,
    ) -> AvanpostDirContactGroupModel | None:
        """
        Получение группы контактов по ID.

        Args:
            session: Сессия БД
            group_id: ID группы

        Returns:
            AvanpostDirContactGroupModel | None: Модель группы или None
        """
        db_logger.info(f"🔍 [get_by_id] Getting contact group by ID: {group_id}")

        stmt = select(AvanpostDirContactGroupModel).where(AvanpostDirContactGroupModel.FID == group_id)

        db_logger.debug(f"📝 SQL: {stmt.compile(compile_kwargs={'literal_binds': True})}")

        result = await session.execute(stmt)
        group = result.scalar_one_or_none()

        if group:
            db_logger.info(f"✅ [get_by_id] Found contact group {group_id}")
        else:
            db_logger.warning(f"⚠️ [get_by_id] Contact group {group_id} not found")

        return group  # type: ignore[no-any-return]

    @staticmethod
    @log_exceptions(db_logger)
    async def get_all(
        session: AsyncSession,
        only_active: bool = True,
    ) -> list[AvanpostDirContactGroupModel]:
        """
        Получение всех групп контактов.

        Args:
            session: Сессия БД
            only_active: Только активные группы

        Returns:
            list[AvanpostDirContactGroupModel]: Список групп
        """
        db_logger.info(f"📋 [get_all] Getting all contact groups: only_active={only_active}")

        stmt = select(AvanpostDirContactGroupModel).order_by(AvanpostDirContactGroupModel.FID)

        # Если есть поле активности, добавить фильтр
        if only_active and hasattr(AvanpostDirContactGroupModel, "FFlagActive"):
            stmt = stmt.where(AvanpostDirContactGroupModel.FFlagActive.is_(True))

        db_logger.debug(f"📝 SQL: {stmt.compile(compile_kwargs={'literal_binds': True})}")

        result = await session.execute(stmt)
        groups = list(result.scalars().all())

        db_logger.info(f"✅ [get_all] Found {len(groups)} contact groups")
        return groups

    @staticmethod
    @log_exceptions(db_logger)
    async def get_by_name(
        session: AsyncSession,
        name: str,
    ) -> AvanpostDirContactGroupModel | None:
        """
        Получение группы контактов по имени.

        Args:
            session: Сессия БД
            name: Имя группы

        Returns:
            AvanpostDirContactGroupModel | None: Модель группы или None
        """
        db_logger.info(f"🔍 [get_by_name] Getting contact group by name: {name}")

        stmt = select(AvanpostDirContactGroupModel).where(AvanpostDirContactGroupModel.FName == name)

        db_logger.debug(f"📝 SQL: {stmt.compile(compile_kwargs={'literal_binds': True})}")

        result = await session.execute(stmt)
        group = result.scalar_one_or_none()

        if group:
            db_logger.info(f"✅ [get_by_name] Found contact group '{name}'")
        else:
            db_logger.warning(f"⚠️ [get_by_name] Contact group '{name}' not found")

        return group  # type: ignore[no-any-return]

    @staticmethod
    @log_exceptions(db_logger)
    async def create(
        session: AsyncSession,
        group_id: int,
        name: str,
        order_by: int | None = None,
    ) -> AvanpostDirContactGroupModel:
        """
        Создание новой группы контактов.

        Args:
            session: Сессия БД
            group_id: ID группы
            name: Название группы
            order_by: Порядок сортировки

        Returns:
            AvanpostDirContactGroupModel: Созданная модель группы
        """
        db_logger.info(f"🆕 [create] Creating contact group: id={group_id}, name={name}")

        group = AvanpostDirContactGroupModel(
            FID=group_id,
            FName=name,
            FOrderBy=order_by,
        )
        session.add(group)
        await session.flush()
        await session.refresh(group)

        db_logger.info(f"✅ [create] Created contact group '{name}' with ID={group_id}")
        return group

    @staticmethod
    @log_exceptions(db_logger)
    async def create_or_update(
        session: AsyncSession,
        group_id: int,
        name: str,
        order_by: int | None = None,
    ) -> AvanpostDirContactGroupModel:
        """
        Создание или обновление группы контактов (UPSERT).

        Args:
            session: Сессия БД
            group_id: ID группы
            name: Название группы
            order_by: Порядок сортировки

        Returns:
            AvanpostDirContactGroupModel: Модель группы
        """
        db_logger.info(f"🔄 [create_or_update] Creating or updating contact group: id={group_id}, name={name}")

        # UPSERT: INSERT ... ON CONFLICT DO UPDATE
        stmt = insert(AvanpostDirContactGroupModel).values(
            FID=group_id,
            FName=name,
            FOrderBy=order_by,
        )
        stmt = stmt.on_conflict_do_update(
            index_elements=["FID"],
            set_={
                "FName": name,
                "FOrderBy": order_by,
            },
        )

        db_logger.debug(f"📝 SQL: {stmt.compile(compile_kwargs={'literal_binds': True})}")

        await session.execute(stmt)
        await session.flush()

        # Получаем созданную/обновленную запись
        group = await DirContactGroupRepository.get_by_id(session, group_id)
        if group is None:
            raise RuntimeError(f"Failed to retrieve contact group after upsert: {group_id}")

        db_logger.info(f"✅ [create_or_update] Contact group {group_id} created or updated")
        return group  # type: ignore[no-any-return]

    @staticmethod
    @log_exceptions(db_logger)
    async def ensure_group(
        session: AsyncSession,
        group_id: int,
        name: str,
        order_by: int | None = None,
    ) -> AvanpostDirContactGroupModel:
        """
        Проверка существования группы и создание при необходимости.

        Args:
            session: Сессия БД
            group_id: ID группы
            name: Название группы
            order_by: Порядок сортировки

        Returns:
            AvanpostDirContactGroupModel: Модель группы
        """
        db_logger.info(f"🔍 [ensure_group] Ensuring contact group exists: id={group_id}, name={name}")

        # Проверяем существование
        existing = await DirContactGroupRepository.get_by_id(session, group_id)

        if existing:
            # Обновляем название, если нужно
            if existing.FName != name:
                existing.FName = name
                await session.flush()
                db_logger.info(f"✅ [ensure_group] Updated contact group '{name}' (ID={group_id})")
            return existing  # type: ignore[no-any-return]

        # Создаем новую группу
        db_logger.warning(f"⚠️ [ensure_group] Contact group with ID={group_id} not found, creating...")
        return await DirContactGroupRepository.create(session, group_id, name, order_by)  # type: ignore[no-any-return]

    @staticmethod
    @log_exceptions(db_logger)
    async def delete(
        session: AsyncSession,
        group_id: int,
    ) -> bool:
        """
        Удаление группы контактов.

        Args:
            session: Сессия БД
            group_id: ID группы

        Returns:
            bool: True если группа была удалена
        """
        db_logger.info(f"🗑️ [delete] Deleting contact group: {group_id}")

        group = await DirContactGroupRepository.get_by_id(session, group_id)

        if not group:
            db_logger.warning(f"⚠️ [delete] Contact group {group_id} not found")
            return False

        # Проверяем, не используется ли группа в других таблицах
        # TODO: Добавить проверку на использование

        await session.delete(group)
        await session.flush()

        db_logger.info(f"✅ [delete] Deleted contact group with ID={group_id}")
        return True

    @staticmethod
    @log_exceptions(db_logger)
    async def get_group_ids(
        session: AsyncSession,
    ) -> list[int]:
        """
        Получение списка всех ID групп контактов.

        Args:
            session: Сессия БД

        Returns:
            list[int]: Список ID групп
        """
        db_logger.info("📋 [get_group_ids] Getting all contact group IDs")

        stmt = select(AvanpostDirContactGroupModel.FID).order_by(AvanpostDirContactGroupModel.FID)

        db_logger.debug(f"📝 SQL: {stmt.compile(compile_kwargs={'literal_binds': True})}")

        result = await session.execute(stmt)
        ids = [row[0] for row in result.all()]

        db_logger.info(f"✅ [get_group_ids] Found {len(ids)} contact group IDs")
        return ids

    @staticmethod
    @log_exceptions(db_logger)
    async def exists(
        session: AsyncSession,
        group_id: int,
    ) -> bool:
        """
        Проверка существования группы контактов.

        Args:
            session: Сессия БД
            group_id: ID группы

        Returns:
            bool: True если группа существует
        """
        db_logger.info(f"🔍 [exists] Checking existence of contact group {group_id}")

        stmt = select(AvanpostDirContactGroupModel).where(AvanpostDirContactGroupModel.FID == group_id)

        db_logger.debug(f"📝 SQL: {stmt.compile(compile_kwargs={'literal_binds': True})}")

        result = await session.execute(stmt)
        exists = result.scalar_one_or_none() is not None

        db_logger.info(f"✅ [exists] Contact group {group_id} exists: {exists}")
        return exists


__all__ = [
    "DirLanguageRepository",
    "DirContactGroupRepository",
]
