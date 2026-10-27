import bcrypt
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

router = APIRouter(prefix="/utils", tags=["utils"])


class HashRequest(BaseModel):
    password: str = Field(..., min_length=1, description="Пароль для хеширования")


class HashResponse(BaseModel):
    hashed: str


@router.post("/hash-password", response_model=HashResponse)
async def hash_password(payload: HashRequest):
    """Хеширует пароль с помощью bcrypt (rounds=10)."""
    try:
        hashed = bcrypt.hashpw(payload.password.encode("utf-8"), bcrypt.gensalt(rounds=10))
        return HashResponse(hashed=hashed.decode("utf-8"))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Hash failed: {e}") from e
