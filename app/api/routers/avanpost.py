"""
Модуль роутера для интеграции с системой Avanpost.

Этот модуль предоставляет API эндпоинты для работы с данными из системы Avanpost:
- Проверка пользователей по номеру телефона
- Получение групп действий
- Получение иерархического меню действий
- Проверка наличия подэлементов в меню
- Проверка доступности базы данных Avanpost

Все эндпоинты используют общий префикс /avanpost и интегрируются
с репозиториями для работы с данными Avanpost.

Роуты:
    POST /users/check - Проверка пользователя по номеру телефона
    GET /groups - Получение списка групп действий
    GET /groups/{group_id}/menu - Получение меню группы
    GET /groups/{group_id}/items/{item_id}/has-subitems - Проверка наличия дочерних элементов
    GET /health - Проверка доступности базы данных Avanpost
"""

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field, field_validator
from sqlalchemy.ext.asyncio import AsyncSession

from ...db import db_manager
from ...db.repositories import AvanpostActionRepository, AvanpostRepository
from ...logger import api_logger
from ...utils.datetime import get_timestamp
from ...utils.decorators import log_exceptions
from ..dependencies import get_session

# Создание роутера с префиксом /avanpost и тегом для документации
router = APIRouter(prefix="/avanpost", tags=["Avanpost"])

# Репозиторий для работы с меню действий (создается один раз на уровне модуля)
_actions_repo = AvanpostActionRepository()


class CheckUserRequest(BaseModel):
    """
    Модель запроса для проверки пользователя по номеру телефона.

    Используется в эндпоинте /users/check для проверки существования
    пользователя в системе Avanpost.
    """

    phone_number: str = Field(..., description="Номер телефона пользователя", min_length=5, max_length=20)

    @field_validator("phone_number")
    @classmethod
    def validate_phone(cls, v: str) -> str:
        """
        Валидация и нормализация номера телефона.

        Удаляет все символы, кроме цифр и знака '+',
        и проверяет длину полученного номера.

        Args:
            v: Исходный номер телефона

        Returns:
            str: Очищенный и нормализованный номер

        Raises:
            ValueError: Если номер пустой или имеет некорректную длину
        """
        cleaned = "".join(c for c in v if c.isdigit() or c == "+")

        if not cleaned:
            raise ValueError("Phone number cannot be empty")

        if len(cleaned) < 5:
            raise ValueError("Phone number must be at least 5 characters")

        if len(cleaned) > 20:
            raise ValueError("Phone number must not exceed 20 characters")

        return cleaned


class CheckUserResponse(BaseModel):
    """Модель ответа для проверки пользователя в Avanpost."""

    success: bool = Field(..., description="Успешность выполнения операции")
    user_id: int | None = Field(None, description="ID пользователя в системе Avanpost")
    group_id: int | None = Field(None, description="ID группы действий пользователя")
    phone_number: str = Field(..., description="Проверяемый номер телефона")
    exists: bool = Field(False, description="Существует ли пользователь в системе")
    timestamp: str = Field(..., description="Время выполнения проверки")


class MenuItemResponse(BaseModel):
    """Модель отдельного пункта меню для ответа."""

    id: int = Field(..., description="Уникальный идентификатор пункта меню")
    name: str = Field(..., description="Название пункта меню")
    has_subitems: bool = Field(False, description="Имеет ли пункт дочерние элементы")
    parent_id: int | None = Field(None, description="ID родительского пункта (None для корневых)")


class MenuItemsResponse(BaseModel):
    """Модель ответа со списком пунктов меню для группы."""

    success: bool = Field(..., description="Успешность выполнения операции")
    group_id: int = Field(..., description="ID группы действий")
    parent_item_id: int | None = Field(None, description="ID родительского элемента (для подменю)")
    items: list[MenuItemResponse] = Field(default_factory=list, description="Список пунктов меню текущего уровня")
    count: int = Field(0, description="Количество пунктов в списке")
    timestamp: str = Field(..., description="Время выполнения запроса")


class GroupResponse(BaseModel):
    """Модель группы действий для ответа."""

    id: int = Field(..., description="Уникальный идентификатор группы")
    name: str = Field(..., description="Название группы действий")


class GroupsResponse(BaseModel):
    """Модель ответа со списком групп действий."""

    success: bool = Field(..., description="Успешность выполнения операции")
    groups: list[GroupResponse] = Field(default_factory=list, description="Список групп действий")
    count: int = Field(0, description="Количество групп в списке")
    timestamp: str = Field(..., description="Время выполнения запроса")


class CheckSubitemsResponse(BaseModel):
    """Модель ответа для проверки наличия дочерних элементов у пункта меню."""

    success: bool = Field(..., description="Успешность выполнения операции")
    group_id: int = Field(..., description="ID группы действий")
    item_id: int = Field(..., description="ID проверяемого пункта меню")
    has_subitems: bool = Field(False, description="Есть ли дочерние элементы")
    timestamp: str = Field(..., description="Время выполнения проверки")


class ErrorResponse(BaseModel):
    """Стандартная модель ответа при возникновении ошибки."""

    success: bool = Field(False, description="Успешность операции (всегда False)")
    error: str = Field(..., description="Сообщение об ошибке")
    timestamp: str = Field(..., description="Время возникновения ошибки")


# ============ Вспомогательные функции ============


def _validate_group_id(group_id: int) -> None:
    """
    Валидация ID группы действий.

    Args:
        group_id: Проверяемый ID

    Raises:
        HTTPException: Если ID <= 0
    """
    if group_id <= 0:
        raise HTTPException(status_code=400, detail="Group ID must be positive")


def _validate_item_id(item_id: int) -> None:
    """
    Валидация ID пункта меню.

    Args:
        item_id: Проверяемый ID

    Raises:
        HTTPException: Если ID <= 0
    """
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
    session: AsyncSession = Depends(get_session),
) -> JSONResponse:
    """
    Проверка существования пользователя в системе Avanpost по номеру телефона.

    Вызывает хранимую процедуру в базе данных Avanpost для поиска пользователя.
    Возвращает ID пользователя и ID его группы действий при наличии.

    Args:
        request: Запрос с номером телефона (уже провалидирован и нормализован)
        session: Асинхронная сессия SQLAlchemy (внедряется через Depends)

    Returns:
        JSONResponse: Результат проверки с информацией о пользователе

    Raises:
        HTTPException: При ошибках валидации или выполнения запроса
    """
    api_logger.info(f"📱 Checking user by phone: {request.phone_number}")

    try:
        phone = request.phone_number

        # Вызов репозитория для проверки пользователя
        user_id, group_id, contact_id = await AvanpostRepository.check_user_by_phone(
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
async def get_groups(
    session: AsyncSession = Depends(get_session),
) -> JSONResponse:
    """
    Получение списка всех групп действий из Avanpost.

    Группы действий используются для организации доступа и определения
    доступных функций для пользователя.

    Args:
        session: Асинхронная сессия SQLAlchemy (внедряется через Depends)

    Returns:
        JSONResponse: Список групп действий с ID и названиями
    """
    api_logger.info("📋 Getting groups from Avanpost")

    try:
        # Получение данных групп из репозитория
        groups_data = await _actions_repo.get_groups(
            session=session,
        )

        # Преобразование данных в формат ответа
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
    description="Возвращает пункты меню для указанной группы действий с поддержкой иерархии",
)
@log_exceptions(api_logger)
async def get_menu_items(
    group_id: int,
    parent_item_id: int | None = Query(
        None,
        description="ID родительского элемента (None для получения корневого меню)",
    ),
    session: AsyncSession = Depends(get_session),
) -> JSONResponse:
    """
    Получение иерархического списка действий для группы.

    Позволяет получить как корневое меню (parent_item_id=None),
    так и подменю для конкретного пункта.

    Args:
        group_id: ID группы действий (из пути)
        parent_item_id: ID родительского пункта меню (параметр запроса, опционально)
        session: Асинхронная сессия SQLAlchemy (внедряется через Depends)

    Returns:
        JSONResponse: Список пунктов меню текущего уровня

    Raises:
        HTTPException: При невалидном ID группы

    Notes:
        - Для получения корневого меню передайте parent_item_id=None
        - Для получения подменю передайте ID родительского пункта
        - Пункты содержат флаг has_subitems для определения наличия дочерних элементов
        - Все названия возвращаются на русском языке (lang_code="RU")
    """
    api_logger.info(f"📋 Getting menu items for group {group_id}, parent={parent_item_id}")

    _validate_group_id(group_id)

    try:
        # Получение пунктов меню из репозитория
        items_data = await _actions_repo.get_menu_items(
            session=session,
            group_id=group_id,
            parent_item_id=parent_item_id,
            lang_code="RU",
        )

        # Преобразование данных в формат ответа
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
    description="Проверяет, есть ли у указанного пункта меню дочерние элементы",
)
@log_exceptions(api_logger)
async def check_has_subitems(
    group_id: int,
    item_id: int,
    session: AsyncSession = Depends(get_session),
) -> JSONResponse:
    """
    Проверка наличия дочерних элементов у пункта меню.

    Используется для определения необходимости отображать кнопку
    перехода на следующий уровень меню.

    Args:
        group_id: ID группы действий (из пути)
        item_id: ID проверяемого пункта меню (из пути)
        session: Асинхронная сессия SQLAlchemy (внедряется через Depends)

    Returns:
        JSONResponse: Результат проверки с булевым флагом has_subitems

    Raises:
        HTTPException: При невалидных ID группы или пункта
    """
    api_logger.info(f"🔍 Checking subitems for group {group_id}, item {item_id}")

    _validate_group_id(group_id)
    _validate_item_id(item_id)

    try:
        # Проверка наличия дочерних элементов через репозиторий
        has_subitems = await _actions_repo.has_subitems(
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
    "/health",
    summary="Проверка доступности Avanpost",
    description="Проверяет подключение к базе данных Avanpost для мониторинга",
)
@log_exceptions(api_logger)
async def health_check_avanpost() -> JSONResponse:
    """
    Проверка доступности базы данных Avanpost.

    Используется для мониторинга и определения работоспособности
    внешней системы Avanpost.

    Returns:
        JSONResponse: Статус подключения с информацией о здоровье

    Notes:
        - Возвращает HTTP 200 при успешном подключении
        - Возвращает HTTP 503 при недоступности базы данных
        - Результат кешируется в db_manager
    """
    api_logger.info("🔍 Checking Avanpost health...")

    try:
        # Проверка подключения к базе данных Avanpost
        is_connected = await db_manager.check_connection("avanpost")

        if is_connected:
            return JSONResponse(
                status_code=200,
                content={
                    "success": True,
                    "status": "healthy",
                    "database": "avanpost",
                    "timestamp": get_timestamp(),
                },
            )
        else:
            return JSONResponse(
                status_code=503,
                content={
                    "success": False,
                    "status": "unhealthy",
                    "database": "avanpost",
                    "error": "Connection failed",
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


# ============ Вспомогательные функции (для внутреннего использования) ============


async def _build_menu_tree(
    session: AsyncSession,
    group_id: int,
    items: list[dict[str, Any]],
    current_depth: int,
    max_depth: int,
) -> list[dict[str, Any]]:
    """
    Рекурсивное построение дерева меню.

    Используется для построения полной иерархической структуры меню
    в один запрос.

    Args:
        session: Асинхронная сессия SQLAlchemy
        group_id: ID группы действий
        items: Список элементов текущего уровня
        current_depth: Текущая глубина вложенности (начинается с 0)
        max_depth: Максимальная глубина для построения

    Returns:
        list[dict]: Дерево меню с вложенными дочерними элементами

    Notes:
        - Рекурсивно обходит меню до достижения max_depth
        - Каждый узел содержит id, name, parent_id, children, has_children
        - Не загружает более max_depth уровней для защиты от бесконечной рекурсии
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

        # Если есть подэлементы и не достигли максимальной глубины
        if item.get("has_subitems", False) and current_depth < max_depth - 1:
            # Загружаем дочерние элементы
            children = await _actions_repo.get_menu_items(
                session=session,
                group_id=group_id,
                parent_item_id=item.get("id"),
                lang_code="RU",
            )

            # Рекурсивно строим поддерево
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
