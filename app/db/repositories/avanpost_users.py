from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from ...exceptions import log_exceptions
from ...logger import db_logger
from ...models.avanpost import (
    AvanpostContactLangModel,
    AvanpostContactModel,
    AvanpostUserChatLangModel,
    AvanpostUserChatModel,
    AvanpostUserOrderLangModel,
    AvanpostUserOrderModel,
    AvanpostUserVehicleModel,
)


class AvanpostUserRepository:
    """Репозиторий для работы с данными пользователей Avanpost."""

    @staticmethod
    @log_exceptions(db_logger)
    async def get_user_orders(
        session: AsyncSession,
        avanpost_user_id: int,
        lang_code: str = "RU",
    ) -> list[dict[str, Any]]:
        """
        Получение списка заказов пользователя.

        Args:
            session: Сессия БД
            avanpost_user_id: ID пользователя в Avanpost
            lang_code: Код языка

        Returns:
            list[dict]: Список заказов с полями id, name
        """
        db_logger.info(f"📋 [get_user_orders] START for user_id={avanpost_user_id}, lang={lang_code}")

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

            compiled = stmt.compile(compile_kwargs={"literal_binds": True})
            db_logger.debug(f"📝 [get_user_orders] SQL: {compiled}")

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
        Получение списка заказов пользователя с пагинацией и поиском.

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
        db_logger.info(
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
            total_result = await session.execute(count_stmt)
            total = total_result.scalar() or 0
            total_pages = (total + page_size - 1) // page_size if total > 0 else 0

            # Пагинация
            offset = page * page_size
            stmt = stmt.offset(offset).limit(page_size)

            result = await session.execute(stmt)
            rows = result.all()

            orders = [
                {
                    "id": row.FID,
                    "name": row.FName or f"Order #{row.FID}",
                }
                for row in rows
            ]

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
        db_logger.info(f"📋 [get_user_chats] START for user_id={avanpost_user_id}, lang={lang_code}")

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

            compiled = stmt.compile(compile_kwargs={"literal_binds": True})
            db_logger.debug(f"📝 [get_user_chats] SQL: {compiled}")

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
        db_logger.info(
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
            total_result = await session.execute(count_stmt)
            total = total_result.scalar() or 0
            total_pages = (total + page_size - 1) // page_size if total > 0 else 0

            # Пагинация
            offset = page * page_size
            stmt = stmt.offset(offset).limit(page_size)

            result = await session.execute(stmt)
            rows = result.all()

            chats = [
                {
                    "id": row.FID,
                    "name": row.FName or f"Chat #{row.FID}",
                }
                for row in rows
            ]

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
        db_logger.info(f"📋 [get_user_vehicles] START for user_id={avanpost_user_id}, lang={lang_code}")

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

            compiled = stmt.compile(compile_kwargs={"literal_binds": True})
            db_logger.debug(f"📝 [get_user_vehicles] SQL: {compiled}")

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
            page: Номер страницы (начиная с 0)
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
        db_logger.info(
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
            total_result = await session.execute(count_stmt)
            total = total_result.scalar() or 0
            total_pages = (total + page_size - 1) // page_size if total > 0 else 0

            # Пагинация
            offset = page * page_size
            stmt = stmt.offset(offset).limit(page_size)

            result = await session.execute(stmt)
            rows = result.all()

            vehicles = [
                {
                    "id": row.FID,
                    "name": row.FName or f"Vehicle #{row.FID}",
                }
                for row in rows
            ]

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


__all__ = ["AvanpostUserRepository"]
