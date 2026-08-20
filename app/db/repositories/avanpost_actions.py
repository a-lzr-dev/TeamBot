from typing import Any

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from ...exceptions import log_exceptions
from ...logger import db_logger
from ...models.avanpost import (
    AvanpostDirScenarioGroupItemModel,
    AvanpostDirScenarioGroupModel,
)


class AvanpostActionsRepository:
    """
    Репозиторий для работы с меню действий Avanpost.

    Поддерживает:
    - Получение списка групп действий
    - Получение пунктов меню с поддержкой иерархии
    - Проверку наличия дочерних элементов
    - Поддержку локализации (языки)
    """

    # ==================== ГРУППЫ ДЕЙСТВИЙ ====================

    @staticmethod
    @log_exceptions(db_logger)
    async def get_groups(
        session: AsyncSession,
        lang_code: str = "ru",
    ) -> list[dict[str, Any]]:
        """
        Получение списка всех групп действий с учетом языка.

        Args:
            session: Сессия БД (main)
            lang_code: Код языка (по умолчанию 'ru')

        Returns:
            list[dict]: Список групп с полями id, name
        """
        try:
            stmt = select(
                AvanpostDirScenarioGroupModel.FID,
                AvanpostDirScenarioGroupModel.FName,
            ).order_by(AvanpostDirScenarioGroupModel.FID)

            result = await session.execute(stmt)
            rows = result.all()

            groups = []
            for row in rows:
                groups.append(
                    {
                        "id": row.FID,
                        "name": row.FName,
                    }
                )

            db_logger.debug(f"📋 Retrieved {len(groups)} groups")
            return groups

        except Exception as e:
            db_logger.error(f"❌ Failed to get groups: {e}", exc_info=True)
            return []

    # ==================== ПУНКТЫ МЕНЮ ====================

    @staticmethod
    @log_exceptions(db_logger)
    async def get_menu_items(
        session: AsyncSession,
        group_id: int,
        parent_item_id: int | None = None,
        lang_code: str = "ru",
    ) -> list[dict[str, Any]]:
        """
        Получение пунктов меню для указанной группы с учетом языка.

        Использует SQLAlchemy ORM с предзагрузкой переводов.

        Args:
            session: Сессия БД (main)
            group_id: ID группы действий
            parent_item_id: ID родительского пункта (None для корневого меню)
            lang_code: Код языка (по умолчанию 'ru')

        Returns:
            list[dict]: Список пунктов меню с полями:
                - id: ID пункта
                - name: Название на указанном языке
                - has_subitems: есть ли дочерние элементы
                - parent_id: ID родителя
                - level: уровень вложенности
                - position: позиция
                - code: код (опционально)
        """
        try:
            # Загрузка пунктов меню с предзагрузкой переводов и дочерних элементов
            stmt = (
                select(AvanpostDirScenarioGroupItemModel)
                .where(
                    AvanpostDirScenarioGroupItemModel.FK_ScenarioGroup == group_id,
                )
                .options(
                    selectinload(AvanpostDirScenarioGroupItemModel.langs),
                    selectinload(AvanpostDirScenarioGroupItemModel.child_items),
                )
                .order_by(
                    AvanpostDirScenarioGroupItemModel.FLevel,
                    AvanpostDirScenarioGroupItemModel.FPosition,
                )
            )

            # Фильтр по родителю
            if parent_item_id is None:
                stmt = stmt.where(AvanpostDirScenarioGroupItemModel.FK_ParentItem.is_(None))
            else:
                stmt = stmt.where(AvanpostDirScenarioGroupItemModel.FK_ParentItem == parent_item_id)

            result = await session.execute(stmt)
            items = result.scalars().all()

            # Формирование результата с учетом языка
            menu_items = []
            for item in items:
                # Поиск названия на нужном языке
                name = None
                for lang in item.langs:
                    if lang.FK_Lang == lang_code:
                        name = lang.FName
                        break

                # Если перевод не найден, используем имя из модели
                if name is None:
                    # Пытаемся найти английский
                    for lang in item.langs:
                        if lang.FK_Lang == "en":
                            name = lang.FName
                            break

                    # Если нет английского, берем первый попавшийся
                    if name is None and item.langs:
                        name = item.langs[0].FName

                    # Если совсем нет переводов, используем заглушку
                    if name is None:
                        name = f"Item {item.FID}"

                # ИСПРАВЛЕНО: используем уже загруженные child_items вместо ленивой загрузки
                has_subitems = len(item.child_items) > 0 if hasattr(item, "child_items") else False

                menu_items.append(
                    {
                        "id": item.FID,
                        "name": name,
                        "has_subitems": has_subitems,
                        "parent_id": item.FK_ParentItem,
                        "level": item.FLevel,
                        "position": item.FPosition,
                        "code": item.FCode,
                    }
                )

            db_logger.debug(
                f"📋 Retrieved {len(menu_items)} menu items "
                f"for group {group_id}, parent={parent_item_id}, lang={lang_code}"
            )
            return menu_items

        except Exception as e:
            db_logger.error(f"❌ Failed to get menu items: {e}", exc_info=True)
            return []

    @staticmethod
    @log_exceptions(db_logger)
    async def get_menu_items_with_parent(
        session: AsyncSession,
        group_id: int,
        parent_item_id: int | None = None,
        lang_code: str = "ru",
    ) -> dict[str, Any]:
        """
        Получение пунктов меню с информацией о родителе.

        Args:
            session: Сессия БД (main)
            group_id: ID группы действий
            parent_item_id: ID родительского пункта
            lang_code: Код языка

        Returns:
            dict: {
                "items": list[dict] - пункты меню,
                "parent_name": str | None - название родителя,
                "parent_id": int | None - ID родителя
            }
        """
        # Получение пунктов меню
        items = await AvanpostActionsRepository.get_menu_items(
            session=session,
            group_id=group_id,
            parent_item_id=parent_item_id,
            lang_code=lang_code,
        )

        # Получение информации о родителе (если есть)
        parent_name = None
        if parent_item_id is not None:
            parent = await AvanpostActionsRepository.get_menu_item_by_id(
                session=session,
                item_id=parent_item_id,
                lang_code=lang_code,
            )
            if parent:
                parent_name = parent.get("name")

        return {
            "items": items,
            "parent_name": parent_name,
            "parent_id": parent_item_id,
        }

    # ==================== ОТДЕЛЬНЫЙ ПУНКТ МЕНЮ ====================

    @staticmethod
    @log_exceptions(db_logger)
    async def get_menu_item_by_id(
        session: AsyncSession,
        item_id: int,
        lang_code: str = "ru",
    ) -> dict[str, Any] | None:
        """
        Получение конкретного пункта меню по ID.

        Args:
            session: Сессия БД (main)
            item_id: ID пункта меню
            lang_code: Код языка

        Returns:
            dict | None: Информация о пункте меню или None
        """
        try:
            stmt = (
                select(AvanpostDirScenarioGroupItemModel)
                .where(AvanpostDirScenarioGroupItemModel.FID == item_id)
                .options(
                    selectinload(AvanpostDirScenarioGroupItemModel.langs),
                    selectinload(AvanpostDirScenarioGroupItemModel.child_items),
                )
            )

            result = await session.execute(stmt)
            item = result.scalar_one_or_none()

            if not item:
                return None

            # Поиск названия на нужном языке
            name = None
            for lang in item.langs:
                if lang.FK_Lang == lang_code:
                    name = lang.FName
                    break

            if name is None and item.langs:
                name = item.langs[0].FName
            if name is None:
                name = f"Item {item.FID}"

            return {
                "id": item.FID,
                "name": name,
                "has_subitems": len(item.child_items) > 0 if hasattr(item, "child_items") else False,
                "parent_id": item.FK_ParentItem,
                "group_id": item.FK_ScenarioGroup,
                "level": item.FLevel,
                "position": item.FPosition,
                "code": item.FCode,
            }

        except Exception as e:
            db_logger.error(f"❌ Failed to get menu item {item_id}: {e}", exc_info=True)
            return None

    # ==================== ПРОВЕРКА НАЛИЧИЯ ДОЧЕРНИХ ЭЛЕМЕНТОВ ====================

    @staticmethod
    @log_exceptions(db_logger)
    async def has_subitems(
        session: AsyncSession,
        group_id: int,
        item_id: int,
    ) -> bool:
        """
        Проверка, есть ли у пункта меню дочерние элементы.

        Args:
            session: Сессия БД (main)
            group_id: ID группы действий
            item_id: ID пункта меню

        Returns:
            bool: True если есть дочерние элементы
        """
        try:
            # Используем EXISTS для быстрой проверки
            stmt = (
                select(AvanpostDirScenarioGroupItemModel)
                .where(
                    AvanpostDirScenarioGroupItemModel.FK_ScenarioGroup == group_id,
                    AvanpostDirScenarioGroupItemModel.FK_ParentItem == item_id,
                )
                .limit(1)
            )

            result = await session.execute(stmt)
            child = result.scalar_one_or_none()

            return child is not None

        except Exception as e:
            db_logger.error(f"❌ Failed to check subitems for item {item_id} in group {group_id}: {e}", exc_info=True)
            return False

    # ==================== ДЕРЕВО МЕНЮ (РЕКУРСИВНОЕ) ====================

    @staticmethod
    @log_exceptions(db_logger)
    async def get_menu_tree(
        session: AsyncSession,
        group_id: int,
        max_depth: int = 5,
        lang_code: str = "ru",
    ) -> list[dict[str, Any]]:
        """
        Получение полного дерева меню (рекурсивно).

        Args:
            session: Сессия БД (main)
            group_id: ID группы действий
            max_depth: Максимальная глубина рекурсии
            lang_code: Код языка

        Returns:
            list[dict]: Дерево меню с вложенными children
        """

        async def _build_tree(parent_id: int | None, current_depth: int) -> list[dict[str, Any]]:
            if current_depth >= max_depth:
                return []

            items = await AvanpostActionsRepository.get_menu_items(
                session=session,
                group_id=group_id,
                parent_item_id=parent_id,
                lang_code=lang_code,
            )

            tree = []
            for item in items:
                node = {
                    "id": item["id"],
                    "name": item["name"],
                    "has_subitems": item["has_subitems"],
                    "parent_id": item["parent_id"],
                    "children": [],
                }

                if item["has_subitems"] and current_depth < max_depth - 1:
                    node["children"] = await _build_tree(
                        parent_id=item["id"],
                        current_depth=current_depth + 1,
                    )

                tree.append(node)

            return tree

        return await _build_tree(parent_id=None, current_depth=0)

    # ==================== ПРЯМЫЕ SQL-ЗАПРОСЫ (ДЛЯ ОПТИМИЗАЦИИ) ====================

    @staticmethod
    @log_exceptions(db_logger)
    async def get_menu_items_raw_sql(
        session: AsyncSession,
        group_id: int,
        parent_item_id: int | None = None,
        lang_code: str = "ru",
    ) -> list[dict[str, Any]]:
        """
        Получение пунктов меню через сырой SQL (оптимизированный вариант).

        Используется для случаев, когда нужна максимальная производительность.

        Args:
            session: Сессия БД (main)
            group_id: ID группы действий
            parent_item_id: ID родительского пункта
            lang_code: Код языка

        Returns:
            list[dict]: Список пунктов меню
        """
        try:
            # SQL-запрос с JOIN для получения названий на нужном языке
            sql = """
                SELECT
                    i.FID as id,
                    COALESCE(l.FName, i.FCode, 'Item ' || CAST(i.FID AS TEXT)) as name,
                    CASE
                        WHEN EXISTS (
                            SELECT 1
                            FROM TAvanpostDirScenariosGroupsItems child
                            WHERE child.FK_ParentItem = i.FID
                        ) THEN true
                        ELSE false
                    END as has_subitems,
                    i.FK_ParentItem as parent_id,
                    i.FLevel as level,
                    i.FPosition as position,
                    i.FCode as code
                FROM TAvanpostDirScenariosGroupsItems i
                LEFT JOIN TAvanpostDirScenariosGroupsItemsLangs l
                    ON l.FK_Parent = i.FID AND l.FK_Lang = :lang_code
                WHERE i.FK_ScenarioGroup = :group_id
                AND (
                    (:parent_id IS NULL AND i.FK_ParentItem IS NULL)
                    OR (i.FK_ParentItem = :parent_id)
                )
                ORDER BY i.FLevel, i.FPosition
            """

            result = await session.execute(
                text(sql),
                {
                    "group_id": group_id,
                    "parent_id": parent_item_id,
                    "lang_code": lang_code,
                },
            )

            rows = result.fetchall()
            items = [
                {
                    "id": row.id,
                    "name": row.name,
                    "has_subitems": row.has_subitems,
                    "parent_id": row.parent_id,
                    "level": row.level,
                    "position": row.position,
                    "code": row.code,
                }
                for row in rows
            ]

            db_logger.debug(
                f"📋 Retrieved {len(items)} menu items via raw SQL "
                f"for group {group_id}, parent={parent_item_id}, lang={lang_code}"
            )
            return items

        except Exception as e:
            db_logger.error(f"❌ Failed to get menu items via raw SQL: {e}", exc_info=True)
            return []

    # ==================== ДОПОЛНИТЕЛЬНЫЕ МЕТОДЫ ====================

    @staticmethod
    @log_exceptions(db_logger)
    async def get_item_ancestors(
        session: AsyncSession,
        item_id: int,
        lang_code: str = "ru",
    ) -> list[dict[str, Any]]:
        """
        Получение всех предков пункта меню (путь от корня до элемента).

        Args:
            session: Сессия БД (main)
            item_id: ID пункта меню
            lang_code: Код языка

        Returns:
            list[dict]: Список предков от корня до родителя
        """
        ancestors: list[dict[str, Any]] = []
        current_id: int | None = item_id

        while current_id is not None:
            item = await AvanpostActionsRepository.get_menu_item_by_id(
                session=session,
                item_id=current_id,
                lang_code=lang_code,
            )
            if not item:
                break

            ancestors.insert(0, item)  # Вставляем в начало (корень первым)
            current_id = item.get("parent_id")

        return ancestors


__all__ = ["AvanpostActionsRepository"]
