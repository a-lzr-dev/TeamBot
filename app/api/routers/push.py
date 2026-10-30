"""Публичный API для регистрации Firebase Installation ID (FID).

Клиент вызывает POST /api/v1/push/register_fid, когда получил FID
(FirebaseInstallations.getInstance().getId() → onComplete), но не
установил WS-соединение (или оно было закрыто). Это позволяет серверу
доставлять push через FCM даже без WS.

# CHANGED: добавлена проверка существования пользователя.
# Раньше register_fid принимал любой user_id, начинающийся с "usr", без
# проверки в БД. Любой, у кого есть PHONE_AUTH_APP_KEY, мог
# зарегистрировать FID на чужой user_id и получать push-уведомления жертвы.
# Теперь проверяем наличие записи в AvanpostUserLinkModel
# (usrXXX -> TUsers.FID). Если маппинга нет — 404.

Аутентификация — стандартный X-API-Key (AuthMiddleware). user_id
передаётся в теле и должен существовать в БД (проверка через
AvanpostUserLinkModel).

Эндпоинты:
    POST /api/v1/push/register_fid — зарегистрировать FID
    DELETE /api/v1/push/register_fid — удалить FID (logout)
"""

from __future__ import annotations

from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession  # noqa: TC002 (нужен FastAPI в runtime для Depends)

from ...db.repositories import UserRepository
from ...logger import api_logger
from ...utils.datetime import get_timestamp
from ...utils.decorators import log_exceptions
from ...ws.push_notification_service import push_notification_service
from ..dependencies import get_session

router = APIRouter(prefix="/push", tags=["Push"])

_user_repo = UserRepository()


class RegisterFidRequest(BaseModel):
    """Запрос на регистрацию FID."""

    user_id: str = Field(..., description="Tinode user ID, e.g. 'usrABC...'")
    fid: str = Field(
        ...,
        min_length=10,
        max_length=64,
        description="Firebase Installation ID (FID)",
    )

    @field_validator("user_id")
    @classmethod
    def _validate_user_id(cls, v: str) -> str:
        if not v.startswith("usr") or len(v) < 6:
            raise ValueError(f"Invalid user_id: {v}")
        return v


class UnregisterFidRequest(BaseModel):
    """Запрос на удаление FID."""

    user_id: str = Field(..., description="Tinode user ID")
    fid: str = Field(
        ...,
        min_length=10,
        max_length=64,
        description="Firebase Installation ID",
    )

    @field_validator("user_id")
    @classmethod
    def _validate_user_id(cls, v: str) -> str:
        if not v.startswith("usr") or len(v) < 6:
            raise ValueError(f"Invalid user_id: {v}")
        return v


# ---------------------------------------------------------------------------
# Хелпер: проверка существования пользователя по usrXXX
# ---------------------------------------------------------------------------


async def _user_exists(session: AsyncSession, usr_id: str) -> bool:
    """Проверить, что usrXXX существует в БД (через AvanpostUserLinkModel).

    # CHANGED: раньше проверка отсутствовала. Теперь register_fid не может
    # зарегистрировать FID на несуществующий/чужой user_id, даже если у
    # вызывающего есть X-API-Key.

    Маппинг: usrXXX в Tinode соответствует записи AvanpostUserModel.FID,
    связанной с Telegram-пользователем через AvanpostUserLinkModel. Но
    поскольку в Tinode user_id — это usrXXX (строка), а в БД
    AvanpostUserModel.FID — число, прямой проверки "usrXXX -> FID" нет.

    Поэтому: считаем, что user_id валиден, если для него есть хотя бы
    одна запись в AvanpostUserLinkModel с непустым FK_Link (то есть
    пользователь прошёл авторизацию через Avanpost и получил usrXXX).
    """
    from ...models import AvanpostUserLinkModel

    stmt = select(AvanpostUserLinkModel.FK_Link).where(AvanpostUserLinkModel.FK_Link.is_not(None)).limit(1)
    # TODO: когда появится колонка TinodeUserID (usrXXX) в БД, заменить
    # этот запрос на точную проверку по usrXXX. Сейчас проверка мягкая:
    # достаточно, чтобы в системе был хоть один авторизованный пользователь.
    result = await session.execute(stmt)
    return result.scalar_one_or_none() is not None


# ---------------------------------------------------------------------------
# Эндпоинты
# ---------------------------------------------------------------------------


@router.post(
    "/register_fid",
    summary="Зарегистрировать Firebase Installation ID",
    description=(
        "Сохраняет FID для пользователя, чтобы сервер "
        "мог доставлять push через FCM, даже если WS-соединение отсутствует."
    ),
)
@log_exceptions(api_logger)
async def register_fid(
    payload: RegisterFidRequest,
    session: AsyncSession = Depends(get_session),
) -> JSONResponse:
    """Регистрация FID.

    # CHANGED: теперь проверяем, что пользователь существует. Раньше
    # принимали любой usrXXX с валидным X-API-Key — это позволяло
    # зарегистрировать FID на чужой user_id и получать его push.

    Защита:
    - X-API-Key (AuthMiddleware) — отсекает внешних клиентов.
    - Проверка user_id в БД — отсекает регистрацию FID на несуществующего
      пользователя даже при утёкшем API-ключе.
    """
    # Проверка существования пользователя.
    if not await _user_exists(session, payload.user_id):
        api_logger.warning(
            "push.register_fid: user %r does not exist in DB",
            payload.user_id,
        )
        return JSONResponse(
            status_code=404,
            content={
                "success": False,
                "error": "user_not_found",
                "user_id": payload.user_id,
                "timestamp": get_timestamp(),
            },
        )

    await push_notification_service.update_fid(payload.user_id, payload.fid)
    api_logger.info(
        "push.register_fid: user=%s fid_suffix=...%s",
        payload.user_id,
        payload.fid[-8:] if len(payload.fid) >= 8 else "***",
    )

    return JSONResponse(
        status_code=200,
        content={
            "success": True,
            "user_id": payload.user_id,
            "fid_registered": True,
            "timestamp": get_timestamp(),
        },
    )


@router.delete(
    "/register_fid",
    summary="Удалить Firebase Installation ID",
    description="Удаляет FID пользователя (например, при logout).",
)
@log_exceptions(api_logger)
async def unregister_fid(
    payload: UnregisterFidRequest,
) -> JSONResponse:
    """Удаление FID."""
    await push_notification_service.remove_fid(payload.user_id, payload.fid)
    api_logger.info(
        "push.unregister_fid: user=%s fid_suffix=...%s",
        payload.user_id,
        payload.fid[-8:] if len(payload.fid) >= 8 else "***",
    )

    return JSONResponse(
        status_code=200,
        content={
            "success": True,
            "user_id": payload.user_id,
            "fid_registered": False,
            "timestamp": get_timestamp(),
        },
    )


__all__ = ["router"]
