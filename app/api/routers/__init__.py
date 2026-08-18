from .admin import router as admin_router
from .automation import router as automation_router
from .avanpost import router as avanpost_router
from .bot_msgs import router as bot_msgs_router
from .bot_sync import router as bot_sync_router
from .errors import router as errors_router
from .reminders import router as reminders_router

__all__ = [
    "admin_router",
    "avanpost_router",
    "automation_router",
    "errors_router",
    "reminders_router",
    "bot_msgs_router",
    "bot_sync_router",
]
