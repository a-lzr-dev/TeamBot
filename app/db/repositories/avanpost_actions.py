from typing import Any

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from ...exceptions import log_exceptions
from ...logger import db_logger
from ...models.avanpost import (
    AvanpostDirScenarioGroupItemLinkScenarioModel,
    AvanpostDirScenarioGroupItemModel,
    AvanpostDirScenarioGroupModel,
    AvanpostDirScenarioModel,
    AvanpostDirScenarioTypeModel,
)


class AvanpostActionRepository:
    """
    Репозиторий для работы с меню действий Avanpost.

    Поддерживает:
    - Получение списка групп действий
    - Получение пунктов меню с поддержкой иерархии
    - Проверку наличия дочерних элементов
    - Поддержку локализации (языки)
    - Получение информации о действии для выполнения
    """

    # ==================== ГРУППЫ ДЕЙСТВИЙ ====================

    @staticmethod
    @log_exceptions(db_logger)
    async def get_groups(
        session: AsyncSession,
        lang_code: str = "RU",
    ) -> list[dict[str, Any]]:
        """
        Получение списка всех групп действий с учетом языка.

        Args:
            session: Сессия БД (main)
            lang_code: Код языка (по умолчанию 'ru')

        Returns:
            list[dict]: Список групп с полями id, name
        """
        db_logger.info(f"📋 [get_groups] START: lang={lang_code}")

        try:
            stmt = select(
                AvanpostDirScenarioGroupModel.FID,
                AvanpostDirScenarioGroupModel.FName,
            ).order_by(AvanpostDirScenarioGroupModel.FID)

            result = await session.execute(stmt)
            rows = result.all()

            db_logger.debug(f"📊 [get_groups] Raw rows count: {len(rows)}")

            groups = []
            for idx, row in enumerate(rows):
                group_data = {
                    "id": row.FID,
                    "name": row.FName,
                }
                groups.append(group_data)
                db_logger.debug(f"  [{idx + 1}] Group: id={row.FID}, name={row.FName}")

            db_logger.info(f"✅ [get_groups] FINISH: returned {len(groups)} groups")
            return groups

        except Exception as e:
            db_logger.error(f"❌ [get_groups] Failed to get groups: {e}", exc_info=True)
            return []

    # ==================== ПУНКТЫ МЕНЮ ====================

    @staticmethod
    @log_exceptions(db_logger)
    async def get_menu_items(
        session: AsyncSession,
        group_id: int,
        parent_item_id: int | None = None,
        lang_code: str = "RU",
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
        db_logger.info(
            f"📋 [get_menu_items] START: group_id={group_id}, parent_item_id={parent_item_id}, lang={lang_code}"
        )

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

            db_logger.debug(f"📊 [get_menu_items] Raw items count: {len(items)}")

            # Формирование результата с учетом языка
            menu_items = []
            for idx, item in enumerate(items):
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

                has_subitems = len(item.child_items) > 0 if hasattr(item, "child_items") else False

                menu_item = {
                    "id": item.FID,
                    "name": name,
                    "has_subitems": has_subitems,
                    "parent_id": item.FK_ParentItem,
                    "level": item.FLevel,
                    "position": item.FPosition,
                    "code": item.FCode,
                }
                menu_items.append(menu_item)
                db_logger.debug(f"  [{idx + 1}] Item: id={item.FID}, name={name}, has_subitems={has_subitems}")

            db_logger.info(f"✅ [get_menu_items] FINISH: returned {len(menu_items)} menu items")
            return menu_items

        except Exception as e:
            db_logger.error(f"❌ [get_menu_items] Failed to get menu items: {e}", exc_info=True)
            return []

    @staticmethod
    @log_exceptions(db_logger)
    async def get_menu_items_with_parent(
        session: AsyncSession,
        group_id: int,
        parent_item_id: int | None = None,
        lang_code: str = "RU",
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
        db_logger.info(
            f"📋 [get_menu_items_with_parent] START: group_id={group_id}, parent_item_id={parent_item_id}, lang={lang_code}"
        )

        # Получение пунктов меню
        items = await AvanpostActionRepository.get_menu_items(
            session=session,
            group_id=group_id,
            parent_item_id=parent_item_id,
            lang_code=lang_code,
        )

        # Получение информации о родителе (если есть)
        parent_name = None
        if parent_item_id is not None:
            parent = await AvanpostActionRepository.get_menu_item_by_id(
                session=session,
                item_id=parent_item_id,
                lang_code=lang_code,
            )
            if parent:
                parent_name = parent.get("name")
                db_logger.debug(f"📊 [get_menu_items_with_parent] Parent: id={parent_item_id}, name={parent_name}")

        result = {
            "items": items,
            "parent_name": parent_name,
            "parent_id": parent_item_id,
        }
        db_logger.info(f"✅ [get_menu_items_with_parent] FINISH: returned {len(items)} items")
        return result

    # ==================== ОТДЕЛЬНЫЙ ПУНКТ МЕНЮ ====================

    @staticmethod
    @log_exceptions(db_logger)
    async def get_menu_item_by_id(
        session: AsyncSession,
        item_id: int,
        lang_code: str = "RU",
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
        db_logger.info(f"🔍 [get_menu_item_by_id] START: item_id={item_id}, lang={lang_code}")

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
                db_logger.warning(f"⚠️ [get_menu_item_by_id] Item not found: item_id={item_id}")
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

            result_data = {
                "id": item.FID,
                "name": name,
                "has_subitems": len(item.child_items) > 0 if hasattr(item, "child_items") else False,
                "parent_id": item.FK_ParentItem,
                "group_id": item.FK_ScenarioGroup,
                "level": item.FLevel,
                "position": item.FPosition,
                "code": item.FCode,
            }
            db_logger.info(f"✅ [get_menu_item_by_id] FINISH: {result_data}")
            return result_data

        except Exception as e:
            db_logger.error(f"❌ [get_menu_item_by_id] Failed to get menu item {item_id}: {e}", exc_info=True)
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
        db_logger.info(f"🔍 [has_subitems] START: group_id={group_id}, item_id={item_id}")

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

            has = child is not None
            db_logger.info(f"✅ [has_subitems] FINISH: has_subitems={has}")
            return has

        except Exception as e:
            db_logger.error(
                f"❌ [has_subitems] Failed to check subitems for item {item_id} in group {group_id}: {e}", exc_info=True
            )
            return False

    # ==================== ДЕРЕВО МЕНЮ (РЕКУРСИВНОЕ) ====================

    @staticmethod
    @log_exceptions(db_logger)
    async def get_menu_tree(
        session: AsyncSession,
        group_id: int,
        max_depth: int = 5,
        lang_code: str = "RU",
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
        db_logger.info(f"🌳 [get_menu_tree] START: group_id={group_id}, max_depth={max_depth}, lang={lang_code}")

        async def _build_tree(parent_id: int | None, current_depth: int) -> list[dict[str, Any]]:
            if current_depth >= max_depth:
                return []

            items = await AvanpostActionRepository.get_menu_items(
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

        result = await _build_tree(parent_id=None, current_depth=0)
        db_logger.info(f"✅ [get_menu_tree] FINISH: built tree with {len(result)} root nodes")
        return result

    # ==================== ПРЯМЫЕ SQL-ЗАПРОСЫ (ДЛЯ ОПТИМИЗАЦИИ) ====================

    @staticmethod
    @log_exceptions(db_logger)
    async def get_menu_items_raw_sql(
        session: AsyncSession,
        group_id: int,
        parent_item_id: int | None = None,
        lang_code: str = "RU",
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
        db_logger.info(
            f"📋 [get_menu_items_raw_sql] START: group_id={group_id}, parent_item_id={parent_item_id}, lang={lang_code}"
        )

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

            db_logger.debug(f"📝 [get_menu_items_raw_sql] SQL: {sql}")

            result = await session.execute(
                text(sql),
                {
                    "group_id": group_id,
                    "parent_id": parent_item_id,
                    "lang_code": lang_code,
                },
            )

            rows = result.fetchall()
            db_logger.debug(f"📊 [get_menu_items_raw_sql] Raw rows count: {len(rows)}")

            items = []
            for idx, row in enumerate(rows):
                item_data = {
                    "id": row.id,
                    "name": row.name,
                    "has_subitems": row.has_subitems,
                    "parent_id": row.parent_id,
                    "level": row.level,
                    "position": row.position,
                    "code": row.code,
                }
                items.append(item_data)
                db_logger.debug(f"  [{idx + 1}] Item: id={row.id}, name={row.name}, has_subitems={row.has_subitems}")

            db_logger.info(f"✅ [get_menu_items_raw_sql] FINISH: returned {len(items)} menu items")
            return items

        except Exception as e:
            db_logger.error(f"❌ [get_menu_items_raw_sql] Failed to get menu items via raw SQL: {e}", exc_info=True)
            return []

    # ==================== ДОПОЛНИТЕЛЬНЫЕ МЕТОДЫ ====================

    @staticmethod
    @log_exceptions(db_logger)
    async def get_item_ancestors(
        session: AsyncSession,
        item_id: int,
        lang_code: str = "RU",
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
        db_logger.info(f"🔍 [get_item_ancestors] START: item_id={item_id}, lang={lang_code}")

        ancestors: list[dict[str, Any]] = []
        current_id: int | None = item_id

        while current_id is not None:
            item = await AvanpostActionRepository.get_menu_item_by_id(
                session=session,
                item_id=current_id,
                lang_code=lang_code,
            )
            if not item:
                break

            ancestors.insert(0, item)  # Вставляем в начало (корень первым)
            current_id = item.get("parent_id")

        db_logger.info(f"✅ [get_item_ancestors] FINISH: found {len(ancestors)} ancestors")
        return ancestors

    # ==================== НОВЫЕ МЕТОДЫ ДЛЯ ВЫПОЛНЕНИЯ ДЕЙСТВИЙ ====================

    @staticmethod
    @log_exceptions(db_logger)
    async def get_action_info(
        action_id: int,
        session: AsyncSession,
    ) -> dict[str, Any] | None:
        """
        Получает информацию о действии (FK_Type и FID сценария) по ID пункта меню.

        Цепочка связей:
        TAvanpostDirScenariosGroupsItems (action_id)
            -> TAvanpostDirScenariosGroupsItemsLinksScenarios (FK_Parent = action_id)
                -> TAvanpostDirScenarios (FK_Link)
                    -> TAvanpostDirScenariosTypes (FK_Type)

        Args:
            action_id: ID пункта меню (AvanpostDirScenarioGroupItemModel.FID)
            session: Асинхронная сессия SQLAlchemy

        Returns:
            Dict с ключами 'fk_type' и 'scenario_fid', или None если не найдено
        """
        db_logger.info(f"🔍 [get_action_info] START for action_id={action_id}")

        try:
            stmt = (
                select(
                    AvanpostDirScenarioModel.FK_Type,
                    AvanpostDirScenarioModel.FID.label("scenario_fid"),
                )
                .select_from(AvanpostDirScenarioGroupItemModel)
                .join(
                    AvanpostDirScenarioGroupItemLinkScenarioModel,
                    AvanpostDirScenarioGroupItemLinkScenarioModel.FK_Parent == AvanpostDirScenarioGroupItemModel.FID,
                )
                .join(
                    AvanpostDirScenarioModel,
                    AvanpostDirScenarioModel.FID == AvanpostDirScenarioGroupItemLinkScenarioModel.FK_Link,
                )
                .where(AvanpostDirScenarioGroupItemModel.FID == action_id)
            )

            result = await session.execute(stmt)
            row = result.first()

            db_logger.debug(f"📊 [get_action_info] Row: {row}")

            if not row:
                db_logger.warning(f"⚠️ [get_action_info] No action info found for action_id={action_id}")
                return None

            action_info = {
                "fk_type": row.FK_Type,
                "scenario_fid": row.scenario_fid,
            }
            db_logger.info(f"✅ [get_action_info] FINISH: {action_info}")
            return action_info

        except Exception as e:
            db_logger.error(f"❌ [get_action_info] Failed to get action info for {action_id}: {e}", exc_info=True)
            return None

    @staticmethod
    @log_exceptions(db_logger)
    async def get_action_info_with_names(
        action_id: int,
        session: AsyncSession,
    ) -> dict[str, Any] | None:
        """
        Получает информацию о действии с названиями типа и сценария.

        Args:
            action_id: ID пункта меню
            session: Асинхронная сессия SQLAlchemy

        Returns:
            Dict с полной информацией или None
        """
        db_logger.info(f"🔍 [get_action_info_with_names] START for action_id={action_id}")

        try:
            sql_query = (
                f"SELECT "
                f"TAvanpostDirScenarios.FK_Type, "
                f"TAvanpostDirScenarios.FID as scenario_fid, "
                f"TAvanpostDirScenariosTypes.FName as type_name, "
                f"TAvanpostDirScenarios.FName as scenario_name "
                f"FROM TAvanpostDirScenariosGroupsItems "
                f"JOIN TAvanpostDirScenariosGroupsItemsLinksScenarios ON TAvanpostDirScenariosGroupsItemsLinksScenarios.FK_Parent = TAvanpostDirScenariosGroupsItems.FID "
                f"JOIN TAvanpostDirScenarios ON TAvanpostDirScenarios.FID = TAvanpostDirScenariosGroupsItemsLinksScenarios.FK_Link "
                f"JOIN TAvanpostDirScenariosTypes ON TAvanpostDirScenariosTypes.FID = TAvanpostDirScenarios.FK_Type "
                f"WHERE TAvanpostDirScenariosGroupsItems.FID = {action_id}"
            )
            db_logger.debug(f"📝 [get_action_info_with_names] SQL: {sql_query}")

            stmt = (
                select(
                    AvanpostDirScenarioModel.FK_Type,
                    AvanpostDirScenarioModel.FID.label("scenario_fid"),
                    AvanpostDirScenarioTypeModel.FName.label("type_name"),
                    AvanpostDirScenarioModel.FName.label("scenario_name"),
                )
                .select_from(AvanpostDirScenarioGroupItemModel)
                .join(
                    AvanpostDirScenarioGroupItemLinkScenarioModel,
                    AvanpostDirScenarioGroupItemLinkScenarioModel.FK_Parent == AvanpostDirScenarioGroupItemModel.FID,
                )
                .join(
                    AvanpostDirScenarioModel,
                    AvanpostDirScenarioModel.FID == AvanpostDirScenarioGroupItemLinkScenarioModel.FK_Link,
                )
                .join(
                    AvanpostDirScenarioTypeModel,
                    AvanpostDirScenarioTypeModel.FID == AvanpostDirScenarioModel.FK_Type,
                )
                .where(AvanpostDirScenarioGroupItemModel.FID == action_id)
            )

            result = await session.execute(stmt)
            row = result.first()

            db_logger.debug(f"📊 [get_action_info_with_names] Row: {row}")

            if not row:
                db_logger.warning(f"⚠️ [get_action_info_with_names] No action info found for action_id={action_id}")
                return None

            action_info = {
                "fk_type": row.FK_Type,
                "scenario_fid": row.scenario_fid,
                "type_name": row.type_name,
                "scenario_name": row.scenario_name,
            }
            db_logger.info(f"✅ [get_action_info_with_names] FINISH: {action_info}")
            return action_info

        except Exception as e:
            db_logger.error(f"❌ [get_action_info_with_names] Failed: {e}", exc_info=True)
            return None

    @staticmethod
    @log_exceptions(db_logger)
    async def get_action_scenario_details(
        action_id: int,
        session: AsyncSession,
    ) -> dict[str, Any] | None:
        """
        Получает детальную информацию о сценарии действия.

        Args:
            action_id: ID пункта меню
            session: Асинхронная сессия SQLAlchemy

        Returns:
            Dict с детальной информацией или None
        """
        db_logger.info(f"🔍 [get_action_scenario_details] START for action_id={action_id}")

        try:
            stmt = (
                select(
                    AvanpostDirScenarioModel.FID.label("scenario_id"),
                    AvanpostDirScenarioModel.FName.label("scenario_name"),
                    AvanpostDirScenarioModel.FK_Type,
                    AvanpostDirScenarioModel.FFlagDefault,
                    AvanpostDirScenarioTypeModel.FName.label("type_name"),
                    AvanpostDirScenarioGroupItemModel.FID.label("action_id"),
                    AvanpostDirScenarioGroupItemModel.FCode.label("action_code"),
                )
                .select_from(AvanpostDirScenarioGroupItemModel)
                .join(
                    AvanpostDirScenarioGroupItemLinkScenarioModel,
                    AvanpostDirScenarioGroupItemLinkScenarioModel.FK_Parent == AvanpostDirScenarioGroupItemModel.FID,
                )
                .join(
                    AvanpostDirScenarioModel,
                    AvanpostDirScenarioModel.FID == AvanpostDirScenarioGroupItemLinkScenarioModel.FK_Link,
                )
                .join(
                    AvanpostDirScenarioTypeModel,
                    AvanpostDirScenarioTypeModel.FID == AvanpostDirScenarioModel.FK_Type,
                )
                .where(AvanpostDirScenarioGroupItemModel.FID == action_id)
            )

            result = await session.execute(stmt)
            row = result.first()

            db_logger.debug(f"📊 [get_action_scenario_details] Row: {row}")

            if not row:
                db_logger.warning(
                    f"⚠️ [get_action_scenario_details] No scenario details found for action_id={action_id}"
                )
                return None

            scenario_details = {
                "scenario_id": row.scenario_id,
                "scenario_name": row.scenario_name,
                "fk_type": row.FK_Type,
                "type_name": row.type_name,
                "is_default": row.FFlagDefault,
                "action_id": row.action_id,
                "action_code": row.action_code,
            }
            db_logger.info(f"✅ [get_action_scenario_details] FINISH: {scenario_details}")
            return scenario_details

        except Exception as e:
            db_logger.error(f"❌ [get_action_scenario_details] Failed: {e}", exc_info=True)
            return None

    @staticmethod
    @log_exceptions(db_logger)
    async def get_actions_by_type(
        fk_type: int,
        session: AsyncSession,
        limit: int = 100,
        offset: int = 0,
    ) -> list[dict[str, Any]]:
        """
        Получает список действий по типу сценария.

        Args:
            fk_type: ID типа сценария (TAvanpostDirScenariosTypes.FID)
            session: Асинхронная сессия SQLAlchemy
            limit: Лимит записей
            offset: Смещение

        Returns:
            list[dict]: Список действий
        """
        db_logger.info(f"📋 [get_actions_by_type] START: fk_type={fk_type}, limit={limit}, offset={offset}")

        try:
            stmt = (
                select(
                    AvanpostDirScenarioGroupItemModel.FID.label("action_id"),
                    AvanpostDirScenarioModel.FID.label("scenario_id"),
                    AvanpostDirScenarioModel.FName.label("scenario_name"),
                    AvanpostDirScenarioTypeModel.FName.label("type_name"),
                )
                .select_from(AvanpostDirScenarioGroupItemModel)
                .join(
                    AvanpostDirScenarioGroupItemLinkScenarioModel,
                    AvanpostDirScenarioGroupItemLinkScenarioModel.FK_Parent == AvanpostDirScenarioGroupItemModel.FID,
                )
                .join(
                    AvanpostDirScenarioModel,
                    AvanpostDirScenarioModel.FID == AvanpostDirScenarioGroupItemLinkScenarioModel.FK_Link,
                )
                .join(
                    AvanpostDirScenarioTypeModel,
                    AvanpostDirScenarioTypeModel.FID == AvanpostDirScenarioModel.FK_Type,
                )
                .where(AvanpostDirScenarioModel.FK_Type == fk_type)
                .order_by(
                    AvanpostDirScenarioGroupItemModel.FLevel,
                    AvanpostDirScenarioGroupItemModel.FPosition,
                )
                .limit(limit)
                .offset(offset)
            )

            result = await session.execute(stmt)
            rows = result.all()

            db_logger.debug(f"📊 [get_actions_by_type] Raw rows count: {len(rows)}")

            actions = []
            for idx, row in enumerate(rows):
                action_data = {
                    "action_id": row.action_id,
                    "scenario_id": row.scenario_id,
                    "scenario_name": row.scenario_name,
                    "type_name": row.type_name,
                }
                actions.append(action_data)
                db_logger.debug(f"  [{idx + 1}] Action: action_id={row.action_id}, scenario_name={row.scenario_name}")

            db_logger.info(f"✅ [get_actions_by_type] FINISH: returned {len(actions)} actions")
            return actions

        except Exception as e:
            db_logger.error(f"❌ [get_actions_by_type] Failed to get actions by type {fk_type}: {e}", exc_info=True)
            return []

    @staticmethod
    @log_exceptions(db_logger)
    async def get_scenario_types_dict(
        session: AsyncSession,
    ) -> dict[int, dict[str, Any]]:
        """
        Получает словарь типов сценариев для кеширования.

        Returns:
            dict: {type_id: {name, description, ...}}
        """
        db_logger.info("📋 [get_scenario_types_dict] START")

        try:
            stmt = select(
                AvanpostDirScenarioTypeModel.FID,
                AvanpostDirScenarioTypeModel.FName,
                AvanpostDirScenarioTypeModel.FOrderBy,
                AvanpostDirScenarioTypeModel.FFlagCustom,
            ).order_by(AvanpostDirScenarioTypeModel.FID)

            result = await session.execute(stmt)
            rows = result.all()

            db_logger.debug(f"📊 [get_scenario_types_dict] Raw rows count: {len(rows)}")

            types_dict = {
                row.FID: {
                    "name": row.FName,
                    "order_by": row.FOrderBy,
                    "is_custom": row.FFlagCustom,
                }
                for row in rows
            }

            db_logger.info(f"✅ [get_scenario_types_dict] FINISH: returned {len(types_dict)} types")
            return types_dict

        except Exception as e:
            db_logger.error(f"❌ [get_scenario_types_dict] Failed to get scenario types: {e}", exc_info=True)
            return {}


__all__ = ["AvanpostActionRepository"]
