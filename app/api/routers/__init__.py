from .admin import router as admin_router
from .automation import router as automation_router
from .avanpost import router as avanpost_router
from .errors import router as errors_router
from .reminders import router as reminders_router
from .tg_msgs import router as tg_msgs_router
from .tg_sync import router as tg_sync_router

__all__ = [
    "admin_router",
    "avanpost_router",
    "automation_router",
    "errors_router",
    "reminders_router",
    "tg_msgs_router",
    "tg_sync_router",
]
