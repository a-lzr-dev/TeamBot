from typing import Any

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field, field_validator
from sqlalchemy.ext.asyncio import AsyncSession

from ...db import AvanpostRepository, db_manager
from ...exceptions import log_exceptions
from ...logger import api_logger
from ...utils.datetime import get_timestamp

router = APIRouter(prefix="/avanpost", tags=["Avanpost"])


class CheckUserRequest(BaseModel):
    """Модель запроса для проверки пользователя"""

    phone_number: str = Field(..., description="Номер телефона", min_length=5, max_length=20)

    @field_validator("phone_number")
    @classmethod
    def validate_phone(cls, v: str) -> str:
        """Валидация и нормализация номера телефона."""
        cleaned = "".join(c for c in v if c.isdigit() or c == "+")

        if not cleaned:
            raise ValueError("Phone number cannot be empty")

        if len(cleaned) < 5:
            raise ValueError("Phone number must be at least 5 characters")

        if len(cleaned) > 20:
            raise ValueError("Phone number must not exceed 20 characters")

        return cleaned


class CheckUserResponse(BaseModel):
    """Модель ответа для проверки пользователя"""

    success: bool = Field(..., description="Успешность операции")
    user_id: int | None = Field(None, description="ID пользователя в Avanpost")
    group_id: int | None = Field(None, description="ID группы действий")
    phone_number: str = Field(..., description="Проверяемый номер телефона")
    exists: bool = Field(False, description="Существует ли пользователь")
    timestamp: str = Field(..., description="Время проверки")


class MenuItemResponse(BaseModel):
    """Модель пункта меню"""

    id: int = Field(..., description="ID пункта")
    name: str = Field(..., description="Название")
    has_subitems: bool = Field(False, description="Есть ли дочерние элементы")
    parent_id: int | None = Field(None, description="ID родительского элемента")


class MenuItemsResponse(BaseModel):
    """Модель ответа со списком меню"""

    success: bool = Field(..., description="Успешность операции")
    group_id: int = Field(..., description="ID группы")
    parent_item_id: int | None = Field(None, description="ID родительского элемента")
    items: list[MenuItemResponse] = Field(default_factory=list, description="Список пунктов меню")
    count: int = Field(0, description="Количество пунктов")
    timestamp: str = Field(..., description="Время запроса")


class GroupResponse(BaseModel):
    """Модель группы действий"""

    id: int = Field(..., description="ID группы")
    name: str = Field(..., description="Название группы")


class GroupsResponse(BaseModel):
    """Модель ответа со списком групп"""

    success: bool = Field(..., description="Успешность операции")
    groups: list[GroupResponse] = Field(default_factory=list, description="Список групп")
    count: int = Field(0, description="Количество групп")
    timestamp: str = Field(..., description="Время запроса")


class CheckSubitemsResponse(BaseModel):
    """Модель ответа для проверки наличия подэлементов"""

    success: bool = Field(..., description="Успешность операции")
    group_id: int = Field(..., description="ID группы")
    item_id: int = Field(..., description="ID элемента")
    has_subitems: bool = Field(False, description="Есть ли дочерние элементы")
    timestamp: str = Field(..., description="Время проверки")


class ErrorResponse(BaseModel):
    """Модель ответа при ошибке"""

    success: bool = Field(False, description="Успешность операции")
    error: str = Field(..., description="Сообщение об ошибке")
    timestamp: str = Field(..., description="Время ошибки")


# ============ Вспомогательные функции ============


def _validate_group_id(group_id: int) -> None:
    """Валидация ID группы"""
    if group_id <= 0:
        raise HTTPException(status_code=400, detail="Group ID must be positive")


def _validate_item_id(item_id: int) -> None:
    """Валидация ID элемента"""
    if item_id <= 0:
        raise HTTPException(status_code=400, detail="Item ID must be positive")


# ============ Эндпоинты ============


@router.post(
    "/users/check",
    response_model=CheckUserResponse,
    summary="Проверить пользователя по номеру телефона",
    description="Проверяет существование пользователя в системе Avanpost по номеру телефона через хранимую процедуру",
)
@log_exceptions(api_logger)
async def check_user_by_phone(
    request: CheckUserRequest,
) -> JSONResponse:
    """
    Проверка пользователя по номеру телефона.

    Args:
        request: Запрос с номером телефона (уже провалидирован и нормализован)

    Returns:
        CheckUserResponse: Результат проверки
    """
    api_logger.info(f"📱 Checking user by phone: {request.phone_number}")

    try:
        phone = request.phone_number

        async with db_manager.get_session("avanpost") as session:
            user_id, group_id = await AvanpostRepository.check_user_by_phone(
                session=session,
                phone_number=phone,
            )

        exists = user_id is not None

        api_logger.info(
            f"✅ User check completed: phone={phone}, exists={exists}, user_id={user_id}, group_id={group_id}"
        )

        return JSONResponse(
            status_code=200,
            content=CheckUserResponse(
                success=True,
                user_id=user_id,
                group_id=group_id,
                phone_number=phone,
                exists=exists,
                timestamp=get_timestamp(),
            ).model_dump(),
        )

    except HTTPException:
        raise
    except Exception as e:
        api_logger.error(f"❌ Failed to check user: {e}", exc_info=True)
        return JSONResponse(
            status_code=500,
            content=ErrorResponse(
                success=False,
                error=f"Failed to check user: {str(e)}",
                timestamp=get_timestamp(),
            ).model_dump(),
        )


@router.get(
    "/groups",
    response_model=GroupsResponse,
    summary="Получить список групп действий",
    description="Возвращает список всех групп действий из системы Avanpost",
)
@log_exceptions(api_logger)
async def get_groups() -> JSONResponse:
    """
    Получение списка групп действий.

    Returns:
        GroupsResponse: Список групп
    """
    api_logger.info("📋 Getting groups from Avanpost")

    try:
        async with db_manager.get_session("avanpost") as session:
            groups_data = await AvanpostRepository.get_groups(session=session)

        groups = [
            GroupResponse(
                id=g.get("id", 0),
                name=g.get("name", "Без названия"),
            )
            for g in groups_data
        ]

        api_logger.info(f"✅ Retrieved {len(groups)} groups")

        return JSONResponse(
            status_code=200,
            content=GroupsResponse(
                success=True,
                groups=groups,
                count=len(groups),
                timestamp=get_timestamp(),
            ).model_dump(),
        )

    except Exception as e:
        api_logger.error(f"❌ Failed to get groups: {e}", exc_info=True)
        return JSONResponse(
            status_code=500,
            content=ErrorResponse(
                success=False,
                error=f"Failed to get groups: {str(e)}",
                timestamp=get_timestamp(),
            ).model_dump(),
        )


@router.get(
    "/groups/{group_id}/menu",
    response_model=MenuItemsResponse,
    summary="Получить меню группы",
    description="Возвращает пункты меню для указанной группы действий",
)
@log_exceptions(api_logger)
async def get_menu_items(
    group_id: int,
    parent_item_id: int | None = Query(
        None,
        description="ID родительского элемента (None для корневого меню)",
    ),
) -> JSONResponse:
    """
    Получение пунктов меню для группы действий.

    Args:
        group_id: ID группы
        parent_item_id: ID родительского элемента (опционально)

    Returns:
        MenuItemsResponse: Список пунктов меню
    """
    api_logger.info(f"📋 Getting menu items for group {group_id}, parent={parent_item_id}")

    _validate_group_id(group_id)

    try:
        async with db_manager.get_session("avanpost") as session:
            items_data = await AvanpostRepository.get_menu_items(
                session=session,
                group_id=group_id,
                parent_item_id=parent_item_id,
            )

        items = [
            MenuItemResponse(
                id=item.get("id", 0),
                name=item.get("name", "Без названия"),
                has_subitems=item.get("has_subitems", False),
                parent_id=item.get("parent_id"),
            )
            for item in items_data
        ]

        api_logger.info(f"✅ Retrieved {len(items)} menu items for group {group_id}")

        return JSONResponse(
            status_code=200,
            content=MenuItemsResponse(
                success=True,
                group_id=group_id,
                parent_item_id=parent_item_id,
                items=items,
                count=len(items),
                timestamp=get_timestamp(),
            ).model_dump(),
        )

    except HTTPException:
        raise
    except Exception as e:
        api_logger.error(f"❌ Failed to get menu items: {e}", exc_info=True)
        return JSONResponse(
            status_code=500,
            content=ErrorResponse(
                success=False,
                error=f"Failed to get menu items: {str(e)}",
                timestamp=get_timestamp(),
            ).model_dump(),
        )


@router.get(
    "/groups/{group_id}/items/{item_id}/has-subitems",
    response_model=CheckSubitemsResponse,
    summary="Проверить наличие дочерних элементов",
    description="Проверяет, есть ли у пункта меню дочерние элементы",
)
@log_exceptions(api_logger)
async def check_has_subitems(
    group_id: int,
    item_id: int,
) -> JSONResponse:
    """
    Проверка наличия дочерних элементов у пункта меню.

    Args:
        group_id: ID группы
        item_id: ID пункта меню

    Returns:
        CheckSubitemsResponse: Результат проверки
    """
    api_logger.info(f"🔍 Checking subitems for group {group_id}, item {item_id}")

    _validate_group_id(group_id)
    _validate_item_id(item_id)

    try:
        async with db_manager.get_session("avanpost") as session:
            has_subitems = await AvanpostRepository.has_subitems(
                session=session,
                group_id=group_id,
                item_id=item_id,
            )

        api_logger.info(f"✅ Subitems check completed: group={group_id}, item={item_id}, has_subitems={has_subitems}")

        return JSONResponse(
            status_code=200,
            content=CheckSubitemsResponse(
                success=True,
                group_id=group_id,
                item_id=item_id,
                has_subitems=has_subitems,
                timestamp=get_timestamp(),
            ).model_dump(),
        )

    except HTTPException:
        raise
    except Exception as e:
        api_logger.error(f"❌ Failed to check subitems: {e}", exc_info=True)
        return JSONResponse(
            status_code=500,
            content=ErrorResponse(
                success=False,
                error=f"Failed to check subitems: {str(e)}",
                timestamp=get_timestamp(),
            ).model_dump(),
        )


@router.get(
    "/groups/{group_id}/menu/tree",
    summary="Получить дерево меню",
    description="Возвращает полное дерево меню для группы действий",
)
@log_exceptions(api_logger)
async def get_menu_tree(
    group_id: int,
    max_depth: int = Query(3, description="Максимальная глубина дерева", ge=1, le=10),
) -> JSONResponse:
    """
    Получение полного дерева меню для группы.

    Args:
        group_id: ID группы
        max_depth: Максимальная глубина

    Returns:
        JSONResponse: Дерево меню
    """
    api_logger.info(f"🌳 Getting menu tree for group {group_id}, max_depth={max_depth}")

    _validate_group_id(group_id)

    try:
        async with db_manager.get_session("avanpost") as session:
            root_items = await AvanpostRepository.get_menu_items(
                session=session,
                group_id=group_id,
                parent_item_id=None,
            )

            tree = await _build_menu_tree(
                session=session,
                group_id=group_id,
                items=root_items,
                current_depth=0,
                max_depth=max_depth,
            )

        return JSONResponse(
            status_code=200,
            content={
                "success": True,
                "group_id": group_id,
                "tree": tree,
                "count": len(tree),
                "timestamp": get_timestamp(),
            },
        )

    except HTTPException:
        raise
    except Exception as e:
        api_logger.error(f"❌ Failed to get menu tree: {e}", exc_info=True)
        return JSONResponse(
            status_code=500,
            content={
                "success": False,
                "error": f"Failed to get menu tree: {str(e)}",
                "timestamp": get_timestamp(),
            },
        )


@router.get(
    "/groups/{group_id}/menu/ancestors",
    summary="Получить путь к элементу",
    description="Возвращает путь (цепочку родителей) до указанного элемента",
)
@log_exceptions(api_logger)
async def get_item_ancestors(
    group_id: int,
    item_id: int = Query(..., description="ID элемента"),
) -> JSONResponse:
    """
    Получение пути к элементу меню.

    Args:
        group_id: ID группы
        item_id: ID элемента

    Returns:
        JSONResponse: Путь к элементу
    """
    api_logger.info(f"🔗 Getting ancestors for group {group_id}, item {item_id}")

    _validate_group_id(group_id)
    _validate_item_id(item_id)

    try:
        async with db_manager.get_session("avanpost") as session:
            all_items = await AvanpostRepository.get_menu_items(
                session=session,
                group_id=group_id,
                parent_item_id=None,
            )

            items_map = {item.get("id"): item for item in all_items}

            ancestors = []
            current_id: int | None = item_id

            while current_id is not None and current_id in items_map:
                item = items_map[current_id]
                ancestors.append(
                    {
                        "id": item.get("id"),
                        "name": item.get("name"),
                        "parent_id": item.get("parent_id"),
                    }
                )
                parent_id = item.get("parent_id")
                current_id = int(parent_id) if parent_id is not None else None

            ancestors.reverse()

        return JSONResponse(
            status_code=200,
            content={
                "success": True,
                "group_id": group_id,
                "item_id": item_id,
                "ancestors": ancestors,
                "depth": len(ancestors),
                "timestamp": get_timestamp(),
            },
        )

    except HTTPException:
        raise
    except Exception as e:
        api_logger.error(f"❌ Failed to get ancestors: {e}", exc_info=True)
        return JSONResponse(
            status_code=500,
            content={
                "success": False,
                "error": f"Failed to get ancestors: {str(e)}",
                "timestamp": get_timestamp(),
            },
        )


@router.get(
    "/health",
    summary="Проверка доступности Avanpost",
    description="Проверяет подключение к базе данных Avanpost",
)
@log_exceptions(api_logger)
async def health_check_avanpost() -> JSONResponse:
    """
    Проверка доступности Avanpost.

    Returns:
        JSONResponse: Статус подключения
    """
    api_logger.info("🔍 Checking Avanpost health...")

    try:
        async with db_manager.get_session("avanpost") as session:
            from sqlalchemy import text

            result = await session.execute(text("SELECT 1"))
            _ = result.fetchone()

        return JSONResponse(
            status_code=200,
            content={
                "success": True,
                "status": "healthy",
                "database": "avanpost",
                "timestamp": get_timestamp(),
            },
        )

    except Exception as e:
        api_logger.error(f"❌ Avanpost health check failed: {e}")
        return JSONResponse(
            status_code=503,
            content={
                "success": False,
                "status": "unhealthy",
                "database": "avanpost",
                "error": str(e),
                "timestamp": get_timestamp(),
            },
        )


# ============ Вспомогательные функции ============


async def _build_menu_tree(
    session: AsyncSession,
    group_id: int,
    items: list[dict[str, Any]],
    current_depth: int,
    max_depth: int,
) -> list[dict[str, Any]]:
    """
    Рекурсивное построение дерева меню.

    Args:
        session: Сессия БД
        group_id: ID группы
        items: Список элементов текущего уровня
        current_depth: Текущая глубина
        max_depth: Максимальная глубина

    Returns:
        list[dict]: Дерево меню
    """
    if current_depth >= max_depth or not items:
        return []

    tree = []

    for item in items:
        node = {
            "id": item.get("id"),
            "name": item.get("name"),
            "parent_id": item.get("parent_id"),
        }

        if item.get("has_subitems", False) and current_depth < max_depth - 1:
            children = await AvanpostRepository.get_menu_items(
                session=session,
                group_id=group_id,
                parent_item_id=item.get("id"),
            )

            node["children"] = await _build_menu_tree(
                session=session,
                group_id=group_id,
                items=children,
                current_depth=current_depth + 1,
                max_depth=max_depth,
            )
            node["has_children"] = bool(node["children"])
        else:
            node["children"] = []
            node["has_children"] = item.get("has_subitems", False) and current_depth < max_depth

        tree.append(node)

    return tree


__all__ = ["router"]
