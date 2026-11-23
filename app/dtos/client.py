"""DTO для публичного API мобильного клиента.

Здесь только контракты запросов/ответов — без бизнес-логики.
Авторизация (расшифровка токена) остаётся в ``api/v1/client.py``.
"""

from __future__ import annotations

from pydantic import BaseModel, Field, field_validator

# ============================================================
# ОБЩЕЕ
# ============================================================


class TokenPayload(BaseModel):
    """Токен в JSON-теле (register/login/update-check/send-code и т.д.)."""

    tkn: str = Field(..., min_length=1)

    @field_validator("tkn")
    @classmethod
    def strip_token(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("empty token")
        return v


# ============================================================
# UPLOADS
# ============================================================


class UploadCreateRequest(BaseModel):
    """POST /uploads — метаданные файла + tkn в теле.

    ``uid`` задаётся клиентом (если не задан — сгенерирует сервер).
    """

    tkn: str = Field(..., min_length=1)
    uid: str | None = Field(None, max_length=64, description="upload_id от клиента")
    fnm: str = Field(..., min_length=1, max_length=255, description="Имя файла")
    fex: str | None = Field(None, max_length=16, description="Расширение без точки")
    fsz: int = Field(..., gt=0, description="Ожидаемый размер, байт")
    sha: str | None = Field(None, max_length=64, description="Ожидаемый SHA-256")

    @field_validator("tkn")
    @classmethod
    def _strip_tkn(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("empty token")
        return v

    @field_validator("fnm")
    @classmethod
    def _clean_name(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("empty fnm")
        # не доверяем имени — отбрасываем путь
        return v.replace("\\", "/").split("/")[-1]

    @field_validator("fex")
    @classmethod
    def _clean_ext(cls, v: str | None) -> str | None:
        if v is None:
            return None
        v = v.strip().lower().lstrip(".")
        return v or None

    @field_validator("sha")
    @classmethod
    def _clean_sha(cls, v: str | None) -> str | None:
        if v is None:
            return None
        v = v.strip().lower()
        return v or None


class UploadCompleteRequest(BaseModel):
    """POST /uploads/{upload_id}/complete — tkn в теле."""

    tkn: str = Field(..., min_length=1)

    @field_validator("tkn")
    @classmethod
    def _strip_tkn(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("empty token")
        return v


# ============================================================
# FILES
# ============================================================


# ============================================================
# MESSAGES
# ============================================================


class MessageItem(BaseModel):
    """Один элемент массива ``p`` в POST /msgs."""

    i: int = Field(1, ge=0, description="Порядковый индекс сообщения в запросе")
    idk: str = Field(..., min_length=1, max_length=36, description="Клиентский ID сообщения (FCode)")
    tpc: str = Field(..., min_length=1, max_length=64, description="Тема (grpXXX/usrXXX/...)")
    tid: str = Field("1", min_length=1, max_length=30, description="Тип: 1=текст, 3=операция")
    txt: str | None = Field(None, max_length=8000)
    fls: list[str] = Field(
        default_factory=list,
        max_length=50,
        description="FUploadID из ответа POST /uploads/{uid}/complete",
    )

    @field_validator("tpc")
    @classmethod
    def _check_topic(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("empty tpc")
        return v

    @field_validator("fls")
    @classmethod
    def _clean_fls(cls, v: list[str]) -> list[str]:
        out: list[str] = []
        for x in v:
            s = str(x).strip()
            if not s:
                continue
            if len(s) > 64:
                raise ValueError(f"file id too long: {len(s)} > 64")
            out.append(s)
        return out


class MessageCreateRequest(BaseModel):
    """POST /msgs — текст + список file_id."""

    tkn: str = Field(..., min_length=1)
    p: list[MessageItem] = Field(..., min_length=1, max_length=50)
    idk: str | None = Field(None, max_length=80, description="Idempotency-Key (опционально)")

    @field_validator("tkn")
    @classmethod
    def _strip_tkn(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("empty token")
        return v


__all__ = [
    "TokenPayload",
    "UploadCreateRequest",
    "UploadCompleteRequest",
    "MessageItem",
    "MessageCreateRequest",
]
