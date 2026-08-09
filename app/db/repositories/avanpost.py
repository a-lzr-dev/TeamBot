from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from ...logger import tg_logger


class AvanpostRepository:
    """Репозиторий для работы с Avanpost (MSSQL)"""

    # ==================== ПОЛЬЗОВАТЕЛИ ====================

    @staticmethod
    async def check_user_by_phone(
        session: AsyncSession,
        phone_number: str,
    ) -> tuple[int | None, int | None]:
        """
        Проверка пользователя по номеру телефона через хранимую процедуру.

        Args:
            session: Сессия БД (avanpost)
            phone_number: Номер телефона

        Returns:
            Tuple[int | None, int | None]: (user_id, group_id) или (None, None)
        """
        try:
            sql = """
                EXEC ext.PA_avp_RSAppUsersObjectsContacts_Check
                    @Contact = :phone
            """

            result = await session.execute(text(sql), {"phone": phone_number})
            row = result.fetchone()

            if row:
                user_id = row[0] if len(row) > 0 else None
                group_id = row[1] if len(row) > 1 else None
                return user_id, group_id

            return None, None

        except Exception as e:
            tg_logger.error(f"❌ Failed to check user in Avanpost: {e}", exc_info=True)
            return None, None

    # ==================== ГРУППЫ ДЕЙСТВИЙ ====================

    @staticmethod
    async def get_groups(
        session: AsyncSession,
    ) -> list[dict]:
        """
        Получение списка групп действий из Avanpost.

        Args:
            session: Сессия БД (avanpost)

        Returns:
            List[Dict]: Список групп
        """
        try:
            sql = """
                EXEC ext.PA_avp_RSAppScenariosGroups_Load
            """

            result = await session.execute(text(sql))
            rows = result.fetchall()

            if not rows:
                return []

            columns = result.keys()
            groups = []

            for row in rows:
                item = dict(zip(columns, row, strict=False))
                groups.append(
                    {
                        "id": item.get("ID"),
                        "name": item.get("Name"),
                    }
                )

            return groups

        except Exception as e:
            tg_logger.error(f"❌ Failed to get groups: {e}", exc_info=True)
            return []

    # ==================== ДЕЙСТВИЯ ====================

    @staticmethod
    async def get_menu_items(
        session: AsyncSession,
        group_id: int,
        parent_item_id: int | None = None,
    ) -> list[dict]:
        """
        Получение действий из Avanpost.

        Args:
            session: Сессия БД (avanpost)
            group_id: ID группы
            parent_item_id: ID родительского элемента

        Returns:
            List[Dict]: Список пунктов меню
        """
        try:
            sql = """
                EXEC ext.PA_avp_RSAppScenariosGroupsItems_Load
                    @GroupID = :group_id,
                    @ParentItemID = :parent_item_id
            """

            result = await session.execute(text(sql), {"group_id": group_id, "parent_item_id": parent_item_id})
            rows = result.fetchall()

            if not rows:
                return []

            columns = result.keys()
            items = []

            for row in rows:
                item = dict(zip(columns, row, strict=False))
                items.append(
                    {
                        "id": item.get("ID"),
                        "name": item.get("Name"),
                        "has_subitems": bool(item.get("FlagHasSubItems") or False),
                        "parent_id": item.get("ParentItemID"),
                    }
                )

            return items

        except Exception as e:
            tg_logger.error(f"❌ Failed to get menu items: {e}", exc_info=True)
            return []

    @staticmethod
    async def has_subitems(
        session: AsyncSession,
        group_id: int,
        item_id: int,
    ) -> bool:
        """
        Проверка, есть ли у действия дочерние элементы.
        Использует get_menu_items для получения данных.

        Args:
            session: Сессия БД (avanpost)
            group_id: ID группы
            item_id: ID пункта меню

        Returns:
            bool: True, если есть дочерние элементы
        """
        try:
            items = await AvanpostRepository.get_menu_items(
                session=session,
                group_id=group_id,
                parent_item_id=item_id,
            )

            # Если есть элементы, значит есть дочерние
            return len(items) > 0

        except Exception as e:
            tg_logger.error(f"❌ Failed to check subitems for item {item_id} in group {group_id}: {e}", exc_info=True)
            return False

    # ==================== ОШИБКИ ====================

    @staticmethod
    async def check_error_exists_by_procedure(
        session: AsyncSession,
        error_code: str,
        check_procedure: str,
    ) -> bool:
        """
        Проверка существования ошибки через хранимую процедуру.

        Args:
            session: Сессия БД (avanpost)
            error_code: Код ошибки
            check_procedure: Имя хранимой процедуры для проверки

        Returns:
            bool: True, если ошибка все еще существует в системе
        """
        try:
            sql = f"EXEC {check_procedure} @ErrorCode = :error_code"
            result = await session.execute(text(sql), {"error_code": error_code})
            rows = result.fetchall()

            # Если есть строки - ошибка все еще существует
            return len(rows) > 0

        except Exception as e:
            tg_logger.error(f"❌ Failed to check error via procedure {check_procedure}: {e}", exc_info=True)
            return True


__all__ = ["AvanpostRepository"]
