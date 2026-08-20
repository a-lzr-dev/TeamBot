# app/db/repositories/dirs.py

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from ...exceptions import log_exceptions
from ...logger import db_logger
from ...models.avanpost import (
    AvanpostDirContactGroupModel,
    AvanpostDirLanguageModel,
)


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
        stmt = select(AvanpostDirLanguageModel).where(AvanpostDirLanguageModel.FID == language_id)
        result = await session.execute(stmt)
        language = result.scalar_one_or_none()
        if language is None:
            return None
        if not isinstance(language, AvanpostDirLanguageModel):
            return None
        return language

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
        stmt = select(AvanpostDirLanguageModel)

        if only_default:
            stmt = stmt.where(AvanpostDirLanguageModel.FFlagDefault.is_(True))

        stmt = stmt.order_by(AvanpostDirLanguageModel.FID)
        result = await session.execute(stmt)
        return list(result.scalars().all())

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
        stmt = select(AvanpostDirLanguageModel).where(AvanpostDirLanguageModel.FFlagDefault.is_(True))
        result = await session.execute(stmt)
        language = result.scalar_one_or_none()
        if language is None:
            return None
        if not isinstance(language, AvanpostDirLanguageModel):
            return None
        return language

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
        stmt = select(AvanpostDirLanguageModel).where(AvanpostDirLanguageModel.FID == language_id)
        result = await session.execute(stmt)
        return result.scalar_one_or_none() is not None

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
        language = AvanpostDirLanguageModel(
            FID=language_id,
            FFlagDefault=is_default,
        )
        session.add(language)
        await session.flush()
        await session.refresh(language)

        db_logger.info(f"✅ Created language '{language_id}' (default={is_default})")
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
        await session.execute(stmt)
        await session.flush()

        # Получаем созданную/обновленную запись
        language = await DirLanguageRepository.get_by_id(session, language_id)
        if language is None:
            raise RuntimeError(f"Failed to retrieve language after upsert: {language_id}")
        return language

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
        # Проверяем существование
        existing = await DirLanguageRepository.get_by_id(session, language_id)

        if existing:
            # Обновляем флаг, если нужно
            if existing.FFlagDefault != is_default:
                existing.FFlagDefault = is_default
                await session.flush()
                db_logger.debug(f"✅ Updated language '{language_id}' (default={is_default})")
            return existing

        # Создаем новый язык
        db_logger.warning(f"⚠️ Language '{language_id}' not found, creating...")
        return await DirLanguageRepository.create(session, language_id, is_default)

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
        language = await DirLanguageRepository.get_by_id(session, language_id)

        if not language:
            return False

        # Проверяем, не является ли язык используемым
        # TODO: Добавить проверку на использование в других таблицах

        await session.delete(language)
        await session.flush()

        db_logger.info(f"🗑️ Deleted language '{language_id}'")
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
        stmt = select(AvanpostDirLanguageModel.FID).order_by(AvanpostDirLanguageModel.FID)
        result = await session.execute(stmt)
        return [row[0] for row in result.all()]


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
        stmt = select(AvanpostDirContactGroupModel).where(AvanpostDirContactGroupModel.FID == group_id)
        result = await session.execute(stmt)
        group = result.scalar_one_or_none()
        if group is None:
            return None
        if not isinstance(group, AvanpostDirContactGroupModel):
            return None
        return group

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
        stmt = select(AvanpostDirContactGroupModel).order_by(AvanpostDirContactGroupModel.FID)

        # Если есть поле активности, добавить фильтр
        if only_active and hasattr(AvanpostDirContactGroupModel, "FFlagActive"):
            stmt = stmt.where(AvanpostDirContactGroupModel.FFlagActive.is_(True))

        result = await session.execute(stmt)
        return list(result.scalars().all())

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
        stmt = select(AvanpostDirContactGroupModel).where(AvanpostDirContactGroupModel.FName == name)
        result = await session.execute(stmt)
        group = result.scalar_one_or_none()
        if group is None:
            return None
        if not isinstance(group, AvanpostDirContactGroupModel):
            return None
        return group

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
        group = AvanpostDirContactGroupModel(
            FID=group_id,
            FName=name,
            FOrderBy=order_by,
        )
        session.add(group)
        await session.flush()
        await session.refresh(group)

        db_logger.info(f"✅ Created contact group '{name}' with ID={group_id}")
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
        await session.execute(stmt)
        await session.flush()

        # Получаем созданную/обновленную запись
        group = await DirContactGroupRepository.get_by_id(session, group_id)
        if group is None:
            raise RuntimeError(f"Failed to retrieve contact group after upsert: {group_id}")
        return group

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
        # Проверяем существование
        existing = await DirContactGroupRepository.get_by_id(session, group_id)

        if existing:
            # Обновляем название, если нужно
            if existing.FName != name:
                existing.FName = name
                await session.flush()
                db_logger.debug(f"✅ Updated contact group '{name}' (ID={group_id})")
            return existing

        # Создаем новую группу
        db_logger.warning(f"⚠️ Contact group with ID={group_id} not found, creating...")
        return await DirContactGroupRepository.create(session, group_id, name, order_by)

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
        group = await DirContactGroupRepository.get_by_id(session, group_id)

        if not group:
            return False

        # Проверяем, не используется ли группа в других таблицах
        # TODO: Добавить проверку на использование

        await session.delete(group)
        await session.flush()

        db_logger.info(f"🗑️ Deleted contact group with ID={group_id}")
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
        stmt = select(AvanpostDirContactGroupModel.FID).order_by(AvanpostDirContactGroupModel.FID)
        result = await session.execute(stmt)
        return [row[0] for row in result.all()]

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
        stmt = select(AvanpostDirContactGroupModel).where(AvanpostDirContactGroupModel.FID == group_id)
        result = await session.execute(stmt)
        return result.scalar_one_or_none() is not None


__all__ = [
    "DirLanguageRepository",
    "DirContactGroupRepository",
]
