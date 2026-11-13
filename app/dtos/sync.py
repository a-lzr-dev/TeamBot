"""DTO для механизма синхронизации мобильного клиента (sync-load / sync-edit).

CHANGED (v12):
  * `SyncLoadResponse` описывает только «реальный пакет»:
    `{"success": 1, "sid": ..., "prm": [...]}`.
  * Для ответа «изменений нет» сервер отдаёт `{"success": 1}`
    (без `sid`/`prm`) — см. `SyncLoadNoChangesResponse`.
  * `SyncLoadRow` больше не используется на публичном контракте — оставлен
    для внутренних тестов/диагностики.

CHANGED (v8):
  * `SyncLoadRequest` упрощён:
      - клиент НЕ передаёт `lmt` (сервер всегда использует
        APP_CLIENT_SYNC_BASE_DEFAULT_LIMIT);
      - `frc` — целое 0/1, поле передаётся ТОЛЬКО когда нужно
        полное обновление (frc=1). Отсутствие = 0;
      - `dtp` — обязательный непустой список DataTypeId.
  * `SyncLoadRow` больше не используется на публичном контракте.

CHANGED (v7):
  * `SyncEditItem`: клиент передаёт только `token` + `sid`.
  * `SyncEditResponse`: committed_items/committed_types/failed_items.

Семантика `prm[i]` (в реальном пакете):
    {
        "dt": int, # DataTypeId
        "exp": int | null, # 1 = DELETE, null = UPSERT
        "val": list[dict]  # JSON-массив записей; [] = пустой тип
    }

Клиент разбирает `prm` сам. Сервер НЕ нормализует `val` в строку,
НЕ считает `HasMore`, НЕ режет oversized — всё это делает SQL
через @Limit (по умолчанию APP_CLIENT_SYNC_BASE_DEFAULT_LIMIT).
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator

# ---------------------------------------------------------------------------
# Load
# ---------------------------------------------------------------------------


class SyncLoadRow(BaseModel):
    """Внутренний DTO строки resultset (для диагностики и тестов).

    На публичном контракте /client/sync-load больше НЕ используется:
    сервер отдаёт клиенту сырой `prm` из поля Result SQL-процедуры.
    """

    DataTypeId: int = Field(..., ge=1, le=32767)
    FlagExpire: int | None = Field(None, ge=0, le=1)
    RecordData: str = Field(..., min_length=2)
    HasMore: int = Field(..., ge=0, le=1)
    SyncTime: str | None = None

    @field_validator("RecordData")
    @classmethod
    def _validate_record_json(cls, v: str) -> str:
        if v in ("[]", ""):
            return v
        try:
            parsed = json.loads(v)
        except json.JSONDecodeError as e:
            raise ValueError(f"RecordData is not valid JSON: {e}") from e
        if not isinstance(parsed, list):
            raise ValueError("RecordData must be a JSON array")
        return v


class SyncLoadRequest(BaseModel):
    """Тело POST /client/sync-load (без токена — он добавляется в роутере).

    Поля:
      * dtp — обязательный непустой список DataTypeId;
      * frc — 1 = полная перезагрузка. Поле передаётся ТОЛЬКО при
              необходимости полного обновления; иначе клиент его
              не отправляет вовсе (сервер трактует отсутствие как 0).

    Клиент НЕ передаёт `lmt` — сервер всегда использует
    APP_CLIENT_SYNC_BASE_DEFAULT_LIMIT.
    """

    data_types: list[int] | None = Field(
        None,
        alias="dtp",
        max_length=256,
        description="Список DataTypeId; null или [] = все типы. Клиент ДОЛЖЕН передавать явный непустой список.",
    )
    force: int = Field(
        0,
        alias="frc",
        ge=0,
        le=1,
        description="1 = игнорировать FDateProcess (полная перезагрузка). Отсутствие поля трактуется как 0.",
    )

    model_config = {"populate_by_name": True}

    @field_validator("data_types")
    @classmethod
    def _empty_to_none(cls, v: list[int] | None) -> list[int] | None:
        if v is not None and len(v) == 0:
            return None
        return v

    @field_validator("data_types")
    @classmethod
    def _validate_data_types_range(cls, v: list[int] | None) -> list[int] | None:
        if v is None:
            return None
        for t in v:
            if t <= 0 or t > 32767:
                raise ValueError(f"dtp value out of range (1..32767): {t}")
        return v


class SyncLoadNoChangesResponse(BaseModel):
    """Ответ POST /client/sync-load для случая «изменений нет».

    CHANGED (v12): сервер отдаёт ТОЛЬКО `{"scs": 1}`.
    Это значит:
      * подтверждать нечего (FDateProcess уже сдвинут процедурой
        через MERGE во внутренней ветке `@HasAnyData = 0`);
      * повторный sync-load не требуется;
      * sync-edit по этому ответу делать НЕЛЬЗЯ (sid отсутствует).

    Поля `sid`/`prm` в этом ответе отсутствуют намеренно —
    чтобы клиент не пытался их парсить.
    """

    success: Literal[1] = Field(1, description="1 = изменений нет")


class SyncLoadResponse(BaseModel):
    """Ответ POST /client/sync-load для случая «есть реальный пакет».

    CHANGED (v12): эта схема описывает ТОЛЬКО пакет с изменениями.
    Для «изменений нет» сервер отдаёт `SyncLoadNoChangesResponse`
    (`{"success": 1}` без `sid`/`prm`).

    Поля:
      * scs      — 1 (OK) / 0 (ошибка, тело содержит error);
      * sid      — UUIDv4 пакета. Клиент ОБЯЗАН передать его
                   в sync-edit БЕЗ парсинга и пересериализации;
      * prm      — сырой JSON из поля Result процедуры
                   ext.PA_mbl_SyncBaseData_Load без изменений.
                   Формат элементов: {"dt": int, "exp": int|null,
                   "val": list[dict] | "[]"}.
    """

    success: int = Field(1, ge=0, le=1)
    sid: str = Field(..., description="UUIDv4 пакета (передавать в sync-edit)")
    prm: list[dict[str, Any]] = Field(
        default_factory=list,
        description="Сырой JSON из поля Result SQL-процедуры без изменений. Элементы: {dt, exp, val}.",
    )


# ---------------------------------------------------------------------------
# Edit
# ---------------------------------------------------------------------------


def _utcnow() -> datetime:
    return datetime.now(UTC)


class SyncEditItem(BaseModel):
    """Один элемент массива Edit.

    Клиент передаёт только `token` + `sid`. `usi`/`api`/`dvc` извлекаются
    из расшифрованного WS-токена, `snc`/`dtp` — из in-memory реестра
    по `sid`.
    """

    token: str = Field(..., min_length=1)
    sid: str = Field(
        ...,
        min_length=8,
        max_length=64,
        description="Идентификатор пакета, полученный в sync-load",
    )


class SyncEditRequest(BaseModel):
    """Тело POST /client/sync-edit (список подтверждений)."""

    items: list[SyncEditItem] = Field(..., min_length=1)


SyncEditRequest.model_rebuild()


class SyncEditResponse(BaseModel):
    """Ответ POST /client/sync-edit.

    retry — подсказка клиенту:
      * "sync-load" — перевызвать Load (invalid_edit / bad_ts /
                      edit_timeout);
      * "sync-edit" — повторить Edit (207 partial, failed_items);
      * "register"  — перерегистрироваться (409 session lost);
      * None        — действие не требуется.
    """

    scs: int = Field(1, ge=0, le=1)
    committed_items: int = 0
    committed_types: int = 0
    failed_items: list[int] = Field(
        default_factory=list,
        description="0-based индексы items, которые не удалось подтвердить",
    )
    error: str | None = None
    retry: Literal["sync-load", "sync-edit", "register"] | None = None


__all__ = [
    "SyncLoadRequest",
    "SyncLoadRow",
    "SyncLoadNoChangesResponse",
    "SyncLoadResponse",
    "SyncEditRequest",
    "SyncEditItem",
    "SyncEditResponse",
]