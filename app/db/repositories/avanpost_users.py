"""
Репозиторий для работы с данными пользователей Avanpost.

Содержит методы для получения данных о пользователях, их заказах, чатах,
транспорте и других связанных сущностях.
"""

from typing import Any

from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from ...logger import db_logger
from ...models.avanpost import (
    AvanpostContactLangModel,
    AvanpostContactModel,
    AvanpostContactMsgModel,
    AvanpostMsgModel,
    AvanpostUserChatLangModel,
    AvanpostUserChatModel,
    AvanpostUserLinkChatContactMsgModel,
    AvanpostUserMissionLangModel,
    AvanpostUserMissionModel,
    AvanpostUserOrderLangModel,
    AvanpostUserOrderLinkMissionModel,
    AvanpostUserOrderModel,
    AvanpostUserVehicleModel,
)
from ...utils.decorators import log_exceptions


class AvanpostUserRepository:
    """
    Репозиторий для работы с данными пользователей Avanpost.

    Группы методов:
    1. Список пользователей (get_avanpost_users_page)
    2. Заказы пользователя (get_user_orders, get_user_orders_page)
    3. Чаты пользователя (get_user_chats, get_user_chats_page)
    4. Транспорт пользователя (get_user_vehicles, get_user_vehicles_page)
    5. Заказы перевозчика (get_carrier_orders_page)
    6. Сообщения чата (get_chat_messages_page) с фильтрацией по направлению
    7. Вспомогательные методы (get_contact_name)
    """

    # ==================== 1. СПИСОК ПОЛЬЗОВАТЕЛЕЙ ====================

    @staticmethod
    @log_exceptions(db_logger)
    async def get_avanpost_users_page(
        session: AsyncSession,
        page: int = 0,
        page_size: int = 10,
        search_query: str | None = None,
    ) -> dict[str, Any]:
        """
        Получение списка пользователей Avanpost с пагинацией и поиском.

        Используется для:
        - Команды /users (административный интерфейс)
        - Поиска пользователей по имени, телефону или связанному Telegram пользователю
        - Выбора пользователя для запуска меню действий от его имени

        Args:
            session: Сессия БД (main)
            page: Номер страницы (начиная с 0)
            page_size: Количество пользователей на странице
            search_query: Поисковый запрос (имя, фамилия, телефон)

        Returns:
            dict: {
                "users": list[dict],  # Список пользователей
                "total": int,         # Общее количество
                "page": int,          # Текущая страница
                "total_pages": int,   # Всего страниц
                "has_prev": bool,     # Есть ли предыдущая страница
                "has_next": bool,     # Есть ли следующая страница
                "search_query": str | None  # Текущий поисковый запрос
            }
        """
        db_logger.debug(
            f"📋 [get_avanpost_users_page] START: page={page}, page_size={page_size}, search={search_query}"
        )

        try:
            from ...models import AvanpostUserLinkModel, AvanpostUserModel, UserModel

            # Базовый запрос с подгрузкой связанных моделей
            stmt = (
                select(AvanpostUserModel)
                .options(selectinload(AvanpostUserModel.user_link).selectinload(AvanpostUserLinkModel.telegram_user))
                .order_by(AvanpostUserModel.FID)
            )

            # Применение поискового фильтра
            if search_query and len(search_query) >= 2:
                search_pattern = f"%{search_query}%"

                conditions = [
                    AvanpostUserModel.FName.ilike(search_pattern),
                    AvanpostUserModel.FPhone.ilike(search_pattern),
                ]

                # Поиск по связанному Telegram пользователю
                subquery = (
                    select(AvanpostUserLinkModel.FK_Parent)
                    .join(UserModel, AvanpostUserLinkModel.FK_Link == UserModel.FID)
                    .where(
                        or_(
                            UserModel.FFirstName.ilike(search_pattern),
                            UserModel.FLastName.ilike(search_pattern),
                            UserModel.FUserName.ilike(search_pattern),
                        )
                    )
                    .scalar_subquery()
                )
                conditions.append(AvanpostUserModel.FID.in_(subquery))

                stmt = stmt.where(or_(*conditions))
                db_logger.debug(f"📝 [get_avanpost_users_page] SQL with search: {stmt}")

            # Подсчет общего количества
            count_stmt = select(func.count()).select_from(AvanpostUserModel)
            db_logger.debug(f"📝 [get_avanpost_users_page] Count SQL: {count_stmt}")

            if search_query and len(search_query) >= 2:
                search_pattern = f"%{search_query}%"
                conditions = [
                    AvanpostUserModel.FName.ilike(search_pattern),
                    AvanpostUserModel.FPhone.ilike(search_pattern),
                ]
                subquery = (
                    select(AvanpostUserLinkModel.FK_Parent)
                    .join(UserModel, AvanpostUserLinkModel.FK_Link == UserModel.FID)
                    .where(
                        or_(
                            UserModel.FFirstName.ilike(search_pattern),
                            UserModel.FLastName.ilike(search_pattern),
                            UserModel.FUserName.ilike(search_pattern),
                        )
                    )
                    .scalar_subquery()
                )
                conditions.append(AvanpostUserModel.FID.in_(subquery))
                count_stmt = count_stmt.where(or_(*conditions))

            total_result = await session.execute(count_stmt)
            total = total_result.scalar() or 0
            total_pages = (total + page_size - 1) // page_size if total > 0 else 0

            db_logger.debug(f"📊 [get_avanpost_users_page] Total users: {total}, total_pages: {total_pages}")

            # Пагинация
            offset = page * page_size
            stmt = stmt.offset(offset).limit(page_size)

            result = await session.execute(stmt)
            users = result.scalars().all()

            # Форматирование пользователей
            users_data = []
            for idx, user in enumerate(users):
                telegram_user = None
                if user.user_link and user.user_link.telegram_user:
                    telegram_user = user.user_link.telegram_user

                fk_user = user.user_link.FK_Link if user.user_link else None

                user_data = {
                    "id": user.FID,
                    "name": user.FName or f"User #{user.FID}",
                    "phone": user.FPhone or "Не указан",
                    "group_id": user.FK_Group,
                    "telegram_id": fk_user,
                    "telegram_name": telegram_user.fullname if telegram_user else None,
                    "is_authorized": fk_user is not None,
                }
                users_data.append(user_data)

                db_logger.debug(
                    f"  [{idx + 1}] User: id={user.FID}, name={user_data['name']}, "
                    f"group_id={user.FK_Group}, authorized={user_data['is_authorized']}"
                )

            db_logger.info(
                f"✅ [get_avanpost_users_page] FINISH: returned {len(users_data)} users (total={total}, page={page})"
            )

            return {
                "users": users_data,
                "total": total,
                "page": page,
                "total_pages": total_pages,
                "has_prev": page > 0,
                "has_next": page < total_pages - 1,
                "search_query": search_query,
            }

        except Exception as e:
            db_logger.error(f"❌ [get_avanpost_users_page] Failed: {e}", exc_info=True)
            return {
                "users": [],
                "total": 0,
                "page": page,
                "total_pages": 0,
                "has_prev": False,
                "has_next": False,
                "search_query": search_query,
                "error": str(e),
            }

    # ==================== 2. ЗАКАЗЫ ПОЛЬЗОВАТЕЛЯ ====================

    @staticmethod
    @log_exceptions(db_logger)
    async def get_user_orders(
        session: AsyncSession,
        avanpost_user_id: int,
        lang_code: str = "RU",
    ) -> list[dict[str, Any]]:
        """
        Получение списка заказов заказчиков пользователя.

        Args:
            session: Сессия БД
            avanpost_user_id: ID пользователя в Avanpost
            lang_code: Код языка

        Returns:
            list[dict]: Список заказов заказчиков с полями id, name
        """
        db_logger.debug(f"📋 [get_user_orders] START for user_id={avanpost_user_id}, lang={lang_code}")

        try:
            stmt = (
                select(
                    AvanpostUserOrderModel.FID,
                    AvanpostUserOrderLangModel.FName,
                )
                .outerjoin(
                    AvanpostUserOrderLangModel,
                    AvanpostUserOrderLangModel.FK_Parent == AvanpostUserOrderModel.FID,
                )
                .where(
                    AvanpostUserOrderModel.FK_User == avanpost_user_id,
                    AvanpostUserOrderLangModel.FK_Lang == lang_code,
                )
                .order_by(AvanpostUserOrderModel.FPosition)
            )

            db_logger.debug(f"📝 [get_user_orders] SQL: {stmt.compile(compile_kwargs={'literal_binds': True})}")

            result = await session.execute(stmt)
            rows = result.all()

            db_logger.debug(f"📊 [get_user_orders] Raw rows count: {len(rows)}")

            orders = []
            for idx, row in enumerate(rows):
                order_data = {
                    "id": row.FID,
                    "name": row.FName or f"Order #{row.FID}",
                }
                orders.append(order_data)
                db_logger.debug(f"  [{idx + 1}] Order: id={row.FID}, name={row.FName}")

            db_logger.info(f"✅ [get_user_orders] FINISH: returned {len(orders)} orders for user {avanpost_user_id}")
            return orders

        except Exception as e:
            db_logger.error(f"❌ [get_user_orders] Failed to get user orders: {e}", exc_info=True)
            return []

    @staticmethod
    @log_exceptions(db_logger)
    async def get_user_orders_page(
        session: AsyncSession,
        avanpost_user_id: int,
        page: int = 0,
        page_size: int = 10,
        search_query: str | None = None,
        lang_code: str = "RU",
    ) -> dict[str, Any]:
        """
        Получение списка заказов заказчиков пользователя с пагинацией и поиском.

        Args:
            session: Сессия БД
            avanpost_user_id: ID пользователя в Avanpost
            page: Номер страницы (начиная с 0)
            page_size: Количество заказов на странице
            search_query: Поисковый запрос (поиск по названию)
            lang_code: Код языка

        Returns:
            dict: {
                "orders": list[dict],
                "total": int,
                "page": int,
                "total_pages": int,
                "has_prev": bool,
                "has_next": bool,
                "search_query": str | None
            }
        """
        db_logger.debug(
            f"📋 [get_user_orders_page] START: user_id={avanpost_user_id}, page={page}, search={search_query}"
        )

        try:
            # Базовый запрос
            stmt = (
                select(
                    AvanpostUserOrderModel.FID,
                    AvanpostUserOrderLangModel.FName,
                )
                .outerjoin(
                    AvanpostUserOrderLangModel,
                    AvanpostUserOrderLangModel.FK_Parent == AvanpostUserOrderModel.FID,
                )
                .where(
                    AvanpostUserOrderModel.FK_User == avanpost_user_id,
                    AvanpostUserOrderLangModel.FK_Lang == lang_code,
                )
            )

            # Применение поискового фильтра
            if search_query and len(search_query) >= 2:
                search_pattern = f"%{search_query}%"
                stmt = stmt.where(AvanpostUserOrderLangModel.FName.ilike(search_pattern))

            stmt = stmt.order_by(AvanpostUserOrderModel.FPosition)

            db_logger.debug(f"📝 [get_user_orders_page] SQL: {stmt.compile(compile_kwargs={'literal_binds': True})}")

            # Подсчет общего количества
            count_stmt = (
                select(func.count())
                .select_from(AvanpostUserOrderModel)
                .where(AvanpostUserOrderModel.FK_User == avanpost_user_id)
            )
            if search_query and len(search_query) >= 2:
                search_pattern = f"%{search_query}%"
                count_stmt = count_stmt.where(
                    AvanpostUserOrderModel.FID.in_(
                        select(AvanpostUserOrderLangModel.FK_Parent).where(
                            AvanpostUserOrderLangModel.FName.ilike(search_pattern)
                        )
                    )
                )

            db_logger.debug(
                f"📝 [get_user_orders_page] SQL (count): {count_stmt.compile(compile_kwargs={'literal_binds': True})}"
            )

            total_result = await session.execute(count_stmt)
            total = total_result.scalar() or 0
            total_pages = (total + page_size - 1) // page_size if total > 0 else 0

            # Пагинация
            offset = page * page_size
            stmt = stmt.offset(offset).limit(page_size)

            db_logger.debug(
                f"📝 [get_user_orders_page] SQL (paginated): {stmt.compile(compile_kwargs={'literal_binds': True})}"
            )

            result = await session.execute(stmt)
            rows = result.all()

            orders = [
                {
                    "id": row.FID,
                    "name": row.FName or f"Order #{row.FID}",
                }
                for row in rows
            ]

            db_logger.info(
                f"✅ [get_user_orders_page] FINISH: returned {len(orders)} orders for user {avanpost_user_id} "
                f"(total={total}, page={page})"
            )

            return {
                "orders": orders,
                "total": total,
                "page": page,
                "total_pages": total_pages,
                "has_prev": page > 0,
                "has_next": page < total_pages - 1,
                "search_query": search_query,
            }

        except Exception as e:
            db_logger.error(f"❌ [get_user_orders_page] Failed: {e}", exc_info=True)
            return {
                "orders": [],
                "total": 0,
                "page": page,
                "total_pages": 0,
                "has_prev": False,
                "has_next": False,
                "search_query": search_query,
                "error": str(e),
            }

    # ==================== 3. ЧАТЫ ПОЛЬЗОВАТЕЛЯ ====================

    @staticmethod
    @log_exceptions(db_logger)
    async def get_user_chats(
        session: AsyncSession,
        avanpost_user_id: int,
        lang_code: str = "RU",
    ) -> list[dict[str, Any]]:
        """
        Получение списка чатов пользователя.

        Args:
            session: Сессия БД
            avanpost_user_id: ID пользователя в Avanpost
            lang_code: Код языка

        Returns:
            list[dict]: Список чатов с полями id, name
        """
        db_logger.debug(f"📋 [get_user_chats] START for user_id={avanpost_user_id}, lang={lang_code}")

        try:
            stmt = (
                select(
                    AvanpostUserChatModel.FID,
                    AvanpostUserChatLangModel.FName,
                )
                .outerjoin(
                    AvanpostUserChatLangModel,
                    AvanpostUserChatLangModel.FK_Parent == AvanpostUserChatModel.FID,
                )
                .where(
                    AvanpostUserChatModel.FK_User == avanpost_user_id,
                    AvanpostUserChatLangModel.FK_Lang == lang_code,
                )
                .order_by(AvanpostUserChatModel.FID)
            )

            db_logger.debug(f"📝 [get_user_chats] SQL: {stmt.compile(compile_kwargs={'literal_binds': True})}")

            result = await session.execute(stmt)
            rows = result.all()

            db_logger.debug(f"📊 [get_user_chats] Raw rows count: {len(rows)}")

            chats = []
            for idx, row in enumerate(rows):
                chat_data = {
                    "id": row.FID,
                    "name": row.FName or f"Chat #{row.FID}",
                }
                chats.append(chat_data)
                db_logger.debug(f"  [{idx + 1}] Chat: id={row.FID}, name={row.FName}")

            db_logger.info(f"✅ [get_user_chats] FINISH: returned {len(chats)} chats for user {avanpost_user_id}")
            return chats

        except Exception as e:
            db_logger.error(f"❌ [get_user_chats] Failed to get user chats: {e}", exc_info=True)
            return []

    @staticmethod
    @log_exceptions(db_logger)
    async def get_user_chats_page(
        session: AsyncSession,
        avanpost_user_id: int,
        page: int = 0,
        page_size: int = 10,
        search_query: str | None = None,
        lang_code: str = "RU",
    ) -> dict[str, Any]:
        """
        Получение списка чатов пользователя с пагинацией и поиском.

        Args:
            session: Сессия БД
            avanpost_user_id: ID пользователя в Avanpost
            page: Номер страницы (начиная с 0)
            page_size: Количество чатов на странице
            search_query: Поисковый запрос (поиск по названию)
            lang_code: Код языка

        Returns:
            dict: {
                "chats": list[dict],
                "total": int,
                "page": int,
                "total_pages": int,
                "has_prev": bool,
                "has_next": bool,
                "search_query": str | None
            }
        """
        db_logger.debug(
            f"📋 [get_user_chats_page] START: user_id={avanpost_user_id}, page={page}, search={search_query}"
        )

        try:
            # Базовый запрос
            stmt = (
                select(
                    AvanpostUserChatModel.FID,
                    AvanpostUserChatLangModel.FName,
                )
                .outerjoin(
                    AvanpostUserChatLangModel,
                    AvanpostUserChatLangModel.FK_Parent == AvanpostUserChatModel.FID,
                )
                .where(
                    AvanpostUserChatModel.FK_User == avanpost_user_id,
                    AvanpostUserChatLangModel.FK_Lang == lang_code,
                )
            )

            # Применение поискового фильтра
            if search_query and len(search_query) >= 2:
                search_pattern = f"%{search_query}%"
                stmt = stmt.where(AvanpostUserChatLangModel.FName.ilike(search_pattern))

            stmt = stmt.order_by(AvanpostUserChatModel.FID)

            db_logger.debug(f"📝 [get_user_chats_page] SQL: {stmt.compile(compile_kwargs={'literal_binds': True})}")

            # Подсчет общего количества
            count_stmt = (
                select(func.count())
                .select_from(AvanpostUserChatModel)
                .where(AvanpostUserChatModel.FK_User == avanpost_user_id)
            )
            if search_query and len(search_query) >= 2:
                search_pattern = f"%{search_query}%"
                count_stmt = count_stmt.where(
                    AvanpostUserChatModel.FID.in_(
                        select(AvanpostUserChatLangModel.FK_Parent).where(
                            AvanpostUserChatLangModel.FName.ilike(search_pattern)
                        )
                    )
                )

            db_logger.debug(
                f"📝 [get_user_chats_page] SQL (count): {count_stmt.compile(compile_kwargs={'literal_binds': True})}"
            )

            total_result = await session.execute(count_stmt)
            total = total_result.scalar() or 0
            total_pages = (total + page_size - 1) // page_size if total > 0 else 0

            # Пагинация
            offset = page * page_size
            stmt = stmt.offset(offset).limit(page_size)

            db_logger.debug(
                f"📝 [get_user_chats_page] SQL (paginated): {stmt.compile(compile_kwargs={'literal_binds': True})}"
            )

            result = await session.execute(stmt)
            rows = result.all()

            chats = [
                {
                    "id": row.FID,
                    "name": row.FName or f"Chat #{row.FID}",
                }
                for row in rows
            ]

            db_logger.info(
                f"✅ [get_user_chats_page] FINISH: returned {len(chats)} chats for user {avanpost_user_id} "
                f"(total={total}, page={page})"
            )

            return {
                "chats": chats,
                "total": total,
                "page": page,
                "total_pages": total_pages,
                "has_prev": page > 0,
                "has_next": page < total_pages - 1,
                "search_query": search_query,
            }

        except Exception as e:
            db_logger.error(f"❌ [get_user_chats_page] Failed: {e}", exc_info=True)
            return {
                "chats": [],
                "total": 0,
                "page": page,
                "total_pages": 0,
                "has_prev": False,
                "has_next": False,
                "search_query": search_query,
                "error": str(e),
            }

    # ==================== 4. ТРАНСПОРТ ПОЛЬЗОВАТЕЛЯ ====================

    @staticmethod
    @log_exceptions(db_logger)
    async def get_user_vehicles(
        session: AsyncSession,
        avanpost_user_id: int,
        lang_code: str = "RU",
    ) -> list[dict[str, Any]]:
        """
        Получение списка транспорта пользователя.

        Args:
            session: Сессия БД
            avanpost_user_id: ID пользователя в Avanpost
            lang_code: Код языка

        Returns:
            list[dict]: Список транспорта с полями id, name
        """
        db_logger.debug(f"📋 [get_user_vehicles] START for user_id={avanpost_user_id}, lang={lang_code}")

        try:
            stmt = (
                select(
                    AvanpostUserVehicleModel.FID,
                    AvanpostContactLangModel.FName,
                )
                .join(
                    AvanpostContactModel,
                    AvanpostContactModel.FID == AvanpostUserVehicleModel.FK_Contact,
                )
                .outerjoin(
                    AvanpostContactLangModel,
                    AvanpostContactLangModel.FK_Parent == AvanpostContactModel.FID,
                )
                .where(
                    AvanpostUserVehicleModel.FK_User == avanpost_user_id,
                    AvanpostContactLangModel.FK_Lang == lang_code,
                )
                .order_by(AvanpostUserVehicleModel.FPosition)
            )

            db_logger.debug(f"📝 [get_user_vehicles] SQL: {stmt.compile(compile_kwargs={'literal_binds': True})}")

            result = await session.execute(stmt)
            rows = result.all()

            db_logger.debug(f"📊 [get_user_vehicles] Raw rows count: {len(rows)}")

            vehicles = []
            for idx, row in enumerate(rows):
                vehicle_data = {
                    "id": row.FID,
                    "name": row.FName or f"Vehicle #{row.FID}",
                }
                vehicles.append(vehicle_data)
                db_logger.debug(f"  [{idx + 1}] Vehicle: id={row.FID}, name={row.FName}")

            db_logger.info(
                f"✅ [get_user_vehicles] FINISH: returned {len(vehicles)} vehicles for user {avanpost_user_id}"
            )
            return vehicles

        except Exception as e:
            db_logger.error(f"❌ [get_user_vehicles] Failed to get user vehicles: {e}", exc_info=True)
            return []

    @staticmethod
    @log_exceptions(db_logger)
    async def get_user_vehicles_page(
        session: AsyncSession,
        avanpost_user_id: int,
        page: int = 0,
        page_size: int = 10,
        search_query: str | None = None,
        lang_code: str = "RU",
    ) -> dict[str, Any]:
        """
        Получение списка транспорта пользователя с пагинацией и поиском.

        Args:
            session: Сессия БД
            avanpost_user_id: ID пользователя в Avanpost
            page: Номер страницы
            page_size: Количество транспорта на странице
            search_query: Поисковый запрос (поиск по названию)
            lang_code: Код языка

        Returns:
            dict: {
                "vehicles": list[dict],
                "total": int,
                "page": int,
                "total_pages": int,
                "has_prev": bool,
                "has_next": bool,
                "search_query": str | None
            }
        """
        db_logger.debug(
            f"📋 [get_user_vehicles_page] START: user_id={avanpost_user_id}, page={page}, search={search_query}"
        )

        try:
            # Базовый запрос
            stmt = (
                select(
                    AvanpostUserVehicleModel.FID,
                    AvanpostContactLangModel.FName,
                )
                .join(
                    AvanpostContactModel,
                    AvanpostContactModel.FID == AvanpostUserVehicleModel.FK_Contact,
                )
                .outerjoin(
                    AvanpostContactLangModel,
                    AvanpostContactLangModel.FK_Parent == AvanpostContactModel.FID,
                )
                .where(
                    AvanpostUserVehicleModel.FK_User == avanpost_user_id,
                    AvanpostContactLangModel.FK_Lang == lang_code,
                )
            )

            # Применение поискового фильтра
            if search_query and len(search_query) >= 2:
                search_pattern = f"%{search_query}%"
                stmt = stmt.where(AvanpostContactLangModel.FName.ilike(search_pattern))

            stmt = stmt.order_by(AvanpostUserVehicleModel.FPosition)

            db_logger.debug(f"📝 [get_user_vehicles_page] SQL: {stmt.compile(compile_kwargs={'literal_binds': True})}")

            # Подсчет общего количества
            count_stmt = (
                select(func.count())
                .select_from(AvanpostUserVehicleModel)
                .where(AvanpostUserVehicleModel.FK_User == avanpost_user_id)
            )
            if search_query and len(search_query) >= 2:
                search_pattern = f"%{search_query}%"
                count_stmt = count_stmt.where(
                    AvanpostUserVehicleModel.FK_Contact.in_(
                        select(AvanpostContactModel.FID)
                        .join(AvanpostContactLangModel, AvanpostContactLangModel.FK_Parent == AvanpostContactModel.FID)
                        .where(AvanpostContactLangModel.FName.ilike(search_pattern))
                    )
                )

            db_logger.debug(
                f"📝 [get_user_vehicles_page] SQL (count): {count_stmt.compile(compile_kwargs={'literal_binds': True})}"
            )

            total_result = await session.execute(count_stmt)
            total = total_result.scalar() or 0
            total_pages = (total + page_size - 1) // page_size if total > 0 else 0

            # Пагинация
            offset = page * page_size
            stmt = stmt.offset(offset).limit(page_size)

            db_logger.debug(
                f"📝 [get_user_vehicles_page] SQL (paginated): {stmt.compile(compile_kwargs={'literal_binds': True})}"
            )

            result = await session.execute(stmt)
            rows = result.all()

            vehicles = [
                {
                    "id": row.FID,
                    "name": row.FName or f"Vehicle #{row.FID}",
                }
                for row in rows
            ]

            db_logger.info(
                f"✅ [get_user_vehicles_page] FINISH: returned {len(vehicles)} vehicles for user {avanpost_user_id} "
                f"(total={total}, page={page})"
            )

            return {
                "vehicles": vehicles,
                "total": total,
                "page": page,
                "total_pages": total_pages,
                "has_prev": page > 0,
                "has_next": page < total_pages - 1,
                "search_query": search_query,
            }

        except Exception as e:
            db_logger.error(f"❌ [get_user_vehicles_page] Failed: {e}", exc_info=True)
            return {
                "vehicles": [],
                "total": 0,
                "page": page,
                "total_pages": 0,
                "has_prev": False,
                "has_next": False,
                "search_query": search_query,
                "error": str(e),
            }

    # ==================== 5. ЗАКАЗЫ ПЕРЕВОЗЧИКА ====================

    @staticmethod
    @log_exceptions(db_logger)
    async def get_carrier_orders_page(
        session: AsyncSession,
        avanpost_user_id: int,
        order_id: int | None = None,
        page: int = 0,
        page_size: int = 10,
        search_query: str | None = None,
        lang_code: str = "RU",
    ) -> dict[str, Any]:
        """
        Получение списка заказов перевозчиков для пользователя с пагинацией и поиском.

        Цепочка связей:
        TAvanpostUsersOrders.FID -> TAvanpostUsersLinksOrdersMissions.FK_Parent
        -> TAvanpostUsersLinksOrdersMissions.FK_Link -> TAvanpostUsersMissions.FID
        -> TAvanpostUsersMissionsLangs.FK_Parent

        Args:
            session: Сессия БД
            avanpost_user_id: ID пользователя в Avanpost
            order_id: ID заказа
            page: Номер страницы
            page_size: Размер страницы
            search_query: Поисковый запрос
            lang_code: Код языка

        Returns:
            dict: Словарь с данными заказов и пагинацией
        """
        db_logger.debug(
            f"📋 [get_carrier_orders_page] START: user_id={avanpost_user_id}, page={page}, search={search_query}"
        )

        try:
            # Базовый запрос
            stmt = (
                select(
                    AvanpostUserOrderModel.FID.label("order_id"),
                    AvanpostUserOrderModel.FPosition.label("order_position"),
                    AvanpostUserMissionModel.FID.label("mission_id"),
                    AvanpostUserMissionModel.FFlagCurrent.label("mission_is_current"),
                    AvanpostUserMissionModel.FFlagNext.label("mission_is_next"),
                    AvanpostUserMissionLangModel.FName.label("mission_name"),
                    AvanpostUserMissionLangModel.FInfo.label("mission_info"),
                )
                .select_from(AvanpostUserOrderModel)
                .join(
                    AvanpostUserOrderLinkMissionModel,
                    AvanpostUserOrderLinkMissionModel.FK_Parent == AvanpostUserOrderModel.FID,
                )
                .join(
                    AvanpostUserMissionModel,
                    AvanpostUserMissionModel.FID == AvanpostUserOrderLinkMissionModel.FK_Link,
                )
                .outerjoin(
                    AvanpostUserMissionLangModel,
                    AvanpostUserMissionLangModel.FK_Parent == AvanpostUserMissionModel.FID,
                )
                .where(
                    AvanpostUserOrderModel.FK_User == avanpost_user_id,
                    AvanpostUserMissionLangModel.FK_Lang == lang_code,
                )
            )

            # Применение фильтра по ID заказа
            if order_id is not None:
                stmt = stmt.where(AvanpostUserOrderLinkMissionModel.FK_Parent == order_id)

            # Применение поискового фильтра (по названию миссии)
            if search_query and len(search_query) >= 2:
                search_pattern = f"%{search_query}%"
                stmt = stmt.where(AvanpostUserMissionLangModel.FName.ilike(search_pattern))

            stmt = stmt.order_by(AvanpostUserOrderModel.FPosition, AvanpostUserOrderModel.FID)

            db_logger.debug(f"📝 [get_carrier_orders_page] SQL: {stmt.compile(compile_kwargs={'literal_binds': True})}")

            # Подсчет общего количества
            count_stmt = (
                select(func.count())
                .select_from(AvanpostUserOrderModel)
                .join(
                    AvanpostUserOrderLinkMissionModel,
                    AvanpostUserOrderLinkMissionModel.FK_Parent == AvanpostUserOrderModel.FID,
                )
                .join(
                    AvanpostUserMissionModel,
                    AvanpostUserMissionModel.FID == AvanpostUserOrderLinkMissionModel.FK_Link,
                )
                .outerjoin(
                    AvanpostUserMissionLangModel,
                    AvanpostUserMissionLangModel.FK_Parent == AvanpostUserMissionModel.FID,
                )
                .where(
                    AvanpostUserOrderModel.FK_User == avanpost_user_id,
                    AvanpostUserMissionLangModel.FK_Lang == lang_code,
                )
            )

            if search_query and len(search_query) >= 2:
                search_pattern = f"%{search_query}%"
                count_stmt = count_stmt.where(AvanpostUserMissionLangModel.FName.ilike(search_pattern))

            db_logger.debug(
                f"📝 [get_carrier_orders_page] SQL (count): {count_stmt.compile(compile_kwargs={'literal_binds': True})}"
            )

            total_result = await session.execute(count_stmt)
            total = total_result.scalar() or 0
            total_pages = (total + page_size - 1) // page_size if total > 0 else 0

            # Пагинация
            offset = page * page_size
            stmt = stmt.offset(offset).limit(page_size)

            db_logger.debug(
                f"📝 [get_carrier_orders_page] SQL (paginated): {stmt.compile(compile_kwargs={'literal_binds': True})}"
            )

            result = await session.execute(stmt)
            rows = result.all()

            orders = []
            for row in rows:
                orders.append(
                    {
                        "id": row.mission_id,
                        "name": row.mission_name or f"Миссия #{row.mission_id}",
                        "info": row.mission_info,
                        "order_id": row.order_id,
                        "mission_id": row.mission_id,
                        "is_current": row.mission_is_current,
                        "is_next": row.mission_is_next,
                        "order_position": row.order_position,
                    }
                )

            db_logger.info(f"✅ [get_carrier_orders_page] FINISH: returned {len(orders)} carrier orders")

            return {
                "orders": orders,
                "total": total,
                "page": page,
                "total_pages": total_pages,
                "has_prev": page > 0,
                "has_next": page < total_pages - 1,
                "search_query": search_query,
            }

        except Exception as e:
            db_logger.error(f"❌ [get_carrier_orders_page] Failed: {e}", exc_info=True)
            return {
                "orders": [],
                "total": 0,
                "page": page,
                "total_pages": 0,
                "has_prev": False,
                "has_next": False,
                "search_query": search_query,
                "error": str(e),
            }

    # ==================== 6. СООБЩЕНИЯ ЧАТА С ФИЛЬТРАЦИЕЙ ====================

    @staticmethod
    @log_exceptions(db_logger)
    async def get_chat_messages_page(
        session: AsyncSession,
        avanpost_user_id: int,
        chat_id: int,
        page: int = 0,
        page_size: int = 20,
        exclude_direction: int | None = None,
    ) -> dict[str, Any]:
        """
        Получение списка сообщений в чате с пагинацией и фильтрацией по направлению.

        Цепочка связей:
        TAvanpostUsersLinksChatsContactsMsgs.FK_Parent -> TAvanpostContactsMsgs.FID
        -> TAvanpostContactsMsgs.FK_Link -> TAvanpostMsgs.FID

        Args:
            session: Сессия БД
            avanpost_user_id: ID пользователя в Avanpost (не используется в запросе, но нужен для API)
            chat_id: ID чата (TAvanpostUsersChats.FID)
            page: Номер страницы
            page_size: Размер страницы
            exclude_direction: Направление для исключения (например, 3)

        Returns:
            dict: Словарь с данными сообщений и пагинацией
        """
        db_logger.debug(
            f"📋 [get_chat_messages_page] START: user_id={avanpost_user_id}, chat_id={chat_id}, page={page}"
        )

        try:
            # Базовый запрос с добавлением поля direction
            stmt = (
                select(
                    AvanpostContactMsgModel.FID.label("message_id"),
                    AvanpostContactMsgModel.FDate.label("date"),
                    AvanpostContactMsgModel.FK_Direction.label("direction"),
                    AvanpostContactMsgModel.FK_Type.label("type"),
                    AvanpostContactMsgModel.FK_ContactAuthor.label("author_contact_id"),
                    AvanpostContactMsgModel.FK_ContactTarget.label("target_contact_id"),
                    AvanpostMsgModel.FID.label("msg_id"),
                    AvanpostMsgModel.FText.label("text"),
                    AvanpostMsgModel.FSize.label("size"),
                )
                .select_from(AvanpostUserLinkChatContactMsgModel)
                .join(
                    AvanpostContactMsgModel,
                    AvanpostContactMsgModel.FID == AvanpostUserLinkChatContactMsgModel.FK_Link,
                )
                .outerjoin(
                    AvanpostMsgModel,
                    AvanpostMsgModel.FID == AvanpostContactMsgModel.FK_Link,
                )
                .where(
                    AvanpostUserLinkChatContactMsgModel.FK_Parent == chat_id,
                )
            )

            # Фильтрация по направлению (исключаем FK_Direction = exclude_direction)
            if exclude_direction is not None:
                stmt = stmt.where(AvanpostContactMsgModel.FK_Direction != exclude_direction)
                db_logger.debug(f"🔍 [get_chat_messages_page] Excluding direction: {exclude_direction}")

            stmt = stmt.order_by(AvanpostContactMsgModel.FDate.desc())

            db_logger.debug(f"📝 [get_chat_messages_page] SQL: {stmt.compile(compile_kwargs={'literal_binds': True})}")

            # Подсчет общего количества с учетом фильтра
            count_stmt = (
                select(func.count())
                .select_from(AvanpostUserLinkChatContactMsgModel)
                .where(AvanpostUserLinkChatContactMsgModel.FK_Parent == chat_id)
            )

            # Добавление фильтра и в COUNT запрос
            if exclude_direction is not None:
                count_stmt = count_stmt.where(
                    AvanpostUserLinkChatContactMsgModel.FK_Link.in_(
                        select(AvanpostContactMsgModel.FID).where(
                            AvanpostContactMsgModel.FK_Direction != exclude_direction
                        )
                    )
                )

            db_logger.debug(
                f"📝 [get_chat_messages_page] SQL (count): {count_stmt.compile(compile_kwargs={'literal_binds': True})}"
            )

            total_result = await session.execute(count_stmt)
            total = total_result.scalar() or 0
            total_pages = (total + page_size - 1) // page_size if total > 0 else 0

            # Пагинация
            offset = page * page_size
            stmt = stmt.offset(offset).limit(page_size)

            db_logger.debug(
                f"📝 [get_chat_messages_page] SQL (paginated): {stmt.compile(compile_kwargs={'literal_binds': True})}"
            )

            result = await session.execute(stmt)
            rows = result.all()

            messages = []
            for row in rows:
                # Получаем имена автора и получателя
                author_name = await AvanpostUserRepository.get_contact_name(
                    session, row.author_contact_id, lang_code="RU"
                )
                target_name = await AvanpostUserRepository.get_contact_name(
                    session, row.target_contact_id, lang_code="RU"
                )

                messages.append(
                    {
                        "id": row.message_id,
                        "date": row.date.isoformat() if row.date else None,
                        "direction": row.direction,  # <-- ДОБАВЛЯЕМ DIRECTION В РЕЗУЛЬТАТ
                        "type": row.type,
                        "author_contact_id": row.author_contact_id,
                        "author_name": author_name,
                        "target_contact_id": row.target_contact_id,
                        "target_name": target_name,
                        "text": row.text,
                        "size": row.size,
                        "has_attachments": row.size is not None and row.size > 0,
                        "msg_id": row.msg_id,
                    }
                )

            db_logger.info(f"✅ [get_chat_messages_page] FINISH: returned {len(messages)} messages")

            return {
                "messages": messages,
                "total": total,
                "page": page,
                "total_pages": total_pages,
                "has_prev": page > 0,
                "has_next": page < total_pages - 1,
            }

        except Exception as e:
            db_logger.error(f"❌ [get_chat_messages_page] Failed: {e}", exc_info=True)
            return {
                "messages": [],
                "total": 0,
                "page": page,
                "total_pages": 0,
                "has_prev": False,
                "has_next": False,
                "error": str(e),
            }

    @staticmethod
    @log_exceptions(db_logger)
    async def get_message_by_id(
        session: AsyncSession,
        message_id: int,
    ) -> dict[str, Any] | None:
        """
        Получение сообщения по ID из TAvanpostContactsMsgs.

        Args:
            session: Сессия БД
            message_id: ID сообщения (TAvanpostContactsMsgs.FID)

        Returns:
            dict | None: Данные сообщения или None
        """
        db_logger.debug(f"🔍 [get_message_by_id] Getting message by ID: {message_id}")

        try:
            stmt = (
                select(
                    AvanpostContactMsgModel.FID.label("id"),
                    AvanpostContactMsgModel.FDate.label("date"),
                    AvanpostContactMsgModel.FK_Direction.label("direction"),
                    AvanpostContactMsgModel.FK_Type.label("type"),
                    AvanpostContactMsgModel.FK_ContactAuthor.label("author_contact_id"),
                    AvanpostContactMsgModel.FK_ContactTarget.label("target_contact_id"),
                    AvanpostMsgModel.FID.label("msg_id"),
                    AvanpostMsgModel.FText.label("text"),
                    AvanpostMsgModel.FSize.label("size"),
                )
                .select_from(AvanpostContactMsgModel)
                .outerjoin(
                    AvanpostMsgModel,
                    AvanpostMsgModel.FID == AvanpostContactMsgModel.FK_Link,
                )
                .where(AvanpostContactMsgModel.FID == message_id)
            )

            db_logger.debug(f"📝 SQL: {stmt.compile(compile_kwargs={'literal_binds': True})}")

            result = await session.execute(stmt)
            row = result.first()

            if not row:
                db_logger.warning(f"⚠️ Message {message_id} not found")
                return None

            # Получение имен контактов
            author_name = await AvanpostUserRepository.get_contact_name(session, row.author_contact_id, lang_code="RU")
            target_name = await AvanpostUserRepository.get_contact_name(session, row.target_contact_id, lang_code="RU")

            return {
                "id": row.id,
                "date": row.date.isoformat() if row.date else None,
                "direction": row.direction,
                "type": row.type,
                "author_contact_id": row.author_contact_id,
                "author_name": author_name,
                "target_contact_id": row.target_contact_id,
                "target_name": target_name,
                "text": row.text,
                "size": row.size,
                "has_attachments": row.size is not None and row.size > 0,
                "msg_id": row.msg_id,
            }

        except Exception as e:
            db_logger.error(f"❌ Failed to get message {message_id}: {e}", exc_info=True)
            return None

    # ==================== 7. ВСПОМОГАТЕЛЬНЫЕ МЕТОДЫ ====================

    @staticmethod
    @log_exceptions(db_logger)
    async def get_contact_name(
        session: AsyncSession,
        contact_id: int | None,
        lang_code: str = "RU",
    ) -> str | None:
        """
        Получение имени контакта по его ID.

        Args:
            session: Сессия БД
            contact_id: ID контакта (TAvanpostContacts.FID)
            lang_code: Код языка

        Returns:
            str | None: Имя контакта или None
        """
        if not contact_id:
            return None

        try:
            stmt = select(AvanpostContactLangModel.FName).where(
                AvanpostContactLangModel.FK_Parent == contact_id,
                AvanpostContactLangModel.FK_Lang == lang_code,
            )
            db_logger.debug(f"📝 [get_contact_name] SQL: {stmt.compile(compile_kwargs={'literal_binds': True})}")

            result = await session.execute(stmt)
            name = result.scalar_one_or_none()
            return name or f"Контакт #{contact_id}"
        except Exception as e:
            db_logger.error(f"❌ [get_contact_name] Failed: {e}", exc_info=True)
            return f"Контакт #{contact_id}"


__all__ = ["AvanpostUserRepository"]
