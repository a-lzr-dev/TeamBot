"""Pydantic-модели для приёма push от Go myrelay-адаптера.

Формат строго соответствует структурам relayBatch и relayPush из
server/push/myrelay/push_myrelay.go.
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator


class RelayPush(BaseModel):
    """Один push для одного получателя.

    Соответствует Go-структуре relayPush.
    Использует алиасы для полей, которые в Go-коде названы в camelCase.
    """

    user_id: str = Field(..., alias="userId", description="Tinode user ID, e.g. 'usrABC...'")
    type: Literal["msg", "sub", "read"] = Field(..., description="Тип действия")
    topic: str = Field(..., description="Topic name")

    from_id: str | None = Field(None, alias="from")
    seq: int | None = None
    unread: int | None = None
    delivered: int | None = None
    devices: list[str] | None = None
    silent: bool = False

    mime: str | None = None
    # Go: json.RawMessage — может прийти как dict, list, str или None.
    content: Any | None = None

    webrtc: str | None = None
    aonly: bool | None = None
    replace: str | None = None

    want: str | None = None
    given: str | None = None

    ts: str = Field(..., description="RFC3339Nano timestamp")

    @field_validator("user_id")
    @classmethod
    def _validate_user_id(cls, v: str) -> str:
        if not v.startswith("usr") or len(v) < 6:
            raise ValueError(f"Invalid user_id: {v}")
        return v

    model_config = {"populate_by_name": True}


class RelayBatch(BaseModel):
    """Батч push-сообщений от Go-адаптера.

    Соответствует Go-структуре relayBatch.
    """

    event_id: str
    ts: str
    pushes: list[RelayPush] = Field(default_factory=list)

    model_config = {"populate_by_name": True}
