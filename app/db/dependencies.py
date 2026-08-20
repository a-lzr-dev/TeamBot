from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from ..db import DBManager


def get_db_manager() -> "DBManager":
    """Получение экземпляра DBManager"""
    from ..db import db_manager

    if db_manager is None:
        raise RuntimeError("DBManager is not initialized")
    return db_manager


__all__ = [
    "get_db_manager",
]
