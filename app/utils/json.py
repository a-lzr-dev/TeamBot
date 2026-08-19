import json
from collections.abc import Callable
from functools import wraps
from typing import Any

from app.logger import app_logger


def log_json_errors(func: Callable) -> Callable:
    """Декоратор для логирования ошибок с выводом JSON-данных"""

    @wraps(func)
    async def wrapper(*args: Any, **kwargs: Any) -> Any:
        try:
            return await func(*args, **kwargs)
        except Exception as e:
            records = None
            for arg in args:
                if isinstance(arg, list | dict):
                    records = arg
                    break

            if records:
                app_logger.error(f"❌ Error in {func.__name__}: {e}")
                app_logger.error(
                    f"   Problematic records (first 3): {json.dumps(records[:3] if isinstance(records, list) else [records], ensure_ascii=False, default=str, indent=2)}"
                )
            raise

    return wrapper
