from ..models import datetime_now


def get_timestamp() -> str:
    """Получение текущего времени в ISO формате"""
    dt = datetime_now()
    return dt.isoformat() + "Z"


__all__ = [
    "get_timestamp",
]
