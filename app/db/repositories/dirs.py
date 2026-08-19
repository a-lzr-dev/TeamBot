from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ...exceptions import log_exceptions
from ...logger import db_logger
from ...models.avanpost import AvanpostDirLanguageModel


class DirLanguageRepository:
    """Репозиторий для работы с языками"""

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
        # Проверка типа (хотя это и избыточно, но mypy поймет)
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
        from sqlalchemy.dialects.postgresql import insert

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


__all__ = ["DirLanguageRepository"]
